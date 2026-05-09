import argparse
import sys
from pathlib import Path

from core.common import backup, get_cfg_path, get_nested, load_json, save_json, set_nested
from core.image_engine import run_image, run_imagine, run_imagine_natural
from core.text_engine import run_text, run_vision
from core.video_engine import run_video



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
        image_url=args.image_url,
        image_file=args.image_file,
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


def cmd_imagine(args) -> int:
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
    cfg = load_json(get_cfg_path(args))
    run_video(
        cfg,
        prompt_override=args.prompt,
        model_override=args.model,
    )
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

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
