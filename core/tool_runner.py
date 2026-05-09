import json
from typing import Any


ALLOWED_ACTION = "run_easy_command"
ALLOWED_ROUTES = {"text", "vision", "image", "imagine", "imagine-natural", "video"}
IMAGE_MODES = {"generate", "edit", "reference_edit", "batch"}
IMAGE_FORMATS = {"url", "base64"}
IMAGE_RESOLUTIONS = {"1k", "2k"}


class ToolRequestError(ValueError):
    pass


def extract_tool_request(text: str) -> dict[str, Any] | None:
    """Return the first supported JSON tool request found in text."""
    for candidate in _json_object_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("action") == ALLOWED_ACTION:
            return data
    return None


def build_easy_command_from_request(
    request: dict[str, Any],
    *,
    python_path: str,
    easy_path: str,
    config_path: str,
    cfg: dict[str, Any] | None = None,
) -> list[str]:
    validate_tool_request(request, cfg=cfg)
    route = str(request["route"])
    args = request.get("args") or {}
    if not isinstance(args, dict):
        raise ToolRequestError("args must be an object.")

    cmd = [python_path, easy_path, "-c", config_path, route]

    if route == "text":
        _append_if(cmd, "--system", args.get("system"))
        _append_if(cmd, "--image-url", args.get("image_url"))
        _append_if(cmd, "--image-file", args.get("image_file"))
        if bool(args.get("no_context")):
            cmd.append("--no-context")
        if bool(args.get("no_session")):
            cmd.append("--no-session")
        _append_prompt(cmd, args.get("prompt"))
        return cmd

    if route == "vision":
        _append_if(cmd, "--image-url", args.get("image_url"))
        _append_if(cmd, "--image-file", args.get("image_file"))
        _append_if(cmd, "--system", args.get("system"))
        if bool(args.get("no_context")):
            cmd.append("--no-context")
        _append_prompt(cmd, args.get("prompt"))
        return cmd

    if route == "video":
        _append_if(cmd, "--model", args.get("model"))
        _append_prompt(cmd, args.get("prompt"))
        return cmd

    if route == "image":
        mode = str(args.get("mode") or "generate")
        cmd += ["--mode", mode]
        _append_if(cmd, "--system", args.get("system"))
        _append_if(cmd, "--llm-system", args.get("llm_system"))
        _append_if(cmd, "--rewrite-model", args.get("rewrite_model"))
        _append_if(cmd, "--model", args.get("model"))
        _append_image_common(cmd, args)
        if mode == "edit":
            _append_if(cmd, "--input-file", args.get("input_file"))
        elif mode == "reference_edit":
            input_files = _string_list(args.get("input_files"))
            if not input_files and args.get("input_file"):
                input_files = _string_list(args.get("input_file"))
            if input_files:
                cmd += ["--input-files", *input_files]
            _append_if(cmd, "--image-urls-json", args.get("image_urls_json"))
        elif mode == "batch":
            n = args.get("n")
            if n is not None:
                cmd += ["-n", str(_int_value(n, "n"))]
        prompt = args.get("prompt")
        if prompt:
            if mode == "reference_edit" and (_string_list(args.get("input_files")) or args.get("input_file")):
                cmd.append("--")
            cmd.append(str(prompt))
        return cmd

    if route in {"imagine", "imagine-natural"}:
        if bool(args.get("dry_run")):
            cmd.append("--dry-run")
        _append_if(cmd, "--system", args.get("system"))
        if route == "imagine":
            _append_if(cmd, "--rewrite-system", args.get("rewrite_system"))
            _append_if(cmd, "--rewrite-model", args.get("rewrite_model"))
        else:
            _append_if(cmd, "--language-model", args.get("language_model"))
        _append_if(cmd, "--model", args.get("model"))
        _append_image_common(cmd, args)
        _append_prompt(cmd, args.get("prompt"))
        return cmd

    raise ToolRequestError(f"Unsupported route: {route}")


def validate_tool_request(request: dict[str, Any], *, cfg: dict[str, Any] | None = None) -> None:
    if not isinstance(request, dict):
        raise ToolRequestError("tool request must be a JSON object.")
    if request.get("action") != ALLOWED_ACTION:
        raise ToolRequestError(f"Only {ALLOWED_ACTION} is allowed.")
    route = request.get("route")
    if route not in ALLOWED_ROUTES:
        raise ToolRequestError(f"Unsupported route: {route}")
    if not _route_enabled(str(route), cfg or {}):
        raise ToolRequestError(f"Tool route is disabled in config: {route}")

    args = request.get("args") or {}
    if not isinstance(args, dict):
        raise ToolRequestError("args must be an object.")
    if "command" in args or "shell" in args or "python_code" in args:
        raise ToolRequestError("Arbitrary command or Python execution is not allowed.")

    if route in {"text", "vision"} and args.get("image_url") and args.get("image_file"):
        raise ToolRequestError(f"{route} tool requests must use either image_url or image_file, not both.")

    if route == "vision" and not args.get("image_url") and not args.get("image_file"):
        raise ToolRequestError("vision tool requests require image_url or image_file.")

    if route == "image":
        mode = str(args.get("mode") or "generate")
        if mode not in IMAGE_MODES:
            raise ToolRequestError(f"Unsupported image mode: {mode}")
        if "image_format" in args and args["image_format"] not in IMAGE_FORMATS:
            raise ToolRequestError(f"Unsupported image_format: {args['image_format']}")
        _validate_common_image_args(args)

    if route in {"imagine", "imagine-natural"}:
        if "image_format" in args and args["image_format"] not in IMAGE_FORMATS:
            raise ToolRequestError(f"Unsupported image_format: {args['image_format']}")
        _validate_common_image_args(args)


def tool_request_summary(request: dict[str, Any]) -> str:
    args = request.get("args") if isinstance(request.get("args"), dict) else {}
    route = request.get("route", "")
    risk = "Low"
    if route in {"image", "imagine", "imagine-natural"}:
        risk = "Medium"
    if route == "video":
        risk = "Low (scaffold)"
    prompt = str(args.get("prompt") or "")
    if len(prompt) > 180:
        prompt = prompt[:177] + "..."
    return "\n".join([
        "Tool Request Detected",
        "",
        f"Action : {request.get('action', '')}",
        f"Route  : {route}",
        f"Risk   : {risk}",
        f"Prompt : {prompt}" if prompt else "Prompt : (from config or omitted)",
        "",
        "Review the command below. Press Run to approve and execute.",
    ])


def build_tool_instructions(cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tools_cfg = cfg.get("tools") if isinstance(cfg.get("tools"), dict) else {}
    enabled = tools_cfg.get("instructions_enabled", True)
    if enabled is False:
        return "", {"enabled": False, "routes": []}

    routes = _active_routes(cfg)
    if not routes:
        return "", {"enabled": False, "routes": []}

    route_lines = "\n".join(f"- {route}" for route in routes)
    instructions = f"""EasyGrok Tool Request Protocol:

You may request local EasyGrok execution by outputting a JSON object.
You do not execute tools yourself. The UI detects the JSON, shows a command preview, and waits for human approval.

Allowed action:
- {ALLOWED_ACTION}

Allowed routes:
{route_lines}

Rules:
- Use a tool request only when it would materially help the user's task.
- If the current user message already includes an attached image, answer from that image directly. Do not request a vision tool for the same image.
- Do not request arbitrary shell commands, arbitrary Python, file deletion, Git operations, environment variable access, or API key access.
- If a tool is useful, include one JSON object with this shape:

{{
  "action": "run_easy_command",
  "route": "text|vision|image|imagine|imagine-natural|video",
  "args": {{
    "prompt": "..."
  }}
}}

For image-aware chat, prefer route "text" with image_file or image_url.
Vision tool requests require image_file or image_url.

Common image args:
- mode: generate | edit | reference_edit | batch
- prompt
- aspect_ratio
- resolution: 1k | 2k
- image_format: url | base64
- input_file: for edit, or one reference image for reference_edit
- input_files: list of reference images for reference_edit
- dry_run

After a tool request, briefly explain why it helps. The user will approve or reject it in the UI."""
    return instructions, {"enabled": True, "routes": routes, "action": ALLOWED_ACTION}


def _append_image_common(cmd: list[str], args: dict[str, Any]) -> None:
    _append_if(cmd, "--aspect-ratio", args.get("aspect_ratio"))
    _append_if(cmd, "--resolution", args.get("resolution"))
    _append_if(cmd, "--image-format", args.get("image_format"))
    if bool(args.get("download")):
        cmd.append("--download")


def _validate_common_image_args(args: dict[str, Any]) -> None:
    if "resolution" in args and args["resolution"] not in IMAGE_RESOLUTIONS:
        raise ToolRequestError(f"Unsupported resolution: {args['resolution']}. Use 1k or 2k.")


def _append_prompt(cmd: list[str], prompt: Any) -> None:
    if prompt:
        cmd.append(str(prompt))


def _append_if(cmd: list[str], flag: str, value: Any) -> None:
    if value is not None and value != "":
        cmd += [flag, str(value)]


def _int_value(value: Any, name: str) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise ToolRequestError(f"{name} must be an integer.") from exc


def _string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    raise ToolRequestError("input_files must be a string or list of strings.")


def _route_enabled(route: str, cfg: dict[str, Any]) -> bool:
    active = cfg.get("tools", {}).get("active", {}) if isinstance(cfg.get("tools"), dict) else {}
    if not isinstance(active, dict) or route not in active:
        return True
    return bool(active.get(route))


def _active_routes(cfg: dict[str, Any]) -> list[str]:
    active = cfg.get("tools", {}).get("active", {}) if isinstance(cfg.get("tools"), dict) else {}
    if not isinstance(active, dict) or not active:
        return sorted(ALLOWED_ROUTES)
    return [route for route in sorted(ALLOWED_ROUTES) if bool(active.get(route, True))]


def _json_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    decoder = json.JSONDecoder()

    for fence in _fenced_json_blocks(text):
        candidates.append(fence)

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _obj, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        candidates.append(text[index:index + end])
    return candidates


def _fenced_json_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    marker = "```"
    start = 0
    while True:
        open_index = text.find(marker, start)
        if open_index == -1:
            break
        line_end = text.find("\n", open_index)
        if line_end == -1:
            break
        fence_label = text[open_index + len(marker):line_end].strip().lower()
        close_index = text.find(marker, line_end + 1)
        if close_index == -1:
            break
        body = text[line_end + 1:close_index].strip()
        if fence_label in {"json", ""} and body.startswith("{"):
            blocks.append(body)
        start = close_index + len(marker)
    return blocks
