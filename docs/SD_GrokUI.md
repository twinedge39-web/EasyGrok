# SD GrokUI / Local SD Adapter Status

SD GrokUI is an experimental local Stable Diffusion adapter UI for EasyGrok.

It is designed to keep Stable Diffusion settings separate from the main
EasyGrok UI while still allowing Grok-assisted prompt/config drafting.

## Purpose

- Use an existing local Stable Diffusion WebUI/Forge server through its API.
- Keep SD-specific settings in `config/config.sd.json`.
- Let the user inspect and edit generation settings before execution.
- Let Grok draft safe config patches, but keep local validation and human
  approval in control.

## Entry Points

Run the SD adapter summary:

```powershell
.\.venv\Scripts\python.exe easy.py sd
```

Run SD GrokUI:

```powershell
.\.venv\Scripts\python.exe sd_grok_ui.py
```

Run the standalone local probe:

```powershell
.\.venv\Scripts\python.exe scripts\sd_local_probe.py
```

## Main Files

- `config/config.sd.json`: local SD runtime config.
- `config/config.sd.example.json`: example SD config.
- `config/sd_ask_persona.md`: SD Grok prompt-editing persona.
- `memory/sd_ask_session.md`: optional local SD prompt/session notes. This is
  runtime memory and should not be published.
- `core/sd_adapter.py`: local SD API adapter.
- `core/sd_config.py`: safe config patch and validation gate.
- `core/sd_ask.py`: Grok-to-SD-config draft helper.
- `scripts/sd_config_tool.py`: command-line config edit tool.
- `scripts/sd_local_probe.py`: standalone API probe/generation script.
- `ui/sd_grok_ui/app.py`: SD GrokUI implementation.
- `sd_grok_ui.py`: SD GrokUI launcher.

## Verified

- Stable Diffusion WebUI/Forge API can be enabled with `--api`.
- `/sdapi/v1/progress` responds when WebUI is fully restarted with API enabled.
- `txt2img` works through the local SD API.
- Checkpoint switching works through the local SD API.
- `DPM++ 2M SDE` with `Karras` schedule is accepted by the tested WebUI.
- `768x1024` generation works on the current local setup.
- `n_iter` can be used for repeated single-image runs.
- Local safety currently keeps `batch_size` at `1`.
- SD GrokUI can preview payloads and execute local generation.
- SD GrokUI can save/load AskLLM/Grok draft JSON.
- SD GrokUI can open the output folder and launch the preview viewer.
- Config backups now go under `config/backups/<config-name>/` instead of
  cluttering `config/`.

## Partially Verified

- `img2img` payload support exists, but heavier reference-image workflows are
  not yet validated on the 8GB VRAM machine.
- Grok Chat can build draft patches in principle, but live testing is paused
  because the current xAI credit/spending limit has been reached.
- The UI can display Grok draft patches, but the conversation UX is still early.
- Error reporting has been improved, but more user-facing polish is needed.

## Not Yet Verified

- Long Grok Chat sessions with multiple turns.
- Cost-safe model selection for SD prompt editing.
- Cached Grok draft responses.
- Hires fix, ADetailer, ControlNet, LoRA management, and reference-heavy
  workflows.
- Robust face/detail recovery for SD1.5 distant full-body compositions.
- Public-safe packaging of SD-specific features.

## Current Constraints

- Local VRAM is treated as limited. Current safe defaults assume 8GB VRAM.
- Keep `batch_size` at `1`.
- Prefer `n_iter` up to `4` for multiple images.
- Avoid distant full-body framing on SD1.5-like models when face quality matters.
- For `yayoiMix_v25`, realistic Japanese/East Asian and bishoujo-oriented
  wording has tested better than generic photo wording.
- Grok API calls cost money. Local `Dry Run`, `Apply`, and SD API generation do
  not call Grok.

## Codex Execution Note

When Codex runs SD generation from the local shell, saving PNG files under
`out/images/sd_images` may require approved execution even if Windows ACLs look
writable.

If a generation run reaches the image-save step and fails with
`PermissionError`, treat it as a Codex sandbox boundary first. Retry with
approved execution before investigating Windows ACLs. Check ACLs only when the
same write also fails from a normal human-run PowerShell.

## Grok API Notes

The Grok helper reads `XAI_API_KEY` from the environment. On Windows it also
falls back to the user/machine environment registry if the current process did
not inherit the variable.

Known failure modes:

- `XAI API credits are exhausted or the monthly spending limit was reached.`
  - The key is valid enough to reach xAI, but the account cannot make requests.
- `dead local proxy at 127.0.0.1:9`
  - A placeholder proxy environment variable is interfering with gRPC.
  - The SD Grok helper now clears that local dead proxy before calling xAI.

## Safety Model

Grok is not allowed to execute arbitrary commands from this path.

The intended flow is:

1. User writes a natural-language prompt/edit request.
2. Grok returns a JSON draft patch.
3. `core.sd_config` validates allowed paths and clamps risky values.
4. User runs `Dry Run`.
5. User chooses whether to `Apply`.
6. User explicitly executes generation.

This keeps the boundary clear:

- Grok drafts.
- Local code validates.
- User approves.
- SD WebUI generates.

## Resume Checklist

When credit testing resumes:

```powershell
.\.venv\Scripts\python.exe easy.py sd-ask "テスト。短く返して。" --dry-run
```

If this passes, test from SD GrokUI:

1. Start `sd_grok_ui.py`.
2. Open `Grok Chat`.
3. Send a short prompt-edit request.
4. Confirm the response appears as chat text.
5. Confirm the draft JSON appears separately.
6. Run `Dry Run`.
7. Apply only after checking the changed paths.

## Design Direction

Keep SD Grok as a separate specialized surface rather than folding all SD
settings into the main EasyGrok prompt console.

Main EasyGrok remains the general API bench.
SD GrokUI remains the local image-generation adapter surface.
