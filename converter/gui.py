"""The desktop window."""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import engine, formats
from .tools import Cancelled, ConversionError, soffice_path

log = logging.getLogger("converter")

APP_DIR = Path(__file__).resolve().parent.parent
ICON = APP_DIR / "assets" / "icon.png"

QUALITY = [("best", "Best quality"), ("balanced", "Balanced"), ("small", "Smaller files")]
MAX_FOLDER_FILES = 2000

# What each type is usually converted to, used until the user picks something else.
DEFAULT_TARGET = {
    "docx": "pdf", "doc": "pdf", "odt": "pdf", "rtf": "pdf", "md": "pdf", "html": "pdf",
    "txt": "pdf", "epub": "pdf", "pptx": "pdf", "ppt": "pdf", "odp": "pdf", "pdf": "docx",
    "xlsx": "csv", "xls": "xlsx", "ods": "xlsx", "csv": "xlsx", "tsv": "xlsx", "json": "csv",
    "yaml": "json", "toml": "json",
    "heic": "jpg", "webp": "png", "png": "jpg", "jpg": "png", "bmp": "png", "tiff": "jpg",
    "avif": "jpg", "svg": "png", "gif": "mp4", "ico": "png", "psd": "png",
    "mov": "mp4", "mkv": "mp4", "avi": "mp4", "webm": "mp4", "wmv": "mp4", "flv": "mp4",
    "mp4": "mp3", "m4v": "mp4", "3gp": "mp4", "mpg": "mp4",
    "wav": "mp3", "flac": "mp3", "m4a": "mp3", "ogg": "mp3", "opus": "mp3", "wma": "mp3",
    "aiff": "mp3", "mp3": "wav", "srt": "vtt", "vtt": "srt", "ass": "srt",
    "zip": "tar.gz", "tar.gz": "zip", "tar": "zip", "tar.bz2": "zip", "tar.xz": "zip",
    "ttf": "woff2", "otf": "woff2",
}


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "FileConverter"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FileConverter"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "file-converter"


def open_path(path, reveal=False):
    path = Path(path)
    try:
        if os.name == "nt":
            if reveal:
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])
    except Exception as exc:
        messagebox.showerror("File Converter", f"Couldn't open {path}:\n{exc}")


def shorten(path, limit=48):
    text = str(path)
    if len(text) <= limit:
        return text
    return text[: limit // 3] + "…" + text[-(limit - limit // 3 - 1):]


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class Item:
    def __init__(self, path: Path):
        self.path = path
        self.ext = formats.get_ext(path)
        self.targets = engine.targets_for(path)
        self.status = "Ready" if self.targets else "Not supported"
        self.outputs = []
        self.iid = None
        try:
            self.size = human_size(path.stat().st_size)
        except OSError:
            self.size = ""


class App:
    def __init__(self, root, files=()):
        self.root = root
        self.items = []
        self.by_iid = {}
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.running = False
        self.drop_enabled = False
        self.target_vars = {}
        self.settings = self._load_settings()
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)

        self.quality = tk.StringVar(value=dict(QUALITY).get(self.settings.get("quality"), "Balanced"))
        self.out_mode = tk.StringVar(value=self.settings.get("out_mode", "same"))
        self.out_dir = tk.StringVar(value=self.settings.get("out_dir") or str(self._default_out_dir()))
        self.status = tk.StringVar(value="Add some files to get started.")

        self._setup_theme()
        self._build()
        self._enable_drop()
        self.add_paths(files)
        self._refresh_targets()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._poll)

    # ---- setup ---------------------------------------------------------

    def _setup_theme(self):
        self.dark = False
        try:
            import darkdetect
            self.dark = bool(darkdetect.isDark())
        except Exception:
            pass
        try:
            import sv_ttk
            sv_ttk.set_theme("dark" if self.dark else "light")
        except Exception:
            style = ttk.Style()
            if "vista" in style.theme_names():
                style.theme_use("vista")
            elif "clam" in style.theme_names():
                style.theme_use("clam")
        style = ttk.Style()
        self.bg = style.lookup("TFrame", "background") or ("#1c1c1c" if self.dark else "#fafafa")
        self.fg = style.lookup("TLabel", "foreground") or ("#ffffff" if self.dark else "#1c1c1c")
        self.muted = "#9a9a9a" if self.dark else "#6b6b6b"
        self.accent = "#57c8ff" if self.dark else "#0067c0"
        self.ok_color = "#6ccb5f" if self.dark else "#0f7b0f"
        self.err_color = "#ff99a4" if self.dark else "#c42b1c"
        self.zone_fill = "#262a30" if self.dark else "#f1f5fb"
        self.zone_line = "#5a6270" if self.dark else "#9aa7b8"

        base = tkfont.nametofont("TkDefaultFont")
        family = base.actual("family")
        self.title_font = tkfont.Font(family=family, size=17, weight="bold")
        self.big_font = tkfont.Font(family=family, size=13, weight="bold")
        self.small_font = tkfont.Font(family=family, size=9)
        self.root.configure(background=self.bg)

    def _build(self):
        root = self.root
        pad = int(14 * self.scale)
        main = ttk.Frame(root, padding=pad)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # Header
        ttk.Label(main, text="File Converter", font=self.title_font).grid(row=0, column=0, sticky="w")
        ttk.Label(main, foreground=self.muted,
                  text="Documents, PDFs, images, video, audio, spreadsheets and more. "
                       "Everything stays on this computer.").grid(row=1, column=0, sticky="w")

        # Drop zone
        self.zone = tk.Canvas(main, height=int(96 * self.scale), highlightthickness=0,
                              background=self.bg, cursor="hand2")
        self.zone.grid(row=2, column=0, sticky="ew", pady=(pad, pad // 2))
        self.zone.bind("<Configure>", lambda e: self._draw_zone())
        self.zone.bind("<Button-1>", lambda e: self.browse_files())
        self._zone_hot = False

        # File list
        box = ttk.Frame(main)
        box.grid(row=3, column=0, sticky="nsew")
        main.rowconfigure(3, weight=1, minsize=int(150 * self.scale))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        cols = ("name", "type", "size", "status")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="extended", height=5)
        for col, text, width, stretch in (("name", "File", 240, True), ("type", "Type", 70, False),
                                          ("size", "Size", 80, False), ("status", "Status", 260, True)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=int(width * self.scale), stretch=stretch, anchor="w")
        self.tree.tag_configure("done", foreground=self.ok_color)
        self.tree.tag_configure("failed", foreground=self.err_color)
        self.tree.tag_configure("unsupported", foreground=self.muted)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_selected())
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())

        row = ttk.Frame(main)
        row.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.add_btn = ttk.Button(row, text="Add files…", command=self.browse_files)
        self.add_btn.pack(side="left")
        self.folder_btn = ttk.Button(row, text="Add folder…", command=self.browse_folder)
        self.folder_btn.pack(side="left", padx=(6, 0))
        self.remove_btn = ttk.Button(row, text="Remove", command=self.remove_selected)
        self.remove_btn.pack(side="left", padx=(6, 0))
        self.clear_btn = ttk.Button(row, text="Clear list", command=self.clear)
        self.clear_btn.pack(side="left", padx=(6, 0))
        self.detail = ttk.Label(row, text="", foreground=self.muted)
        self.detail.pack(side="left", padx=(12, 0), fill="x", expand=True)

        # Convert-to menus, one per file type in the list. Scrolls when there are many types.
        frame = ttk.LabelFrame(main, text="Convert to", padding=int(8 * self.scale))
        frame.grid(row=6, column=0, sticky="ew", pady=(pad // 2, 0))
        frame.columnconfigure(0, weight=1)
        self.targets_canvas = tk.Canvas(frame, highlightthickness=0, background=self.bg, height=40)
        self.targets_canvas.grid(row=0, column=0, sticky="ew")
        self.targets_scroll = ttk.Scrollbar(frame, orient="vertical", command=self.targets_canvas.yview)
        self.targets_canvas.configure(yscrollcommand=self.targets_scroll.set)
        self.targets_box = ttk.Frame(self.targets_canvas)
        self.targets_canvas.create_window(0, 0, window=self.targets_box, anchor="nw")
        self.targets_box.bind("<Configure>", lambda e: self._fit_targets())
        for widget in (self.targets_canvas, self.targets_box):
            widget.bind("<Enter>", lambda e: self._wheel(True))
            widget.bind("<Leave>", lambda e: self._wheel(False))

        # Options
        opts = ttk.Frame(main)
        opts.grid(row=7, column=0, sticky="ew", pady=(pad // 2, 0))
        opts.columnconfigure(5, weight=1)
        ttk.Label(opts, text="Quality").grid(row=0, column=0, sticky="w")
        self.quality_box = ttk.Combobox(opts, textvariable=self.quality, state="readonly", width=14,
                                        values=[label for _, label in QUALITY])
        self.quality_box.grid(row=0, column=1, sticky="w", padx=(8, 20))
        ttk.Label(opts, text="Save to").grid(row=0, column=2, sticky="w")
        self.same_radio = ttk.Radiobutton(opts, text="Same folder as each file", value="same",
                                          variable=self.out_mode, command=self._sync_out_widgets)
        self.same_radio.grid(row=0, column=3, sticky="w", padx=(8, 12))
        self.folder_radio = ttk.Radiobutton(opts, text="This folder:", value="folder",
                                            variable=self.out_mode, command=self._sync_out_widgets)
        self.folder_radio.grid(row=0, column=4, sticky="w")
        self.out_entry = ttk.Entry(opts, textvariable=self.out_dir)
        self.out_entry.grid(row=0, column=5, sticky="ew", padx=(6, 6))
        self.out_browse = ttk.Button(opts, text="Browse…", command=self._pick_out_dir)
        self.out_browse.grid(row=0, column=6, sticky="e")
        self._sync_out_widgets()

        # Progress and actions
        bottom = ttk.Frame(main)
        bottom.grid(row=8, column=0, sticky="ew", pady=(pad, 0))
        bottom.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(bottom, textvariable=self.status).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.open_btn = ttk.Button(bottom, text="Open output folder", command=self._open_output_folder,
                                   state="disabled")
        self.open_btn.grid(row=1, column=1, sticky="e", padx=(6, 0), pady=(8, 0))
        self.cancel_btn = ttk.Button(bottom, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(8, 0))
        try:  # the Sun Valley theme's blue button
            self.convert_btn = ttk.Button(bottom, text="Convert", command=self.start, style="Accent.TButton")
        except tk.TclError:
            self.convert_btn = ttk.Button(bottom, text="Convert", command=self.start)
        self.convert_btn.grid(row=1, column=3, sticky="e", padx=(6, 0), pady=(8, 0))

        if not soffice_path():
            link = ttk.Label(main, cursor="hand2", foreground=self.accent, font=self.small_font,
                             text="Tip: install LibreOffice (free) for PowerPoint files and "
                                  "pixel-perfect Word/Excel → PDF.")
            link.grid(row=9, column=0, sticky="w", pady=(8, 0))
            link.bind("<Button-1>", lambda e: webbrowser.open("https://www.libreoffice.org/download/"))

        root.bind("<Command-o>" if sys.platform == "darwin" else "<Control-o>", lambda e: self.browse_files())

    def _draw_zone(self):
        c = self.zone
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10:
            return
        line = self.accent if self._zone_hot else self.zone_line
        fill = self.zone_fill
        r, m = 14, 2
        pts = [m + r, m, w - m - r, m, w - m, m, w - m, m + r, w - m, h - m - r, w - m, h - m,
               w - m - r, h - m, m + r, h - m, m, h - m, m, h - m - r, m, m + r, m, m]
        c.create_polygon(pts, smooth=True, fill=fill, outline=line, width=2, dash=(6, 4))
        main_text = "Drop files here" if self.drop_enabled else "Click to choose files"
        c.create_text(w / 2, h / 2 - 11 * self.scale, text=main_text, fill=self.fg, font=self.big_font)
        sub = "or click to choose files" if self.drop_enabled else "(drag and drop isn't available on this system)"
        c.create_text(w / 2, h / 2 + 13 * self.scale, text=sub, fill=self.muted)

    def _enable_drop(self):
        self.drop_enabled = False
        try:
            from tkinterdnd2 import DND_FILES
            for widget in (self.root, self.zone, self.tree):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda e: self._set_hot(True, e))
                widget.dnd_bind("<<DropLeave>>", lambda e: self._set_hot(False, e))
            self.drop_enabled = True
        except Exception as exc:
            log.info("drag and drop unavailable: %s", exc)
        if sys.platform == "darwin":
            # Files dropped on the Dock icon / app bundle.
            self.root.createcommand("::tk::mac::OpenDocument", lambda *paths: self.add_paths(paths))
        self._draw_zone()

    def _set_hot(self, hot, event=None):
        self._zone_hot = hot
        self._draw_zone()
        return getattr(event, "action", None)

    def _on_drop(self, event):
        self._set_hot(False)
        self.add_paths(self.root.tk.splitlist(event.data))
        return getattr(event, "action", None)

    # ---- files ---------------------------------------------------------

    def add_paths(self, paths):
        if self.busy:
            self.status.set("Wait for the current conversion to finish before adding files.")
            return
        known = {item.path for item in self.items}
        added = 0
        for raw in paths:
            path = Path(str(raw)).expanduser()
            files = []
            if path.is_dir():
                files = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith("."))
                files = files[:MAX_FOLDER_FILES]
            elif path.is_file():
                files = [path]
            for f in files:
                f = f.resolve()
                if f in known:
                    continue
                known.add(f)
                item = Item(f)
                item.iid = self.tree.insert("", "end", values=(f.name, item.ext.upper() or "?",
                                                               item.size, item.status))
                if not item.targets:
                    self.tree.item(item.iid, tags=("unsupported",))
                self.items.append(item)
                self.by_iid[item.iid] = item
                added += 1
        if added:
            self._refresh_targets()
            self.status.set(f"{len(self.items)} file(s) ready.")

    def browse_files(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(title="Choose files to convert",
                                            initialdir=self.settings.get("last_dir") or str(Path.home()))
        if paths:
            self.settings["last_dir"] = str(Path(paths[0]).parent)
            self.add_paths(paths)

    def browse_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title="Add every file in a folder",
                                         initialdir=self.settings.get("last_dir") or str(Path.home()))
        if folder:
            self.settings["last_dir"] = folder
            self.add_paths([folder])

    def remove_selected(self):
        if self.busy:
            return
        for iid in self.tree.selection():
            item = self.by_iid.pop(iid, None)
            if item:
                self.items.remove(item)
            self.tree.delete(iid)
        self._refresh_targets()
        self._show_selected()

    def clear(self):
        if self.busy:
            return
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        self.by_iid.clear()
        self.progress["value"] = 0
        self.status.set("Add some files to get started.")
        self._refresh_targets()
        self._show_selected()

    def _set_row(self, item, status, tag=None):
        item.status = status
        if self.tree.exists(item.iid):
            self.tree.set(item.iid, "status", status)
            self.tree.item(item.iid, tags=(tag,) if tag else ())
        self._show_selected()

    def _show_selected(self):
        sel = self.tree.selection()
        item = self.by_iid.get(sel[0]) if len(sel) == 1 else None
        if not item:
            self.detail.configure(text="")
            return
        if item.outputs:
            text = f"Double-click to open · saved in {shorten(item.outputs[0].parent)}"
        elif not item.targets:
            text = engine.hint_for(item.path)
        elif item.status.startswith("✗"):
            text = "Conversion failed. Double-click for details."
        else:
            text = shorten(item.path)
        self.detail.configure(text=text)

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        item = self.by_iid.get(iid)
        if not item:
            return
        if item.status.startswith("✗"):
            messagebox.showerror("File Converter", f"{item.path.name}\n\n{item.status[2:]}")
        else:
            open_path(item.outputs[0] if item.outputs else item.path)

    # ---- convert-to menus --------------------------------------------------

    def _fit_targets(self):
        """Show up to four rows; scroll for the rest."""
        need = self.targets_box.winfo_reqheight()
        rows = max(1, len(self.targets_box.grid_slaves(column=0)))
        limit = int(need / rows * 4.3) if rows > 4 else need
        self.targets_canvas.configure(height=min(need, limit), scrollregion=(0, 0, 0, need))
        if need > limit:
            self.targets_scroll.grid(row=0, column=1, sticky="ns")
        else:
            self.targets_scroll.grid_remove()
            self.targets_canvas.yview_moveto(0)

    def _wheel(self, on):
        if on:
            self.root.bind_all("<MouseWheel>", self._on_wheel)
            self.root.bind_all("<Button-4>", lambda e: self.targets_canvas.yview_scroll(-1, "units"))
            self.root.bind_all("<Button-5>", lambda e: self.targets_canvas.yview_scroll(1, "units"))
        else:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.unbind_all(seq)

    def _on_wheel(self, event):
        if self.targets_scroll.winfo_ismapped():
            step = -1 if event.delta > 0 else 1
            self.targets_canvas.yview_scroll(step, "units")

    def _refresh_targets(self):
        for child in self.targets_box.winfo_children():
            child.destroy()
        groups = {}
        for item in self.items:
            groups.setdefault(item.ext, []).append(item)
        saved = self.settings.setdefault("targets", {})
        row = 0
        if not groups:
            ttk.Label(self.targets_box, foreground=self.muted,
                      text="Add files and choose what to turn each type into.").grid(row=0, column=0, sticky="w")
        for ext in formats.sort_formats(groups):
            items = groups[ext]
            targets = items[0].targets
            name = formats.label(ext) if ext else "Files without an extension"
            ttk.Label(self.targets_box, text=f"{len(items)} × {name}").grid(
                row=row, column=0, sticky="w", pady=2)
            if not targets:
                ttk.Label(self.targets_box, text=engine.hint_for(items[0].path),
                          foreground=self.muted).grid(row=row, column=1, columnspan=2, sticky="w",
                                                      padx=(12, 0))
            else:
                labels = [formats.label(t) for t in targets]
                var = self.target_vars.get(ext)
                if var is None or var.get() not in labels:
                    choice = saved.get(ext) if saved.get(ext) in targets else DEFAULT_TARGET.get(ext)
                    if choice not in targets:
                        choice = targets[0]
                    var = tk.StringVar(value=formats.label(choice))
                    self.target_vars[ext] = var
                ttk.Label(self.targets_box, text="→").grid(row=row, column=1, sticky="w", padx=(12, 8))
                box = ttk.Combobox(self.targets_box, textvariable=var, values=labels,
                                   state="readonly", width=34, height=20)
                box.grid(row=row, column=2, sticky="w", pady=2, padx=(0, 4))
            row += 1
        ready = any(item.targets for item in self.items)
        self.convert_btn.configure(state="normal" if ready and not self.busy else "disabled")

    def _chosen_target(self, item):
        var = self.target_vars.get(item.ext)
        if not var:
            return None
        return next((t for t in item.targets if formats.label(t) == var.get()), None)

    # ---- output folder ---------------------------------------------------------

    def _default_out_dir(self):
        for name in ("Desktop", "Downloads"):
            if (Path.home() / name).is_dir():
                return Path.home() / name
        return Path.home()

    def _sync_out_widgets(self):
        state = "normal" if self.out_mode.get() == "folder" else "disabled"
        self.out_entry.configure(state=state)
        self.out_browse.configure(state=state)

    def _pick_out_dir(self):
        folder = filedialog.askdirectory(title="Save converted files to", initialdir=self.out_dir.get())
        if folder:
            self.out_dir.set(folder)

    def _open_output_folder(self):
        done = [item for item in self.items if item.outputs]
        sel = [self.by_iid[i] for i in self.tree.selection() if i in self.by_iid and self.by_iid[i].outputs]
        target = (sel or done[-1:] or [None])[0]
        if target:
            open_path(target.outputs[0], reveal=True)

    # ---- running -----------------------------------------------------------

    @property
    def busy(self):
        return self.running

    def start(self):
        if self.busy:
            return
        jobs = [(item, self._chosen_target(item)) for item in self.items if item.targets]
        jobs = [(item, target) for item, target in jobs if target]
        if not jobs:
            return
        out_dir = None
        if self.out_mode.get() == "folder":
            out_dir = Path(self.out_dir.get()).expanduser()
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("File Converter", f"Can't use that folder:\n{exc}")
                return
        quality = next(key for key, label in QUALITY if label == self.quality.get())
        self._save_settings(quality)

        for item, _ in jobs:
            item.outputs = []
            self._set_row(item, "Waiting")
        self.cancel.clear()
        self.progress["value"] = 0
        self._total = len(jobs)
        self._finished = 0
        self.running = True
        self._set_busy(True)
        self.status.set(f"Converting {len(jobs)} file(s)…")
        self.worker = threading.Thread(target=self._work, args=(jobs, out_dir, quality), daemon=True)
        self.worker.start()

    def _work(self, jobs, out_dir, quality):
        post = self.events.put
        for item, target in jobs:
            if self.cancel.is_set():
                post(("cancelled", item, None))
                continue
            post(("start", item, target))
            try:
                outputs = engine.convert(item.path, target, out_dir, quality,
                                         progress=lambda f, it=item: post(("progress", it, f)),
                                         cancel=self.cancel)
                post(("done", item, outputs))
            except Cancelled:
                post(("cancelled", item, None))
            except ConversionError as exc:
                post(("failed", item, str(exc)))
            except Exception as exc:  # keep going with the other files
                log.exception("unexpected failure on %s", item.path)
                post(("failed", item, f"Unexpected error: {exc}"))
        post(("finished", None, None))

    def _poll(self):
        try:
            while True:
                kind, item, data = self.events.get_nowait()
                self._handle(kind, item, data)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _handle(self, kind, item, data):
        if kind == "start":
            self._current = 0.0
            self._set_row(item, f"Converting to .{data}…")
        elif kind == "progress":
            self._current = data
            self._set_row(item, f"Converting… {int(data * 100)}%")
        elif kind == "done":
            item.outputs = [Path(p) for p in data]
            names = ", ".join(p.name + ("/" if p.is_dir() else "") for p in item.outputs)
            self._set_row(item, f"✓ Saved {names}", "done")
            self._finished += 1
            self._current = 0.0
            self.open_btn.configure(state="normal")
        elif kind == "failed":
            self._set_row(item, f"✗ {data}", "failed")
            self._finished += 1
            self._current = 0.0
        elif kind == "cancelled":
            self._set_row(item, "Cancelled", "unsupported")
            self._finished += 1
            self._current = 0.0
        elif kind == "finished":
            self.running = False
            self._set_busy(False)
            ok = sum(1 for it in self.items if it.outputs)
            bad = sum(1 for it in self.items if it.status.startswith("✗"))
            parts = [f"{ok} converted"] + ([f"{bad} failed"] if bad else [])
            if self.cancel.is_set():
                parts.append("cancelled")
            self.status.set("Done: " + ", ".join(parts) + ".")
            self.progress["value"] = 100 if not self.cancel.is_set() else self.progress["value"]
            if bad:
                self.status.set(self.status.get() + " Double-click a red row to see why.")
            return
        total = max(1, getattr(self, "_total", 1))
        self.progress["value"] = 100 * (self._finished + getattr(self, "_current", 0.0)) / total

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.add_btn, self.folder_btn, self.remove_btn, self.clear_btn,
                       self.quality_box, self.same_radio, self.folder_radio):
            widget.configure(state=state if widget is not self.quality_box else
                             ("disabled" if busy else "readonly"))
        for child in self.targets_box.winfo_children():
            if isinstance(child, ttk.Combobox):
                child.configure(state="disabled" if busy else "readonly")
        self.convert_btn.configure(state=state)
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if not busy:
            self._sync_out_widgets()
            self._refresh_targets()
        else:
            self.out_entry.configure(state="disabled")
            self.out_browse.configure(state="disabled")

    def _cancel(self):
        self.cancel.set()
        self.status.set("Cancelling…")

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno("File Converter", "A conversion is still running. Stop it and quit?"):
                return
            self.cancel.set()
            if self.worker:
                self.worker.join(timeout=5)
        quality = next((k for k, label in QUALITY if label == self.quality.get()), "balanced")
        self._save_settings(quality)
        self.root.destroy()

    # ---- settings ---------------------------------------------------------------

    def _load_settings(self):
        try:
            return json.loads((config_dir() / "settings.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self, quality):
        targets = self.settings.setdefault("targets", {})
        for ext, var in self.target_vars.items():
            fmt = next((t for t in formats.FORMATS if formats.label(t) == var.get()), None)
            if fmt:
                targets[ext] = fmt
        self.settings.update(quality=quality, out_mode=self.out_mode.get(), out_dir=self.out_dir.get())
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            (config_dir() / "settings.json").write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError:
            log.warning("couldn't save settings", exc_info=True)


def run_app(files=()):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FileConverter.App")
        except Exception:
            pass
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    root.title("File Converter")
    scale = max(1.0, root.winfo_fpixels("1i") / 96)
    width = min(int(920 * scale), root.winfo_screenwidth() - 40)
    height = min(int(740 * scale), root.winfo_screenheight() - 80)
    root.geometry(f"{width}x{height}")
    root.minsize(min(width, int(720 * scale)), min(height, int(600 * scale)))
    if ICON.exists():
        try:
            root.iconphoto(True, tk.PhotoImage(file=str(ICON)))
        except tk.TclError:
            pass
    App(root, files)
    root.mainloop()
