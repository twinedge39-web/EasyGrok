import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Optional


from xai_sdk import Client
from xai_sdk.chat import system, user, image


# ========= Field Groups =========
FIELDS_TEXT_VISION = [
    ("defaults.timeout_sec", "Timeout (sec)"),
    ("defaults.output.dir", "Output directory"),
    ("defaults.output.save_raw_json", "Save raw JSON (true/false)"),
    ("defaults.output.save_md", "Save Markdown (true/false)"),
    ("defaults.output.print_mode", "Print mode (minimal/content/none)"),

    ("defaults.models.text_reasoning", "Text model (reasoning)"),
    ("defaults.models.text_non_reasoning", "Text model (non-reasoning)"),
    ("defaults.models.vision", "Vision model"),

    ("text.system_prompt", "System prompt (text)"),
    ("text.user_prompt", "User prompt (text)"),

    ("vision.system_prompt", "System prompt (vision)"),
    ("vision.user_prompt", "User prompt (vision)"),
    ("vision.image_url", "Vision image_url (optional; for menu-run)"),
]

FIELDS_IMAGE = [
    ("defaults.timeout_sec", "Timeout (sec)"),
    ("defaults.output.dir", "Output directory"),
    ("defaults.output.save_raw_json", "Save raw JSON (true/false)"),
    ("defaults.output.save_md", "Save Markdown (true/false)"),
    ("defaults.output.print_mode", "Print mode (minimal/content/none)"),

    ("defaults.models.image", "Image model"),

    ("image.prompt", "Image prompt (generate/batch)"),
    ("image.n", "Image n (batch count)"),
    ("image.aspect_ratio", "Image aspect_ratio (e.g. 16:9)"),
    ("image.resolution", "Image resolution (e.g. 2k)"),

    ("image.edit.input_file", "Image edit input_file (local path)"),
    ("image.edit.prompt", "Image edit prompt"),

    ("image.reference_edit.prompt", "Image reference_edit prompt"),
    ("image.reference_edit.image_urls", "Image reference_edit image_urls (JSON array)"),
]


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


def set_nested(d: dict, dotted_key: str, value: str) -> None:
    """Set nested key. Tries: bool -> JSON(list/dict) -> int -> float -> string."""
    keys = dotted_key.split(".")
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]

    v = value.strip()

    # bool
    if v.lower() in ("true", "false"):
        cur[keys[-1]] = (v.lower() == "true")
        return

    # JSON list/dict (for image_urls etc.)
    if (v.startswith("[") and v.endswith("]")) or (v.startswith("{") and v.endswith("}")):
        try:
            cur[keys[-1]] = json.loads(v)
            return
        except Exception:
            pass

    # int
    try:
        cur[keys[-1]] = int(v)
        return
    except ValueError:
        pass

    # float
    try:
        cur[keys[-1]] = float(v)
        return
    except ValueError:
        pass

    # string
    cur[keys[-1]] = v


def backup(path: Path, data: dict) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak_{stamp}")
    save_json(bak, data)
    return bak


# ========= Shared utils =========
def ensure_out_dir(out_dir: str) -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_images_dir(out_dir: str) -> Path:
    base = ensure_out_dir(out_dir)
    p = base / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


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


def output_record(cfg: dict, out_path: Path, prefix: str, record: dict) -> None:
    save_raw = bool(
        get_nested(cfg, "defaults.output.save_raw_json")
        if get_nested(cfg, "defaults.output.save_raw_json") is not None
        else True
    )
    save_md = bool(
        get_nested(cfg, "defaults.output.save_md")
        if get_nested(cfg, "defaults.output.save_md") is not None
        else True
    )
    print_mode = get_nested(cfg, "defaults.output.print_mode") or "minimal"

    stamp = now_stamp()
    json_path = out_path / f"{prefix}_raw_{stamp}.json"
    md_path = out_path / f"{prefix}_{stamp}.md"

    content = record.get("content") or ""

    if save_raw:
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    if save_md:
        md_path.write_text(content, encoding="utf-8")

    if print_mode == "none":
        return

    if print_mode == "content":
        print(content)
        return

    # minimal
    if save_raw:
        print(f"OK: saved {json_path.as_posix()}")
    else:
        print("OK")

    if content:
        print("\n---\n")
        print(content)


def _data_url_from_file(image_file: str) -> str:
    p = Path(image_file)
    if not p.exists():
        raise SystemExit(f"ERROR: Image file not found: {p.resolve()}")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _guess_ext_from_headers(content_type: Optional[str], url: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"

    # fallback from URL
    u = url.lower().split("?")[0].split("#")[0]
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if u.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".bin"


def download_url_to_file(url: str, dest_dir: Path, base_name: str) -> Optional[Path]:
    """
    Download image from URL to dest_dir. Returns saved file path or None on failure.
    This does NOT guarantee long-term availability; it just tries immediately.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type")
            data = resp.read()

        ext = _guess_ext_from_headers(content_type, url)
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


# ========= Run (uses in-memory cfg) =========
def run_text(cfg: dict, prompt_override: Optional[str] = None, system_override: Optional[str] = None) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = get_nested(cfg, "defaults.models.text_reasoning") or "grok-4-1-fast-reasoning"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    system_prompt = system_override or (get_nested(cfg, "text.system_prompt") or "You are a helpful assistant.")
    user_prompt = prompt_override or (get_nested(cfg, "text.user_prompt") or "Hello.")

    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=model)
    if system_prompt:
        chat.append(system(system_prompt))
    chat.append(user(user_prompt))

    resp = chat.sample()
    content = getattr(resp, "content", "") or ""

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "text",
        "model": getattr(resp, "model", model),
        "prompt": user_prompt,
        "system": system_prompt,
        "content": content,
    }
    output_record(cfg, out_path, "text", record)


def run_vision(cfg: dict,
              image_url: Optional[str] = None,
              image_file: Optional[str] = None,
              prompt_override: Optional[str] = None,
              system_override: Optional[str] = None) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = get_nested(cfg, "defaults.models.vision") or "grok-2-vision-1212"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    system_prompt = system_override or (get_nested(cfg, "vision.system_prompt") or "You are a helpful assistant.")
    user_prompt = prompt_override or (get_nested(cfg, "vision.user_prompt") or "What's in this image?")

    if image_url and image_file:
        raise SystemExit("ERROR: Use either image_url or image_file, not both.")

    if not image_url and not image_file:
        image_url = get_nested(cfg, "vision.image_url")

    if image_url:
        img_payload = image_url
        img_meta = {"url_or_data": image_url}
    elif image_file:
        img_payload = _data_url_from_file(image_file)
        img_meta = {"url_or_data": f"file:{image_file}"}
    else:
        raise SystemExit("ERROR: No image source. Set vision.image_url or provide --image-url/--image-file.")

    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=model)
    if system_prompt:
        chat.append(system(system_prompt))

    chat.append(user(user_prompt, image(img_payload)))
    resp = chat.sample()
    content = getattr(resp, "content", "") or ""

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "vision",
        "model": getattr(resp, "model", model),
        "prompt": user_prompt,
        "system": system_prompt,
        "image": img_meta,
        "content": content,
    }
    output_record(cfg, out_path, "vision", record)


def run_image(cfg: dict,
              mode: str = "generate",
              prompt_override: Optional[str] = None,
              input_file: Optional[str] = None,
              image_urls_json: Optional[str] = None,
              n_override: Optional[int] = None,
              aspect_ratio_override: Optional[str] = None,
              resolution_override: Optional[str] = None,
              download: bool = False,
              download_dir: Optional[str] = None) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = get_nested(cfg, "defaults.models.image") or "grok-imagine-image"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    aspect_ratio = aspect_ratio_override or get_nested(cfg, "image.aspect_ratio")
    resolution = resolution_override or get_nested(cfg, "image.resolution")

    client = Client(api_key=get_api_key(), timeout=timeout_sec)

    urls: list[str] = []
    saved_files: list[str] = []

    def _maybe_download(url_list: list[str], tag: str) -> None:
        nonlocal saved_files
        if not download:
            return
        img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir)
        for i, u in enumerate(url_list, start=1):
            base = f"{tag}_{now_stamp()}_{i}"
            p = download_url_to_file(u, img_dir, base)
            if p:
                saved_files.append(p.as_posix())

    if mode == "generate":
        prompt = prompt_override or (get_nested(cfg, "image.prompt") or "")
        if not prompt:
            raise SystemExit("ERROR: image.prompt is empty.")
        resp = client.image.sample(
            prompt=prompt, model=model, aspect_ratio=aspect_ratio, resolution=resolution
        )
        u = getattr(resp, "url", None)
        if u:
            urls = [u]
        _maybe_download(urls, "image_generate")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.generate",
            "model": getattr(resp, "model", model),
            "prompt": prompt,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(urls) if urls else "",
        }
        output_record(cfg, out_path, "image", record)
        return

    if mode == "edit":
        prompt = prompt_override or (get_nested(cfg, "image.edit.prompt") or "")
        in_file = input_file or get_nested(cfg, "image.edit.input_file")
        if not prompt:
            raise SystemExit("ERROR: image.edit.prompt is empty.")
        if not in_file:
            raise SystemExit("ERROR: image.edit.input_file is empty.")
        data_url = _data_url_from_file(in_file)
        resp = client.image.sample(
            prompt=prompt, model=model, image_url=data_url, aspect_ratio=aspect_ratio, resolution=resolution
        )
        u = getattr(resp, "url", None)
        if u:
            urls = [u]
        _maybe_download(urls, "image_edit")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.edit",
            "model": getattr(resp, "model", model),
            "prompt": prompt,
            "input_file": in_file,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(urls) if urls else "",
        }
        output_record(cfg, out_path, "image", record)
        return

    if mode == "reference_edit":
        prompt = prompt_override or (get_nested(cfg, "image.reference_edit.prompt") or "")
        image_urls = get_nested(cfg, "image.reference_edit.image_urls") or []
        if image_urls_json:
            try:
                image_urls = json.loads(image_urls_json)
            except Exception as e:
                raise SystemExit(f"ERROR: image_urls_json must be JSON array. {e}")

        if not prompt:
            raise SystemExit("ERROR: image.reference_edit.prompt is empty.")
        if not isinstance(image_urls, list) or len(image_urls) < 1:
            raise SystemExit("ERROR: image.reference_edit.image_urls must be a JSON array with >= 1 URL.")

        resp = client.image.sample(
            prompt=prompt, model=model, image_urls=image_urls, aspect_ratio=aspect_ratio, resolution=resolution
        )
        u = getattr(resp, "url", None)
        if u:
            urls = [u]
        _maybe_download(urls, "image_reference_edit")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.reference_edit",
            "model": getattr(resp, "model", model),
            "prompt": prompt,
            "image_urls": image_urls,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(urls) if urls else "",
        }
        output_record(cfg, out_path, "image", record)
        return

    if mode == "batch":
        prompt = prompt_override or (get_nested(cfg, "image.prompt") or "")
        n = int(n_override or (get_nested(cfg, "image.n") or 4))
        if not prompt:
            raise SystemExit("ERROR: image.prompt is empty.")
        if n < 1:
            raise SystemExit("ERROR: n must be >= 1.")
        resps = client.image.sample_batch(
            prompt=prompt, model=model, n=n, aspect_ratio=aspect_ratio, resolution=resolution
        )
        for r in (resps or []):
            u = getattr(r, "url", None)
            if u:
                urls.append(u)
        _maybe_download(urls, "image_batch")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.batch",
            "model": model,
            "prompt": prompt,
            "n": n,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(urls) if urls else "",
        }
        output_record(cfg, out_path, "image", record)
        return

    raise SystemExit(f"ERROR: Unknown mode: {mode}")


# ========= Menu (filtered + run) =========
def _select_menu_mode() -> str:
    while True:
        print("\n=== MENU MODE ===")
        print("1) text + vision")
        print("2) image")
        print("3) all (debug)")
        print("Q) quit")
        c = input("> ").strip().lower()
        if c == "1":
            return "tv"
        if c == "2":
            return "img"
        if c == "3":
            return "all"
        if c == "q":
            raise SystemExit(0)


def _fields_for_mode(mode: str):
    if mode == "tv":
        return FIELDS_TEXT_VISION
    if mode == "img":
        return FIELDS_IMAGE
    return FIELDS_TEXT_VISION + [x for x in FIELDS_IMAGE if x not in FIELDS_TEXT_VISION]


def _menu_help(mode: str) -> None:
    print("\n=== Actions ===")
    print("number : edit item")
    print("S      : save config")
    print("Q      : quit (no save)")
    print("M      : switch menu mode (text+vision / image)")
    print("R      : refresh view")
    print("T      : RUN text (uses current in-memory config)")
    print("V      : RUN vision (uses current in-memory config)")
    print("I      : RUN image (uses current in-memory config)")
    if mode == "img":
        print("      (I prompts for image mode: generate/edit/reference_edit/batch)")


def _prompt_save_if_needed(cfg_path: Path, cfg: dict) -> None:
    ans = input("Save config before run? (y/N): ").strip().lower()
    if ans == "y":
        save_json(cfg_path, cfg)
        print(f"OK: saved {cfg_path}")


def filtered_menu_with_run(cfg_path: Path, cfg: dict) -> None:
    mode = _select_menu_mode()

    while True:
        fields = _fields_for_mode(mode)
        print("\n=== Config Menu ===")
        print(f"[mode: {mode}]  (M: switch)")
        for i, (key, label) in enumerate(fields, start=1):
            val = get_nested(cfg, key)
            short = "(unset)" if val is None else str(val)
            if len(short) > 90:
                short = short[:87] + "..."
            print(f"{i:2d}) {label}\n    {key} = {short}")

        _menu_help(mode)
        choice = input("> ").strip()
        c = choice.lower()

        if c == "q":
            return
        if c == "r":
            continue
        if c == "m":
            mode = _select_menu_mode()
            continue
        if c == "s":
            save_json(cfg_path, cfg)
            print(f"OK: saved {cfg_path}")
            continue

        if c == "t":
            _prompt_save_if_needed(cfg_path, cfg)
            try:
                run_text(cfg)
            except Exception as e:
                print(f"RUN text failed: {e}", file=sys.stderr)
            continue

        if c == "v":
            _prompt_save_if_needed(cfg_path, cfg)
            img_url = get_nested(cfg, "vision.image_url")
            img_file = None
            if not img_url:
                print("Vision needs image source.")
                print("1) use image-url")
                print("2) use local image-file")
                pick = input("> ").strip()
                if pick == "1":
                    img_url = input("image-url: ").strip()
                elif pick == "2":
                    img_file = input("image-file path: ").strip()
                else:
                    print("Canceled.")
                    continue
            try:
                run_vision(cfg, image_url=img_url, image_file=img_file)
            except Exception as e:
                print(f"RUN vision failed: {e}", file=sys.stderr)
            continue

        if c == "i":
            _prompt_save_if_needed(cfg_path, cfg)

            # download?
            dl = input("Download generated images now? (y/N): ").strip().lower() == "y"

            print("\nImage mode:")
            print("1) generate")
            print("2) edit")
            print("3) reference_edit")
            print("4) batch")
            pick = input("> ").strip()
            mode_map = {"1": "generate", "2": "edit", "3": "reference_edit", "4": "batch"}
            imode = mode_map.get(pick)
            if not imode:
                print("Canceled.")
                continue

            try:
                if imode == "edit":
                    in_file = get_nested(cfg, "image.edit.input_file")
                    ans = input(f"input_file [{in_file}]: ").strip()
                    if ans:
                        in_file = ans
                    run_image(cfg, mode="edit", input_file=in_file, download=dl)
                elif imode == "reference_edit":
                    print("image_urls: use config by default. If you want override, paste JSON array. Blank=use config.")
                    j = input("image_urls_json: ").strip()
                    run_image(cfg, mode="reference_edit", image_urls_json=(j or None), download=dl)
                elif imode == "batch":
                    n = get_nested(cfg, "image.n") or 4
                    ans = input(f"n [{n}]: ").strip()
                    n2 = int(ans) if ans else int(n)
                    run_image(cfg, mode="batch", n_override=n2, download=dl)
                else:
                    run_image(cfg, mode="generate", download=dl)
            except Exception as e:
                print(f"RUN image failed: {e}", file=sys.stderr)
            continue

        if not choice.isdigit():
            print("Invalid input.")
            continue

        idx = int(choice)
        if not (1 <= idx <= len(fields)):
            print("Out of range.")
            continue

        key, label = fields[idx - 1]
        cur = get_nested(cfg, key)
        print(f"\nEditing: {label}\n  {key}\nCurrent: {cur}")
        newv = input("New value (blank=cancel): ")
        if newv.strip() == "":
            continue

        set_nested(cfg, key, newv)
        print("OK: updated in memory.")


# ========= CLI Commands =========
def cmd_menu(args) -> int:
    cfg_path = get_cfg_path(args)
    cfg = load_json(cfg_path)

    bak = backup(cfg_path, cfg)
    print(f"Backup created: {bak}")

    filtered_menu_with_run(cfg_path, cfg)
    return 0


def cmd_text(args) -> int:
    cfg = load_json(get_cfg_path(args))
    run_text(cfg, prompt_override=args.prompt, system_override=args.system)
    return 0


def cmd_vision(args) -> int:
    cfg = load_json(get_cfg_path(args))
    run_vision(
        cfg,
        image_url=args.image_url,
        image_file=args.image_file,
        prompt_override=args.prompt,
        system_override=args.system
    )
    return 0


def cmd_image(args) -> int:
    cfg = load_json(get_cfg_path(args))
    run_image(
        cfg,
        mode=args.mode,
        prompt_override=args.prompt,
        input_file=args.input_file,
        image_urls_json=args.image_urls_json,
        n_override=args.n,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
        download=bool(args.download),
        download_dir=args.download_dir,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="easy.py",
        description="Grok EASY runner (text + menu + vision + image) [menu supports run + optional download]"
    )
    ap.add_argument("-c", "--config", help="Config JSON path (default: ./config/config.user.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_menu = sub.add_parser("menu", help="Interactive config editor + RUN (creates backup)")
    p_menu.set_defaults(fn=cmd_menu)

    p_text = sub.add_parser("text", help="Run text LLM")
    p_text.add_argument("prompt", nargs="?", help="Override user prompt")
    p_text.add_argument("--system", help="Override system prompt")
    p_text.set_defaults(fn=cmd_text)

    p_vis = sub.add_parser("vision", help="Analyze image (URL or local file) with vision model")
    p_vis.add_argument("--image-url", help="Image URL")
    p_vis.add_argument("--image-file", help="Local image path (.png/.jpg)")
    p_vis.add_argument("prompt", nargs="?", help="Override user prompt")
    p_vis.add_argument("--system", help="Override system prompt")
    p_vis.set_defaults(fn=cmd_vision)

    p_img = sub.add_parser("image", help="Generate/edit images and save URLs (optional download)")
    p_img.add_argument("--mode", choices=["generate", "edit", "reference_edit", "batch"], default="generate")
    p_img.add_argument("prompt", nargs="?", help="Override prompt (otherwise from config)")
    p_img.add_argument("--input-file", help="(edit) Local image path (.png/.jpg)")
    p_img.add_argument("--image-urls-json", help="(reference_edit) JSON array of image URLs")
    p_img.add_argument("-n", type=int, help="(batch) number of images")
    p_img.add_argument("--aspect-ratio", help="Override aspect_ratio (e.g. 16:9)")
    p_img.add_argument("--resolution", help="Override resolution (e.g. 2k)")
    p_img.add_argument("--download", action="store_true", help="Download returned URL(s) immediately to ./out/images/")
    p_img.add_argument("--download-dir", help="Custom download directory (default: ./out/images/)")
    p_img.set_defaults(fn=cmd_image)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())