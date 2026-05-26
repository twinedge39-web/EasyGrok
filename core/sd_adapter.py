import base64
import json
from pathlib import Path
from typing import Any
from urllib import error, request

from core.common import BASE_DIR, get_nested, now_stamp, resolve_project_path, safe_print
from core.sd_config import load_sd_config


DEFAULT_SD_CONFIG = BASE_DIR / "config" / "config.sd.json"


def _timeout(cfg: dict) -> int:
    return int(get_nested(cfg, "connection.timeout_sec") or cfg.get("timeout_sec") or 3600)


def _api_url(cfg: dict, endpoint: str) -> str:
    base = str(get_nested(cfg, "connection.api_url") or cfg.get("api_url") or "http://127.0.0.1:7860").rstrip("/")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return base + endpoint


def _read_json_response(resp) -> Any:
    raw = resp.read().decode("utf-8")
    if not raw:
        return {}
    return json.loads(raw)


def sd_get_json(cfg: dict, endpoint: str) -> Any:
    url = _api_url(cfg, endpoint)
    try:
        with request.urlopen(url, timeout=_timeout(cfg)) as resp:
            return _read_json_response(resp)
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {e.code}: {body}") from e
    except error.URLError as e:
        raise RuntimeError(f"GET {url} failed: {e}") from e


def sd_post_json(cfg: dict, endpoint: str, payload: dict) -> Any:
    url = _api_url(cfg, endpoint)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=_timeout(cfg)) as resp:
            return _read_json_response(resp)
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: HTTP {e.code}: {detail}") from e
    except error.URLError as e:
        raise RuntimeError(f"POST {url} failed: {e}") from e


def check_sd(cfg: dict) -> dict:
    return sd_get_json(cfg, "/sdapi/v1/progress?skip_current_image=true")


def get_options(cfg: dict) -> dict:
    return sd_get_json(cfg, "/sdapi/v1/options")


def get_models(cfg: dict) -> list:
    return sd_get_json(cfg, "/sdapi/v1/sd-models")


def get_samplers(cfg: dict) -> list:
    return sd_get_json(cfg, "/sdapi/v1/samplers")


def get_schedulers(cfg: dict) -> list:
    return sd_get_json(cfg, "/sdapi/v1/schedulers")


def summarize_options(cfg: dict, options: dict) -> dict:
    fields = get_nested(cfg, "inspect.option_fields") or []
    selected = {field: options.get(field) for field in fields}
    modules = selected.get("forge_additional_modules") or []
    if modules:
        selected["forge_additional_modules"] = [Path(str(x)).name for x in modules]
    return {
        "backend": get_nested(cfg, "profile.backend") or cfg.get("backend"),
        "api_url": get_nested(cfg, "connection.api_url") or cfg.get("api_url"),
        "api_enabled": options.get("api_enable_requests"),
        "model": options.get("sd_model_checkpoint"),
        "model_hash": options.get("sd_checkpoint_hash"),
        "forge_preset": options.get("forge_preset"),
        "txt2img": {
            "width": options.get("sd_t2i_width"),
            "height": options.get("sd_t2i_height"),
            "cfg": options.get("sd_t2i_cfg"),
        },
        "img2img": {
            "width": options.get("sd_i2i_width"),
            "height": options.get("sd_i2i_height"),
        },
        "outputs": {
            "txt2img": options.get("outdir_txt2img_samples"),
            "img2img": options.get("outdir_img2img_samples"),
            "save": options.get("outdir_save"),
        },
        "selected_options": selected,
}


def _generation_defaults(cfg: dict, mode: str) -> dict:
    generation = cfg.get("generation") or {}
    common = generation.get("common") or {}
    mode_defaults = generation.get(mode) or {}
    legacy = cfg.get("defaults") or {}
    merged = {}
    merged.update(legacy)
    merged.update(common)
    merged.update(mode_defaults)
    return merged


def _prompt_value(cfg: dict, key: str) -> str:
    legacy_key = {"prompt": "positive", "negative_prompt": "negative"}.get(key, key)
    return (
        get_nested(cfg, f"generation.{key}")
        or get_nested(cfg, f"prompt.{legacy_key}")
        or get_nested(cfg, f"prompt.{key}")
        or ""
    )


def _model_overrides(cfg: dict) -> dict:
    if not get_nested(cfg, "model.apply_overrides"):
        return {}

    override_settings = {}
    checkpoint = get_nested(cfg, "model.checkpoint")
    vae = get_nested(cfg, "model.vae")
    clip_skip = get_nested(cfg, "model.clip_skip")
    if checkpoint:
        override_settings["sd_model_checkpoint"] = checkpoint
    if vae:
        override_settings["sd_vae"] = vae
    if clip_skip is not None:
        override_settings["CLIP_stop_at_last_layers"] = int(clip_skip)
    return override_settings


def build_txt2img_payload(
    cfg: dict,
    prompt_override: str | None = None,
    negative_override: str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    seed: int | None = None,
) -> dict:
    defaults = _generation_defaults(cfg, "txt2img")
    prompt = prompt_override or _prompt_value(cfg, "prompt")
    negative = negative_override or _prompt_value(cfg, "negative_prompt")
    payload = {
        "prompt": prompt,
        "negative_prompt": negative,
        "width": int(width if width is not None else defaults.get("width", 768)),
        "height": int(height if height is not None else defaults.get("height", 1024)),
        "steps": int(steps if steps is not None else defaults.get("steps", 24)),
        "cfg_scale": float(cfg_scale if cfg_scale is not None else defaults.get("cfg_scale", 6.5)),
        "sampler_name": sampler_name or defaults.get("sampler_name", "DPM++ 2M SDE"),
        "scheduler": scheduler or defaults.get("scheduler", "Karras"),
        "seed": int(seed if seed is not None else defaults.get("seed", -1)),
        "batch_size": min(int(defaults.get("batch_size", 1)), int(defaults.get("max_batch_size", defaults.get("batch_size", 1)))),
        "n_iter": min(int(defaults.get("n_iter", 1)), int(defaults.get("max_n_iter", defaults.get("n_iter", 1)))),
        "restore_faces": bool(defaults.get("restore_faces", False)),
        "tiling": bool(defaults.get("tiling", False)),
    }

    override_settings = _model_overrides(cfg)
    if override_settings:
        payload["override_settings"] = override_settings

    return payload


def _image_to_base64(path_value: str) -> str:
    path = resolve_project_path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"img2img input image not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_img2img_payload(
    cfg: dict,
    prompt_override: str | None = None,
    negative_override: str | None = None,
    input_image: str | None = None,
    denoising_strength: float | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    seed: int | None = None,
    resize_mode: int | None = None,
) -> dict:
    defaults = _generation_defaults(cfg, "img2img")
    source = input_image or defaults.get("input_image")
    if not source:
        raise ValueError("img2img needs --input-image or generation.img2img.input_image")

    payload = build_txt2img_payload(
        cfg,
        prompt_override=prompt_override,
        negative_override=negative_override,
        width=width if width is not None else defaults.get("width"),
        height=height if height is not None else defaults.get("height"),
        steps=steps,
        cfg_scale=cfg_scale,
        sampler_name=sampler_name,
        scheduler=scheduler,
        seed=seed,
    )
    payload["init_images"] = [_image_to_base64(str(source))]
    payload["denoising_strength"] = float(
        denoising_strength if denoising_strength is not None else defaults.get("denoising_strength", 0.45)
    )
    payload["resize_mode"] = int(resize_mode if resize_mode is not None else defaults.get("resize_mode", 0))
    return payload


def build_payload(
    cfg: dict,
    mode: str | None = None,
    prompt_override: str | None = None,
    negative_override: str | None = None,
    input_image: str | None = None,
    denoising_strength: float | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    cfg_scale: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    seed: int | None = None,
    resize_mode: int | None = None,
) -> tuple[str, dict]:
    selected = mode or get_nested(cfg, "generation.mode") or get_nested(cfg, "defaults.route") or "txt2img"
    if selected == "txt2img":
        return selected, build_txt2img_payload(
            cfg,
            prompt_override=prompt_override,
            negative_override=negative_override,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler_name=sampler_name,
            scheduler=scheduler,
            seed=seed,
        )
    if selected == "img2img":
        return selected, build_img2img_payload(
            cfg,
            prompt_override=prompt_override,
            negative_override=negative_override,
            input_image=input_image,
            denoising_strength=denoising_strength,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            sampler_name=sampler_name,
            scheduler=scheduler,
            seed=seed,
            resize_mode=resize_mode,
        )
    raise ValueError(f"Unsupported SD mode: {selected}")


def _decode_image(data: str) -> bytes:
    if "," in data and data.split(",", 1)[0].startswith("data:"):
        data = data.split(",", 1)[1]
    return base64.b64decode(data)


def execute_payload(cfg: dict, mode: str, payload: dict) -> dict:
    endpoint = "/sdapi/v1/img2img" if mode == "img2img" else "/sdapi/v1/txt2img"
    result = sd_post_json(cfg, endpoint, payload)
    out_dir = resolve_project_path(
        get_nested(cfg, "save.codex_output_dir") or cfg.get("output_dir") or "out/sd_images"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    saved = []

    for idx, image_data in enumerate(result.get("images") or [], start=1):
        image_bytes = _decode_image(image_data)
        image_path = out_dir / f"sd_{mode}_{stamp}_{idx}.png"
        image_path.write_bytes(image_bytes)
        saved.append(str(image_path))

    if bool(get_nested(cfg, "save.metadata")):
        meta_path = out_dir / f"sd_{mode}_{stamp}_meta.json"
        meta = {
            "mode": mode,
            "endpoint": endpoint,
            "payload": payload,
            "info": result.get("info"),
            "parameters": result.get("parameters"),
            "saved_images": saved,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        meta_path = None

    return {
        "saved_images": saved,
        "metadata": str(meta_path) if meta_path else None,
        "info": result.get("info"),
    }


def execute_txt2img(cfg: dict, payload: dict) -> dict:
    return execute_payload(cfg, "txt2img", payload)


def scrub_payload_for_print(payload: dict) -> dict:
    scrubbed = dict(payload)
    if "init_images" in scrubbed:
        scrubbed["init_images"] = [
            f"<base64 image {len(str(image))} chars>" for image in scrubbed["init_images"]
        ]
    return scrubbed


def print_json(data: Any) -> None:
    safe_print(json.dumps(data, ensure_ascii=False, indent=2))


def format_summary_text(summary: dict) -> str:
    lines = [
        "SD Adapter Summary",
        f"- backend: {summary.get('backend')}",
        f"- api_url: {summary.get('api_url')}",
        f"- api_enabled: {summary.get('api_enabled')}",
        f"- model: {summary.get('model')}",
        f"- model_hash: {summary.get('model_hash')}",
        f"- forge_preset: {summary.get('forge_preset')}",
        f"- txt2img: {summary.get('txt2img')}",
        f"- img2img: {summary.get('img2img')}",
        f"- outputs: {summary.get('outputs')}",
    ]
    return "\n".join(lines)
