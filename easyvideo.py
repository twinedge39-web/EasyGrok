import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import xai_sdk


# ========= JSON helpers =========
def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path.resolve()}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_nested(d: dict, dotted_key: str):
    cur = d
    for k in dotted_key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def set_nested(d: dict, dotted_key: str, value) -> None:
    keys = dotted_key.split(".")
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def backup(path: Path, data: dict) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak_{stamp}")
    save_json(bak, data)
    return bak


# ========= shared =========
def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_cfg_path(args) -> Path:
    return Path(args.config) if args.config else Path("./config/config.user.json")


def get_api_key() -> str:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        print("ERROR: XAI_API_KEY is not set in environment variables.", file=sys.stderr)
        raise SystemExit(2)
    return api_key


def ensure_out_dir(out_dir: str) -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_videos_dir(out_dir: str) -> Path:
    p = ensure_out_dir(out_dir) / "videos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def guess_ext_from_headers(content_type: Optional[str], url: str) -> str:
    ct = (content_type or "").lower()
    if "mp4" in ct:
        return ".mp4"
    if "quicktime" in ct or "mov" in ct:
        return ".mov"

    u = url.lower().split("?")[0].split("#")[0]
    for ext in (".mp4", ".mov", ".webm"):
        if u.endswith(ext):
            return ext
    return ".mp4"


def download_url_to_file(url: str, dest_dir: Path, base_name: str) -> Optional[Path]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type")
            data = resp.read()

        ext = guess_ext_from_headers(content_type, url)
        out_path = dest_dir / f"{base_name}{ext}"
        out_path.write_bytes(data)
        return out_path
    except urllib.error.HTTPError as e:
        print(f"DL failed (HTTP {e.code}): {url}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"DL failed (URL error): {url} ({e})", file=sys.stderr)
    except Exception as e:
        print(f"DL failed: {url} ({e})", file=sys.stderr)
    return None


def write_record(cfg: dict, prefix: str, record: dict) -> Path:
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    stamp = now_stamp()
    p = out_path / f"{prefix}_{stamp}.json"
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def make_client(cfg: dict):
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    return xai_sdk.Client(api_key=get_api_key(), timeout=timeout_sec)


def get_video_cfg(cfg: dict) -> dict:
    v = get_nested(cfg, "video")
    if not isinstance(v, dict):
        raise SystemExit("ERROR: video block not found in config.user.json")
    return v


def save_cfg_if_needed(cfg_path: Path, cfg: dict) -> None:
    save_json(cfg_path, cfg)


# ========= builders =========
def build_video_kwargs(cfg: dict,
                       prompt_override: Optional[str] = None,
                       image_url_override: Optional[str] = None,
                       video_url_override: Optional[str] = None,
                       duration_override: Optional[int] = None,
                       aspect_ratio_override: Optional[str] = None,
                       resolution_override: Optional[str] = None) -> dict:
    vcfg = get_video_cfg(cfg)

    model = vcfg.get("model") or "grok-imagine-video"
    prompt = prompt_override or vcfg.get("prompt") or ""
    duration = int(duration_override or vcfg.get("duration") or 5)
    aspect_ratio = aspect_ratio_override or vcfg.get("aspect_ratio") or "16:9"
    resolution = resolution_override or vcfg.get("resolution") or "720p"
    image_url = image_url_override if image_url_override is not None else (vcfg.get("image_url") or "")
    video_url = video_url_override if video_url_override is not None else (vcfg.get("video_url") or "")

    if not prompt:
        raise SystemExit("ERROR: video.prompt is empty.")

    kwargs = {
        "prompt": prompt,
        "model": model,
    }

    # text-to-video
    if not image_url and not video_url:
        kwargs["duration"] = duration
        kwargs["aspect_ratio"] = aspect_ratio
        kwargs["resolution"] = resolution
        return kwargs

    # image-to-video
    if image_url and not video_url:
        kwargs["image_url"] = image_url
        kwargs["duration"] = duration
        kwargs["aspect_ratio"] = aspect_ratio
        kwargs["resolution"] = resolution
        return kwargs

    # video edit
    if video_url and not image_url:
        kwargs["video_url"] = video_url
        return kwargs

    raise SystemExit("ERROR: Set either video.image_url or video.video_url, not both.")


# ========= state =========
def update_last_state(cfg: dict, cfg_path: Path,
                      request_id: Optional[str] = None,
                      video_url: Optional[str] = None) -> None:
    if request_id is not None:
        set_nested(cfg, "video.last_request_id", request_id)
    if video_url is not None:
        set_nested(cfg, "video.last_video_url", video_url)
    save_cfg_if_needed(cfg_path, cfg)


# ========= commands =========
def cmd_generate(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)
    client = make_client(cfg)

    vcfg = get_video_cfg(cfg)
    poll_timeout_sec = int(vcfg.get("poll_timeout_sec") or 900)
    poll_interval_sec = int(vcfg.get("poll_interval_sec") or 5)

    kwargs = build_video_kwargs(
        cfg,
        prompt_override=args.prompt,
        image_url_override=args.image_url,
        video_url_override=args.video_url,
        duration_override=args.duration,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
    )

    response = client.video.generate(
        **kwargs,
        timeout=timedelta(seconds=poll_timeout_sec),
        interval=timedelta(seconds=poll_interval_sec),
    )

    video_url = getattr(response, "url", "") or ""
    model = getattr(response, "model", kwargs["model"])
    duration = getattr(response, "duration", None)
    respect_moderation = getattr(response, "respect_moderation", None)

    update_last_state(cfg, cfg_path, video_url=video_url)

    saved_file = None
    download_now = bool(args.download or vcfg.get("download_now"))
    if download_now and video_url:
        dest = ensure_videos_dir(get_nested(cfg, "defaults.output.dir") or "./out")
        saved = download_url_to_file(video_url, dest, f"video_generate_{now_stamp()}")
        if saved:
            saved_file = saved.as_posix()

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "video.generate",
        "request": kwargs,
        "model": model,
        "video_url": video_url,
        "duration": duration,
        "respect_moderation": respect_moderation,
        "saved_file": saved_file,
    }
    p = write_record(cfg, "video_generate", record)
    print(f"OK: saved {p.as_posix()}")
    if video_url:
        print(video_url)
    if saved_file:
        print(f"Downloaded: {saved_file}")
    return 0


def cmd_start(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)
    client = make_client(cfg)

    kwargs = build_video_kwargs(
        cfg,
        prompt_override=args.prompt,
        image_url_override=args.image_url,
        video_url_override=args.video_url,
        duration_override=args.duration,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
    )

    response = client.video.start(**kwargs)
    request_id = getattr(response, "request_id", "") or ""
    if not request_id:
        raise SystemExit("ERROR: No request_id returned.")

    update_last_state(cfg, cfg_path, request_id=request_id)

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "video.start",
        "request": kwargs,
        "request_id": request_id,
    }
    p = write_record(cfg, "video_start", record)
    print(f"OK: saved {p.as_posix()}")
    print(f"request_id: {request_id}")
    return 0


def cmd_get(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)
    client = make_client(cfg)

    request_id = args.request_id or get_nested(cfg, "video.last_request_id")
    if not request_id:
        raise SystemExit("ERROR: request_id is empty. Use start first or pass --request-id.")

    result = client.video.get(request_id)

    # SDK object differences are possible, so access defensively
    status = getattr(result, "status", None)
    status_name = getattr(status, "name", None) or str(status)

    response = getattr(result, "response", None)
    video_url = ""
    duration = None
    respect_moderation = None
    model = None

    if response is not None:
        video = getattr(response, "video", None)
        if video is not None:
            video_url = getattr(video, "url", "") or ""
            duration = getattr(video, "duration", None)
            respect_moderation = getattr(video, "respect_moderation", None)
        model = getattr(response, "model", None)

    if video_url:
        update_last_state(cfg, cfg_path, video_url=video_url)

    saved_file = None
    vcfg = get_video_cfg(cfg)
    download_now = bool(args.download or vcfg.get("download_now"))
    if download_now and video_url and status_name.upper().endswith("DONE"):
        dest = ensure_videos_dir(get_nested(cfg, "defaults.output.dir") or "./out")
        saved = download_url_to_file(video_url, dest, f"video_get_{now_stamp()}")
        if saved:
            saved_file = saved.as_posix()

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "video.get",
        "request_id": request_id,
        "status": status_name,
        "model": model,
        "video_url": video_url,
        "duration": duration,
        "respect_moderation": respect_moderation,
        "saved_file": saved_file,
    }
    p = write_record(cfg, "video_get", record)
    print(f"OK: saved {p.as_posix()}")
    print(f"status: {status_name}")
    if video_url:
        print(video_url)
    if saved_file:
        print(f"Downloaded: {saved_file}")
    return 0


def cmd_poll(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)
    client = make_client(cfg)

    request_id = args.request_id or get_nested(cfg, "video.last_request_id")
    if not request_id:
        raise SystemExit("ERROR: request_id is empty. Use start first or pass --request-id.")

    vcfg = get_video_cfg(cfg)
    timeout_sec = int(args.timeout or vcfg.get("poll_timeout_sec") or 900)
    interval_sec = int(args.interval or vcfg.get("poll_interval_sec") or 5)

    deadline = time.time() + timeout_sec
    last_status = None

    while True:
        result = client.video.get(request_id)
        status = getattr(result, "status", None)
        status_name = getattr(status, "name", None) or str(status)

        if status_name != last_status:
            print(f"status: {status_name}")
            last_status = status_name

        response = getattr(result, "response", None)
        video_url = ""
        duration = None
        respect_moderation = None
        model = None

        if response is not None:
            video = getattr(response, "video", None)
            if video is not None:
                video_url = getattr(video, "url", "") or ""
                duration = getattr(video, "duration", None)
                respect_moderation = getattr(video, "respect_moderation", None)
            model = getattr(response, "model", None)

        if status_name.upper().endswith("DONE"):
            if video_url:
                update_last_state(cfg, cfg_path, video_url=video_url)

            saved_file = None
            download_now = bool(args.download or vcfg.get("download_now"))
            if download_now and video_url:
                dest = ensure_videos_dir(get_nested(cfg, "defaults.output.dir") or "./out")
                saved = download_url_to_file(video_url, dest, f"video_poll_{now_stamp()}")
                if saved:
                    saved_file = saved.as_posix()

            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "mode": "video.poll.done",
                "request_id": request_id,
                "status": status_name,
                "model": model,
                "video_url": video_url,
                "duration": duration,
                "respect_moderation": respect_moderation,
                "saved_file": saved_file,
            }
            p = write_record(cfg, "video_poll", record)
            print(f"OK: saved {p.as_posix()}")
            if video_url:
                print(video_url)
            if saved_file:
                print(f"Downloaded: {saved_file}")
            return 0

        if status_name.upper().endswith("FAILED") or status_name.upper().endswith("EXPIRED"):
            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "mode": "video.poll.stop",
                "request_id": request_id,
                "status": status_name,
            }
            p = write_record(cfg, "video_poll", record)
            print(f"OK: saved {p.as_posix()}")
            return 1

        if time.time() >= deadline:
            raise TimeoutError(f"Polling timed out after {timeout_sec} seconds.")

        time.sleep(interval_sec)


def cmd_download_last(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)

    video_url = get_nested(cfg, "video.last_video_url")
    if not video_url:
        raise SystemExit("ERROR: video.last_video_url is empty.")

    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    dest = ensure_videos_dir(out_dir)

    saved = download_url_to_file(video_url, dest, f"video_last_{now_stamp()}")
    if not saved:
        raise SystemExit("ERROR: download failed.")

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "video.download_last",
        "video_url": video_url,
        "saved_file": saved.as_posix(),
    }
    p = write_record(cfg, "video_download", record)
    print(f"OK: saved {p.as_posix()}")
    print(f"Downloaded: {saved.as_posix()}")
    return 0


# ========= menu =========
VIDEO_FIELDS = [
    ("video.model", "Video model"),
    ("video.prompt", "Video prompt"),
    ("video.duration", "Duration"),
    ("video.aspect_ratio", "Aspect ratio"),
    ("video.resolution", "Resolution"),
    ("video.poll_interval_sec", "Poll interval sec"),
    ("video.poll_timeout_sec", "Poll timeout sec"),
    ("video.download_now", "Download now"),
    ("video.save_request_id", "Save request_id"),
    ("video.last_request_id", "Last request_id"),
    ("video.last_video_url", "Last video_url"),
    ("video.image_url", "Image URL (for image-to-video)"),
    ("video.video_url", "Video URL (for video edit)"),
]


def parse_menu_value(v: str):
    s = v.strip()
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def menu(cfg_path: Path, cfg: dict) -> None:
    while True:
        print("\n=== easyvideo menu ===")
        for i, (key, label) in enumerate(VIDEO_FIELDS, start=1):
            val = get_nested(cfg, key)
            short = "(unset)" if val is None else str(val)
            if len(short) > 100:
                short = short[:97] + "..."
            print(f"{i:2d}) {label}\n    {key} = {short}")

        print("\nActions:")
        print(" number : edit item")
        print(" S      : save config")
        print(" G      : generate (auto wait)")
        print(" T      : start only")
        print(" P      : poll last request_id")
        print(" K      : get last request_id once")
        print(" D      : download last video")
        print(" Q      : quit")

        c = input("> ").strip().lower()

        if c == "q":
            return
        if c == "s":
            save_json(cfg_path, cfg)
            print(f"OK: saved {cfg_path}")
            continue
        if c == "g":
            save_json(cfg_path, cfg)
            cmd_generate(argparse.Namespace(
                config=str(cfg_path),
                prompt=None,
                image_url=None,
                video_url=None,
                duration=None,
                aspect_ratio=None,
                resolution=None,
                download=False,
            ))
            continue
        if c == "t":
            save_json(cfg_path, cfg)
            cmd_start(argparse.Namespace(
                config=str(cfg_path),
                prompt=None,
                image_url=None,
                video_url=None,
                duration=None,
                aspect_ratio=None,
                resolution=None,
            ))
            continue
        if c == "p":
            save_json(cfg_path, cfg)
            cmd_poll(argparse.Namespace(
                config=str(cfg_path),
                request_id=None,
                timeout=None,
                interval=None,
                download=False,
            ))
            continue
        if c == "k":
            save_json(cfg_path, cfg)
            cmd_get(argparse.Namespace(
                config=str(cfg_path),
                request_id=None,
                download=False,
            ))
            continue
        if c == "d":
            save_json(cfg_path, cfg)
            cmd_download_last(argparse.Namespace(config=str(cfg_path)))
            continue

        if not c.isdigit():
            print("Invalid input.")
            continue

        idx = int(c)
        if not (1 <= idx <= len(VIDEO_FIELDS)):
            print("Out of range.")
            continue

        key, label = VIDEO_FIELDS[idx - 1]
        cur = get_nested(cfg, key)
        print(f"\nEditing: {label}\n  {key}\nCurrent: {cur}")
        newv = input("New value (blank=cancel): ")
        if not newv.strip():
            continue

        set_nested(cfg, key, parse_menu_value(newv))
        print("OK: updated in memory.")


def cmd_menu(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)
    bak = backup(cfg_path, cfg)
    print(f"Backup created: {bak}")
    menu(cfg_path, cfg)
    return 0


# ========= parser =========
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="easyvideo.py",
        description="Grok EASY video runner"
    )
    ap.add_argument("-c", "--config", help="Config JSON path (default: ./config/config.user.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_menu = sub.add_parser("menu", help="Interactive video config editor")
    p_menu.set_defaults(fn=cmd_menu)

    p_generate = sub.add_parser("generate", help="Generate video and auto-wait")
    p_generate.add_argument("prompt", nargs="?", help="Override prompt")
    p_generate.add_argument("--image-url", help="Source image URL for image-to-video")
    p_generate.add_argument("--video-url", help="Source video URL for video editing")
    p_generate.add_argument("--duration", type=int, help="Override duration")
    p_generate.add_argument("--aspect-ratio", help="Override aspect ratio")
    p_generate.add_argument("--resolution", help="Override resolution")
    p_generate.add_argument("--download", action="store_true", help="Download video immediately")
    p_generate.set_defaults(fn=cmd_generate)

    p_start = sub.add_parser("start", help="Start video generation only and save request_id")
    p_start.add_argument("prompt", nargs="?", help="Override prompt")
    p_start.add_argument("--image-url", help="Source image URL for image-to-video")
    p_start.add_argument("--video-url", help="Source video URL for video editing")
    p_start.add_argument("--duration", type=int, help="Override duration")
    p_start.add_argument("--aspect-ratio", help="Override aspect ratio")
    p_start.add_argument("--resolution", help="Override resolution")
    p_start.set_defaults(fn=cmd_start)

    p_get = sub.add_parser("get", help="Check one request_id once")
    p_get.add_argument("--request-id", help="Explicit request_id; default is config video.last_request_id")
    p_get.add_argument("--download", action="store_true", help="Download if ready")
    p_get.set_defaults(fn=cmd_get)

    p_poll = sub.add_parser("poll", help="Poll request_id until done/failed/expired")
    p_poll.add_argument("--request-id", help="Explicit request_id; default is config video.last_request_id")
    p_poll.add_argument("--timeout", type=int, help="Polling timeout sec")
    p_poll.add_argument("--interval", type=int, help="Polling interval sec")
    p_poll.add_argument("--download", action="store_true", help="Download when done")
    p_poll.set_defaults(fn=cmd_poll)

    p_dl = sub.add_parser("download-last", help="Download last_video_url from config")
    p_dl.set_defaults(fn=cmd_download_last)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())