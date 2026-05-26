import json
from pathlib import Path
from typing import Any

from core.common import BASE_DIR, backup, get_nested, load_json, save_json


DEFAULT_SD_CONFIG = BASE_DIR / "config" / "config.sd.json"
MAX_LOCAL_N_ITER = 4
MAX_LOCAL_BATCH_SIZE = 1
MAX_LOCAL_STEPS = 60
MAX_LOCAL_DIMENSION = 1536


ALLOWED_SET_PATHS = {
    "generation.mode",
    "generation.prompt",
    "generation.negative_prompt",
    "generation.common.steps",
    "generation.common.cfg_scale",
    "generation.common.sampler_name",
    "generation.common.scheduler",
    "generation.common.seed",
    "generation.common.batch_size",
    "generation.common.n_iter",
    "generation.common.restore_faces",
    "generation.common.tiling",
    "generation.txt2img.width",
    "generation.txt2img.height",
    "generation.img2img.input_image",
    "generation.img2img.width",
    "generation.img2img.height",
    "generation.img2img.denoising_strength",
    "generation.img2img.resize_mode",
    "model.checkpoint",
    "model.vae",
    "model.clip_skip",
    "model.apply_overrides",
    "style.preset",
    "style.supplements",
}


def resolve_config_path(path: str | Path | None = None) -> Path:
    cfg_path = Path(path) if path else DEFAULT_SD_CONFIG
    if not cfg_path.is_absolute():
        cfg_path = BASE_DIR / cfg_path
    return cfg_path


def load_sd_config(path: str | Path | None = None) -> dict:
    return normalize_sd_config(load_json(resolve_config_path(path)))


def save_sd_config(path: str | Path | None, data: dict, create_backup: bool = True) -> dict:
    cfg_path = resolve_config_path(path)
    before = load_json(cfg_path) if cfg_path.exists() else {}
    normalized = normalize_sd_config(data)
    backup_path = backup(cfg_path, before) if create_backup and before else None
    save_json(cfg_path, normalized)
    return {
        "saved": str(cfg_path),
        "backup": str(backup_path) if backup_path else None,
        "normalized": normalized,
    }


def parse_value(value: str) -> Any:
    text = value.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if text.lower() == "null":
        return None
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        return json.loads(text)
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return value


def set_allowed_path(data: dict, dotted_path: str, value: Any) -> None:
    if dotted_path not in ALLOWED_SET_PATHS:
        raise ValueError(f"Path is not allowed for LLM SD config edits: {dotted_path}")
    _set_nested_value(data, dotted_path, value)


def flatten_patch(patch: dict, prefix: str = "") -> dict[str, Any]:
    flat = {}
    for key, value in patch.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten_patch(value, dotted))
        else:
            flat[dotted] = value
    return flat


def apply_patch(data: dict, patch: dict) -> dict:
    changed = {}
    patch_body = patch.get("sd_config_patch") if isinstance(patch.get("sd_config_patch"), dict) else patch
    for dotted_path, value in flatten_patch(patch_body).items():
        if dotted_path not in ALLOWED_SET_PATHS:
            raise ValueError(f"Patch contains disallowed path: {dotted_path}")
        set_allowed_path(data, dotted_path, value)
        changed[dotted_path] = value
    normalize_sd_config(data)
    return changed


def validate_sd_config(data: dict) -> list[str]:
    issues = []
    mode = get_nested(data, "generation.mode")
    if mode not in ("txt2img", "img2img"):
        issues.append("generation.mode must be txt2img or img2img")

    prompt = get_nested(data, "generation.prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        issues.append("generation.prompt is empty")

    common = get_nested(data, "generation.common") or {}
    if int(common.get("batch_size", 1)) > MAX_LOCAL_BATCH_SIZE:
        issues.append(f"generation.common.batch_size is capped at {MAX_LOCAL_BATCH_SIZE}")
    if int(common.get("n_iter", 1)) > MAX_LOCAL_N_ITER:
        issues.append(f"generation.common.n_iter is capped at {MAX_LOCAL_N_ITER}")

    return issues


def normalize_sd_config(data: dict) -> dict:
    generation = data.setdefault("generation", {})
    mode = generation.get("mode") or "txt2img"
    if mode not in ("txt2img", "img2img"):
        mode = "txt2img"
    generation["mode"] = mode

    common = generation.setdefault("common", {})
    common["steps"] = _clamp_int(common.get("steps", 24), 1, MAX_LOCAL_STEPS)
    common["cfg_scale"] = _clamp_float(common.get("cfg_scale", 6.5), 1.0, 20.0)
    common["seed"] = _normalize_seed(common.get("seed", -1))
    common["batch_size"] = _clamp_int(common.get("batch_size", 1), 1, MAX_LOCAL_BATCH_SIZE)
    common["max_batch_size"] = MAX_LOCAL_BATCH_SIZE
    common["n_iter"] = _clamp_int(common.get("n_iter", 1), 1, MAX_LOCAL_N_ITER)
    common["max_n_iter"] = MAX_LOCAL_N_ITER
    common["restore_faces"] = bool(common.get("restore_faces", False))
    common["tiling"] = bool(common.get("tiling", False))

    txt2img = generation.setdefault("txt2img", {})
    txt2img["width"] = _clamp_dimension(txt2img.get("width", 768))
    txt2img["height"] = _clamp_dimension(txt2img.get("height", 1024))

    img2img = generation.setdefault("img2img", {})
    img2img["width"] = _clamp_dimension(img2img.get("width", txt2img["width"]))
    img2img["height"] = _clamp_dimension(img2img.get("height", txt2img["height"]))
    img2img["denoising_strength"] = _clamp_float(img2img.get("denoising_strength", 0.45), 0.0, 1.0)
    img2img["resize_mode"] = _clamp_int(img2img.get("resize_mode", 0), 0, 3)
    img2img.setdefault("input_image", "")

    return data


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    parsed = int(value)
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    parsed = float(value)
    return max(minimum, min(maximum, parsed))


def _normalize_seed(value: Any) -> int:
    parsed = int(value)
    return parsed if parsed >= -1 else -1


def _clamp_dimension(value: Any) -> int:
    parsed = _clamp_int(value, 64, MAX_LOCAL_DIMENSION)
    return max(64, int(round(parsed / 8) * 8))


def print_json(data: Any) -> None:
    from core.common import safe_print

    safe_print(json.dumps(data, ensure_ascii=False, indent=2))


def _set_nested_value(data: dict, dotted_path: str, value: Any) -> None:
    cur = data
    keys = dotted_path.split(".")
    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[keys[-1]] = value
