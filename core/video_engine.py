from .common import ensure_out_dir, get_nested, output_record


def run_video(cfg: dict, prompt_override: str | None = None, model_override: str | None = None) -> None:
    """Placeholder engine for future video generation experiments."""
    out_dir = get_nested(cfg, "defaults.output.dir") or "./out"
    out_path = ensure_out_dir(out_dir)
    prompt = prompt_override or (get_nested(cfg, "video.prompt") or "")
    model = model_override or get_nested(cfg, "defaults.models.video") or ""
    content = "Video engine scaffold is ready, but no video API route is implemented yet."
    if prompt:
        content += f"\n\nPrompt: {prompt}"
    if model:
        content += f"\nModel: {model}"
    record = {
        "mode": "video.scaffold",
        "model": model,
        "prompt": prompt,
        "content": content,
    }
    output_record(cfg, out_path, "video", record)

