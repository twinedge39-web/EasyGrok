---

# 🧠 Grok CLI Orchestrator

Reproducible CLI environment for xAI Grok API.
Minimal. Transparent. Hackable.

---

## 📌 What This Is

This is **not** a product.
This is a **reproducibility-first CLI harness** for Grok API.

* No GUI
* No magic state
* No hidden prompts
* No middleware abstraction layer

Everything is explicit.
Everything is logged.

Modify freely.

---

## 🎯 Design Philosophy

1. API is stateless → always send system prompt
2. Save raw JSON every time
3. Human-readable Markdown output
4. No session illusions
5. Config-driven execution

If you want a polished UX, build your own on top.

---

## 📂 Structure

```
project/
│
├─ config/
│   └─ config.user.json
│
├─ out/
│   ├─ text_raw_*.json
│   ├─ vision_raw_*.json
│   ├─ image_raw_*.json
│   └─ images/
│
├─ easy.py
└─ README.md
```

---

## 🛠 Requirements

* Python 3.10+
* xai-sdk

Install:

```bash
pip install xai-sdk
```

Set API key:

### macOS / Linux

```bash
export XAI_API_KEY="your_api_key"
```

### Windows (PowerShell)

```powershell
setx XAI_API_KEY "your_api_key"
```

---

## ⚙️ Models (snapshot)

Refer to snapshot memo:


Default config uses:

* grok-4-1-fast-reasoning
* grok-2-vision-1212
* grok-imagine-image

Update as needed.

---

## 🧩 Configuration

Main config:

`config/config.user.json`

Reference template:


Everything user-adjustable lives there:

* models
* prompts
* output behavior
* image settings

No hidden runtime state.

---

## 🚀 Usage

### Text

```bash
python easy.py text
```

Override prompt:

```bash
python easy.py text "Explain entropy in Japanese"
```

---

### Vision

```bash
python easy.py vision --image-url https://example.com/image.jpg
```

Local file:

```bash
python easy.py vision --image-file test.jpg
```

---

### Image (Generate)

```bash
python easy.py image
```

Batch:

```bash
python easy.py image --mode batch -n 4
```

Download immediately:

```bash
python easy.py image --download
```

---

### Image Edit

```bash
python easy.py image --mode edit --input-file input.jpg
```

---

### Interactive Menu

```bash
python easy.py menu
```

Features:

* Live config editing
* Mode switching
* Backup auto-created
* Optional immediate execution

---

## 📦 Output Policy

Each run produces:

### Raw JSON (canonical log)

```json
{
  "ts": "...",
  "mode": "...",
  "model": "...",
  "prompt": "...",
  "content": "..."
}
```

### Markdown

Human-readable output only.

### Images

* URL always saved
* Optional immediate download

No silent discard.

---

## ⚠️ Disclaimer

* Generated images are subject to moderation.
* Returned URLs may not be permanent.
* No warranty.
* No support.
* No responsibility.

This repository is provided as-is.

---

## 🔥 Why This Exists

Because UI != reproducibility.

This tool exists to:

* Test API behavior
* Observe moderation differences
* Compare model variants
* Preserve raw evidence
* Build your own orchestration layer

---

## 🧩 Extend It Yourself

Ideas:

* Thread manager
* Token usage tracker
* Cost estimator
* Batch experiment runner
* Video model integration
* Automatic retry logic
* Prompt pass-rate logging

This repo intentionally stays minimal.

---

## 🪓 License

Choose your own.

If you don't care:

* MIT is fine.
* Or just say "Do whatever you want."

---

---