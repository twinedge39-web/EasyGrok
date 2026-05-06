# EasyGrok

EasyGrok is a small reproducible CLI harness for the xAI Grok API.

It is built for local experiments where the important parts are explicit:
models, prompts, context files, raw responses, Markdown output, and saved images.

## Features

- Text completion
- Vision analysis from image URL or local image file
- Image generation, image edit, reference edit, and batch generation
- Optional LLM rewrite before image generation
- Markdown context memory
- Short-term session logging
- Raw JSON and Markdown output
- Interactive config menu

## Install

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set your API key:

```powershell
setx XAI_API_KEY "your_xai_api_key"
```

Restart the terminal after `setx`.

## Configure

Copy the example config and edit it locally:

```powershell
Copy-Item config\config.user.example.json config\config.user.json
```

`config/config.user.json` is intentionally ignored by Git.

## Usage

Text:

```powershell
py easy.py text "こんにちは。短く自己紹介して。"
```

Vision:

```powershell
py easy.py vision --image-url "https://example.com/image.jpg" "この画像を説明して。"
```

Local image vision:

```powershell
py easy.py vision --image-file ".\sample.jpg" "見えているものを説明して。"
```

Image generation:

```powershell
py easy.py image "A quiet futuristic study room, warm desk light, cinematic realism"
```

Image generation with base64 file saving:

```powershell
py easy.py image "A clean product photo of a small robot assistant" --image-format base64
```

Reference edit from local files:

```powershell
py easy.py image --mode reference_edit --input-files ".\ref1.jpg" ".\ref2.jpg" "Combine the visual style of both references."
```

Interactive menu:

```powershell
py easy.py menu
```

## Context Memory

EasyGrok can load Markdown context files before a text or vision run.

The example config uses:

- `memory/context.md`
- `memory/assistant_profile.md`
- `memory/session.md`

Disable context for one run:

```powershell
py easy.py text --no-context "短く答えて。"
```

Disable session append for one run:

```powershell
py easy.py text --no-session "これはセッションログに残さないで。"
```

## Output

By default, EasyGrok writes output to `out/`.

Typical files:

- `text_*.md`
- `text_raw_*.json`
- `vision_*.md`
- `vision_raw_*.json`
- `image_*.md`
- `image_raw_*.json`
- `out/images/*`

`out/` is ignored by Git.

## Public Safety

This repository is a public-safe starter version.

It does not include private API keys, private character material, generated image logs, or local experiment outputs.

Keep personal configs, logs, prompts, generated media, and private memory files out of Git unless you intentionally want to publish them.

