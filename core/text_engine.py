from typing import Optional
from datetime import datetime
import base64
from pathlib import Path

from xai_sdk import Client
from xai_sdk.chat import system, user, image

from .common import (
    append_session_turn,
    build_context_block,
    ensure_out_dir,
    get_api_key,
    get_nested,
    merge_system_with_context,
    output_record,
    session_enabled,
)


def _data_url_from_file(image_file: str) -> str:
    path = Path(image_file)
    if not path.exists():
        raise SystemExit(f"ERROR: Image file not found: {path.resolve()}")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


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


