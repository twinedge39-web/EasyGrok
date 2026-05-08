import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from xai_sdk import Client
from xai_sdk.chat import system, user

from .common import (
    ensure_images_dir,
    ensure_out_dir,
    get_api_key,
    get_nested,
    now_stamp,
    output_record,
    save_image_bytes,
)

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


def parse_json_object_from_text(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(raw[start:end + 1])
        if isinstance(obj, dict):
            return obj

    raise ValueError("No JSON object found in model output.")


def extract_image_prompt_from_natural_reply(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None

    # Prefer fenced prompt/code blocks.
    lines = raw.splitlines()
    in_block = False
    block_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_block:
                candidate = "\n".join(block_lines).strip()
                if candidate:
                    return candidate
                block_lines = []
                in_block = False
            else:
                in_block = True
                block_lines = []
            continue
        if in_block:
            block_lines.append(line)

    # Then quoted strings, which Grok often uses for suggested prompts.
    quoted: list[str] = []
    current: list[str] = []
    quote_char = ""
    for ch in raw:
        if quote_char:
            if ch == quote_char:
                candidate = "".join(current).strip()
                if len(candidate) >= 20:
                    quoted.append(candidate)
                current = []
                quote_char = ""
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            quote_char = ch
    if quoted:
        return max(quoted, key=len)

    # Finally, use the longest English-looking line.
    candidates = []
    for line in lines:
        stripped = line.strip(" -`*>")
        if len(stripped) < 30:
            continue
        ascii_letters = sum(1 for c in stripped if ("a" <= c.lower() <= "z"))
        if ascii_letters / max(len(stripped), 1) > 0.45:
            candidates.append(stripped)
    if candidates:
        return max(candidates, key=len)

    return None
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
        img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
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
                img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
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
            img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
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


def run_imagine(cfg: dict,
                prompt_override: Optional[str] = None,
                system_override: Optional[str] = None,
                rewrite_system_override: Optional[str] = None,
                rewrite_model_override: Optional[str] = None,
                model_override: Optional[str] = None,
                aspect_ratio_override: Optional[str] = None,
                resolution_override: Optional[str] = None,
                image_format_override: Optional[str] = None,
                download: bool = False,
                download_dir: Optional[str] = None,
                dry_run: bool = False) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    rewrite_model = (
        rewrite_model_override
        or get_nested(cfg, "defaults.models.text_non_reasoning")
        or get_nested(cfg, "defaults.models.text_reasoning")
        or "grok-4-1-fast-non-reasoning"
    )
    image_model = model_override or get_nested(cfg, "defaults.models.image") or "grok-imagine-image"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    user_request = prompt_override or (get_nested(cfg, "image.prompt") or "")
    if not user_request:
        raise SystemExit("ERROR: imagine prompt is empty.")

    aspect_ratio = aspect_ratio_override or get_nested(cfg, "image.aspect_ratio")
    resolution = resolution_override or get_nested(cfg, "image.resolution")
    image_format = image_format_override or get_nested(cfg, "image.response_format") or "url"
    if image_format not in ("url", "base64"):
        raise SystemExit("ERROR: image response format must be 'url' or 'base64'.")

    image_system = system_override if system_override is not None else (get_nested(cfg, "image.system_prompt") or "")
    rewrite_system = rewrite_system_override or (
        "You convert user requests into image-generation actions for Grok Imagine. "
        "Return only a valid JSON object. No markdown, no prose outside JSON. "
        "Schema: {\"action\":\"image.generate\",\"prompt\":\"...\",\"notes\":\"...\"}. "
        "The prompt must be a concise English image-generation prompt. "
        "If the request is not an image request or should not be executed, return "
        "{\"action\":\"none\",\"prompt\":\"\",\"notes\":\"brief reason\"}."
    )

    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=rewrite_model)
    chat.append(system(rewrite_system))
    chat.append(user(
        "Convert this user request into the JSON action schema.\n\n"
        f"User request:\n{user_request.strip()}"
    ))
    rewrite_resp = chat.sample()
    raw_rewrite = (getattr(rewrite_resp, "content", "") or "").strip()

    rewrite_error = None
    action_obj = None
    try:
        action_obj = parse_json_object_from_text(raw_rewrite)
    except Exception as e:
        rewrite_error = str(e)

    urls: list[str] = []
    saved_files: list[str] = []
    image_error = None
    image_resp_model = image_model

    if rewrite_error:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "imagine.rewrite_error",
            "user_request": user_request,
            "rewrite": {
                "model": getattr(rewrite_resp, "model", rewrite_model),
                "system": rewrite_system,
                "raw_content": raw_rewrite,
                "error": rewrite_error,
            },
            "content": raw_rewrite,
        }
        output_record(cfg, out_path, "imagine", record)
        raise SystemExit("ERROR: imagine rewrite did not return valid JSON.")

    action = str(action_obj.get("action", "")).strip()
    image_prompt = str(action_obj.get("prompt", "")).strip()
    notes = str(action_obj.get("notes", "")).strip()

    if action != "image.generate" or not image_prompt:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "imagine.no_action",
            "user_request": user_request,
            "rewrite": {
                "model": getattr(rewrite_resp, "model", rewrite_model),
                "system": rewrite_system,
                "raw_content": raw_rewrite,
                "action": action_obj,
            },
            "content": notes or raw_rewrite,
        }
        output_record(cfg, out_path, "imagine", record)
        return

    if image_system:
        effective_prompt = (
            "Instruction profile:\n"
            f"{image_system.strip()}\n\n"
            "Image request:\n"
            f"{image_prompt}"
        )
    else:
        effective_prompt = image_prompt

    if not dry_run:
        try:
            image_resp = client.image.sample(
                prompt=effective_prompt,
                model=image_model,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                image_format=image_format,
            )
            image_resp_model = getattr(image_resp, "model", image_model)
            if image_format == "base64":
                image_bytes = getattr(image_resp, "image", None)
                if image_bytes:
                    img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
                    p = save_image_bytes(image_bytes, img_dir, f"image_imagine_{now_stamp()}_1")
                    saved_files.append(p.as_posix())
                else:
                    u = safe_get_image_url(image_resp)
                    if u:
                        urls.append(u)
            else:
                u = safe_get_image_url(image_resp)
                if u:
                    urls.append(u)
                if download:
                    img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
                    for i, url_value in enumerate(urls, start=1):
                        p = download_url_to_file(url_value, img_dir, f"image_imagine_{now_stamp()}_{i}")
                        if p:
                            saved_files.append(p.as_posix())
        except Exception as e:
            image_error = str(e)

    output_lines = [
        "PROMPT:",
        image_prompt,
    ]
    if dry_run:
        output_lines.extend(["", "DRY RUN: image generation skipped."])
    elif saved_files or urls:
        output_lines.extend(["", "OUTPUT:"])
        output_lines.extend(saved_files if saved_files else urls)
    elif image_error:
        output_lines.extend(["", "IMAGE ERROR:", image_error])

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "imagine",
        "user_request": user_request,
        "rewrite": {
            "model": getattr(rewrite_resp, "model", rewrite_model),
            "system": rewrite_system,
            "raw_content": raw_rewrite,
            "action": action_obj,
            "prompt": image_prompt,
            "notes": notes,
        },
        "image": {
            "executed": not dry_run,
            "model": image_resp_model,
            "system": image_system,
            "effective_prompt": effective_prompt,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "error": image_error,
        },
        "content": "\n".join(output_lines),
    }
    output_record(cfg, out_path, "imagine", record)

    if image_error:
        raise SystemExit("ERROR: imagine image generation failed.")


def run_imagine_natural(cfg: dict,
                        prompt_override: Optional[str] = None,
                        system_override: Optional[str] = None,
                        language_model_override: Optional[str] = None,
                        model_override: Optional[str] = None,
                        aspect_ratio_override: Optional[str] = None,
                        resolution_override: Optional[str] = None,
                        image_format_override: Optional[str] = None,
                        download: bool = False,
                        download_dir: Optional[str] = None,
                        dry_run: bool = False) -> None:
    timeout_sec = int(get_nested(cfg, "defaults.timeout_sec") or 3600)
    language_model = (
        language_model_override
        or get_nested(cfg, "defaults.models.text_reasoning")
        or "grok-4-1-fast-reasoning"
    )
    image_model = model_override or get_nested(cfg, "defaults.models.image") or "grok-imagine-image"
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)

    user_request = prompt_override or (get_nested(cfg, "image.prompt") or "")
    if not user_request:
        raise SystemExit("ERROR: imagine-natural prompt is empty.")

    aspect_ratio = aspect_ratio_override or get_nested(cfg, "image.aspect_ratio")
    resolution = resolution_override or get_nested(cfg, "image.resolution")
    image_format = image_format_override or get_nested(cfg, "image.response_format") or "url"
    if image_format not in ("url", "base64"):
        raise SystemExit("ERROR: image response format must be 'url' or 'base64'.")

    language_system = system_override or (
        "You are Grok. Reply honestly. If you cannot directly render an image in this text channel, "
        "help the user by giving a concise image-generation prompt that could be used with Grok Imagine."
    )
    natural_user_prompt = (
        "Please create this image. If you cannot directly create or display the image here, "
        "provide the best prompt to generate it.\n\n"
        f"Request:\n{user_request.strip()}"
    )

    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=language_model)
    chat.append(system(language_system))
    chat.append(user(natural_user_prompt))
    language_resp = chat.sample()
    raw_reply = (getattr(language_resp, "content", "") or "").strip()
    extracted_prompt = extract_image_prompt_from_natural_reply(raw_reply)

    urls: list[str] = []
    saved_files: list[str] = []
    image_error = None
    image_resp_model = image_model

    if not extracted_prompt:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": "imagine-natural.extract_error",
            "user_request": user_request,
            "language": {
                "model": getattr(language_resp, "model", language_model),
                "system": language_system,
                "prompt": natural_user_prompt,
                "raw_content": raw_reply,
                "extracted_prompt": None,
            },
            "content": raw_reply,
        }
        output_record(cfg, out_path, "imagine_natural", record)
        raise SystemExit("ERROR: could not extract an image prompt from natural reply.")

    if not dry_run:
        try:
            image_resp = client.image.sample(
                prompt=extracted_prompt,
                model=image_model,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                image_format=image_format,
            )
            image_resp_model = getattr(image_resp, "model", image_model)
            if image_format == "base64":
                image_bytes = getattr(image_resp, "image", None)
                if image_bytes:
                    img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
                    p = save_image_bytes(image_bytes, img_dir, f"image_imagine_natural_{now_stamp()}_1")
                    saved_files.append(p.as_posix())
                else:
                    u = safe_get_image_url(image_resp)
                    if u:
                        urls.append(u)
            else:
                u = safe_get_image_url(image_resp)
                if u:
                    urls.append(u)
                if download:
                    img_dir = Path(download_dir) if download_dir else ensure_images_dir(out_dir, get_nested(cfg, "defaults.output.image_dir"))
                    for i, url_value in enumerate(urls, start=1):
                        p = download_url_to_file(url_value, img_dir, f"image_imagine_natural_{now_stamp()}_{i}")
                        if p:
                            saved_files.append(p.as_posix())
        except Exception as e:
            image_error = str(e)

    output_lines = [
        "NATURAL REPLY:",
        raw_reply,
        "",
        "EXTRACTED PROMPT:",
        extracted_prompt,
    ]
    if dry_run:
        output_lines.extend(["", "DRY RUN: image generation skipped."])
    elif saved_files or urls:
        output_lines.extend(["", "OUTPUT:"])
        output_lines.extend(saved_files if saved_files else urls)
    elif image_error:
        output_lines.extend(["", "IMAGE ERROR:", image_error])

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": "imagine-natural",
        "user_request": user_request,
        "language": {
            "model": getattr(language_resp, "model", language_model),
            "system": language_system,
            "prompt": natural_user_prompt,
            "raw_content": raw_reply,
            "extracted_prompt": extracted_prompt,
        },
        "image": {
            "executed": not dry_run,
            "model": image_resp_model,
            "effective_prompt": extracted_prompt,
            "image_format": image_format,
            "options": {"aspect_ratio": aspect_ratio, "resolution": resolution},
            "urls": urls,
            "saved_files": saved_files,
            "error": image_error,
        },
        "content": "\n".join(output_lines),
    }
    output_record(cfg, out_path, "imagine_natural", record)

    if image_error:
        raise SystemExit("ERROR: imagine-natural image generation failed.")


