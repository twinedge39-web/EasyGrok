import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from ctypes import byref, c_int, windll
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import sd_adapter, sd_ask, sd_config
from core.common import get_nested, load_json, resolve_project_path


CONFIG_PATH = BASE_DIR / "config" / "config.sd.json"
EASY_CONFIG_PATH = BASE_DIR / "config" / "config.user.json"


class SDGrokUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SD GrokUI")
        self.geometry("1120x1040")
        self.minsize(980, 900)

        self.cfg = {}
        self.process_running = False
        self.samplers = []
        self.schedulers = []
        self.last_images = []
        self.grok_history = []

        self._configure_dark_style()
        self._enable_dark_title_bar()
        self._build_vars()
        self._build_layout()
        self.reload_config()

    def _enable_dark_title_bar(self):
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = windll.user32.GetParent(self.winfo_id())
            value = c_int(1)
            # Windows 11 uses 20. Older Windows 10 builds use 19.
            for attribute in (20, 19):
                result = windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, byref(value), 4)
                if result == 0:
                    break
        except Exception:
            pass

    def _configure_dark_style(self):
        self.bg = "#101216"
        self.panel = "#171a21"
        self.panel_2 = "#1f2430"
        self.fg = "#e8edf2"
        self.muted = "#9ca8b4"
        self.accent = "#78a6ff"
        self.danger = "#ff7a90"

        self.configure(bg=self.bg)
        self.ui_font = ("Segoe UI", 10)
        self.mono_font = ("Consolas", 10)
        self.option_add("*Font", self.ui_font)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=self.bg, foreground=self.fg, fieldbackground=self.panel_2)
        style.configure("TFrame", background=self.bg)
        style.configure("Panel.TFrame", background=self.panel)
        style.configure("TLabel", background=self.bg, foreground=self.fg)
        style.configure("Muted.TLabel", background=self.bg, foreground=self.muted)
        style.configure("Panel.TLabel", background=self.panel, foreground=self.fg)
        style.configure("TButton", background=self.panel_2, foreground=self.fg, bordercolor="#303745")
        style.map("TButton", background=[("active", "#2b3342")])
        style.configure("Accent.TButton", background="#244a88", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#2f5cab")])
        style.configure("TEntry", fieldbackground=self.panel_2, foreground=self.fg, bordercolor="#303745")
        style.configure("TCombobox", fieldbackground=self.panel_2, foreground=self.fg, bordercolor="#303745")
        style.configure("TCheckbutton", background=self.bg, foreground=self.fg)
        style.configure("TLabelframe", background=self.bg, foreground=self.fg, bordercolor="#303745")
        style.configure("TLabelframe.Label", background=self.bg, foreground=self.fg)
        style.configure("TNotebook", background=self.bg, bordercolor="#303745")
        style.configure("TNotebook.Tab", background=self.panel_2, foreground=self.fg, padding=(14, 7))
        style.map("TNotebook.Tab", background=[("selected", "#263247"), ("active", "#2b3342")])

    def _build_vars(self):
        self.status = tk.StringVar(value="Ready.")
        self.mode = tk.StringVar(value="txt2img")
        self.api_url = tk.StringVar(value="")
        self.profile = tk.StringVar(value="")
        self.model = tk.StringVar(value="")
        self.seed = tk.StringVar(value="-1")
        self.width = tk.StringVar(value="768")
        self.height = tk.StringVar(value="1024")
        self.steps = tk.StringVar(value="24")
        self.cfg_scale = tk.StringVar(value="6.5")
        self.sampler = tk.StringVar(value="DPM++ 2M SDE")
        self.scheduler = tk.StringVar(value="Karras")
        self.n_iter = tk.StringVar(value="1")
        self.input_image = tk.StringVar(value="")
        self.denoising_strength = tk.StringVar(value="0.45")
        self.resize_mode = tk.StringVar(value="0")
        self.grok_request = tk.StringVar(value="")

    def _build_layout(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="SD GrokUI", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status, style="Muted.TLabel").pack(side="right")

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_control_panel(left)
        self._build_text_panel(right)

    def _build_control_panel(self, parent):
        row = 0
        ttk.Label(parent, text="Connection", style="Panel.TLabel", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self._readonly(parent, "Profile", self.profile, row)
        row += 1
        self._readonly(parent, "API", self.api_url, row)
        row += 1
        self._readonly(parent, "Model", self.model, row)
        row += 1
        ttk.Button(parent, text="Refresh", command=self.refresh_live_status).grid(row=row, column=0, sticky="ew", pady=(8, 14))
        ttk.Button(parent, text="Reload Config", command=self.reload_config).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 14))
        ttk.Button(parent, text="Save Config", command=self.save_config).grid(row=row, column=2, sticky="ew", pady=(8, 14))
        row += 1

        ttk.Label(parent, text="Generation", style="Panel.TLabel", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self._combo(parent, "Mode", self.mode, ["txt2img", "img2img"], row)
        row += 1
        self._entry(parent, "Width", self.width, row)
        row += 1
        self._entry(parent, "Height", self.height, row)
        row += 1
        self._entry(parent, "Steps", self.steps, row)
        row += 1
        self._entry(parent, "CFG", self.cfg_scale, row)
        row += 1
        self._combo(parent, "Sampler", self.sampler, ["DPM++ 2M SDE", "Euler a"], row)
        row += 1
        self._combo(parent, "Scheduler", self.scheduler, ["Karras", "Automatic", "Exponential"], row)
        row += 1
        self._entry(parent, "Seed", self.seed, row)
        row += 1
        self._entry(parent, "Runs", self.n_iter, row)
        row += 1
        ttk.Label(
            parent,
            text="Runs uses n_iter. Keep batch at 1 for 8GB VRAM.",
            style="Panel.TLabel",
            foreground=self.muted,
            wraplength=330,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        ttk.Label(parent, text="Img2Img", style="Panel.TLabel", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, columnspan=3, sticky="w", pady=(14, 0))
        row += 1
        ttk.Label(parent, text="Input", style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.input_image, width=32).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=self.browse_input_image).grid(row=row, column=2, sticky="ew", padx=(6, 0), pady=4)
        row += 1
        self._entry(parent, "Denoise", self.denoising_strength, row)
        row += 1
        self._entry(parent, "Resize", self.resize_mode, row)
        row += 1

        ttk.Button(parent, text="Preview Payload", style="Accent.TButton", command=self.preview_payload).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(18, 6))
        row += 1
        ttk.Button(parent, text="Execute", command=self.execute_generation).grid(row=row, column=0, columnspan=3, sticky="ew")
        row += 1
        ttk.Button(parent, text="Start Preview Viewer", command=self.start_preview_viewer).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(14, 6))
        row += 1
        ttk.Button(parent, text="Open Output Folder", command=self.open_output_folder).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        row += 1
        ttk.Button(parent, text="Open Latest in Viewer", command=self.open_latest_in_viewer).grid(row=row, column=0, columnspan=3, sticky="ew")

        for col in range(3):
            parent.columnconfigure(col, weight=1)

    def _build_text_panel(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.grid(row=0, column=0, rowspan=2, sticky="nsew")
        generate_tab = ttk.Frame(notebook, padding=0)
        grok_chat_tab = ttk.Frame(notebook, padding=0)
        notebook.add(generate_tab, text="Generate")
        notebook.add(grok_chat_tab, text="Grok Chat")
        generate_tab.columnconfigure(0, weight=1)
        generate_tab.rowconfigure(0, weight=1)
        generate_tab.rowconfigure(1, weight=1)
        grok_chat_tab.columnconfigure(0, weight=1)
        grok_chat_tab.rowconfigure(1, weight=1)
        grok_chat_tab.rowconfigure(5, weight=1)

        prompt_frame = ttk.Frame(generate_tab)
        prompt_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.columnconfigure(1, weight=1)
        prompt_frame.rowconfigure(1, weight=1)

        ttk.Label(prompt_frame, text="Prompt").grid(row=0, column=0, sticky="w")
        ttk.Label(prompt_frame, text="Negative").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.prompt_text = self._dark_text(prompt_frame, height=10)
        self.negative_text = self._dark_text(prompt_frame, height=10)
        self.prompt_text.grid(row=1, column=0, sticky="nsew")
        self.negative_text.grid(row=1, column=1, sticky="nsew", padx=(10, 0))

        output_frame = ttk.Frame(generate_tab)
        output_frame.grid(row=1, column=0, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(1, weight=1)
        ttk.Label(output_frame, text="Output").grid(row=0, column=0, sticky="w")
        self.output_text = self._dark_text(output_frame, height=18)
        self.output_text.grid(row=1, column=0, sticky="nsew")

        self._build_grok_chat_panel(grok_chat_tab)

    def _build_grok_chat_panel(self, parent):
        ttk.Label(parent, text="Grok Conversation").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.grok_chat_text = self._dark_text(parent, height=8)
        self.grok_chat_text.grid(row=1, column=0, sticky="nsew")
        self.grok_chat_text.insert(
            "1.0",
            "Tell Grok how to change the SD prompt or settings. Grok returns a safe JSON patch.\n"
            "Dry Run and Apply still pass through core.sd_config.\n",
        )

        request_row = ttk.Frame(parent)
        request_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        request_row.columnconfigure(0, weight=1)
        ttk.Entry(request_row, textvariable=self.grok_request).grid(row=0, column=0, sticky="ew")
        ttk.Button(request_row, text="Ask Grok", style="Accent.TButton", command=self.ask_grok_for_patch).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(parent, text="Draft Patch").grid(row=4, column=0, sticky="w", pady=(14, 6))
        self.askllm_text = self._dark_text(parent, height=24)
        self.askllm_text.grid(row=5, column=0, sticky="nsew")

        buttons = ttk.Frame(parent)
        buttons.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        buttons.columnconfigure(3, weight=1)
        buttons.columnconfigure(4, weight=1)
        buttons.columnconfigure(5, weight=1)
        ttk.Button(buttons, text="Insert Sample", command=self.insert_askllm_sample).grid(row=0, column=0, sticky="ew")
        ttk.Button(buttons, text="Paste", command=self.paste_askllm).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(buttons, text="Save Draft", command=self.save_askllm_draft).grid(row=0, column=2, sticky="ew")
        ttk.Button(buttons, text="Load Draft", command=self.load_askllm_draft).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(buttons, text="Dry Run", command=self.dry_run_askllm_patch).grid(row=0, column=4, sticky="ew")
        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=self.apply_askllm_patch).grid(row=0, column=5, sticky="ew", padx=(6, 0))

        note = (
            "Grok output and pasted JSON are drafts only. Allowed paths are checked by core.sd_config. "
            "Apply saves config with backup; Execute still requires the Generate tab."
        )
        ttk.Label(parent, text=note, style="Muted.TLabel", wraplength=760).grid(row=7, column=0, sticky="w", pady=(8, 0))

    def _dark_text(self, parent, **kwargs) -> tk.Text:
        return tk.Text(
            parent,
            bg=self.panel,
            fg=self.fg,
            insertbackground=self.fg,
            selectbackground="#315b9e",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
            font=self.mono_font,
            wrap="word",
            **kwargs,
        )

    def _readonly(self, parent, label, variable, row):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable, state="readonly", width=42).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _combo(self, parent, label, variable, values, row):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        box = ttk.Combobox(parent, textvariable=variable, values=values, width=24)
        box.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        if label == "Sampler":
            self.sampler_box = box
        if label == "Scheduler":
            self.scheduler_box = box

    def reload_config(self):
        try:
            self.cfg = sd_adapter.load_sd_config(CONFIG_PATH)
            self._apply_config_to_fields()
            self.status.set("Config loaded.")
            self._log(f"Loaded {CONFIG_PATH}")
            self.refresh_live_status()
        except Exception as exc:
            self.status.set("Config load failed.")
            self._log_error(exc)

    def _apply_config_to_fields(self):
        self.profile.set(str(get_nested(self.cfg, "profile.name") or ""))
        self.api_url.set(str(get_nested(self.cfg, "connection.api_url") or ""))
        self.mode.set(str(get_nested(self.cfg, "generation.mode") or "txt2img"))
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", str(get_nested(self.cfg, "generation.prompt") or ""))
        self.negative_text.delete("1.0", "end")
        self.negative_text.insert("1.0", str(get_nested(self.cfg, "generation.negative_prompt") or ""))

        common = get_nested(self.cfg, "generation.common") or {}
        txt2img = get_nested(self.cfg, "generation.txt2img") or {}
        img2img = get_nested(self.cfg, "generation.img2img") or {}
        self.width.set(str(txt2img.get("width") or img2img.get("width") or 768))
        self.height.set(str(txt2img.get("height") or img2img.get("height") or 1024))
        self.steps.set(str(common.get("steps", 24)))
        self.cfg_scale.set(str(common.get("cfg_scale", 6.5)))
        self.sampler.set(str(common.get("sampler_name", "DPM++ 2M SDE")))
        self.scheduler.set(str(common.get("scheduler", "Karras")))
        self.seed.set(str(common.get("seed", -1)))
        self.n_iter.set(str(common.get("n_iter", 1)))
        self.input_image.set(str(img2img.get("input_image") or ""))
        self.denoising_strength.set(str(img2img.get("denoising_strength", 0.45)))
        self.resize_mode.set(str(img2img.get("resize_mode", 0)))

    def _apply_fields_to_config(self):
        generation = self.cfg.setdefault("generation", {})
        generation["mode"] = self.mode.get()
        generation["prompt"] = self.prompt_text.get("1.0", "end").strip()
        generation["negative_prompt"] = self.negative_text.get("1.0", "end").strip()
        common = generation.setdefault("common", {})
        common["steps"] = int(self.steps.get())
        common["cfg_scale"] = float(self.cfg_scale.get())
        common["sampler_name"] = self.sampler.get()
        common["scheduler"] = self.scheduler.get()
        common["seed"] = int(self.seed.get())
        common["batch_size"] = 1
        common["max_batch_size"] = 1
        common["n_iter"] = self._bounded_int(self.n_iter.get(), 1, int(common.get("max_n_iter", 4)))
        common["max_n_iter"] = int(common.get("max_n_iter", 4))
        common.setdefault("restore_faces", False)
        common.setdefault("tiling", False)

        txt2img = generation.setdefault("txt2img", {})
        txt2img["width"] = int(self.width.get())
        txt2img["height"] = int(self.height.get())
        img2img = generation.setdefault("img2img", {})
        img2img["input_image"] = self.input_image.get().strip()
        img2img["width"] = int(self.width.get())
        img2img["height"] = int(self.height.get())
        img2img["denoising_strength"] = float(self.denoising_strength.get())
        img2img["resize_mode"] = int(self.resize_mode.get())

    def save_config(self):
        try:
            self._apply_fields_to_config()
            sd_config.save_sd_config(CONFIG_PATH, self.cfg, create_backup=True)
            self.status.set("Config saved.")
            self._log(f"Saved {CONFIG_PATH}")
        except Exception as exc:
            self.status.set("Config save failed.")
            self._log_error(exc)

    def refresh_live_status(self):
        self._run_background(self._refresh_live_status_worker, "Refreshing live SD status...")

    def _refresh_live_status_worker(self):
        progress = sd_adapter.check_sd(self.cfg)
        options = sd_adapter.get_options(self.cfg)
        summary = sd_adapter.summarize_options(self.cfg, options)
        self.samplers = [item.get("name") for item in sd_adapter.get_samplers(self.cfg) if item.get("name")]
        self.schedulers = [
            item.get("label") or item.get("name") for item in sd_adapter.get_schedulers(self.cfg)
            if item.get("label") or item.get("name")
        ]
        return {"progress": progress, "summary": summary}

    def _finish_refresh_live_status(self, data):
        summary = data["summary"]
        self.model.set(str(summary.get("model") or ""))
        if self.samplers:
            self.sampler_box.configure(values=self.samplers)
        if self.schedulers:
            self.scheduler_box.configure(values=self.schedulers)
        self.status.set("Live status refreshed.")
        self._log(json.dumps(summary, ensure_ascii=False, indent=2))

    def browse_input_image(self):
        path = filedialog.askopenfilename(
            title="Select img2img input image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.input_image.set(path)

    def insert_askllm_sample(self):
        sample = {
            "sd_config_patch": {
                "generation": {
                    "prompt": "realistic portrait photo of an adult Japanese bishoujo, East Asian features, long dark hair, upper body framing, close distance, slight upward perspective, looking slightly downward at the viewer, calm evaluative gaze, composed expression, quiet confidence, soft but distant eye contact, relaxed without performance, focused only on the viewer, minimal gray studio background, soft directional light, natural skin texture, high quality photography",
                    "negative_prompt": "lowres, blurry, bad anatomy, bad hands, extra fingers, missing fingers, text, watermark, logo, cropped, nsfw, cute smile, idol pose, cheerful expression, innocent look, exaggerated glamour, western face",
                    "common": {
                        "n_iter": 2,
                        "seed": -1
                    }
                }
            }
        }
        self.askllm_text.delete("1.0", "end")
        self.askllm_text.insert("1.0", json.dumps(sample, ensure_ascii=False, indent=2))

    def paste_askllm(self):
        try:
            text = self.clipboard_get()
            self.askllm_text.delete("1.0", "end")
            self.askllm_text.insert("1.0", text)
        except Exception as exc:
            self._log_error(exc)

    def ask_grok_for_patch(self):
        if self.process_running:
            messagebox.showinfo("SD GrokUI", "Another operation is already running.")
            return
        request_text = self.grok_request.get().strip()
        if not request_text:
            messagebox.showinfo("SD GrokUI", "Enter a request for Grok first.")
            return
        self._append_grok_chat("You", request_text)
        self._run_background(lambda: self._ask_grok_worker(request_text), "Asking Grok for SD patch...")

    def _ask_grok_worker(self, request_text: str):
        self._apply_fields_to_config()
        easy_cfg = load_json(EASY_CONFIG_PATH)
        result = sd_ask.ask_for_sd_chat(
            easy_cfg=easy_cfg,
            current_sd_cfg=self.cfg,
            request_text=request_text,
            chat_history=self.grok_history[-8:],
        )
        preview = sd_ask.dry_run_patch(self.cfg, result["patch"])
        return {
            "grok_chat": True,
            "model": result.get("model"),
            "content": result.get("content"),
            "assistant_message": result.get("assistant_message"),
            "patch": result["patch"],
            "preview": preview,
            "request_text": request_text,
        }

    def _finish_grok_chat(self, data):
        patch_text = json.dumps(data["patch"], ensure_ascii=False, indent=2)
        self.askllm_text.delete("1.0", "end")
        self.askllm_text.insert("1.0", patch_text)
        assistant_message = data.get("assistant_message") or "Draftを作りました。下のDraft Patchで確認できます。"
        self._append_grok_chat("Grok", assistant_message)
        self.grok_history.append({"role": "user", "content": data.get("request_text", "")})
        self.grok_history.append({"role": "assistant", "content": assistant_message})
        self.status.set("Grok draft ready.")
        self._log(json.dumps({
            "grok_chat": True,
            "model": data.get("model"),
            "changed": data.get("preview", {}).get("changed"),
            "issues": data.get("preview", {}).get("issues"),
        }, ensure_ascii=False, indent=2))

    def _append_grok_chat(self, speaker: str, text: str):
        self.grok_chat_text.insert("end", f"\n[{speaker}]\n{text.strip()}\n")
        self.grok_chat_text.see("end")

    def save_askllm_draft(self):
        try:
            text = self.askllm_text.get("1.0", "end").strip()
            if not text:
                raise ValueError("AskLLM draft is empty")
            json.loads(text)
            path = filedialog.asksaveasfilename(
                title="Save AskLLM draft",
                initialdir=str(self._draft_dir()),
                initialfile="sd_askllm_draft.json",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not path:
                return
            Path(path).write_text(text + "\n", encoding="utf-8")
            self.status.set("AskLLM draft saved.")
            self._log(f"Saved AskLLM draft: {path}")
        except Exception as exc:
            self.status.set("AskLLM draft save failed.")
            self._log_error(exc)

    def load_askllm_draft(self):
        try:
            path = filedialog.askopenfilename(
                title="Load AskLLM draft",
                initialdir=str(self._draft_dir()),
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if not path:
                return
            text = Path(path).read_text(encoding="utf-8")
            json.loads(text)
            self.askllm_text.delete("1.0", "end")
            self.askllm_text.insert("1.0", text)
            self.status.set("AskLLM draft loaded.")
            self._log(f"Loaded AskLLM draft: {path}")
        except Exception as exc:
            self.status.set("AskLLM draft load failed.")
            self._log_error(exc)

    def _read_askllm_patch(self):
        text = self.askllm_text.get("1.0", "end").strip()
        if not text:
            raise ValueError("AskLLM patch is empty")
        return json.loads(text)

    def dry_run_askllm_patch(self):
        try:
            draft = self._read_askllm_patch()
            candidate = json.loads(json.dumps(self.cfg, ensure_ascii=False))
            changed = sd_config.apply_patch(candidate, draft)
            self._log(json.dumps({"dry_run": True, "changed": changed, "normalized": candidate}, ensure_ascii=False, indent=2))
            self.status.set("AskLLM dry run ready.")
        except Exception as exc:
            self.status.set("AskLLM dry run failed.")
            self._log_error(exc)

    def apply_askllm_patch(self):
        try:
            draft = self._read_askllm_patch()
            changed = sd_config.apply_patch(self.cfg, draft)
            result = sd_config.save_sd_config(CONFIG_PATH, self.cfg, create_backup=True)
            self._apply_config_to_fields()
            self._log(json.dumps({"applied": True, "changed": changed, "saved": result["saved"], "backup": result["backup"]}, ensure_ascii=False, indent=2))
            self.status.set("AskLLM patch applied.")
        except Exception as exc:
            self.status.set("AskLLM apply failed.")
            self._log_error(exc)

    def _current_payload(self):
        self._apply_fields_to_config()
        mode, payload = sd_adapter.build_payload(
            self.cfg,
            mode=self.mode.get(),
            prompt_override=self.prompt_text.get("1.0", "end").strip(),
            negative_override=self.negative_text.get("1.0", "end").strip(),
            input_image=self.input_image.get().strip() or None,
            denoising_strength=float(self.denoising_strength.get()),
            width=int(self.width.get()),
            height=int(self.height.get()),
            steps=int(self.steps.get()),
            cfg_scale=float(self.cfg_scale.get()),
            sampler_name=self.sampler.get(),
            scheduler=self.scheduler.get(),
            seed=int(self.seed.get()),
            resize_mode=int(self.resize_mode.get()),
        )
        return mode, payload

    def _bounded_int(self, value, minimum, maximum):
        parsed = int(value)
        if parsed < minimum:
            return minimum
        if parsed > maximum:
            self._log(f"Runs capped at {maximum} for local VRAM safety.")
            return maximum
        return parsed

    def preview_payload(self):
        try:
            mode, payload = self._current_payload()
            self._log(json.dumps({"mode": mode, "payload": sd_adapter.scrub_payload_for_print(payload)}, ensure_ascii=False, indent=2))
            self.status.set("Payload preview ready.")
        except Exception as exc:
            self.status.set("Preview failed.")
            self._log_error(exc)

    def execute_generation(self):
        if self.process_running:
            messagebox.showinfo("SD GrokUI", "Generation is already running.")
            return
        try:
            mode, payload = self._current_payload()
        except Exception as exc:
            self.status.set("Execute setup failed.")
            self._log_error(exc)
            return
        self._run_background(lambda: sd_adapter.execute_payload(self.cfg, mode, payload), f"Executing {mode}...")

    def _draft_dir(self) -> Path:
        path = BASE_DIR / "out" / "sd_askllm_drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _output_dir(self) -> Path:
        return resolve_project_path(
            get_nested(self.cfg, "save.codex_output_dir") or self.cfg.get("output_dir") or "out/sd_images"
        )

    def open_output_folder(self):
        try:
            folder = self._output_dir()
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))
            else:
                subprocess.Popen([self._platform_open_command(), str(folder)])
            self.status.set("Output folder opened.")
            self._log(f"Opened output folder: {folder}")
        except Exception as exc:
            self.status.set("Open output folder failed.")
            self._log_error(exc)

    def start_preview_viewer(self):
        try:
            folder = self._output_dir()
            folder.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable,
                str(BASE_DIR / "easy_viewer.py"),
                "--watch",
                str(folder),
                "--open-latest",
            ]
            subprocess.Popen(cmd, cwd=str(BASE_DIR))
            self.status.set("Preview viewer started.")
            self._log(f"Started preview viewer watching: {folder}")
        except Exception as exc:
            self.status.set("Start preview viewer failed.")
            self._log_error(exc)

    def open_latest_in_viewer(self):
        try:
            folder = self._output_dir()
            folder.mkdir(parents=True, exist_ok=True)
            latest = self._latest_image_path(folder)
            if latest is None:
                raise FileNotFoundError(f"No generated image found in {folder}")
            cmd = [
                sys.executable,
                str(BASE_DIR / "easy_viewer.py"),
                "--watch",
                str(folder),
                "--open-latest",
            ]
            subprocess.Popen(cmd, cwd=str(BASE_DIR))
            self.status.set("Viewer opened.")
            self._log(f"Opened viewer for latest image: {latest}")
        except Exception as exc:
            self.status.set("Open viewer failed.")
            self._log_error(exc)

    def _latest_image_path(self, folder: Path) -> Path | None:
        if self.last_images:
            for item in reversed(self.last_images):
                path = Path(item)
                if path.exists():
                    return path
        image_exts = {".png", ".jpg", ".jpeg", ".webp"}
        images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in image_exts]
        if not images:
            return None
        return max(images, key=lambda p: (p.stat().st_mtime, p.name))

    def _platform_open_command(self):
        if sys.platform == "darwin":
            return "open"
        return "xdg-open"

    def _run_background(self, worker, status):
        if self.process_running:
            return
        self.process_running = True
        self.status.set(status)
        thread = threading.Thread(target=self._background_wrapper, args=(worker,), daemon=True)
        thread.start()

    def _background_wrapper(self, worker):
        try:
            result = worker()
            self.after(0, lambda result=result: self._finish_background(result))
        except Exception as exc:
            self.after(0, lambda exc=exc: self._finish_background(exc))

    def _finish_background(self, result):
        self.process_running = False
        if isinstance(result, Exception):
            self.status.set("Operation failed.")
            self._log_error(result)
            return
        if isinstance(result, dict) and "summary" in result:
            self._finish_refresh_live_status(result)
            return
        if isinstance(result, dict) and result.get("grok_chat"):
            self._finish_grok_chat(result)
            return
        if isinstance(result, dict) and result.get("saved_images"):
            self.last_images = list(result.get("saved_images") or [])
        self.status.set("Operation finished.")
        self._log(json.dumps(result, ensure_ascii=False, indent=2))

    def _log(self, text):
        self.output_text.insert("end", str(text).rstrip() + "\n")
        self.output_text.see("end")

    def _log_error(self, exc):
        self._log(f"ERROR: {exc}")


def main() -> int:
    app = SDGrokUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
