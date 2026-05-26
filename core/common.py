import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
CONFIG_BACKUP_DIR = CONFIG_DIR / "backups"

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path.resolve()}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_nested(d: dict, dotted_key: str):
    cur = d
    for k in dotted_key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def set_nested(d: dict, dotted_key: str, value: str) -> None:
    """Set nested key. Tries: bool -> JSON(list/dict) -> int -> float -> string."""
    keys = dotted_key.split(".")
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]

    v = value.strip()

    # bool
    if v.lower() in ("true", "false"):
        cur[keys[-1]] = (v.lower() == "true")
        return

    # JSON list/dict (for image_urls etc.)
    if (v.startswith("[") and v.endswith("]")) or (v.startswith("{") and v.endswith("}")):
        try:
            cur[keys[-1]] = json.loads(v)
            return
        except Exception:
            pass

    # int
    try:
        cur[keys[-1]] = int(v)
        return
    except ValueError:
        pass

    # float
    try:
        cur[keys[-1]] = float(v)
        return
    except ValueError:
        pass

    # string
    cur[keys[-1]] = v


def backup(path: Path, data: dict) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg_path = Path(path)
    backup_root = CONFIG_BACKUP_DIR if cfg_path.parent.resolve() == CONFIG_DIR.resolve() else cfg_path.parent / "backups"
    bak_dir = backup_root / cfg_path.stem
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"{cfg_path.name}.bak_{stamp}"
    save_json(bak, data)
    return bak


# ========= Shared utils =========
def resolve_project_path(path_value: str) -> Path:
    p = Path(path_value).expanduser()
    if p.is_absolute():
        return p
    return BASE_DIR / p


def build_context_block(cfg: dict,
                        override_files: Optional[list[str]] = None,
                        disabled: bool = False) -> tuple[str, dict]:
    if disabled:
        return "", {"enabled": False, "files": [], "total_chars": 0, "truncated": False}

    configured = get_nested(cfg, "memory.context_files") or []
    enabled = bool(get_nested(cfg, "memory.enabled")) if get_nested(cfg, "memory.enabled") is not None else False

    if override_files:
        files = override_files
        enabled = True
    else:
        files = configured

    if isinstance(files, str):
        files = [files]
    if not enabled or not files:
        return "", {"enabled": False, "files": [], "total_chars": 0, "truncated": False}

    max_chars = int(get_nested(cfg, "memory.max_chars") or 12000)
    chunks: list[str] = []
    meta_files: list[dict] = []
    used_chars = 0
    truncated = False

    for item in files:
        path = resolve_project_path(str(item))
        entry = {"path": str(path), "exists": path.exists(), "chars": 0, "used_chars": 0}
        if not path.exists() or not path.is_file():
            meta_files.append(entry)
            continue
        text = path.read_text(encoding="utf-8").strip()
        entry["chars"] = len(text)
        if not text:
            meta_files.append(entry)
            continue

        remaining = max_chars - used_chars
        if remaining <= 0:
            truncated = True
            meta_files.append(entry)
            continue

        header = f"## Context File: {item}\n"
        available = max(0, remaining - len(header) - 2)
        piece = text[:available]
        if len(piece) < len(text):
            truncated = True
        entry["used_chars"] = len(piece)
        chunks.append(header + piece)
        used_chars += len(header) + len(piece) + 2
        meta_files.append(entry)

    if not chunks:
        return "", {"enabled": True, "files": meta_files, "total_chars": 0, "truncated": truncated}

    block = (
        "Runtime Markdown Context:\n"
        "Use the following project memory as background context. "
        "Treat it as lower priority than the user's latest request.\n\n"
        + "\n\n".join(chunks)
    )
    return block, {"enabled": True, "files": meta_files, "total_chars": used_chars, "truncated": truncated}


def merge_system_with_context(system_prompt: str, context_block: str) -> str:
    if not context_block:
        return system_prompt
    if not system_prompt:
        return context_block
    return f"{system_prompt.strip()}\n\n---\n\n{context_block.strip()}"


def session_enabled(cfg: dict, disabled: bool = False) -> bool:
    if disabled:
        return False
    value = get_nested(cfg, "memory.session.enabled")
    return bool(value) if value is not None else False


def get_session_path(cfg: dict) -> Path:
    return resolve_project_path(get_nested(cfg, "memory.session.file") or "memory/session.md")


def append_session_turn(cfg: dict, user_prompt: str, assistant_content: str, model: str) -> dict:
    path = get_session_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text("# EasyGrok Session\n\n", encoding="utf-8")

    stamp = datetime.now().isoformat(timespec="seconds")
    max_assistant_chars = int(get_nested(cfg, "memory.session.max_assistant_chars") or 4000)
    stored_content = assistant_content[:max_assistant_chars]
    truncated = len(stored_content) < len(assistant_content)

    turn = (
        f"## {stamp}\n\n"
        f"Model: `{model}`\n\n"
        "User:\n"
        f"{user_prompt.strip()}\n\n"
        "Assistant:\n"
        f"{stored_content.strip()}"
        + ("\n\n[assistant content truncated]" if truncated else "")
        + "\n\n"
    )

    with path.open("a", encoding="utf-8") as f:
        f.write(turn)

    return {
        "enabled": True,
        "file": str(path),
        "appended": True,
        "assistant_chars": len(assistant_content),
        "stored_assistant_chars": len(stored_content),
        "truncated": truncated,
    }


def ensure_out_dir(out_dir: str) -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_media_dir(out_dir: str, configured_dir: Optional[str], default_subdir: str) -> Path:
    base = ensure_out_dir(out_dir)
    if configured_dir:
        p = Path(configured_dir).expanduser()
        if not p.is_absolute():
            p = base / p
    else:
        p = base / default_subdir
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_images_dir(out_dir: str, configured_dir: Optional[str] = None) -> Path:
    return ensure_media_dir(out_dir, configured_dir, "images")


def ensure_videos_dir(out_dir: str, configured_dir: Optional[str] = None) -> Path:
    return ensure_media_dir(out_dir, configured_dir, "videos")


def ensure_log_dir(out_path: Path, configured_dir: Optional[str], default_subdir: str) -> Path:
    if configured_dir:
        p = Path(configured_dir).expanduser()
        if not p.is_absolute():
            p = out_path / p
    else:
        p = out_path / default_subdir
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_image_bytes(image_bytes: bytes, dest_dir: Path, base_name: str, ext: str = ".jpg") -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{base_name}{ext}"
    out_path.write_bytes(image_bytes)
    return out_path


def get_cfg_path(args) -> Path:
    return Path(args.config) if args.config else Path("./config/config.user.json")


def get_api_key() -> str:
    api_key = os.getenv("XAI_API_KEY") or get_windows_env_var("XAI_API_KEY")
    if not api_key:
        print("ERROR: XAI_API_KEY is not set in environment variables.", file=sys.stderr)
        raise SystemExit(2)
    return api_key


def clear_dead_local_proxy_env() -> list[str]:
    """Remove placeholder proxy values that make gRPC connect to localhost:9."""
    cleared = []
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY"):
        value = os.getenv(name, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            os.environ.pop(name, None)
            cleared.append(name)
    return cleared


def get_windows_env_var(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except Exception:
        return ""

    locations = [
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    for root, subkey in locations:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if value:
                    return str(value)
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return ""


def safe_print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_text)


def output_record(cfg: dict, out_path: Path, prefix: str, record: dict) -> None:
    save_raw = bool(
        get_nested(cfg, "defaults.output.save_raw_json")
        if get_nested(cfg, "defaults.output.save_raw_json") is not None
        else True
    )
    save_md = bool(
        get_nested(cfg, "defaults.output.save_md")
        if get_nested(cfg, "defaults.output.save_md") is not None
        else True
    )
    print_mode = get_nested(cfg, "defaults.output.print_mode") or "minimal"

    stamp = now_stamp()
    json_dir = ensure_log_dir(out_path, get_nested(cfg, "defaults.output.raw_json_dir"), "logs/json")
    md_dir = ensure_log_dir(out_path, get_nested(cfg, "defaults.output.md_dir"), "logs/md")
    json_path = json_dir / f"{prefix}_raw_{stamp}.json"
    md_path = md_dir / f"{prefix}_{stamp}.md"

    content = record.get("content") or ""

    if save_raw:
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    if save_md:
        md_path.write_text(content, encoding="utf-8")

    if print_mode == "none":
        return

    if print_mode == "content":
        safe_print(content)
        return

    # minimal
    if save_raw:
        safe_print(f"OK: saved {json_path.as_posix()}")
    else:
        safe_print("OK")

    if content:
        safe_print("\n---\n")
        safe_print(content)

