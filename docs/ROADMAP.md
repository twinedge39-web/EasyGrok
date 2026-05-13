# EasyGrok Roadmap

EasyGrok is a reproducible local harness for working with Grok text, vision,
and image APIs.

The project is guided by one simple theme:

```text
Make AI runs explicit, inspectable, and replayable.
```

EasyGrok is not trying to hide prompts, context, model choices, or outputs behind
a polished black box. It is meant to show what was sent, what came back, and how
the result can be reviewed later.

---

## Guiding Principles

### Transparency First

Every run should make its inputs and outputs visible:

- model
- prompt
- context files
- image inputs
- output format
- raw response
- Markdown summary

The goal is to make experimentation easier to inspect and easier to explain.

### CLI First

The CLI is the source of truth.

The Tkinter console is an orchestration UI over explicit commands, not a hidden
workflow engine. This keeps runs scriptable, auditable, and easier to reproduce.

### Local Files Are Canonical

Returned URLs may expire or change.

EasyGrok prefers saving useful outputs locally, along with enough metadata to
understand how they were produced.

### Human Approval For Tool Runs

When an LLM suggests a local EasyGrok action, the UI shows the command and waits
for human approval.

The model may propose. The user triggers execution.

---

## Current Status

Implemented today:

- Text runs
- Text runs with optional image attachment
- Vision runs from image URL or local image file
- Image generation
- Image edit and reference edit
- Batch image generation
- Imagine relay, where a language model prepares an image prompt
- Natural Imagine relay, where a natural response is converted into an image prompt
- Raw JSON and Markdown logs
- Markdown context memory
- Session append, reset, and archive
- Tkinter prompt console
- Logs tab with replay command preview
- Tool request detection and approval
- Recent generated image handoff for review
- Video route scaffold

Not implemented yet:

- Real video generation API flow
- Job queue and polling
- Automatic retry policies
- Prompt success database
- Local Stable Diffusion adapter
- Local LLM adapter
- Explicit persona profile switching

---

## Roadmap

### 1. Strengthen Replay And Audit

Replay is not exact determinism. LLM and image APIs can change behavior over
time.

EasyGrok treats replay as condition reconstruction:

```text
same command
same prompt
same context
same model settings
new API run
```

Planned work:

- improve raw JSON pairing with Markdown logs
- show replay differences more clearly
- record tool approval metadata
- preserve local file references
- add checksums for saved images

### 2. Make Local Saving The Default Path

URL outputs are convenient but fragile.

Planned work:

- optional auto-download for URL image outputs
- checksum saved files
- store metadata next to saved media
- make local saved files easier to review from the UI

### 3. Separate Public And Lab Profiles

EasyGrok should support public-safe usage without blocking deeper local
experimentation.

Planned work:

- public-safe example config
- lab config conventions
- clearer ignored-file boundaries
- docs for what should never be committed

### 4. Build A Prompt And Log Index

Logs become more useful when they can be searched, tagged, and reused.

Planned work:

- log index
- tags
- favorites
- reuse count
- success or moderation result
- prompt family notes

### 5. Treat Queue As A General Job System

Video generation will need polling, status, and delayed completion. The same
structure can later support longer workflows.

Possible job flow:

```text
rewrite prompt
generate
analyze result
suggest fix
retry with limit
archive output
```

Planned work:

- job queue
- max retry limits
- progress display
- result archive

### 6. Add More Engines Carefully

EasyGrok can grow beyond direct xAI API calls while keeping the same transparency
model.

Possible adapters:

- local Stable Diffusion APIs
- ComfyUI
- AUTOMATIC1111 or Forge-compatible endpoints
- local LLMs such as Ollama, LM Studio, llama.cpp, or vLLM

Likely roles for local LLMs:

- rewrite
- classification
- tagging
- low-cost review

### 7. Separate Persona And Safety Profiles

Personas can control tone, goals, and default workflows.

Safety profiles should be separate so the same persona can be used in different
operating contexts.

Planned structure:

```text
persona profile
+
safety profile
+
tool permissions
```

---

## Long-Term Direction

EasyGrok is moving toward a local AI operations bench:

```text
prompt
context
tool request
human approval
execution
local output
log
review
replay
```

The important part is not only generation. The important part is knowing what
happened, preserving the evidence, and making the next run easier to reason
about.

