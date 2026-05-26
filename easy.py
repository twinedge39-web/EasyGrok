import argparse
import sys
from pathlib import Path
from copy import deepcopy

from core.common import backup, get_cfg_path, get_nested, load_json, save_json, set_nested
from core import sd_adapter



# ========= Field Groups =========
FIELDS_TEXT_VISION = [
    ("defaults.timeout_sec", "Timeout (sec)"),
    ("defaults.output.dir", "Output directory"),
    ("defaults.output.raw_json_dir", "Raw JSON log directory"),
    ("defaults.output.md_dir", "Markdown log directory"),
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
    ("defaults.output.raw_json_dir", "Raw JSON log directory"),
    ("defaults.output.md_dir", "Markdown log directory"),
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
            from core.text_engine import run_text

            _prompt_save_if_needed(cfg_path, cfg)
            try:
                run_text(cfg)
            except Exception as e:
                print(f"RUN text failed: {e}", file=sys.stderr)
            continue

        if c == "v":
            from core.text_engine import run_vision

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
            from core.image_engine import run_image

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
    from core.text_engine import run_text

    cfg = load_json(get_cfg_path(args))
    run_text(
        cfg,
        prompt_override=args.prompt,
        system_override=args.system,
        context_files=args.context,
        no_context=bool(args.no_context),
        no_session=bool(args.no_session),
        image_url=args.image_url,
        image_file=args.image_file,
    )
    return 0


def cmd_vision(args) -> int:
    from core.text_engine import run_vision

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
    from core.image_engine import run_image

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


def cmd_imagine(args) -> int:
    from core.image_engine import run_imagine

    cfg = load_json(get_cfg_path(args))
    run_imagine(
        cfg,
        prompt_override=args.prompt,
        system_override=args.system,
        rewrite_system_override=args.rewrite_system,
        rewrite_model_override=args.rewrite_model,
        model_override=args.model,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
        image_format_override=args.image_format,
        download=bool(args.download),
        download_dir=args.download_dir,
        dry_run=bool(args.dry_run),
    )
    return 0


def cmd_imagine_natural(args) -> int:
    from core.image_engine import run_imagine_natural

    cfg = load_json(get_cfg_path(args))
    run_imagine_natural(
        cfg,
        prompt_override=args.prompt,
        system_override=args.system,
        language_model_override=args.language_model,
        model_override=args.model,
        aspect_ratio_override=args.aspect_ratio,
        resolution_override=args.resolution,
        image_format_override=args.image_format,
        download=bool(args.download),
        download_dir=args.download_dir,
        dry_run=bool(args.dry_run),
    )
    return 0


def cmd_video(args) -> int:
    from core.video_engine import run_video

    cfg = load_json(get_cfg_path(args))
    run_video(
        cfg,
        prompt_override=args.prompt,
        model_override=args.model,
    )
    return 0


def cmd_sd(args) -> int:
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
        state = progress.get("state") or {}
        sd_adapter.print_json(
            {
                "ok": True,
                "progress": progress.get("progress"),
                "job": state.get("job"),
                "job_count": state.get("job_count"),
            }
        )

    if args.summary or args.options:
        options = sd_adapter.get_options(cfg)
        summary = sd_adapter.summarize_options(cfg, options)
        if args.options:
            sd_adapter.print_json(summary)
        else:
            print(sd_adapter.format_summary_text(summary))

    if args.models:
        for item in sd_adapter.get_models(cfg):
            print(item.get("title") or item.get("model_name") or str(item))

    if args.samplers:
        for item in sd_adapter.get_samplers(cfg):
            print(item.get("name") or str(item))

    if args.schedulers:
        for item in sd_adapter.get_schedulers(cfg):
            print(item.get("label") or item.get("name") or str(item))

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


def cmd_sd_ask(args) -> int:
    from core import sd_ask, sd_config

    if not args.request and not args.input_json:
        raise SystemExit("ERROR: Provide a request text or --input-json.")

    easy_cfg = load_json(get_cfg_path(args))
    current_sd_cfg = sd_config.load_sd_config(args.sd_config)
    input_json = sd_ask.load_input_json(args.input_json)
    result = sd_ask.ask_for_sd_patch(
        easy_cfg,
        current_sd_cfg,
        args.request or "",
        input_json=input_json,
        model_override=args.model,
        persona_path=args.persona,
        session_memory_path=args.session_memory,
        use_session_memory=not bool(args.no_session_memory),
    )
    patch = result["patch"]

    if args.patch_only and not args.dry_run and not args.apply:
        sd_ask.print_json(patch)
        return 0

    output = {
        "ok": True,
        "model": result["model"],
        "patch": patch,
    }

    if args.include_raw:
        output["raw"] = result["content"]

    if args.dry_run or args.apply:
        preview = sd_ask.dry_run_patch(current_sd_cfg, patch)
        output["dry_run"] = preview
        if preview["issues"]:
            output["ok"] = False
            if args.apply:
                output["saved"] = None
                sd_ask.print_json(output)
                return 1

    if args.apply:
        candidate = deepcopy(current_sd_cfg)
        changed = sd_config.apply_patch(candidate, patch)
        save_result = sd_config.save_sd_config(args.sd_config, candidate, create_backup=not args.no_backup)
        output["applied"] = {
            "changed": changed,
            "saved": save_result["saved"],
            "backup": save_result["backup"],
        }

    sd_ask.print_json(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="easy.py",
        description="Grok EASY runner (text + menu + vision + image + imagine + video scaffold) [menu supports run + optional download]"
    )
    ap.add_argument("-c", "--config", help="Config JSON path (default: ./config/config.user.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_menu = sub.add_parser("menu", help="Interactive config editor + RUN (creates backup)")
    p_menu.set_defaults(fn=cmd_menu)

    p_text = sub.add_parser("text", help="Run text LLM")
    p_text.add_argument("prompt", nargs="?", help="Override user prompt")
    p_text.add_argument("--system", help="Override system prompt")
    p_text.add_argument("--image-url", help="Attach image URL to this text run")
    p_text.add_argument("--image-file", help="Attach local image file to this text run")
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

    p_imagine = sub.add_parser("imagine", help="Ask language Grok to write an Imagine prompt, then run image generation")
    p_imagine.add_argument("prompt", nargs="?", help="User image request (otherwise from config image.prompt)")
    p_imagine.add_argument("--system", help="System-style instructions to prepend to the final image prompt")
    p_imagine.add_argument("--rewrite-system", help="Override the language Grok system prompt used to produce JSON action")
    p_imagine.add_argument("--rewrite-model", help="Override language Grok model used for prompt conversion")
    p_imagine.add_argument("--model", help="Override image model (e.g. grok-imagine-image-pro)")
    p_imagine.add_argument("--aspect-ratio", help="Override aspect_ratio (e.g. 16:9)")
    p_imagine.add_argument("--resolution", help="Override resolution (e.g. 2k)")
    p_imagine.add_argument("--image-format", choices=["url", "base64"], help="Return URLs or save base64 image bytes")
    p_imagine.add_argument("--download", action="store_true", help="Download returned URL immediately to ./out/images/")
    p_imagine.add_argument("--download-dir", help="Custom download directory (default: ./out/images/)")
    p_imagine.add_argument("--dry-run", action="store_true", help="Only run language Grok prompt conversion; skip image generation")
    p_imagine.set_defaults(fn=cmd_imagine)

    p_nat = sub.add_parser("imagine-natural", help="Ask language Grok naturally for an image, extract its suggested prompt, then optionally run Imagine")
    p_nat.add_argument("prompt", nargs="?", help="Natural user image request (otherwise from config image.prompt)")
    p_nat.add_argument("--system", help="Override natural language Grok system prompt")
    p_nat.add_argument("--language-model", help="Override language Grok model used for natural reply")
    p_nat.add_argument("--model", help="Override image model (e.g. grok-imagine-image-pro)")
    p_nat.add_argument("--aspect-ratio", help="Override aspect_ratio (e.g. 16:9)")
    p_nat.add_argument("--resolution", help="Override resolution (e.g. 2k)")
    p_nat.add_argument("--image-format", choices=["url", "base64"], help="Return URLs or save base64 image bytes")
    p_nat.add_argument("--download", action="store_true", help="Download returned URL immediately to ./out/images/")
    p_nat.add_argument("--download-dir", help="Custom download directory (default: ./out/images/)")
    p_nat.add_argument("--dry-run", action="store_true", help="Only ask language Grok and extract prompt; skip image generation")
    p_nat.set_defaults(fn=cmd_imagine_natural)

    p_video = sub.add_parser("video", help="Video engine scaffold (no generation API route yet)")
    p_video.add_argument("prompt", nargs="?", help="Video prompt placeholder")
    p_video.add_argument("--model", help="Override video model placeholder")
    p_video.set_defaults(fn=cmd_video)

    p_sd = sub.add_parser("sd", help="Local Stable Diffusion API adapter")
    p_sd.add_argument("prompt", nargs="?", help="Prompt override for preview/execute")
    p_sd.add_argument("--sd-config", default="config/config.sd.json", help="SD config JSON path")
    p_sd.add_argument("--check", action="store_true", help="Check local SD API progress endpoint")
    p_sd.add_argument("--summary", action="store_true", help="Print compact live settings summary")
    p_sd.add_argument("--options", action="store_true", help="Print selected live options as JSON")
    p_sd.add_argument("--models", action="store_true", help="List checkpoint titles")
    p_sd.add_argument("--samplers", action="store_true", help="List sampler names")
    p_sd.add_argument("--schedulers", action="store_true", help="List scheduler labels")
    p_sd.add_argument("--mode", choices=["txt2img", "img2img"], help="Generation mode override")
    p_sd.add_argument("--preview", action="store_true", help="Print SD payload without generating")
    p_sd.add_argument("--execute", action="store_true", help="Run SD generation and save returned PNG files")
    p_sd.add_argument("--negative", help="Negative prompt override")
    p_sd.add_argument("--input-image", help="Input image path for img2img")
    p_sd.add_argument("--denoising-strength", type=float)
    p_sd.add_argument("--resize-mode", type=int)
    p_sd.add_argument("--width", type=int)
    p_sd.add_argument("--height", type=int)
    p_sd.add_argument("--steps", type=int)
    p_sd.add_argument("--cfg-scale", type=float)
    p_sd.add_argument("--sampler")
    p_sd.add_argument("--scheduler")
    p_sd.add_argument("--seed", type=int)
    p_sd.set_defaults(fn=cmd_sd)

    p_sd_ask = sub.add_parser("sd-ask", help="Ask Grok to produce a safe SD config JSON patch")
    p_sd_ask.add_argument("request", nargs="?", help="Natural language SD config edit request")
    p_sd_ask.add_argument("--sd-config", default="config/config.sd.json", help="SD config JSON path")
    p_sd_ask.add_argument("--input-json", help="Optional JSON file to include as source material")
    p_sd_ask.add_argument("--model", help="Override Grok text model")
    p_sd_ask.add_argument("--persona", help="Override SD Ask persona Markdown path")
    p_sd_ask.add_argument("--session-memory", help="Override SD Ask session memory Markdown path")
    p_sd_ask.add_argument("--no-session-memory", action="store_true", help="Do not include SD Ask session memory")
    p_sd_ask.add_argument("--patch-only", action="store_true", help="Print only the returned JSON patch")
    p_sd_ask.add_argument("--include-raw", action="store_true", help="Include raw Grok response in output")
    p_sd_ask.add_argument("--dry-run", action="store_true", help="Validate patch against current SD config without saving")
    p_sd_ask.add_argument("--apply", action="store_true", help="Apply returned patch to SD config after validation")
    p_sd_ask.add_argument("--no-backup", action="store_true", help="Do not create a config backup when --apply is used")
    p_sd_ask.set_defaults(fn=cmd_sd_ask)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
