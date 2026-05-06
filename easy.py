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

BASE_DIR = Path(__file__).resolve().parent


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

    ("memory.enabled", "Use Markdown context memory (true/false)"),
    ("memory.context_files", "Markdown context files (JSON array)"),
    ("memory.max_chars", "Max context chars"),

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
    ("image.response_format", "Image response format (url/base64)"),

    ("image.system_prompt", "System prompt style instructions (prepended to image prompt)"),
    ("image.llm_system_prompt", "LLM system prompt for image prompt rewrite"),
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
def resolve_project_path(path_value: str) -> Path:
    p = Path(path_value).expanduser()
    if p.is_absolute():
        return p
    return BASE_DIR / p


def build_context_block(cfg: dict,
                        override_files: Optional[list[str]] = None,
                        disabled: bool = False) -> tuple[str, dict]:
    if disabled:
        return "", {"enabled": False, "files": [], "total_chars": 0, "truncated": False}

    configured = get_nested(cfg, "memory.context_files") or []
    enabled = bool(get_nested(cfg, "memory.enabled")) if get_nested(cfg, "memory.enabled") is not None else False

    if override_files:
        files = override_files
        enabled = True
    else:
        files = configured

    if isinstance(files, str):
        files = [files]
    if not enabled or not files:
        return "", {"enabled": False, "files": [], "total_chars": 0, "truncated": False}

    max_chars = int(get_nested(cfg, "memory.max_chars") or 12000)
    chunks: list[str] = []
    meta_files: list[dict] = []
    used_chars = 0
    truncated = False

    for item in files:
        path = resolve_project_path(str(item))
        entry = {"path": str(path), "exists": path.exists(), "chars": 0, "used_chars": 0}
        if not path.exists() or not path.is_file():
            meta_files.append(entry)
            continue
        text = path.read_text(encoding="utf-8").strip()
        entry["chars"] = len(text)
        if not text:
            meta_files.append(entry)
            continue

        remaining = max_chars - used_chars
        if remaining <= 0:
            truncated = True
            meta_files.append(entry)
            continue

        header = f"## Context File: {item}\n"
        available = max(0, remaining - len(header) - 2)
        piece = text[:available]
        if len(piece) < len(text):
            truncated = True
        entry["used_chars"] = len(piece)
        chunks.append(header + piece)
        used_chars += len(header) + len(piece) + 2
        meta_files.append(entry)

    if not chunks:
        return "", {"enabled": True, "files": meta_files, "total_chars": 0, "truncated": truncated}

    block = (
        "Runtime Markdown Context:\n"
        "Use the following project memory as background context. "
        "Treat it as lower priority than the user's latest request.\n\n"
        + "\n\n".join(chunks)
    )
    return block, {"enabled": True, "files": meta_files, "total_chars": used_chars, "truncated": truncated}


def merge_system_with_context(system_prompt: str, context_block: str) -> str:
    if not context_block:
        return system_prompt
    if not system_prompt:
        return context_block
    return f"{system_prompt.strip()}\n\n---\n\n{context_block.strip()}"


def session_enabled(cfg: dict, disabled: bool = False) -> bool:
    if disabled:
        return False
    value = get_nested(cfg, "memory.session.enabled")
    return bool(value) if value is not None else False


def get_session_path(cfg: dict) -> Path:
    return resolve_project_path(get_nested(cfg, "memory.session.file") or "memory/session.md")


def append_session_turn(cfg: dict, user_prompt: str, assistant_content: str, model: str) -> dict:
    path = get_session_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text("# EasyGrok Session\n\n", encoding="utf-8")

    stamp = datetime.now().isoformat(timespec="seconds")
    max_assistant_chars = int(get_nested(cfg, "memory.session.max_assistant_chars") or 4000)
    stored_content = assistant_content[:max_assistant_chars]
    truncated = len(stored_content) < len(assistant_content)

    turn = (
        f"## {stamp}\n\n"
        f"Model: `{model}`\n\n"
        "User:\n"
        f"{user_prompt.strip()}\n\n"
        "Assistant:\n"
        f"{stored_content.strip()}"
        + ("\n\n[assistant content truncated]" if truncated else "")
        + "\n\n"
    )

    with path.open("a", encoding="utf-8") as f:
        f.write(turn)

    return {
        "enabled": True,
        "file": str(path),
        "appended": True,
        "assistant_chars": len(assistant_content),
        "stored_assistant_chars": len(stored_content),
        "truncated": truncated,
    }


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


def save_image_bytes(image_bytes: bytes, dest_dir: Path, base_name: str, ext: str = ".jpg") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{base_name}{ext}"
    out_path.write_bytes(image_bytes)
    return out_path


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


def safe_get_image_url(resp) -> Optional[str]:
    try:
        return getattr(resp, "url", None)
    except Exception as e:
        print(f"Image URL unavailable: {e}", file=sys.stderr)
        return None


# ========= Run (uses in-memory cfg) =========
def run_text(cfg: dict,
             prompt_override: Optional[str] = None,
             system_override: Optional[str] = None,
             context_files: Optional[list[str]] = None,
             no_context: bool = False,
             no_session: bool = False) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = get_nested(cfg, "defaults.models.text_reasoning") or "grok-4-1-fast-reasoning"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    base_system_prompt = system_override or (get_nested(cfg, "text.system_prompt") or "You are a helpful assistant.")
    user_prompt = prompt_override or (get_nested(cfg, "text.user_prompt") or "Hello.")
    context_block, context_meta = build_context_block(cfg, context_files, no_context)
    system_prompt = merge_system_with_context(base_system_prompt, context_block)

    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=model)
    if system_prompt:
        chat.append(system(system_prompt))
    chat.append(user(user_prompt))

    resp = chat.sample()
    content = getattr(resp, "content", "") or ""
    model_name = getattr(resp, "model", model)
    session_meta = {"enabled": False, "appended": False}
    if session_enabled(cfg, no_session):
        session_meta = append_session_turn(cfg, user_prompt, content, model_name)

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "text",
        "model": model_name,
        "prompt": user_prompt,
        "system": system_prompt,
        "base_system": base_system_prompt,
        "context": context_meta,
        "session": session_meta,
        "content": content,
    }
    output_record(cfg, out_path, "text", record)


def run_vision(cfg: dict,
              image_url: Optional[str] = None,
              image_file: Optional[str] = None,
              prompt_override: Optional[str] = None,
              system_override: Optional[str] = None,
              context_files: Optional[list[str]] = None,
              no_context: bool = False) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = (
        get_nested(cfg, "defaults.models.vision")
        or get_nested(cfg, "defaults.models.vision_chat")
        or "grok-4.20-reasoning"
    )
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    base_system_prompt = system_override or (get_nested(cfg, "vision.system_prompt") or "You are a helpful assistant.")
    user_prompt = prompt_override or (get_nested(cfg, "vision.user_prompt") or "What's in this image?")
    context_block, context_meta = build_context_block(cfg, context_files, no_context)
    system_prompt = merge_system_with_context(base_system_prompt, context_block)

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

    chat.append(user(user_prompt, image(image_url=img_payload, detail="high")))
    resp = chat.sample()
    content = getattr(resp, "content", "") or ""

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "vision",
        "model": getattr(resp, "model", model),
        "prompt": user_prompt,
        "system": system_prompt,
        "base_system": base_system_prompt,
        "context": context_meta,
        "image": img_meta,
        "content": content,
    }
    output_record(cfg, out_path, "vision", record)


def run_image(cfg: dict,
              mode: str = "generate",
              prompt_override: Optional[str] = None,
              system_override: Optional[str] = None,
              llm_system_override: Optional[str] = None,
              rewrite_model_override: Optional[str] = None,
              model_override: Optional[str] = None,
              input_file: Optional[str] = None,
              input_files: Optional[list[str]] = None,
              image_urls_json: Optional[str] = None,
              n_override: Optional[int] = None,
              aspect_ratio_override: Optional[str] = None,
              resolution_override: Optional[str] = None,
              image_format_override: Optional[str] = None,
              download: bool = False,
              download_dir: Optional[str] = None) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    model = model_override or get_nested(cfg, "defaults.models.image") or "grok-imagine-image"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    aspect_ratio = aspect_ratio_override or get_nested(cfg, "image.aspect_ratio")
    resolution = resolution_override or get_nested(cfg, "image.resolution")
    image_format = image_format_override or get_nested(cfg, "image.response_format") or "url"
    if image_format not in ("url", "base64"):
        raise SystemExit("ERROR: image response format must be 'url' or 'base64'.")

    client = Client(api_key=get_api_key(), timeout=timeout_sec)

    urls: list[str] = []
    saved_files: list[str] = []
    system_prompt = system_override if system_override is not None else (get_nested(cfg, "image.system_prompt") or "")
    llm_system_prompt = (
        llm_system_override
        if llm_system_override is not None
        else (get_nested(cfg, "image.llm_system_prompt") or "")
    )
    rewrite_record = None

    def _rewrite_prompt_with_llm(prompt: str) -> str:
        nonlocal rewrite_record
        if not llm_system_prompt:
            return prompt
        rewrite_model = (
            rewrite_model_override
            or get_nested(cfg, "defaults.models.text_non_reasoning")
            or get_nested(cfg, "defaults.models.text_reasoning")
            or "grok-4-1-fast-non-reasoning"
        )
        chat = client.chat.create(model=rewrite_model)
        chat.append(system(llm_system_prompt))
        chat.append(user(
            "Rewrite the following request into one concise image-generation prompt. "
            "Preserve the user's visual intent and all safety/age/context constraints. "
            "Output only the final prompt text, with no markdown, no commentary, and no quotes.\n\n"
            f"Request:\n{prompt.strip()}"
        ))
        resp = chat.sample()
        rewritten = (getattr(resp, "content", "") or "").strip()
        if not rewritten:
            rewritten = prompt
        rewrite_record = {
            "model": getattr(resp, "model", rewrite_model),
            "system": llm_system_prompt,
            "input_prompt": prompt,
            "output_prompt": rewritten,
        }
        return rewritten

    def _effective_prompt(prompt: str) -> str:
        if not system_prompt:
            return prompt
        return (
            "Instruction profile:\n"
            f"{system_prompt.strip()}\n\n"
            "Image request:\n"
            f"{prompt.strip()}"
        )

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

    def _capture_single_image(resp, tag: str) -> None:
        nonlocal urls, saved_files
        if image_format == "base64":
            try:
                image_bytes = getattr(resp, "image", None)
            except Exception as e:
                print(f"Image base64 decode failed: {e}", file=sys.stderr)
                image_bytes = None
            if image_bytes:
                img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir)
                base = f"{tag}_{now_stamp()}_1"
                p = save_image_bytes(image_bytes, img_dir, base)
                saved_files.append(p.as_posix())
                return
            u = safe_get_image_url(resp)
            if u:
                urls = [u]
            return

        u = safe_get_image_url(resp)
        if u:
            urls = [u]
        _maybe_download(urls, tag)

    def _capture_batch_images(resps, tag: str) -> None:
        nonlocal urls, saved_files
        if image_format == "base64":
            img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir)
            for i, r in enumerate((resps or []), start=1):
                try:
                    image_bytes = getattr(r, "image", None)
                except Exception as e:
                    print(f"Image base64 decode failed for item {i}: {e}", file=sys.stderr)
                    image_bytes = None
                if not image_bytes:
                    u = safe_get_image_url(r)
                    if u:
                        urls.append(u)
                    continue
                base = f"{tag}_{now_stamp()}_{i}"
                p = save_image_bytes(image_bytes, img_dir, base)
                saved_files.append(p.as_posix())
            return

        for r in (resps or []):
            u = safe_get_image_url(r)
            if u:
                urls.append(u)
        _maybe_download(urls, tag)

    if mode == "generate":
        prompt = prompt_override or (get_nested(cfg, "image.prompt") or "")
        if not prompt:
            raise SystemExit("ERROR: image.prompt is empty.")
        llm_rewritten_prompt = _rewrite_prompt_with_llm(prompt)
        effective_prompt = _effective_prompt(llm_rewritten_prompt)
        resp = client.image.sample(
            prompt=effective_prompt, model=model, aspect_ratio=aspect_ratio, resolution=resolution, image_format=image_format
        )
        _capture_single_image(resp, "image_generate")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.generate",
            "model": getattr(resp, "model", model),
            "system": system_prompt,
            "llm_rewrite": rewrite_record,
            "prompt": prompt,
            "llm_rewritten_prompt": llm_rewritten_prompt,
            "effective_prompt": effective_prompt,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(saved_files if saved_files else urls),
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
        llm_rewritten_prompt = _rewrite_prompt_with_llm(prompt)
        effective_prompt = _effective_prompt(llm_rewritten_prompt)
        resp = client.image.sample(
            prompt=effective_prompt, model=model, image_url=data_url, aspect_ratio=aspect_ratio, resolution=resolution, image_format=image_format
        )
        _capture_single_image(resp, "image_edit")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.edit",
            "model": getattr(resp, "model", model),
            "system": system_prompt,
            "llm_rewrite": rewrite_record,
            "prompt": prompt,
            "llm_rewritten_prompt": llm_rewritten_prompt,
            "effective_prompt": effective_prompt,
            "input_file": in_file,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(saved_files if saved_files else urls),
        }
        output_record(cfg, out_path, "image", record)
        return

    if mode == "reference_edit":
        prompt = prompt_override or (get_nested(cfg, "image.reference_edit.prompt") or "")
        image_urls = get_nested(cfg, "image.reference_edit.image_urls") or []
        if input_files:
            image_urls = [_data_url_from_file(p) for p in input_files]
        if image_urls_json:
            try:
                image_urls = json.loads(image_urls_json)
            except Exception as e:
                raise SystemExit(f"ERROR: image_urls_json must be JSON array. {e}")

        if not prompt:
            raise SystemExit("ERROR: image.reference_edit.prompt is empty.")
        if not isinstance(image_urls, list) or len(image_urls) < 1:
            raise SystemExit("ERROR: image.reference_edit.image_urls must be a JSON array with >= 1 URL.")

        llm_rewritten_prompt = _rewrite_prompt_with_llm(prompt)
        effective_prompt = _effective_prompt(llm_rewritten_prompt)
        resp = client.image.sample(
            prompt=effective_prompt, model=model, image_urls=image_urls, aspect_ratio=aspect_ratio, resolution=resolution, image_format=image_format
        )
        _capture_single_image(resp, "image_reference_edit")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.reference_edit",
            "model": getattr(resp, "model", model),
            "system": system_prompt,
            "llm_rewrite": rewrite_record,
            "prompt": prompt,
            "llm_rewritten_prompt": llm_rewritten_prompt,
            "effective_prompt": effective_prompt,
            "input_files": input_files or [],
            "image_urls": [] if input_files else image_urls,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(saved_files if saved_files else urls),
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
        llm_rewritten_prompt = _rewrite_prompt_with_llm(prompt)
        effective_prompt = _effective_prompt(llm_rewritten_prompt)
        resps = client.image.sample_batch(
            prompt=effective_prompt, model=model, n=n, aspect_ratio=aspect_ratio, resolution=resolution, image_format=image_format
        )
        _capture_batch_images(resps, "image_batch")
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "image.batch",
            "model": model,
            "system": system_prompt,
            "llm_rewrite": rewrite_record,
            "prompt": prompt,
            "llm_rewritten_prompt": llm_rewritten_prompt,
            "effective_prompt": effective_prompt,
            "n": n,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "content": "\n".join(saved_files if saved_files else urls),
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
        print("      image.response_format is a config item; edit number + save to keep it as default")


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

            current_format = get_nested(cfg, "image.response_format") or "url"
            print(f"Current config image.response_format = {current_format}")
            ans = input(f"image response format [{current_format}] (url/base64, blank=use current): ").strip().lower()
            image_format = ans if ans else current_format
            if image_format not in ("url", "base64"):
                print("Canceled: image response format must be url or base64.")
                continue
            if image_format != current_format:
                print("Temporary override only. Edit image.response_format in the menu and save if you want to keep it.")

            dl = False
            if image_format == "url":
                dl = input("Download generated images now? (y/N): ").strip().lower() == "y"
            else:
                print("base64 mode: generated images will be saved directly as files.")

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
                    run_image(cfg, mode="edit", input_file=in_file, image_format_override=image_format, download=dl)
                elif imode == "reference_edit":
                    print("image_urls: use config by default. If you want override, paste JSON array. Blank=use config.")
                    j = input("image_urls_json: ").strip()
                    run_image(cfg, mode="reference_edit", image_urls_json=(j or None), image_format_override=image_format, download=dl)
                elif imode == "batch":
                    n = get_nested(cfg, "image.n") or 4
                    ans = input(f"n [{n}]: ").strip()
                    n2 = int(ans) if ans else int(n)
                    run_image(cfg, mode="batch", n_override=n2, image_format_override=image_format, download=dl)
                else:
                    run_image(cfg, mode="generate", image_format_override=image_format, download=dl)
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
    run_text(
        cfg,
        prompt_override=args.prompt,
        system_override=args.system,
        context_files=args.context,
        no_context=bool(args.no_context),
        no_session=bool(args.no_session),
    )
    return 0


def cmd_vision(args) -> int:
    cfg = load_json(get_cfg_path(args))
    run_vision(
        cfg,
        image_url=args.image_url,
        image_file=args.image_file,
        prompt_override=args.prompt,
        system_override=args.system,
        context_files=args.context,
        no_context=bool(args.no_context),
    )
    return 0


def cmd_image(args) -> int:
    cfg = load_json(get_cfg_path(args))
    run_image(
        cfg,
        mode=args.mode,
        prompt_override=args.prompt,
        system_override=args.system,
        llm_system_override=args.llm_system,
        rewrite_model_override=args.rewrite_model,
        model_override=args.model,
        input_file=args.input_file,
        input_files=args.input_files,
        image_urls_json=args.image_urls_json,
        n_override=args.n,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
        image_format_override=args.image_format,
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
    p_text.add_argument("--context", nargs="+", help="Override Markdown context files for this run")
    p_text.add_argument("--no-context", action="store_true", help="Disable Markdown context for this run")
    p_text.add_argument("--no-session", action="store_true", help="Do not append this text run to the session log")
    p_text.set_defaults(fn=cmd_text)

    p_vis = sub.add_parser("vision", help="Analyze image (URL or local file) with vision model")
    p_vis.add_argument("--image-url", help="Image URL")
    p_vis.add_argument("--image-file", help="Local image path (.png/.jpg)")
    p_vis.add_argument("prompt", nargs="?", help="Override user prompt")
    p_vis.add_argument("--system", help="Override system prompt")
    p_vis.add_argument("--context", nargs="+", help="Override Markdown context files for this run")
    p_vis.add_argument("--no-context", action="store_true", help="Disable Markdown context for this run")
    p_vis.set_defaults(fn=cmd_vision)

    p_img = sub.add_parser("image", help="Generate/edit images and save URLs (optional download)")
    p_img.add_argument("--mode", choices=["generate", "edit", "reference_edit", "batch"], default="generate")
    p_img.add_argument("prompt", nargs="?", help="Override prompt (otherwise from config)")
    p_img.add_argument("--system", help="System-style instructions to prepend to image prompt")
    p_img.add_argument("--llm-system", help="Actual chat-model system prompt used to rewrite the image prompt before generation")
    p_img.add_argument("--rewrite-model", help="Override chat model used for --llm-system prompt rewrite")
    p_img.add_argument("--model", help="Override image model (e.g. grok-imagine-image-pro)")
    p_img.add_argument("--input-file", help="(edit) Local image path (.png/.jpg)")
    p_img.add_argument("--input-files", nargs="+", help="(reference_edit) Local image paths (.png/.jpg)")
    p_img.add_argument("--image-urls-json", help="(reference_edit) JSON array of image URLs")
    p_img.add_argument("-n", type=int, help="(batch) number of images")
    p_img.add_argument("--aspect-ratio", help="Override aspect_ratio (e.g. 16:9)")
    p_img.add_argument("--resolution", help="Override resolution (e.g. 2k)")
    p_img.add_argument("--image-format", choices=["url", "base64"], help="Return URLs or save base64 image bytes")
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
