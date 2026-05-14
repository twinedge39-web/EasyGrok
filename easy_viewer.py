from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog
import winsound


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv")
DEFAULT_EXTS = IMAGE_EXTS + VIDEO_EXTS
DEFAULT_WINDOW_HEIGHT = 860
Image = None
ImageTk = None
ImageDraw = None
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
MAX_EMBEDDED_METADATA_CHARS = 20000
THUMB_CACHE_DIR = Path(__file__).resolve().parent / "out" / ".easy_viewer_cache"
LOCAL_FFMPEG_CANDIDATES = (
    Path(__file__).resolve().parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="easy_viewer.py",
        description="Watch an image folder and show new images as quick previews.",
    )
    ap.add_argument("--watch", default="./out/images", help="Image folder to watch (default: ./out/images)")
    ap.add_argument("--recursive", action="store_true", help="Watch files under subfolders too.")
    ap.add_argument("--topmost", action="store_true", help="Keep the preview window above other windows (default).")
    ap.add_argument("--no-topmost", action="store_true", help="Start without keeping the preview window above others.")
    ap.add_argument("--poll", type=float, default=1.0, help="Polling interval in seconds (default: 1.0)")
    ap.add_argument("--open-latest", action="store_true", help="Show the latest existing image on startup.")
    ap.add_argument("--choose-folder", action="store_true", help="Choose the watch folder with a folder dialog on startup.")
    ap.add_argument(
        "--height",
        type=int,
        default=DEFAULT_WINDOW_HEIGHT,
        help=f"Preview window height in pixels (default: {DEFAULT_WINDOW_HEIGHT}, matching ui_tk.py).",
    )
    ap.add_argument(
        "--fit",
        choices=("contain", "actual"),
        default="contain",
        help="Preview sizing mode (default: contain).",
    )
    ap.add_argument(
        "--ext",
        nargs="+",
        default=list(DEFAULT_EXTS),
        help="File extensions to watch (default: images + common videos)",
    )
    return ap.parse_args()


def normalize_exts(values: list[str]) -> set[str]:
    exts = set()
    for value in values:
        item = value.strip().lower()
        if not item:
            continue
        if not item.startswith("."):
            item = f".{item}"
        exts.add(item)
    return exts or set(DEFAULT_EXTS)


def list_media(folder: Path, exts: set[str], recursive: bool = False) -> list[Path]:
    if not folder.exists():
        return []
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        (
            p
            for p in iterator
            if p.is_file()
            and p.suffix.lower() in exts
            and ".easy_viewer_cache" not in p.parts
        ),
        key=lambda p: (p.stat().st_mtime, p.name),
    )


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def format_size(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_mb:.2f} MB"


def format_embedded_metadata(info: dict) -> list[str]:
    if not info:
        return []

    lines = ["", "embedded_metadata:"]
    total_chars = 0
    for key in sorted(info.keys()):
        value = info[key]
        if isinstance(value, bytes):
            text = f"<{len(value)} bytes>"
        else:
            text = str(value)

        remaining = MAX_EMBEDDED_METADATA_CHARS - total_chars
        if remaining <= 0:
            lines.append("... embedded metadata truncated ...")
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n... truncated ..."

        lines.append(f"{key}:")
        lines.append(text)
        total_chars += len(text)

    return lines


def video_thumb_cache_path(path: Path) -> Path:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", errors="replace")
    digest = hashlib.sha1(raw).hexdigest()
    return THUMB_CACHE_DIR / f"{digest}.jpg"


def ensure_thumb_cache_dir() -> Optional[Path]:
    for cache_dir in (
        THUMB_CACHE_DIR,
        Path(tempfile.gettempdir()) / "easy_viewer_cache",
    ):
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except OSError:
            continue
    return None


def generate_video_thumbnail(path: Path) -> Optional[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        for candidate in LOCAL_FFMPEG_CANDIDATES:
            if candidate.exists():
                ffmpeg = str(candidate)
                break
    if not ffmpeg:
        return None

    cache_dir = ensure_thumb_cache_dir()
    if cache_dir is None:
        return None

    thumb_path = cache_dir / video_thumb_cache_path(path).name
    if thumb_path.exists():
        return thumb_path

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "00:00:01",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(thumb_path),
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        return None
    if result.returncode == 0 and thumb_path.exists():
        return thumb_path
    return None


def copy_image_to_clipboard(image) -> None:
    output = io.BytesIO()
    image.convert("RGB").save(output, "BMP")
    dib = output.getvalue()[14:]
    output.close()

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
    if not handle:
        raise OSError("GlobalAlloc failed")

    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise OSError("GlobalLock failed")

    ctypes.memmove(locked, dib, len(dib))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise OSError("OpenClipboard failed")

    try:
        if not user32.EmptyClipboard():
            raise OSError("EmptyClipboard failed")
        if not user32.SetClipboardData(CF_DIB, handle):
            raise OSError("SetClipboardData failed")
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


class QuickPreviewViewer:
    def __init__(
        self,
        watch_dir: Path,
        exts: set[str],
        poll_sec: float,
        topmost: bool,
        fit: str,
        window_height: int,
        recursive: bool,
        open_latest: bool,
        choose_folder: bool,
    ) -> None:
        self.watch_dir = watch_dir
        self.root_watch_dir = watch_dir
        self.exts = exts
        self.poll_ms = max(100, int(poll_sec * 1000))
        self.topmost = topmost
        self.fit = fit
        self.window_height = max(360, int(window_height))
        self.recursive = recursive

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("EasyGrok Image Viewer")

        self.window: Optional[tk.Toplevel] = None
        self.label: Optional[tk.Label] = None
        self.status_frame: Optional[tk.Frame] = None
        self.menu: Optional[tk.Menu] = None
        self.topmost_menu_index: Optional[int] = None
        self.path_var = tk.StringVar(value="")
        self.meta_var = tk.StringVar(value="")
        self.watch_var = tk.StringVar(value=f"Watch: {self.watch_dir.resolve()}")
        self.photo: Optional[ImageTk.PhotoImage] = None

        self.seen: set[Path] = set()
        self.pending: dict[Path, tuple[int, float]] = {}
        self.images: list[Path] = []
        self.current_index: Optional[int] = None
        self.current_path: Optional[Path] = None

        if choose_folder:
            selected = filedialog.askdirectory(
                title="Select image watch folder",
                initialdir=str(self.watch_dir.resolve()),
            )
            if selected:
                self.watch_dir = Path(selected)
                self.watch_var.set(f"Watch: {self.watch_dir.resolve()}")

        existing = list_media(self.watch_dir, self.exts, self.recursive)
        self.images = existing
        if open_latest and existing:
            latest = existing[-1]
            self.seen.update(existing)
            self.show_file(latest)
        else:
            self.seen.update(existing)

        print(f"Watching: {self.watch_dir.resolve()}")
        print("Close the preview window any time; the next image will reopen it.")
        print("Keys: Left=older, Right=newer, Home=oldest, End=latest.")

    def run(self) -> None:
        self.root.after(self.poll_ms, self.poll_once)
        self.root.mainloop()

    def poll_once(self) -> None:
        try:
            self.watch_dir.mkdir(parents=True, exist_ok=True)
            self.images = list_media(self.watch_dir, self.exts, self.recursive)
            for path in self.images:
                if path in self.seen:
                    continue
                if self.is_ready(path):
                    self.seen.add(path)
                    self.pending.pop(path, None)
                    self.show_file(path)
        except Exception as exc:
            print(f"viewer warning: {exc}", file=sys.stderr)
        finally:
            self.root.after(self.poll_ms, self.poll_once)

    def is_ready(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        current = (stat.st_size, stat.st_mtime)
        previous = self.pending.get(path)
        self.pending[path] = current
        return stat.st_size > 0 and previous == current

    def ensure_window(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            return

        self.window = tk.Toplevel(self.root)
        self.window.title("EasyGrok Image Viewer")
        self.window.configure(bg="#111111")
        self.window.protocol("WM_DELETE_WINDOW", self.close_window)
        self.apply_topmost()

        self.label = tk.Label(self.window, bg="#111111")
        self.label.pack(fill="both", expand=True)

        self.status_frame = tk.Frame(self.window, bg="#202020")
        self.status_frame.pack(fill="x", side="bottom")

        watch_row = tk.Frame(self.status_frame, bg="#202020")
        watch_row.pack(fill="x", padx=6, pady=(5, 2))
        tk.Button(watch_row, text="Folder...", command=self.choose_folder).pack(side="left")
        tk.Button(watch_row, text="Root", command=self.return_to_root_folder).pack(side="left", padx=(4, 0))
        tk.Label(
            watch_row,
            textvariable=self.watch_var,
            anchor="w",
            bg="#202020",
            fg="#d8d8d8",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        path_row = tk.Frame(self.status_frame, bg="#202020")
        path_row.pack(fill="x", padx=6, pady=(2, 5))
        tk.Button(path_row, text="Copy Path", command=self.copy_current_path).pack(side="left")
        tk.Label(
            path_row,
            textvariable=self.path_var,
            anchor="w",
            bg="#202020",
            fg="#ffffff",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        meta_row = tk.Frame(self.status_frame, bg="#202020")
        meta_row.pack(fill="x", padx=6, pady=(0, 5))
        tk.Label(
            meta_row,
            textvariable=self.meta_var,
            anchor="w",
            bg="#202020",
            fg="#cfcfcf",
        ).pack(side="left", fill="x", expand=True)

        self.window.bind("<Left>", lambda event: self.show_relative(-1))
        self.window.bind("<Right>", lambda event: self.show_relative(1))
        self.window.bind("<Home>", lambda event: self.show_at_index(0))
        self.window.bind("<End>", lambda event: self.show_at_index(len(self.images) - 1))
        self.bind_context_menu()

    def close_window(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        self.label = None
        self.photo = None

    def show_file(self, path: Path) -> None:
        if is_video_path(path):
            self.show_video_placeholder(path)
        else:
            self.show_image(path)

    def show_image(self, path: Path) -> None:
        self.refresh_history(path)
        self.current_path = path
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            print(f"viewer warning: cannot open {path}: {exc}", file=sys.stderr)
            return

        self.ensure_window()
        if self.window is None or self.label is None:
            return

        position = self.current_position_text()
        self.update_status_text()
        self.window.update_idletasks()
        status_height = self.status_frame.winfo_reqheight() if self.status_frame is not None else 0
        target_height = self.target_window_height()
        max_image_height = max(120, target_height - status_height)
        display = self.resize_for_screen(image, max_image_height=max_image_height)
        self.photo = ImageTk.PhotoImage(display)
        self.label.configure(image=self.photo)

        width, _height = display.size
        window_width = max(width, 640)
        self.window.geometry(f"{window_width}x{target_height}")
        self.window.title(f"EasyGrok Image Viewer - {position} - {path.name}")
        self.window.deiconify()
        self.window.lift()
        if self.topmost:
            self.window.attributes("-topmost", True)

        print(f"Showing: {path}")

    def show_video_placeholder(self, path: Path) -> None:
        self.refresh_history(path)
        self.current_path = path
        self.ensure_window()
        if self.window is None or self.label is None:
            return

        position = self.current_position_text()
        self.update_status_text()
        self.window.update_idletasks()
        status_height = self.status_frame.winfo_reqheight() if self.status_frame is not None else 0
        target_height = self.target_window_height()
        placeholder_height = max(220, target_height - status_height)

        thumb_path = generate_video_thumbnail(path)
        if thumb_path:
            try:
                thumb = Image.open(thumb_path)
                thumb.load()
                display = self.resize_for_screen(thumb, max_image_height=placeholder_height)
            except Exception:
                display = self.make_video_placeholder(path, 720, placeholder_height)
        else:
            display = self.make_video_placeholder(path, 720, placeholder_height)

        self.photo = ImageTk.PhotoImage(display)
        self.label.configure(image=self.photo)

        width, _height = display.size
        window_width = max(width, 640)
        self.window.geometry(f"{window_width}x{target_height}")
        self.window.title(f"EasyGrok Image Viewer - {position} - {path.name}")
        self.window.deiconify()
        self.window.lift()
        if self.topmost:
            self.window.attributes("-topmost", True)

        print(f"Showing video: {path}")

    def make_video_placeholder(self, path: Path, width: int, height: int):
        image = Image.new("RGB", (width, height), "#111111")
        draw = ImageDraw.Draw(image)
        stat = path.stat()
        title = "VIDEO"
        name = path.name
        meta = f"{path.suffix.upper().lstrip('.')} | {format_size(stat.st_size)}"

        triangle_w = 96
        triangle_h = 120
        cx = width // 2
        cy = max(150, height // 2 - 30)
        triangle = [
            (cx - triangle_w // 3, cy - triangle_h // 2),
            (cx - triangle_w // 3, cy + triangle_h // 2),
            (cx + triangle_w // 2, cy),
        ]
        draw.rounded_rectangle((40, 40, width - 40, height - 40), radius=8, outline="#444444", width=2)
        draw.polygon(triangle, fill="#d8d8d8")
        draw.text((width // 2, cy + 90), title, fill="#ffffff", anchor="mm")
        draw.text((width // 2, cy + 124), name, fill="#d8d8d8", anchor="mm")
        draw.text((width // 2, cy + 154), meta, fill="#a8a8a8", anchor="mm")
        draw.text((width // 2, height - 70), "Right-click for path, metadata, or folder.", fill="#888888", anchor="mm")
        return image

    def update_status_text(self) -> None:
        self.watch_var.set(f"Watch: {self.watch_dir.resolve()}")
        if self.current_path is None:
            self.path_var.set("Path: (no image)")
            self.meta_var.set("")
            return
        self.path_var.set(f"Path: {self.current_path.resolve()}")
        self.meta_var.set(self.current_metadata_summary())

    def copy_current_path(self) -> None:
        if self.current_path is None:
            self.beep()
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(str(self.current_path.resolve()))
        self.root.update()

    def copy_current_metadata(self) -> None:
        if self.current_path is None:
            self.beep()
            return
        try:
            metadata = self.current_metadata_text()
        except Exception as exc:
            print(f"viewer warning: cannot read metadata {self.current_path}: {exc}", file=sys.stderr)
            self.beep()
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(metadata)
        self.root.update()

    def current_metadata_summary(self) -> str:
        if self.current_path is None:
            return ""
        try:
            stat = self.current_path.stat()
            if is_video_path(self.current_path):
                return f"VIDEO | {self.current_path.suffix.upper().lstrip('.')} | {format_size(stat.st_size)}"
            with Image.open(self.current_path) as image:
                return (
                    f"{image.format or self.current_path.suffix.lstrip('.').upper()} | "
                    f"{image.width}x{image.height} | "
                    f"{format_size(stat.st_size)}"
                )
        except Exception:
            return "metadata unavailable"

    def current_metadata_text(self) -> str:
        if self.current_path is None:
            raise ValueError("no current image")

        path = self.current_path.resolve()
        stat = self.current_path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        if is_video_path(self.current_path):
            return "\n".join(
                [
                    f"path: {path}",
                    f"filename: {self.current_path.name}",
                    f"type: video",
                    f"extension: {self.current_path.suffix.lower()}",
                    f"size_bytes: {stat.st_size}",
                    f"size_mb: {stat.st_size / (1024 * 1024):.2f}",
                    f"modified: {modified}",
                ]
            )

        with Image.open(self.current_path) as image:
            image.load()
            fmt = image.format or self.current_path.suffix.lstrip(".").upper()
            lines = [
                f"path: {path}",
                f"filename: {self.current_path.name}",
                f"format: {fmt}",
                f"dimensions: {image.width}x{image.height}",
                f"mode: {image.mode}",
                f"size_bytes: {stat.st_size}",
                f"size_mb: {stat.st_size / (1024 * 1024):.2f}",
                f"modified: {modified}",
            ]
            lines.extend(format_embedded_metadata(dict(image.info)))
            return "\n".join(lines)

    def copy_current_image(self) -> None:
        if self.current_path is None:
            self.beep()
            return
        if is_video_path(self.current_path):
            self.beep()
            return
        try:
            image = Image.open(self.current_path)
            image.load()
            copy_image_to_clipboard(image)
        except Exception as exc:
            print(f"viewer warning: cannot copy image {self.current_path}: {exc}", file=sys.stderr)
            self.beep()

    def open_current_folder(self) -> None:
        if self.current_path is None:
            self.beep()
            return
        try:
            subprocess.Popen(["explorer", f"/select,{self.current_path.resolve()}"])
        except Exception as exc:
            print(f"viewer warning: cannot open folder {self.current_path}: {exc}", file=sys.stderr)
            self.beep()

    def open_current_file(self) -> None:
        if self.current_path is None:
            self.beep()
            return
        try:
            subprocess.Popen(["cmd", "/c", "start", "", str(self.current_path.resolve())], shell=False)
        except Exception as exc:
            print(f"viewer warning: cannot open file {self.current_path}: {exc}", file=sys.stderr)
            self.beep()

    def bind_context_menu(self) -> None:
        self.menu = tk.Menu(self.window, tearoff=False)
        self.menu.add_command(label="Copy Image", command=self.copy_current_image)
        self.menu.add_command(label="Copy Path", command=self.copy_current_path)
        self.menu.add_command(label="Copy Metadata", command=self.copy_current_metadata)
        self.menu.add_command(label="Open File", command=self.open_current_file)
        self.menu.add_command(label="Open Folder", command=self.open_current_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Choose Folder...", command=self.choose_folder)
        self.menu.add_command(label="Return to Root", command=self.return_to_root_folder)
        self.menu.add_separator()
        self.topmost_menu_index = self.menu.index("end") + 1
        self.menu.add_command(label=self.topmost_menu_label(), command=self.toggle_topmost)

        def show_menu(event) -> None:
            if self.menu is None:
                return
            self.menu.tk_popup(event.x_root, event.y_root)
            self.menu.grab_release()

        self.window.bind("<Button-3>", show_menu)
        if self.label is not None:
            self.label.bind("<Button-3>", show_menu)
        if self.status_frame is not None:
            self.status_frame.bind("<Button-3>", show_menu)

    def topmost_menu_label(self) -> str:
        return "Disable Topmost" if self.topmost else "Enable Topmost"

    def apply_topmost(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.attributes("-topmost", bool(self.topmost))

    def toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.apply_topmost()
        if self.menu is not None and self.topmost_menu_index is not None:
            self.menu.entryconfigure(self.topmost_menu_index, label=self.topmost_menu_label())

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Select image watch folder",
            initialdir=str(self.watch_dir.resolve()),
        )
        if not selected:
            return
        self.set_watch_folder(Path(selected))

    def return_to_root_folder(self) -> None:
        if self.watch_dir.resolve() == self.root_watch_dir.resolve():
            self.beep()
            return
        self.set_watch_folder(self.root_watch_dir)

    def set_watch_folder(self, folder: Path) -> None:
        self.watch_dir = folder
        self.pending.clear()
        self.images = list_media(self.watch_dir, self.exts, self.recursive)
        self.seen = set(self.images)
        self.current_index = None
        self.current_path = None
        self.update_status_text()
        if self.images:
            self.show_file(self.images[-1])
        else:
            self.show_empty_placeholder()
            self.beep()

    def show_empty_placeholder(self) -> None:
        self.ensure_window()
        if self.window is None or self.label is None:
            return

        self.update_status_text()
        self.window.update_idletasks()
        status_height = self.status_frame.winfo_reqheight() if self.status_frame is not None else 0
        target_height = self.target_window_height()
        placeholder_height = max(220, target_height - status_height)
        placeholder_width = 720
        image = Image.new("RGB", (placeholder_width, placeholder_height), "#111111")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((40, 40, placeholder_width - 40, placeholder_height - 40), radius=8, outline="#444444", width=2)
        draw.text((placeholder_width // 2, placeholder_height // 2 - 24), "NO MEDIA", fill="#ffffff", anchor="mm")
        draw.text((placeholder_width // 2, placeholder_height // 2 + 18), str(self.watch_dir.resolve()), fill="#a8a8a8", anchor="mm")
        draw.text((placeholder_width // 2, placeholder_height - 70), "Drop an image or video into this folder.", fill="#888888", anchor="mm")

        self.photo = ImageTk.PhotoImage(image)
        self.label.configure(image=self.photo)
        self.window.geometry(f"{placeholder_width}x{target_height}")
        self.window.title("EasyGrok Image Viewer - no media")
        self.window.deiconify()
        self.window.lift()
        if self.topmost:
            self.window.attributes("-topmost", True)

    def refresh_history(self, current: Optional[Path] = None) -> None:
        self.images = list_media(self.watch_dir, self.exts, self.recursive)
        if current is None:
            return
        try:
            self.current_index = self.images.index(current)
        except ValueError:
            self.current_index = None

    def current_position_text(self) -> str:
        if self.current_index is None or not self.images:
            return "?/?"
        return f"{self.current_index + 1}/{len(self.images)}"

    def show_relative(self, offset: int) -> None:
        self.refresh_history()
        if not self.images:
            self.beep()
            return
        if self.current_index is None:
            index = len(self.images) - 1
        else:
            index = self.current_index + offset
        if index < 0 or index >= len(self.images):
            self.beep()
            return
        self.show_at_index(index)

    def show_at_index(self, index: int) -> None:
        self.refresh_history()
        if not self.images:
            self.beep()
            return
        safe_index = max(0, min(index, len(self.images) - 1))
        if safe_index != index:
            self.beep()
            return
        self.show_file(self.images[safe_index])

    def beep(self) -> None:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

    def target_window_height(self) -> int:
        screen_h = self.root.winfo_screenheight()
        return min(self.window_height, max(360, int(screen_h * 0.95)))

    def resize_for_screen(self, image: Image.Image, max_image_height: Optional[int] = None) -> Image.Image:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        max_w = min(1000, max(320, int(screen_w * 0.85)))
        max_h = min(1000, max(240, int(screen_h * 0.85)))
        if max_image_height is not None:
            max_h = min(max_h, max_image_height)

        width, height = image.size
        scale = min(max_w / width, max_h / height, 1.0)

        if self.fit == "actual" and width <= max_w and height <= max_h:
            scale = 1.0

        if scale >= 1.0:
            return image.copy()

        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        return image.resize(new_size, Image.Resampling.LANCZOS)


def main() -> int:
    global Image, ImageTk, ImageDraw
    args = parse_args()
    try:
        from PIL import Image as PilImage
        from PIL import ImageDraw as PilImageDraw
        from PIL import ImageTk as PilImageTk
    except ImportError as exc:
        raise SystemExit(
            "ERROR: easy_viewer.py requires Pillow.\n"
            "Install it with: python -m pip install Pillow"
        ) from exc
    Image = PilImage
    ImageDraw = PilImageDraw
    ImageTk = PilImageTk

    viewer = QuickPreviewViewer(
        watch_dir=Path(args.watch),
        exts=normalize_exts(args.ext),
        poll_sec=args.poll,
        topmost=not bool(args.no_topmost),
        fit=args.fit,
        window_height=args.height,
        recursive=bool(args.recursive),
        open_latest=bool(args.open_latest),
        choose_folder=bool(args.choose_folder),
    )
    viewer.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
