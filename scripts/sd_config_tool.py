import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import sd_config
from core.common import get_nested, safe_print


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Safe SD config edit gate for LLM/Codex drafts")
    ap.add_argument("--sd-config", default="config/config.sd.json", help="SD config JSON path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="Read a dotted config path")
    p_get.add_argument("path")

    p_set = sub.add_parser("set", help="Set an allowed dotted config path")
    p_set.add_argument("path")
    p_set.add_argument("value")
    p_set.add_argument("--dry-run", action="store_true")
    p_set.add_argument("--no-backup", action="store_true")

    p_patch = sub.add_parser("patch", help="Apply an allowed JSON patch")
    p_patch.add_argument("patch_json", help="Patch JSON file")
    p_patch.add_argument("--dry-run", action="store_true")
    p_patch.add_argument("--no-backup", action="store_true")

    sub.add_parser("validate", help="Validate and normalize config")
    sub.add_parser("allowed", help="List paths allowed for LLM edits")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    cfg = sd_config.load_sd_config(args.sd_config)

    if args.cmd == "get":
        sd_config.print_json({"path": args.path, "value": get_nested(cfg, args.path)})
        return 0

    if args.cmd == "allowed":
        sd_config.print_json(sorted(sd_config.ALLOWED_SET_PATHS))
        return 0

    if args.cmd == "validate":
        issues = sd_config.validate_sd_config(cfg)
        result = sd_config.save_sd_config(args.sd_config, cfg, create_backup=True)
        sd_config.print_json({"ok": not issues, "issues": issues, "saved": result["saved"], "backup": result["backup"]})
        return 0 if not issues else 1

    if args.cmd == "set":
        value = sd_config.parse_value(args.value)
        before = get_nested(cfg, args.path)
        sd_config.set_allowed_path(cfg, args.path, value)
        sd_config.normalize_sd_config(cfg)
        after = get_nested(cfg, args.path)
        output = {"path": args.path, "before": before, "requested": value, "after": after}
        if args.dry_run:
            sd_config.print_json({"dry_run": True, **output})
            return 0
        result = sd_config.save_sd_config(args.sd_config, cfg, create_backup=not args.no_backup)
        sd_config.print_json({"dry_run": False, **output, "saved": result["saved"], "backup": result["backup"]})
        return 0

    if args.cmd == "patch":
        patch_path = Path(args.patch_json)
        patch = json.loads(patch_path.read_text(encoding="utf-8"))
        changed = sd_config.apply_patch(cfg, patch)
        if args.dry_run:
            sd_config.print_json({"dry_run": True, "changed": changed, "normalized": cfg})
            return 0
        result = sd_config.save_sd_config(args.sd_config, cfg, create_backup=not args.no_backup)
        sd_config.print_json({"dry_run": False, "changed": changed, "saved": result["saved"], "backup": result["backup"]})
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
