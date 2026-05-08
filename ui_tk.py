import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.user.json"
EASY_PATH = BASE_DIR / "easy.py"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_with_backup(path: Path, data: dict) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak_{stamp}")
    if path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


def get_nested(data: dict, dotted_key: str, default=None):
    cur = data
    for key in dotted_key.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def set_nested(data: dict, dotted_key: str, value):
    cur = data
    keys = dotted_key.split(".")
    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[keys[-1]] = value


def decode_process_output(data: bytes) -> str:
    if not data:
        return ""

    candidates = []
    for encoding in ("utf-8", "cp932", "utf-8-sig"):
        text = data.decode(encoding, errors="replace")
        candidates.append((text.count("\ufffd"), text))

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


class EasyGrokUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EasyGrok Prompt Console")
        self.geometry("1400x860")
        self.minsize(1180, 720)

        self.cfg = load_json(CONFIG_PATH)
        self.current_command: list[str] = []
        self.log_replay_command: list[str] = []
        self.selected_log_record: dict | None = None
        self.selected_log_path: Path | None = None
        self.process_running = False

        self._build_vars()
        self._build_layout()
        self._refresh_command_preview()
        self._log("Ready.")

    def _build_vars(self):
        self.text_model = tk.StringVar(value=get_nested(self.cfg, "defaults.models.text_reasoning", ""))
        self.vision_model = tk.StringVar(value=get_nested(self.cfg, "defaults.models.vision", ""))
        self.image_model = tk.StringVar(value=get_nested(self.cfg, "defaults.models.image", "grok-imagine-image"))

        self.output_dir = tk.StringVar(value=get_nested(self.cfg, "defaults.output.dir", "./out"))
        self.raw_json_dir = tk.StringVar(value=get_nested(self.cfg, "defaults.output.raw_json_dir", "logs/json"))
        self.md_dir = tk.StringVar(value=get_nested(self.cfg, "defaults.output.md_dir", "logs/md"))
        self.image_dir = tk.StringVar(value=get_nested(self.cfg, "defaults.output.image_dir", "images"))
        self.video_dir = tk.StringVar(value=get_nested(self.cfg, "defaults.output.video_dir", "videos"))
        self.print_mode = tk.StringVar(value=get_nested(self.cfg, "defaults.output.print_mode", "content"))
        self.save_raw_json = tk.BooleanVar(value=bool(get_nested(self.cfg, "defaults.output.save_raw_json", True)))
        self.save_md = tk.BooleanVar(value=bool(get_nested(self.cfg, "defaults.output.save_md", True)))

        self.memory_enabled = tk.BooleanVar(value=bool(get_nested(self.cfg, "memory.enabled", False)))
        self.session_enabled_var = tk.BooleanVar(value=bool(get_nested(self.cfg, "memory.session.enabled", False)))
        self.memory_max_chars = tk.StringVar(value=str(get_nested(self.cfg, "memory.max_chars", 12000)))
        self.session_file = tk.StringVar(value=get_nested(self.cfg, "memory.session.file", "memory/session.md"))
        self.session_template_file = tk.StringVar(value=get_nested(self.cfg, "memory.session.template_file", "memory/session.template.md"))
        self.session_archive_dir = tk.StringVar(value=get_nested(self.cfg, "memory.session.archive_dir", "memory/archive/session"))
        self.session_backup_on_reset = tk.BooleanVar(value=bool(get_nested(self.cfg, "memory.session.backup_on_reset", True)))

        self.vision_url = tk.StringVar(value=get_nested(self.cfg, "vision.image_url", ""))
        self.vision_file = tk.StringVar(value="")

        self.route = tk.StringVar(value="image")
        self.image_mode = tk.StringVar(value="generate")
        self.image_format = tk.StringVar(value=get_nested(self.cfg, "image.response_format", "base64"))
        self.aspect_ratio = tk.StringVar(value=get_nested(self.cfg, "image.aspect_ratio", ""))
        self.resolution = tk.StringVar(value=get_nested(self.cfg, "image.resolution", ""))
        self.input_file = tk.StringVar(value=get_nested(self.cfg, "image.edit.input_file", ""))
        self.input_files = tk.StringVar(value="")
        self.batch_n = tk.StringVar(value=str(get_nested(self.cfg, "image.n", 4)))
        self.download_urls = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)

        self.video_model = tk.StringVar(value=get_nested(self.cfg, "defaults.models.video", ""))
        self.status = tk.StringVar(value="Ready")

    def _build_layout(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(0, weight=1)

        self.tabs = ttk.Notebook(root)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.tabs.bind("<<NotebookTabChanged>>", lambda _event: self._refresh_command_preview())

        self._build_text_tab()
        self._build_vision_tab()
        self._build_image_tab()
        self._build_video_tab()
        self._build_memory_tab()
        self._build_logs_tab()
        self._build_output_tab()

        side = ttk.Frame(root)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)

        ttk.Label(side, text="Command Preview").grid(row=0, column=0, sticky="w")
        self.command_text = tk.Text(side, height=7, wrap="word")
        self.command_text.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        self.command_text.configure(state="disabled")

        ttk.Label(side, text="Run Output").grid(row=2, column=0, sticky="nw")
        self.output_text = tk.Text(side, wrap="word")
        self.output_text.grid(row=3, column=0, sticky="nsew", pady=(4, 10))

        buttons = ttk.Frame(side)
        buttons.grid(row=4, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)

        ttk.Button(buttons, text="Save Config", command=self.save_config).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Preview", command=self._refresh_command_preview).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(buttons, text="Run", command=self.run_current).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        ttk.Label(side, textvariable=self.status).grid(row=5, column=0, sticky="w", pady=(10, 0))

    def _build_text_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Text")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(5, weight=1)

        self._entry(tab, "Text model", self.text_model, 0, model_category="language")
        ttk.Label(tab, text="System prompt").grid(row=1, column=0, sticky="w", pady=(8, 2))
        self.text_system = tk.Text(tab, height=7, wrap="word")
        self.text_system.insert("1.0", get_nested(self.cfg, "text.system_prompt", ""))
        self.text_system.grid(row=2, column=0, sticky="ew")

        ttk.Label(tab, text="User prompt").grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.text_prompt = tk.Text(tab, height=12, wrap="word")
        self.text_prompt.insert("1.0", get_nested(self.cfg, "text.user_prompt", ""))
        self.text_prompt.grid(row=4, column=0, sticky="nsew")

        ttk.Button(tab, text="Use Text Route", command=self._refresh_command_preview).grid(row=6, column=0, sticky="w", pady=(10, 0))

    def _build_vision_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Vision")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(6, weight=1)

        self._entry(tab, "Vision model", self.vision_model, 0, model_category="language")
        self._entry(tab, "Image URL", self.vision_url, 1)

        file_row = ttk.Frame(tab)
        file_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        file_row.columnconfigure(1, weight=1)
        ttk.Label(file_row, text="Image file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(file_row, textvariable=self.vision_file).grid(row=0, column=1, sticky="ew")
        ttk.Button(file_row, text="Browse", command=lambda: self._browse_file(self.vision_file)).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(tab, text="Vision prompt").grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.vision_prompt = tk.Text(tab, height=12, wrap="word")
        self.vision_prompt.insert("1.0", get_nested(self.cfg, "vision.user_prompt", get_nested(self.cfg, "vision.question", "")))
        self.vision_prompt.grid(row=4, column=0, sticky="nsew")

        ttk.Label(tab, text="Use either Image URL or Image file. If both are set, file wins for the UI command.").grid(
            row=5, column=0, sticky="w", pady=(8, 0)
        )

    def _build_image_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Image")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(9, weight=1)

        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew")
        for i in range(6):
            top.columnconfigure(i, weight=1)

        self._combo(top, "Route", self.route, ["image", "imagine", "imagine-natural"], 0, 0)
        self._combo(top, "Mode", self.image_mode, ["generate", "edit", "reference_edit", "batch"], 0, 1)
        self._combo(top, "Format", self.image_format, ["base64", "url"], 0, 2)
        self._entry_grid(top, "Model", self.image_model, 0, 3, model_category="image")
        self._entry_grid(top, "Aspect", self.aspect_ratio, 0, 4)
        self._entry_grid(top, "Resolution", self.resolution, 0, 5)

        opts = ttk.Frame(tab)
        opts.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(opts, text="Dry run for imagine routes", variable=self.dry_run, command=self._refresh_command_preview).pack(side="left")
        ttk.Checkbutton(opts, text="Download URL outputs", variable=self.download_urls, command=self._refresh_command_preview).pack(side="left", padx=(16, 0))
        ttk.Label(opts, text="Batch n").pack(side="left", padx=(16, 4))
        ttk.Entry(opts, textvariable=self.batch_n, width=6).pack(side="left")

        self._entry(tab, "Edit input file", self.input_file, 2, browse=True)
        self._entry(tab, "Reference input files (semicolon separated)", self.input_files, 3, browse_multi=True)

        ttk.Label(tab, text="Image prompt").grid(row=8, column=0, sticky="w", pady=(8, 2))
        self.image_prompt = tk.Text(tab, height=16, wrap="word")
        self.image_prompt.insert("1.0", get_nested(self.cfg, "image.prompt", ""))
        self.image_prompt.grid(row=9, column=0, sticky="nsew")

        for var in (self.route, self.image_mode, self.image_format, self.aspect_ratio, self.resolution, self.batch_n):
            var.trace_add("write", lambda *_args: self._refresh_command_preview())

    def _build_video_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Video")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)

        self._entry(tab, "Video model placeholder", self.video_model, 0, model_category="video")
        ttk.Label(tab, text="Video prompt").grid(row=1, column=0, sticky="w", pady=(8, 2))
        self.video_prompt = tk.Text(tab, height=12, wrap="word")
        self.video_prompt.insert("1.0", get_nested(self.cfg, "video.prompt", ""))
        self.video_prompt.grid(row=2, column=0, sticky="nsew")
        ttk.Label(tab, text="Current video route is a scaffold only. It does not call a generation API yet.").grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

    def _build_memory_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Memory")
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(5, weight=1)

        flags = ttk.Frame(tab)
        flags.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(flags, text="Enable memory context", variable=self.memory_enabled).pack(side="left")
        ttk.Checkbutton(flags, text="Enable session append", variable=self.session_enabled_var).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(flags, text="Backup on reset", variable=self.session_backup_on_reset).pack(side="left", padx=(16, 0))

        left = ttk.Frame(tab)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(4, weight=1)

        self._entry(left, "Session file", self.session_file, 0)
        self._entry(left, "Template file", self.session_template_file, 1)
        self._entry(left, "Archive dir", self.session_archive_dir, 2)
        self._entry(left, "Max context chars", self.memory_max_chars, 3)

        ttk.Label(left, text="Context files").grid(row=4, column=0, sticky="w", pady=(8, 2))
        context_frame = ttk.Frame(left)
        context_frame.grid(row=5, column=0, sticky="nsew")
        context_frame.columnconfigure(0, weight=1)
        context_frame.rowconfigure(0, weight=1)

        self.memory_context_list = tk.Listbox(context_frame, exportselection=False)
        self.memory_context_list.grid(row=0, column=0, sticky="nsew")
        for item in get_nested(self.cfg, "memory.context_files", []) or []:
            self.memory_context_list.insert("end", str(item))
        context_scroll = ttk.Scrollbar(context_frame, orient="vertical", command=self.memory_context_list.yview)
        context_scroll.grid(row=0, column=1, sticky="ns")
        self.memory_context_list.configure(yscrollcommand=context_scroll.set)

        context_buttons = ttk.Frame(left)
        context_buttons.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(context_buttons, text="Add", command=self._add_context_file).pack(side="left")
        ttk.Button(context_buttons, text="Remove", command=self._remove_context_file).pack(side="left", padx=(6, 0))
        ttk.Button(context_buttons, text="Move Up", command=lambda: self._move_context_file(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(context_buttons, text="Move Down", command=lambda: self._move_context_file(1)).pack(side="left", padx=(6, 0))
        ttk.Button(context_buttons, text="Open", command=self._open_context_file).pack(side="left", padx=(6, 0))

        right = ttk.Frame(tab)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        buttons = ttk.Frame(right)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(buttons, text="Refresh Preview", command=self._refresh_memory_status).pack(side="left")
        ttk.Button(buttons, text="Reset Session", command=self._reset_session).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Archive + Reset", command=self._archive_and_reset_session).pack(side="left", padx=(8, 0))

        self.memory_status_text = tk.Text(right, height=8, width=48, wrap="word")
        self.memory_status_text.grid(row=1, column=0, sticky="nsew")
        self.memory_status_text.configure(state="disabled")

        self._refresh_memory_status()

    def _build_logs_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Logs")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Refresh Logs", command=self._refresh_log_list).pack(side="left")
        ttk.Button(controls, text="Load Selected", command=self._load_selected_log).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Preview Replay", command=self._preview_selected_log_replay).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Add Vision to Memory", command=self._add_selected_vision_to_memory).pack(side="left", padx=(8, 0))
        ttk.Label(controls, text="Markdown logs from output md_dir. Replay command is rebuilt from raw JSON.").pack(side="left", padx=(16, 0))

        left = ttk.Frame(tab)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.log_list = tk.Listbox(left, exportselection=False)
        self.log_list.grid(row=0, column=0, sticky="nsew")
        self.log_list.bind("<<ListboxSelect>>", lambda _event: self._load_selected_log())
        log_scroll = ttk.Scrollbar(left, orient="vertical", command=self.log_list.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_list.configure(yscrollcommand=log_scroll.set)

        right = ttk.Frame(tab)
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.log_meta_text = tk.Text(right, height=9, wrap="word")
        self.log_meta_text.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.log_meta_text.configure(state="disabled")

        self.log_body_text = tk.Text(right, wrap="word")
        self.log_body_text.grid(row=1, column=0, sticky="nsew")

        self._refresh_log_list()

    def _build_output_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="Output")
        tab.columnconfigure(0, weight=1)

        self._entry(tab, "Output dir", self.output_dir, 0, browse_dir="project")
        self._entry(tab, "Raw JSON dir", self.raw_json_dir, 1, browse_dir="output")
        self._entry(tab, "Markdown dir", self.md_dir, 2, browse_dir="output")
        self._entry(tab, "Image dir", self.image_dir, 3, browse_dir="output")
        self._entry(tab, "Video dir", self.video_dir, 4, browse_dir="output")
        self._combo(tab, "Print mode", self.print_mode, ["content", "minimal", "none"], 5, 0)
        ttk.Checkbutton(tab, text="Save raw JSON", variable=self.save_raw_json).grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(tab, text="Save Markdown", variable=self.save_md).grid(row=7, column=0, sticky="w", pady=(4, 0))

    def _entry(self, parent, label, variable, row, browse=False, browse_multi=False, browse_dir=False, model_category=None):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=variable).grid(row=0, column=1, sticky="ew")
        if browse:
            ttk.Button(frame, text="Browse", command=lambda: self._browse_file(variable)).grid(row=0, column=2, padx=(8, 0))
        if browse_multi:
            ttk.Button(frame, text="Browse", command=lambda: self._browse_files(variable)).grid(row=0, column=2, padx=(8, 0))
        if browse_dir:
            ttk.Button(frame, text="Browse", command=lambda: self._browse_dir(variable, str(browse_dir))).grid(row=0, column=2, padx=(8, 0))
        if model_category:
            ttk.Button(frame, text="Models", command=lambda: self._open_model_picker(variable, model_category)).grid(
                row=0, column=3, padx=(8, 0)
            )
        variable.trace_add("write", lambda *_args: self._refresh_command_preview())

    def _entry_grid(self, parent, label, variable, row, column, model_category=None):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="ew", padx=(0, 8))
        ttk.Label(frame, text=label).pack(anchor="w")
        row_frame = ttk.Frame(frame)
        row_frame.pack(fill="x")
        row_frame.columnconfigure(0, weight=1)
        ttk.Entry(row_frame, textvariable=variable).grid(row=0, column=0, sticky="ew")
        if model_category:
            ttk.Button(row_frame, text="Models", command=lambda: self._open_model_picker(variable, model_category)).grid(
                row=0, column=1, padx=(6, 0)
            )
        variable.trace_add("write", lambda *_args: self._refresh_command_preview())

    def _combo(self, parent, label, variable, values, row, column):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="ew", padx=(0, 8), pady=(0, 8))
        ttk.Label(frame, text=label).pack(anchor="w")
        box = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly")
        box.pack(fill="x")
        box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_command_preview())

    def _browse_file(self, variable):
        path = filedialog.askopenfilename(initialdir=str(BASE_DIR))
        if path:
            variable.set(path)

    def _browse_files(self, variable):
        paths = filedialog.askopenfilenames(initialdir=str(BASE_DIR))
        if paths:
            variable.set(";".join(paths))

    def _browse_dir(self, variable, base_kind: str = "project"):
        base = BASE_DIR
        if base_kind == "output":
            base = self._project_path(self.output_dir.get().strip() or "./out")
        path = filedialog.askdirectory(initialdir=str(base))
        if path:
            try:
                variable.set(str(Path(path).relative_to(base)))
            except ValueError:
                variable.set(path)

    def _context_files_from_list(self) -> list[str]:
        if not hasattr(self, "memory_context_list"):
            return []
        return [str(self.memory_context_list.get(i)) for i in range(self.memory_context_list.size())]

    def _selected_context_index(self) -> int | None:
        selection = self.memory_context_list.curselection()
        if not selection:
            return None
        return int(selection[0])

    def _add_context_file(self):
        path = filedialog.askopenfilename(
            initialdir=str(BASE_DIR / "memory"),
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            value = str(Path(path).relative_to(BASE_DIR))
        except ValueError:
            value = path
        existing = self._context_files_from_list()
        if value not in existing:
            self.memory_context_list.insert("end", value)
            self.memory_context_list.selection_clear(0, "end")
            self.memory_context_list.selection_set("end")
        self._refresh_memory_status()

    def _remove_context_file(self):
        index = self._selected_context_index()
        if index is None:
            return
        self.memory_context_list.delete(index)
        if self.memory_context_list.size() > 0:
            self.memory_context_list.selection_set(min(index, self.memory_context_list.size() - 1))
        self._refresh_memory_status()

    def _move_context_file(self, direction: int):
        index = self._selected_context_index()
        if index is None:
            return
        new_index = index + direction
        if new_index < 0 or new_index >= self.memory_context_list.size():
            return
        value = self.memory_context_list.get(index)
        self.memory_context_list.delete(index)
        self.memory_context_list.insert(new_index, value)
        self.memory_context_list.selection_set(new_index)
        self._refresh_memory_status()

    def _open_context_file(self):
        index = self._selected_context_index()
        if index is None:
            return
        path = self._project_path(str(self.memory_context_list.get(index)))
        if not path.exists():
            messagebox.showerror("EasyGrok", f"Context file not found:\n{path}")
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("EasyGrok", f"Could not open file:\n{path}\n\n{exc}")

    def _project_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return BASE_DIR / path

    def _session_template_text(self) -> str:
        template_path = self._project_path(self.session_template_file.get().strip() or "memory/session.template.md")
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return (
            "# EasyGrok Session\n\n"
            "This file is short-term conversational memory for EasyGrok text runs.\n"
            "It is automatically read as Markdown context and appended after each successful text run.\n\n"
            "Keep durable facts in separate files such as `memory/context.md`, `memory/easygrok_state.md`, or character/profile files.\n"
        )

    def _backup_session(self, session_path: Path, target_dir: Path | None = None) -> Path | None:
        if not session_path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if target_dir is None:
            backup_path = session_path.with_suffix(session_path.suffix + f".bak_{stamp}")
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            backup_path = target_dir / f"{session_path.stem}_{stamp}{session_path.suffix}"
        backup_path.write_text(session_path.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path

    def _write_session_template(self):
        session_path = self._project_path(self.session_file.get().strip() or "memory/session.md")
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(self._session_template_text(), encoding="utf-8")
        return session_path

    def _reset_session(self):
        session_path = self._project_path(self.session_file.get().strip() or "memory/session.md")
        backup_path = None
        if self.session_backup_on_reset.get():
            backup_path = self._backup_session(session_path)
        self._write_session_template()
        self._refresh_memory_status()
        msg = f"Session reset: {self._display_path(str(session_path))}"
        if backup_path:
            msg += f"\nBackup: {self._display_path(str(backup_path))}"
        self.status.set("Session reset")
        self._log(msg)

    def _archive_and_reset_session(self):
        session_path = self._project_path(self.session_file.get().strip() or "memory/session.md")
        archive_dir = self._project_path(self.session_archive_dir.get().strip() or "memory/archive/session")
        archive_path = self._backup_session(session_path, archive_dir)
        self._write_session_template()
        self._refresh_memory_status()
        msg = f"Session archived and reset: {self._display_path(str(session_path))}"
        if archive_path:
            msg += f"\nArchive: {self._display_path(str(archive_path))}"
        self.status.set("Session archived and reset")
        self._log(msg)

    def _refresh_memory_status(self):
        if not hasattr(self, "memory_status_text"):
            return
        session_path = self._project_path(self.session_file.get().strip() or "memory/session.md")
        template_path = self._project_path(self.session_template_file.get().strip() or "memory/session.template.md")
        context_files = self._context_files_from_list()
        total_chars = 0
        context_lines = []
        for item in context_files:
            path = self._project_path(item)
            if path.exists() and path.is_file():
                chars = len(path.read_text(encoding="utf-8", errors="replace"))
                total_chars += chars
                context_lines.append(f"  OK {item} ({chars} chars)")
            else:
                context_lines.append(f"  missing {item}")

        if session_path.exists():
            stat = session_path.stat()
            session_info = [
                f"Session file : {self._display_path(str(session_path))}",
                f"Session size : {stat.st_size} bytes",
                f"Updated      : {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}",
            ]
        else:
            session_info = [
                f"Session file : {self._display_path(str(session_path))}",
                "Session size : missing",
            ]

        lines = [
            f"Memory enabled : {self.memory_enabled.get()}",
            f"Session append : {self.session_enabled_var.get()}",
            f"Max chars      : {self.memory_max_chars.get()}",
            f"Template       : {self._display_path(str(template_path))} exists={template_path.exists()}",
            "",
            *session_info,
            "",
            f"Context files  : {len(context_files)}",
            f"Total chars    : {total_chars}",
            *context_lines,
        ]
        self.memory_status_text.configure(state="normal")
        self.memory_status_text.delete("1.0", "end")
        self.memory_status_text.insert("1.0", "\n".join(lines))
        self.memory_status_text.configure(state="disabled")

    def _configured_log_dir(self, kind: str) -> Path:
        out_dir = Path(self.output_dir.get().strip() or "./out")
        if not out_dir.is_absolute():
            out_dir = BASE_DIR / out_dir
        key = "raw_json_dir" if kind == "json" else "md_dir"
        default = "logs/json" if kind == "json" else "logs/md"
        subdir = getattr(self, key).get().strip() or default
        path = Path(subdir)
        if not path.is_absolute():
            path = out_dir / path
        return path

    def _configured_media_dir(self, kind: str) -> Path:
        out_dir = Path(self.output_dir.get().strip() or "./out")
        if not out_dir.is_absolute():
            out_dir = BASE_DIR / out_dir
        if kind == "video":
            configured = self.video_dir.get().strip() or "videos"
        else:
            configured = self.image_dir.get().strip() or "images"
        path = Path(configured)
        if not path.is_absolute():
            path = out_dir / path
        return path

    def _refresh_log_list(self):
        if not hasattr(self, "log_list"):
            return
        self.log_list.delete(0, "end")
        md_dir = self._configured_log_dir("md")
        self.log_paths = []
        if not md_dir.exists():
            self._set_log_meta(f"Markdown log directory does not exist:\n{md_dir}")
            self._set_log_body("")
            return
        files = sorted(md_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:300]:
            self.log_paths.append(path)
            label = f"{datetime.fromtimestamp(path.stat().st_mtime).strftime('%m-%d %H:%M:%S')}  {path.name}"
            self.log_list.insert("end", label)
        if self.log_paths:
            self.log_list.selection_set(0)
            self._load_selected_log()

    def _load_selected_log(self):
        if not hasattr(self, "log_list"):
            return
        selection = self.log_list.curselection()
        if not selection:
            return
        path = self.log_paths[selection[0]]
        body = path.read_text(encoding="utf-8", errors="replace")
        record = self._load_json_for_md_log(path)
        self.selected_log_path = path
        self.selected_log_record = record
        self._set_log_meta(self._format_log_summary(path, record))
        self._set_log_body(body)
        self.log_replay_command = self._replay_command_from_record(record) if record else []
        if self._active_tab_name() == "Logs":
            self._refresh_command_preview()

    def _preview_selected_log_replay(self):
        self._load_selected_log()
        self._refresh_command_preview()

    def _add_selected_vision_to_memory(self):
        record = self.selected_log_record
        if not record or record.get("mode") != "vision":
            messagebox.showinfo("EasyGrok", "Select a vision log with raw JSON first.")
            return

        notes_path = self._project_path("memory/vision_notes.md")
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        if not notes_path.exists():
            notes_path.write_text(
                "# Vision Notes\n\n"
                "This file stores selected image analysis results that should be available to later text and vision runs.\n\n",
                encoding="utf-8",
            )

        image_ref = get_nested(record, "image.url_or_data") or ""
        entry = (
            f"\n## {record.get('ts', datetime.now().isoformat(timespec='seconds'))}\n\n"
            f"Source: `{image_ref}`\n\n"
            f"Model: `{record.get('model', '')}`\n\n"
            "Prompt:\n"
            f"{record.get('prompt', '').strip()}\n\n"
            "Analysis:\n"
            f"{record.get('content', '').strip()}\n"
        )
        with notes_path.open("a", encoding="utf-8") as f:
            f.write(entry)

        if hasattr(self, "memory_context_list"):
            items = self._context_files_from_list()
            if "memory/vision_notes.md" not in items:
                self.memory_context_list.insert("end", "memory/vision_notes.md")
                self._refresh_memory_status()

        self.status.set("Vision analysis added to memory")
        self._log(f"Added vision analysis to {self._display_path(str(notes_path))}")

    def _load_json_for_md_log(self, md_path: Path) -> dict | None:
        match = re.match(r"^(?P<prefix>.+)_(?P<stamp>\d{8}_\d{6})$", md_path.stem)
        if not match:
            return None
        json_name = f"{match.group('prefix')}_raw_{match.group('stamp')}.json"
        json_path = self._configured_log_dir("json") / json_name
        if not json_path.exists():
            return None
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _base_easy_command(self) -> list[str]:
        return [sys.executable, str(EASY_PATH), "-c", str(CONFIG_PATH)]

    def _replay_command_from_record(self, record: dict | None) -> list[str]:
        if not record:
            return []

        mode = str(record.get("mode", "")).strip()
        cmd = self._base_easy_command()

        if mode == "text":
            cmd.append("text")
            context = record.get("context")
            if isinstance(context, dict) and context.get("enabled") is False:
                cmd.append("--no-context")
            prompt = record.get("prompt")
            if prompt:
                cmd.append(str(prompt))
            return cmd

        if mode == "vision":
            cmd.append("vision")
            context = record.get("context")
            if isinstance(context, dict) and context.get("enabled") is False:
                cmd.append("--no-context")
            image_ref = get_nested(record, "image.url_or_data") or ""
            if isinstance(image_ref, str) and image_ref.startswith("file:"):
                cmd += ["--image-file", image_ref[5:]]
            elif isinstance(image_ref, str) and image_ref.startswith(("http://", "https://")):
                cmd += ["--image-url", image_ref]
            prompt = record.get("prompt")
            if prompt:
                cmd.append(str(prompt))
            return cmd

        if mode.startswith("image."):
            image_mode = mode.split(".", 1)[1]
            cmd += ["image", "--mode", image_mode]
            if record.get("model"):
                cmd += ["--model", str(record["model"])]
            self._append_replay_image_options(cmd, record)
            if image_mode == "edit" and record.get("input_file"):
                cmd += ["--input-file", str(record["input_file"])]
            if image_mode == "reference_edit":
                input_files = record.get("input_files") or []
                image_urls = record.get("image_urls") or []
                if input_files:
                    cmd += ["--input-files", *[str(p) for p in input_files]]
                elif image_urls:
                    cmd += ["--image-urls-json", json.dumps(image_urls, ensure_ascii=False)]
            if image_mode == "batch" and record.get("n"):
                cmd += ["-n", str(record["n"])]
            prompt = record.get("prompt")
            if prompt:
                if image_mode == "reference_edit" and record.get("input_files"):
                    cmd.append("--")
                cmd.append(str(prompt))
            return cmd

        if mode == "imagine":
            cmd.append("imagine")
            if not bool(get_nested(record, "image.executed")):
                cmd.append("--dry-run")
            image_model = get_nested(record, "image.model")
            if image_model:
                cmd += ["--model", str(image_model)]
            rewrite_model = get_nested(record, "rewrite.model")
            if rewrite_model:
                cmd += ["--rewrite-model", str(rewrite_model)]
            self._append_replay_image_options(cmd, get_nested(record, "image") or {})
            if record.get("user_request"):
                cmd.append(str(record["user_request"]))
            return cmd

        if mode == "imagine-natural":
            cmd.append("imagine-natural")
            if not bool(get_nested(record, "image.executed")):
                cmd.append("--dry-run")
            image_model = get_nested(record, "image.model")
            if image_model:
                cmd += ["--model", str(image_model)]
            language_model = get_nested(record, "language.model")
            if language_model:
                cmd += ["--language-model", str(language_model)]
            self._append_replay_image_options(cmd, get_nested(record, "image") or {})
            if record.get("user_request"):
                cmd.append(str(record["user_request"]))
            return cmd

        if mode == "video.scaffold":
            cmd.append("video")
            if record.get("model"):
                cmd += ["--model", str(record["model"])]
            if record.get("prompt"):
                cmd.append(str(record["prompt"]))
            return cmd

        return []

    def _append_replay_image_options(self, cmd: list[str], record: dict):
        options = record.get("options") if isinstance(record, dict) else None
        if not isinstance(options, dict):
            options = {}
        aspect_ratio = options.get("aspect_ratio")
        resolution = options.get("resolution")
        image_format = record.get("image_format") if isinstance(record, dict) else None
        if aspect_ratio:
            cmd += ["--aspect-ratio", str(aspect_ratio)]
        if resolution:
            cmd += ["--resolution", str(resolution)]
        if image_format:
            cmd += ["--image-format", str(image_format)]

    def _format_log_summary(self, md_path: Path, record: dict | None) -> str:
        lines = [
            f"Markdown: {self._display_path(str(md_path))}",
            f"Updated : {datetime.fromtimestamp(md_path.stat().st_mtime).isoformat(timespec='seconds')}",
        ]
        if not record:
            lines.append("JSON    : not found")
            return "\n".join(lines)

        lines.extend([
            f"JSON    : found",
            f"ts      : {record.get('ts', '')}",
            f"mode    : {record.get('mode', '')}",
            f"model   : {record.get('model') or get_nested(record, 'image.model') or get_nested(record, 'rewrite.model') or get_nested(record, 'language.model') or ''}",
            f"prompt  : {self._short_text(record.get('prompt') or record.get('user_request') or get_nested(record, 'rewrite.prompt') or get_nested(record, 'language.extracted_prompt') or '')}",
        ])

        options = get_nested(record, "options") or get_nested(record, "image.options")
        if options:
            lines.append(f"options : {options}")

        saved_files = record.get("saved_files") or get_nested(record, "image.saved_files")
        urls = record.get("urls") or get_nested(record, "image.urls")
        if saved_files:
            lines.append(f"files   : {saved_files}")
        if urls:
            lines.append(f"urls    : {urls}")

        context = record.get("context")
        if isinstance(context, dict):
            lines.append(f"context : enabled={context.get('enabled')} chars={context.get('total_chars')} truncated={context.get('truncated')}")
        replay = self._replay_command_from_record(record)
        lines.append(f"replay  : {'available' if replay else 'not available'}")
        return "\n".join(lines)

    def _short_text(self, value: str, limit: int = 240) -> str:
        text = " ".join(str(value).split())
        if len(text) <= limit:
            return text
        return text[:limit - 3] + "..."

    def _set_log_meta(self, text: str):
        self.log_meta_text.configure(state="normal")
        self.log_meta_text.delete("1.0", "end")
        self.log_meta_text.insert("1.0", text)
        self.log_meta_text.configure(state="disabled")

    def _set_log_body(self, text: str):
        self.log_body_text.delete("1.0", "end")
        self.log_body_text.insert("1.0", text)

    def _model_names(self, category: str) -> list[str]:
        catalog = get_nested(self.cfg, f"model_catalog.{category}", [])
        names = []
        if isinstance(catalog, list):
            for item in catalog:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
        return names

    def _open_model_picker(self, target_var: tk.StringVar, category: str):
        names = self._model_names(category)
        if not names:
            messagebox.showinfo("EasyGrok", f"No models found in config model_catalog.{category}.")
            return

        win = tk.Toplevel(self)
        win.title(f"Models: {category}")
        win.geometry("520x360")
        win.transient(self)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text=f"model_catalog.{category}").grid(row=0, column=0, sticky="w")

        listbox = tk.Listbox(frame, exportselection=False)
        listbox.grid(row=1, column=0, sticky="nsew", pady=(6, 10))
        for name in names:
            listbox.insert("end", name)

        current = target_var.get().strip()
        if current in names:
            index = names.index(current)
            listbox.selection_set(index)
            listbox.see(index)
        else:
            listbox.selection_set(0)

        def selected_name() -> str:
            selection = listbox.curselection()
            if not selection:
                return ""
            return str(listbox.get(selection[0]))

        def use_selected():
            name = selected_name()
            if name:
                target_var.set(name)
                win.destroy()

        def copy_selected():
            name = selected_name()
            if name:
                self.clipboard_clear()
                self.clipboard_append(name)
                self.status.set(f"Copied model: {name}")

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        ttk.Button(buttons, text="Use Selected", command=use_selected).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Copy", command=copy_selected).grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(buttons, text="Close", command=win.destroy).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        listbox.bind("<Double-Button-1>", lambda _event: use_selected())

    def _active_tab_name(self) -> str:
        tab_id = self.tabs.select()
        return self.tabs.tab(tab_id, "text")

    def _text_value(self, widget: tk.Text) -> str:
        return widget.get("1.0", "end").strip()

    def save_config(self):
        set_nested(self.cfg, "defaults.models.text_reasoning", self.text_model.get().strip())
        set_nested(self.cfg, "defaults.models.vision", self.vision_model.get().strip())
        set_nested(self.cfg, "defaults.models.image", self.image_model.get().strip())
        if self.video_model.get().strip():
            set_nested(self.cfg, "defaults.models.video", self.video_model.get().strip())

        set_nested(self.cfg, "defaults.output.dir", self.output_dir.get().strip() or "./out")
        set_nested(self.cfg, "defaults.output.raw_json_dir", self.raw_json_dir.get().strip() or "logs/json")
        set_nested(self.cfg, "defaults.output.md_dir", self.md_dir.get().strip() or "logs/md")
        set_nested(self.cfg, "defaults.output.image_dir", self.image_dir.get().strip() or "images")
        set_nested(self.cfg, "defaults.output.video_dir", self.video_dir.get().strip() or "videos")
        set_nested(self.cfg, "defaults.output.print_mode", self.print_mode.get().strip() or "content")
        set_nested(self.cfg, "defaults.output.save_raw_json", bool(self.save_raw_json.get()))
        set_nested(self.cfg, "defaults.output.save_md", bool(self.save_md.get()))

        set_nested(self.cfg, "memory.enabled", bool(self.memory_enabled.get()))
        set_nested(self.cfg, "memory.max_chars", int(self.memory_max_chars.get().strip() or "12000"))
        set_nested(self.cfg, "memory.context_files", self._context_files_from_list())
        set_nested(self.cfg, "memory.session.enabled", bool(self.session_enabled_var.get()))
        set_nested(self.cfg, "memory.session.file", self.session_file.get().strip() or "memory/session.md")
        set_nested(self.cfg, "memory.session.template_file", self.session_template_file.get().strip() or "memory/session.template.md")
        set_nested(self.cfg, "memory.session.archive_dir", self.session_archive_dir.get().strip() or "memory/archive/session")
        set_nested(self.cfg, "memory.session.backup_on_reset", bool(self.session_backup_on_reset.get()))

        set_nested(self.cfg, "text.system_prompt", self._text_value(self.text_system))
        set_nested(self.cfg, "text.user_prompt", self._text_value(self.text_prompt))

        set_nested(self.cfg, "vision.image_url", self.vision_url.get().strip())
        set_nested(self.cfg, "vision.user_prompt", self._text_value(self.vision_prompt))
        set_nested(self.cfg, "vision.question", self._text_value(self.vision_prompt))

        set_nested(self.cfg, "image.prompt", self._text_value(self.image_prompt))
        set_nested(self.cfg, "image.response_format", self.image_format.get().strip() or "base64")
        set_nested(self.cfg, "image.aspect_ratio", self.aspect_ratio.get().strip())
        set_nested(self.cfg, "image.resolution", self.resolution.get().strip())
        set_nested(self.cfg, "image.edit.input_file", self.input_file.get().strip())
        try:
            set_nested(self.cfg, "image.n", int(self.batch_n.get().strip() or "4"))
        except ValueError:
            set_nested(self.cfg, "image.n", 4)

        set_nested(self.cfg, "video.prompt", self._text_value(self.video_prompt))

        backup_path = save_json_with_backup(CONFIG_PATH, self.cfg)
        self.status.set(f"Saved. Backup: {backup_path.name}")
        self._log(f"Saved config. Backup: {backup_path}")
        self._refresh_command_preview()

    def _build_command(self) -> list[str]:
        tab = self._active_tab_name()
        if tab == "Logs":
            return self.log_replay_command.copy()

        cmd = self._base_easy_command()

        if tab == "Text":
            prompt = self._text_value(self.text_prompt)
            cmd += ["text"]
            if prompt:
                cmd.append(prompt)
            return cmd

        if tab == "Vision":
            prompt = self._text_value(self.vision_prompt)
            cmd += ["vision"]
            if self.vision_file.get().strip():
                cmd += ["--image-file", self.vision_file.get().strip()]
            elif self.vision_url.get().strip():
                cmd += ["--image-url", self.vision_url.get().strip()]
            if prompt:
                cmd.append(prompt)
            return cmd

        if tab == "Video":
            prompt = self._text_value(self.video_prompt)
            cmd += ["video"]
            if self.video_model.get().strip():
                cmd += ["--model", self.video_model.get().strip()]
            if prompt:
                cmd.append(prompt)
            return cmd

        route = self.route.get()
        prompt = self._text_value(self.image_prompt)
        if route == "image":
            cmd += ["image", "--mode", self.image_mode.get()]
            if self.image_model.get().strip():
                cmd += ["--model", self.image_model.get().strip()]
            self._append_common_image_args(cmd)
            mode = self.image_mode.get()
            if mode == "edit" and self.input_file.get().strip():
                cmd += ["--input-file", self.input_file.get().strip()]
            if mode == "reference_edit":
                files = [p.strip() for p in self.input_files.get().split(";") if p.strip()]
                if files:
                    cmd += ["--input-files", *files]
            if mode == "batch":
                cmd += ["-n", self.batch_n.get().strip() or "4"]
            if prompt:
                if mode == "reference_edit" and files:
                    cmd.append("--")
                cmd.append(prompt)
            return cmd

        if route == "imagine":
            cmd += ["imagine"]
            if self.dry_run.get():
                cmd.append("--dry-run")
            if self.image_model.get().strip():
                cmd += ["--model", self.image_model.get().strip()]
            self._append_common_image_args(cmd)
            if prompt:
                cmd.append(prompt)
            return cmd

        cmd += ["imagine-natural"]
        if self.dry_run.get():
            cmd.append("--dry-run")
        if self.image_model.get().strip():
            cmd += ["--model", self.image_model.get().strip()]
        self._append_common_image_args(cmd)
        if prompt:
            cmd.append(prompt)
        return cmd

    def _append_common_image_args(self, cmd: list[str]):
        if self.aspect_ratio.get().strip():
            cmd += ["--aspect-ratio", self.aspect_ratio.get().strip()]
        if self.resolution.get().strip():
            cmd += ["--resolution", self.resolution.get().strip()]
        if self.image_format.get().strip():
            cmd += ["--image-format", self.image_format.get().strip()]
        if self.download_urls.get():
            cmd.append("--download")

    def _refresh_command_preview(self):
        try:
            tab = self._active_tab_name()
            if tab == "Memory":
                self.current_command = []
                preview = self._format_memory_notes()
            elif tab == "Output":
                self.current_command = []
                preview = self._format_output_notes()
            else:
                self.current_command = self._build_command()
                if self.current_command:
                    preview = self._format_command_preview(self.current_command)
                elif tab == "Logs":
                    preview = "No replay command available for the selected log."
                else:
                    preview = "No command available."
        except Exception as exc:
            preview = f"Could not build command: {exc}"
            self.current_command = []
        self.command_text.configure(state="normal")
        self.command_text.delete("1.0", "end")
        self.command_text.insert("1.0", preview)
        self.command_text.configure(state="disabled")

    def _format_memory_notes(self) -> str:
        context_files = self._context_files_from_list()
        return "\n".join([
            "Memory Notes",
            "",
            "Memory is loaded as Markdown context for text and vision runs.",
            "context_files are read in list order.",
            "session.md is persistent until Reset Session.",
            "vision_notes.md is updated only by Add Vision to Memory.",
            "",
            f"Memory enabled : {self.memory_enabled.get()}",
            f"Session append : {self.session_enabled_var.get()}",
            f"Context files  : {len(context_files)}",
            f"Max chars      : {self.memory_max_chars.get()}",
            "",
            "Use Save Config to write context_files changes.",
            "Use Refresh Preview to recalculate file status.",
        ])

    def _format_output_notes(self) -> str:
        out_dir = self._configured_log_dir("md").parent.parent
        return "\n".join([
            "Output Notes",
            "",
            f"Base output dir : {self._display_path(str(out_dir))}",
            f"Markdown logs   : {self._display_path(str(self._configured_log_dir('md')))}",
            f"Raw JSON logs   : {self._display_path(str(self._configured_log_dir('json')))}",
            f"Images          : {self._display_path(str(self._configured_media_dir('image')))}",
            f"Videos          : {self._display_path(str(self._configured_media_dir('video')))}",
            "",
            f"Save raw JSON   : {self.save_raw_json.get()}",
            f"Save Markdown   : {self.save_md.get()}",
            f"Print mode      : {self.print_mode.get()}",
            "",
            "Browse changes paths in the UI only.",
            "Use Save Config to persist output settings.",
        ])

    def _format_command_preview(self, cmd: list[str]) -> str:
        if len(cmd) < 4:
            return subprocess.list2cmdline(cmd)

        route_index = 4 if len(cmd) > 4 else None
        route = cmd[route_index] if route_index is not None else ""
        args = cmd[route_index + 1:] if route_index is not None else []
        display_cmd = [self._display_path(part) for part in cmd]

        lines = [
            "Run command preview",
            "",
            f"Python : {self._display_path(cmd[0])}",
            f"Script : {self._display_path(cmd[1])}",
            f"Config : {self._display_path(cmd[3]) if len(cmd) > 3 and cmd[2] == '-c' else '(default)'}",
            f"Route  : {route}",
        ]
        if args:
            lines.extend(["", "Args:"])
            lines.extend(f"  {self._display_path(arg)}" for arg in args)

        lines.extend(["", "Raw:", subprocess.list2cmdline(display_cmd)])
        return "\n".join(lines)

    def _display_path(self, value: str) -> str:
        if not value:
            return value
        try:
            path = Path(value)
            if path.is_absolute():
                return str(path.relative_to(BASE_DIR))
        except Exception:
            pass
        return value

    def run_current(self):
        if self.process_running:
            messagebox.showinfo("EasyGrok", "A command is already running.")
            return
        self.save_config()
        self._refresh_command_preview()
        if not self.current_command:
            messagebox.showerror("EasyGrok", "No command to run.")
            return

        self.process_running = True
        self.status.set("Running...")
        self._log("")
        self._log("$ " + subprocess.list2cmdline(self.current_command))

        thread = threading.Thread(target=self._run_worker, args=(self.current_command.copy(),), daemon=True)
        thread.start()

    def _run_worker(self, cmd: list[str]):
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            proc = subprocess.run(
                cmd,
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                check=False,
            )
            output = decode_process_output(proc.stdout)
            if proc.stderr:
                output += "\n[stderr]\n" + decode_process_output(proc.stderr)
            self.after(0, lambda: self._finish_run(proc.returncode, output))
        except Exception as exc:
            self.after(0, lambda: self._finish_run(1, str(exc)))

    def _finish_run(self, returncode: int, output: str):
        self._log(output.strip() or "(no output)")
        self.status.set(f"Finished with exit code {returncode}")
        self.process_running = False

    def _log(self, text: str):
        self.output_text.insert("end", text + "\n")
        self.output_text.see("end")


def main() -> int:
    app = EasyGrokUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
