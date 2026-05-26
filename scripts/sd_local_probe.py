import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import sd_adapter
from core.common import safe_print


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Local Stable Diffusion API probe")
    ap.add_argument("prompt", nargs="?", help="Prompt override for preview/execute")
    ap.add_argument("--sd-config", default="config/config.sd.json", help="SD config JSON path")
    ap.add_argument("--check", action="store_true", help="Check progress endpoint")
    ap.add_argument("--summary", action="store_true", help="Print compact options summary")
    ap.add_argument("--options", action="store_true", help="Print selected options summary as JSON")
    ap.add_argument("--models", action="store_true", help="List model titles")
    ap.add_argument("--samplers", action="store_true", help="List sampler names")
    ap.add_argument("--schedulers", action="store_true", help="List scheduler labels")
    ap.add_argument("--mode", choices=["txt2img", "img2img"], help="Generation mode override")
    ap.add_argument("--preview", action="store_true", help="Print SD payload without generating")
    ap.add_argument("--execute", action="store_true", help="Run SD generation and save returned PNG files")
    ap.add_argument("--negative", help="Negative prompt override")
    ap.add_argument("--input-image", help="Input image path for img2img")
    ap.add_argument("--denoising-strength", type=float)
    ap.add_argument("--resize-mode", type=int)
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--cfg-scale", type=float)
    ap.add_argument("--sampler")
    ap.add_argument("--scheduler")
    ap.add_argument("--seed", type=int)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    cfg = sd_adapter.load_sd_config(args.sd_config)
    any_action = any(
        [
            args.check,
            args.summary,
            args.options,
            args.models,
            args.samplers,
            args.schedulers,
            args.preview,
            args.execute,
        ]
    )

    if not any_action:
        args.check = True
        args.summary = True

    if args.check:
        progress = sd_adapter.check_sd(cfg)
        safe_print(f"OK: progress={progress.get('progress')} job={progress.get('state', {}).get('job')!r}")

    if args.summary or args.options:
        options = sd_adapter.get_options(cfg)
        summary = sd_adapter.summarize_options(cfg, options)
        if args.options:
            sd_adapter.print_json(summary)
        else:
            safe_print(sd_adapter.format_summary_text(summary))

    if args.models:
        for item in sd_adapter.get_models(cfg):
            safe_print(item.get("title") or item.get("model_name") or str(item))

    if args.samplers:
        for item in sd_adapter.get_samplers(cfg):
            safe_print(item.get("name") or str(item))

    if args.schedulers:
        for item in sd_adapter.get_schedulers(cfg):
            safe_print(item.get("label") or item.get("name") or str(item))

    if args.preview or args.execute:
        mode, payload = sd_adapter.build_payload(
            cfg,
            mode=args.mode,
            prompt_override=args.prompt,
            negative_override=args.negative,
            input_image=args.input_image,
            denoising_strength=args.denoising_strength,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg_scale=args.cfg_scale,
            sampler_name=args.sampler,
            scheduler=args.scheduler,
            seed=args.seed,
            resize_mode=args.resize_mode,
        )
        if args.preview:
            sd_adapter.print_json({"mode": mode, "payload": sd_adapter.scrub_payload_for_print(payload)})
        if args.execute:
            sd_adapter.print_json(sd_adapter.execute_payload(cfg, mode, payload))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
