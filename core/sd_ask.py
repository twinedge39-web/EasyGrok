import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from xai_sdk import Client
from xai_sdk.chat import system, user

from core.common import BASE_DIR, clear_dead_local_proxy_env, get_api_key, get_nested, safe_print
from core import sd_config


DEFAULT_MODEL = "grok-4-1-fast-reasoning"
DEFAULT_PERSONA_PATH = BASE_DIR / "config" / "sd_ask_persona.md"
DEFAULT_SESSION_MEMORY_PATH = BASE_DIR / "memory" / "sd_ask_session.md"


SYSTEM_PROMPT = """You write Stable Diffusion local API config patches.

Return only one JSON object.
Do not use Markdown.
Do not explain.
Do not add keys outside the allowed paths.
Use this exact envelope:
{
  "sd_config_patch": {
    "generation": {
      "prompt": "...",
      "negative_prompt": "...",
      "common": {
        "n_iter": 2,
        "seed": -1
      }
    }
  }
}

Rules:
- Preserve the user's intent.
- Prefer prompt and negative_prompt edits unless another parameter is clearly requested.
- Keep batch_size at 1.
- Keep n_iter between 1 and 4.
- Keep SD1.5/yayoi constraints in mind: face in frame, upper body or close portrait is safer than distant full body.
- For local 8GB VRAM, avoid reference-image/controlnet/hires/adetailer keys.
- Use short English prompt phrases.
- The patch must be accepted by the allowed path list.
"""


CHAT_SYSTEM_PROMPT = """You are an SD Grok chat assistant for a local image generation adapter.

Return only one JSON object.
Do not use Markdown.
Use this exact envelope:
{
  "assistant_message": "short Japanese reply to the user",
  "sd_config_patch": {
    "generation": {
      "prompt": "...",
      "negative_prompt": "...",
      "common": {
        "n_iter": 2,
        "seed": -1
      }
    }
  }
}

Rules:
- First answer the user's intent in assistant_message, briefly in Japanese.
- Then provide a safe draft patch.
- Do not simply repeat the current prompt unless the user asks to preserve it exactly.
- If the request is vague, improve clarity, composition, and model fit.
- Preserve the user's intent, but remove accidental drift.
- Do not introduce age numbers, childlike wording, or explicit nudity by default.
- Prefer adult Japanese woman / East Asian features when the model is yayoiMix-like.
- Prefer prompt and negative_prompt edits unless another parameter is clearly requested.
- Keep batch_size at 1.
- Keep n_iter between 1 and 4.
- Keep SD1.5/yayoi constraints in mind: face in frame, upper body or close portrait is safer than distant full body.
- For local 8GB VRAM, avoid reference-image/controlnet/hires/adetailer keys.
- Use short English prompt phrases in the patch.
- The patch must be accepted by the allowed path list.
"""


def ask_for_sd_patch(
    easy_cfg: dict,
    current_sd_cfg: dict,
    request_text: str,
    input_json: dict | None = None,
    model_override: str | None = None,
    persona_path: str | None = None,
    session_memory_path: str | None = None,
    use_session_memory: bool = True,
) -> dict[str, Any]:
    model = model_override or get_nested(easy_cfg, "defaults.models.text_reasoning") or DEFAULT_MODEL
    timeout_sec = int(get_nested(easy_cfg, "defaults.timeout_sec") or 3600)

    clear_dead_local_proxy_env()
    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=model)
    chat.append(system(build_system_prompt(persona_path, session_memory_path, use_session_memory)))
    chat.append(user(build_user_prompt(current_sd_cfg, request_text, input_json)))
    resp = sample_chat(chat)
    content = getattr(resp, "content", "") or ""
    parsed = extract_json_object(content)
    return {
        "model": getattr(resp, "model", model),
        "content": content,
        "patch": parsed,
    }


def ask_for_sd_chat(
    easy_cfg: dict,
    current_sd_cfg: dict,
    request_text: str,
    chat_history: list[dict[str, str]] | None = None,
    input_json: dict | None = None,
    model_override: str | None = None,
    persona_path: str | None = None,
    session_memory_path: str | None = None,
    use_session_memory: bool = True,
) -> dict[str, Any]:
    model = model_override or get_nested(easy_cfg, "defaults.models.text_reasoning") or DEFAULT_MODEL
    timeout_sec = int(get_nested(easy_cfg, "defaults.timeout_sec") or 3600)

    clear_dead_local_proxy_env()
    client = Client(api_key=get_api_key(), timeout=timeout_sec)
    chat = client.chat.create(model=model)
    chat.append(system(build_system_prompt(
        persona_path,
        session_memory_path,
        use_session_memory,
        base_prompt=CHAT_SYSTEM_PROMPT,
        chat_mode=True,
    )))
    chat.append(user(build_chat_user_prompt(current_sd_cfg, request_text, chat_history, input_json)))
    resp = sample_chat(chat)
    content = getattr(resp, "content", "") or ""
    parsed = extract_json_object(content)
    patch = {"sd_config_patch": parsed.get("sd_config_patch", {})}
    return {
        "model": getattr(resp, "model", model),
        "content": content,
        "assistant_message": str(parsed.get("assistant_message") or ""),
        "patch": patch,
        "chat_response": parsed,
    }


def build_system_prompt(
    persona_path: str | None = None,
    session_memory_path: str | None = None,
    use_session_memory: bool = True,
    base_prompt: str = SYSTEM_PROMPT,
    chat_mode: bool = False,
) -> str:
    parts = [base_prompt.strip()]
    persona = load_text_file(persona_path, DEFAULT_PERSONA_PATH)
    if persona:
        if chat_mode:
            persona = persona.replace("You are not a general chat assistant in this mode.", "")
            persona = persona.replace("Output only the requested JSON object.", "")
            persona = persona.replace("Return JSON only.", "")
            persona = persona.replace("Do not include prose outside JSON.", "")
        parts.append("## SD Ask Persona\n\n" + persona.strip())
    if use_session_memory:
        memory = load_text_file(session_memory_path, DEFAULT_SESSION_MEMORY_PATH)
        if memory:
            parts.append("## SD Ask Session Memory\n\n" + memory.strip())
    return "\n\n---\n\n".join(parts)


def sample_chat(chat):
    try:
        return chat.sample()
    except Exception as exc:
        text = str(exc)
        if "used all available credits" in text or "monthly spending limit" in text:
            raise RuntimeError("XAI API credits are exhausted or the monthly spending limit was reached.") from exc
        if "127.0.0.1:9" in text or "localhost:9" in text:
            raise RuntimeError("XAI API connection was blocked by a dead local proxy at 127.0.0.1:9.") from exc
        raise


def load_text_file(path: str | None, default_path: Path) -> str:
    text_path = Path(path) if path else default_path
    if not text_path.is_absolute():
        text_path = BASE_DIR / text_path
    if not text_path.exists():
        return ""
    return text_path.read_text(encoding="utf-8")


def build_user_prompt(current_sd_cfg: dict, request_text: str, input_json: dict | None = None) -> str:
    payload = {
        "request": request_text,
        "allowed_paths": sorted(sd_config.ALLOWED_SET_PATHS),
        "current_sd_config_summary": summarize_sd_config(current_sd_cfg),
    }
    if input_json is not None:
        payload["input_json"] = input_json
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_chat_user_prompt(
    current_sd_cfg: dict,
    request_text: str,
    chat_history: list[dict[str, str]] | None = None,
    input_json: dict | None = None,
) -> str:
    payload = {
        "request": request_text,
        "chat_history": chat_history or [],
        "allowed_paths": sorted(sd_config.ALLOWED_SET_PATHS),
        "current_sd_config_summary": summarize_sd_config(current_sd_cfg),
        "instruction": (
            "Reply with assistant_message plus sd_config_patch. "
            "Make a useful change from the current prompt. "
            "Do not just echo the current prompt."
        ),
    }
    if input_json is not None:
        payload["input_json"] = input_json
    return json.dumps(payload, ensure_ascii=False, indent=2)


def summarize_sd_config(cfg: dict) -> dict[str, Any]:
    generation = cfg.get("generation") or {}
    return {
        "profile": cfg.get("profile"),
        "generation": {
            "mode": generation.get("mode"),
            "prompt": generation.get("prompt"),
            "negative_prompt": generation.get("negative_prompt"),
            "common": generation.get("common"),
            "txt2img": generation.get("txt2img"),
            "img2img": _scrub_img2img(generation.get("img2img") or {}),
        },
        "model": cfg.get("model"),
        "style": cfg.get("style"),
    }


def _scrub_img2img(data: dict) -> dict:
    scrubbed = dict(data)
    if scrubbed.get("input_image"):
        scrubbed["input_image"] = str(scrubbed["input_image"])
    return scrubbed


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _strip_code_fence(stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Grok response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def load_input_json(path: str | None) -> dict | None:
    if not path:
        return None
    json_path = Path(path)
    if not json_path.is_absolute():
        json_path = BASE_DIR / json_path
    return json.loads(json_path.read_text(encoding="utf-8"))


def dry_run_patch(current_sd_cfg: dict, patch: dict) -> dict:
    candidate = deepcopy(current_sd_cfg)
    changed = sd_config.apply_patch(candidate, patch)
    issues = sd_config.validate_sd_config(candidate)
    return {
        "changed": changed,
        "issues": issues,
        "normalized": candidate,
    }


def print_json(data: Any) -> None:
    safe_print(json.dumps(data, ensure_ascii=False, indent=2))
