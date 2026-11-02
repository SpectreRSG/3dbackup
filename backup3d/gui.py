"""The window version of the tool, built with tkinter (comes with Python).

The window has three screens and only shows one at a time:

    Home     two big choices: "Back up" or "Open a backup"
    Backup   scans the computer, lists what was found, one "Save" button
    Viewer   profiles on the left, their settings on the right,
             one "Restore" button

Colours, fonts and spacing are all set in one place (_setup_style) so the
look is easy to change.
"""

from __future__ import annotations

import datetime as _dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .backup import (CAT_APP, CAT_FILAMENT, CAT_HOST, CAT_OTHER, CAT_PRINT,
                     CAT_PRINTER, CAT_RESIN, CAT_RESIN_PRINT, CAT_SNAPSHOT,
                     CAT_VENDOR, FILE_EXTENSION, Backup, BackupError,
                     create_backup, default_backup_name, restore, restore_target)
from .detect import Scanner
from .settings import parse, profile_name

APP_TITLE = "3D Print Backup"

# ----------------------------------------------------------------------
# Colours (change these to re-theme the whole program)
# ----------------------------------------------------------------------
BG = "#f5f6f8"          # window background
SURFACE = "#ffffff"     # cards, lists, tables
BORDER = "#e2e5e9"      # thin lines
TEXT = "#1f2328"        # normal text
MUTED = "#6b7280"       # grey helper text
ACCENT = "#2563eb"      # blue buttons and highlights
ACCENT_DARK = "#1d4ed8"
ACCENT_SOFT = "#e8effd"  # light blue (selected rows, icon circles)
SUCCESS = "#16a34a"
SUCCESS_SOFT = "#dcfce7"
ORANGE = ("#ffaa3c", "#e6781e", "#be5a14")   # the cube logo

# How each category is counted in plain words: (one, many)
NOUNS = {
    CAT_PRINTER: ("printer", "printers"),
    CAT_FILAMENT: ("filament", "filaments"),
    CAT_RESIN: ("resin", "resins"),
    CAT_PRINT: ("print profile", "print profiles"),
    CAT_RESIN_PRINT: ("resin print profile", "resin print profiles"),
    CAT_HOST: ("config file", "config files"),
    CAT_APP: ("settings file", "settings files"),
    CAT_VENDOR: ("vendor profile", "vendor profiles"),
    CAT_SNAPSHOT: ("snapshot", "snapshots"),
    CAT_OTHER: ("other file", "other files"),
}


def summarize(app) -> str:
    """'2 printers · 14 filaments · 5 print profiles'"""
    parts = []
    for cat, files in app.categories().items():
        one, many = NOUNS.get(cat, ("file", "files"))
        parts.append(f"{len(files)} {one if len(files) == 1 else many}")
    return " · ".join(parts)


def nice_date(iso: str) -> str:
    try:
        d = _dt.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso or "?"
    return f"{d.day} {d:%b %Y}, {d:%H:%M}"


def _enable_sharp_text():
    """On Windows, ask for sharp (not blurry) text on high-resolution screens."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:   # noqa: BLE001 - older Windows: just carry on
            pass


class App(tk.Tk):
    def __init__(self, scanner: Scanner | None = None):
        _enable_sharp_text()
        super().__init__()
        self.scanner = scanner or Scanner()
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self._jobs = queue.Queue()
        self.screen = None          # the frame currently shown
        self.backup = None          # the backup being viewed or made

        self.title(APP_TITLE)
        self.configure(background=BG)
        self._set_icon()
        self._setup_style()
        w, h = self.px(980), self.px(640)
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(self.px(760), self.px(500))
        self.bind_all("<Control-o>", lambda e: self.open_backup())
        self.after(100, self._poll_jobs)
        self.show_home()

    def px(self, n) -> int:
        """Scale a size in pixels for high-resolution screens."""
        return int(n * self.scale)

    # ------------------------------------------------------------------
    # Look and feel
    # ------------------------------------------------------------------
    def _set_icon(self):
        """Inside the .exe the icon is unpacked to sys._MEIPASS; when run
        from source it's in the packaging folder."""
        here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "packaging"))
        icon = here / "icon.ico"
        try:
            if icon.exists() and sys.platform.startswith("win"):
                self.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    def _setup_style(self):
        families = set(tkfont.families(self))
        family = next((f for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter",
                                   "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans")
                       if f in families), "TkDefaultFont")
        mono = next((f for f in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                                 "DejaVu Sans Mono") if f in families), "TkFixedFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        self.f_body = (family, 10)
        self.f_small = (family, 9)
        self.f_bold = (family, 10, "bold")
        self.f_small_bold = (family, 9, "bold")
        self.f_h2 = (family, 14, "bold")
        self.f_title = (family, 22, "bold")
        self.f_mono = (mono, 10)
        px = self.px

        s = ttk.Style(self)
        s.theme_use("clam")    # the most customisable built-in theme
        s.configure(".", background=BG, foreground=TEXT, font=self.f_body,
                    borderwidth=0, focuscolor=BG)
        s.configure("TFrame", background=BG)
        s.configure("Surface.TFrame", background=SURFACE)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Title.TLabel", font=self.f_title)
        s.configure("H2.TLabel", font=self.f_h2)
        s.configure("Bold.TLabel", font=self.f_bold)

        # Buttons: blue "primary", white "secondary", text-only "link"
        s.configure("Primary.TButton", background=ACCENT, foreground="white",
                    font=self.f_bold, padding=(px(18), px(8)), bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, relief="flat")
        s.map("Primary.TButton",
              background=[("disabled", "#a9b8d6"), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
              bordercolor=[("disabled", "#a9b8d6"), ("active", ACCENT_DARK)],
              lightcolor=[("disabled", "#a9b8d6"), ("active", ACCENT_DARK)],
              darkcolor=[("disabled", "#a9b8d6"), ("active", ACCENT_DARK)],
              foreground=[("disabled", "white")])
        s.configure("Secondary.TButton", background=SURFACE, foreground=TEXT,
                    padding=(px(16), px(7)), bordercolor=BORDER, lightcolor=SURFACE,
                    darkcolor=SURFACE, relief="solid", borderwidth=1)
        s.map("Secondary.TButton", background=[("active", "#f0f2f5")],
              lightcolor=[("active", "#f0f2f5")], darkcolor=[("active", "#f0f2f5")])
        s.configure("Link.TButton", background=BG, foreground=ACCENT,
                    padding=(px(4), px(4)), relief="flat")
        s.map("Link.TButton", background=[("active", BG)],
              foreground=[("active", ACCENT_DARK)])

        # Lists and tables: white, no borders, roomy rows
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, rowheight=px(30), indent=px(16), borderwidth=0)
        s.map("Treeview", background=[("selected", ACCENT_SOFT)],
              foreground=[("selected", TEXT)])
        s.configure("Treeview.Heading", background=SURFACE, foreground=MUTED,
                    font=self.f_small_bold, relief="flat", borderwidth=0,
                    padding=(px(8), px(8)))
        s.map("Treeview.Heading", background=[("active", SURFACE)])

        s.configure("Search.TEntry", fieldbackground=SURFACE, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(px(10), px(6)),
                    insertcolor=TEXT)
        s.map("Search.TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)])
        s.configure("Placeholder.Search.TEntry", foreground=MUTED)

        # Slim scrollbars without arrow buttons
        for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
            s.layout(f"{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {
                "sticky": sticky,
                "children": [(f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            s.configure(f"{orient}.TScrollbar", troughcolor=SURFACE, background="#cfd4da",
                        bordercolor=SURFACE, lightcolor="#cfd4da", darkcolor="#cfd4da",
                        gripcount=0, arrowsize=px(8))
            s.map(f"{orient}.TScrollbar", background=[("active", "#b5bcc5")])
        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BORDER,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT,
                    thickness=px(4))

    # ------------------------------------------------------------------
    # Small building blocks
    # ------------------------------------------------------------------
    def _new_screen(self, top_bar_back=None):
        """Remove the old screen and return a fresh, empty one."""
        if self.screen is not None:
            self.screen.destroy()
        self.screen = ttk.Frame(self)
        self.screen.pack(fill="both", expand=True)
        if top_bar_back:
            bar = ttk.Frame(self.screen, padding=(self.px(12), self.px(10), self.px(16), 0))
            bar.pack(fill="x")
            ttk.Button(bar, text="‹  Home", style="Link.TButton",
                       command=top_bar_back).pack(side="left")
            self.top_bar = bar
        return self.screen

    def _scrolled_tree(self, parent, **kw):
        frame = ttk.Frame(parent, style="Surface.TFrame")
        tree = ttk.Treeview(frame, **kw)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return frame, tree

    def _card(self, parent, icon, title, text, command):
        """A big clickable tile with an icon, a title and one line of help."""
        px = self.px
        card = tk.Frame(parent, background=SURFACE, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=ACCENT,
                        cursor="hand2", takefocus=1, padx=px(22), pady=px(20))
        canvas = tk.Canvas(card, width=px(44), height=px(44), background=SURFACE,
                           highlightthickness=0)
        self._draw_icon(canvas, icon, px(44))
        canvas.pack(anchor="w")
        t = tk.Label(card, text=title, font=self.f_h2, background=SURFACE, foreground=TEXT)
        t.pack(anchor="w", pady=(px(12), px(2)))
        d = tk.Label(card, text=text, font=self.f_body, background=SURFACE, foreground=MUTED,
                     justify="left", wraplength=px(230))
        d.pack(anchor="w")

        def hover(on):
            card.configure(highlightbackground=ACCENT if on else BORDER)
        for w in (card, canvas, t, d):
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
            w.bind("<Button-1>", lambda e: command())
        card.bind("<Return>", lambda e: command())
        card.bind("<space>", lambda e: command())
        return card

    def _draw_icon(self, c, kind, size):
        s = size / 44
        c.create_oval(0, 0, size, size, fill=SUCCESS_SOFT if kind == "check" else ACCENT_SOFT,
                      outline="")
        line = dict(fill=SUCCESS if kind == "check" else ACCENT, width=max(2, 2.4 * s),
                    capstyle="round", joinstyle="round")
        if kind == "backup":       # arrow down into a tray
            c.create_line(22 * s, 11 * s, 22 * s, 26 * s, **line)
            c.create_line(16 * s, 20 * s, 22 * s, 26 * s, 28 * s, 20 * s, **line)
            c.create_line(13 * s, 26 * s, 13 * s, 32 * s, 31 * s, 32 * s, 31 * s, 26 * s, **line)
        elif kind == "open":       # a page with lines of text
            c.create_line(15 * s, 11 * s, 25 * s, 11 * s, 30 * s, 16 * s, 30 * s, 33 * s,
                          15 * s, 33 * s, 15 * s, 11 * s, **line)
            for y in (20, 25):
                c.create_line(19 * s, y * s, 26 * s, y * s, **line)
        elif kind == "check":
            c.create_line(13 * s, 23 * s, 19 * s, 29 * s, 31 * s, 16 * s, **line)

    def _draw_logo(self, c, size):
        """The orange cube."""
        cx, cy, r = size / 2, size / 2 - size * 0.02, size * 0.42
        w = r * 0.87
        top = [cx, cy - r, cx + w, cy - r / 2, cx, cy, cx - w, cy - r / 2]
        left = [cx - w, cy - r / 2, cx, cy, cx, cy + r, cx - w, cy + r / 2]
        right = [cx, cy, cx + w, cy - r / 2, cx + w, cy + r / 2, cx, cy + r]
        for pts, col in ((top, ORANGE[0]), (left, ORANGE[1]), (right, ORANGE[2])):
            c.create_polygon(pts, fill=col, outline=col)

    def toast(self, text, error=False):
        """A small message that pops up at the bottom and fades away."""
        label = tk.Label(self, text=text, font=self.f_body, foreground="white",
                         background="#b91c1c" if error else TEXT,
                         padx=self.px(16), pady=self.px(8))
        label.place(relx=0.5, rely=1.0, y=-self.px(20), anchor="s")
        self.after(4000, label.destroy)

    # ------------------------------------------------------------------
    # Background work (so the window doesn't freeze while reading files)
    # ------------------------------------------------------------------
    def _run_background(self, work, done):
        def runner():
            try:
                result, error = work(), None
            except Exception as exc:   # noqa: BLE001 - shown to the user
                result, error = None, exc
            self._jobs.put((done, result, error))
        threading.Thread(target=runner, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                item = self._jobs.get_nowait()
                if callable(item):        # a progress update
                    item()
                    continue
                done, result, error = item
                if error:
                    messagebox.showerror(APP_TITLE, str(error), parent=self)
                    self.show_home()
                else:
                    done(result)
        except queue.Empty:
            pass
        self.after(100, self._poll_jobs)

    # ------------------------------------------------------------------
    # Screen 1: Home
    # ------------------------------------------------------------------
    def show_home(self):
        px = self.px
        screen = self._new_screen()
        box = ttk.Frame(screen)
        box.place(relx=0.5, rely=0.46, anchor="center")

        logo = tk.Canvas(box, width=px(64), height=px(64), background=BG, highlightthickness=0)
        self._draw_logo(logo, px(64))
        logo.pack()
        ttk.Label(box, text=APP_TITLE, style="Title.TLabel").pack(pady=(px(10), px(2)))
        ttk.Label(box, text="Keep your printer, filament and slicer settings safe in one file.",
                  style="Muted.TLabel").pack()

        cards = ttk.Frame(box)
        cards.pack(pady=(px(30), 0))
        self._card(cards, "backup", "Back up",
                   "Find your 3D printing programs and save all their settings.",
                   self.start_backup).pack(side="left", padx=px(8))
        self._card(cards, "open", "Open a backup",
                   "See what's inside a backup and put settings back.",
                   self.open_backup).pack(side="left", padx=px(8))

        ttk.Label(screen, text=f"Version {__version__}", style="Muted.TLabel",
                  font=self.f_small).place(relx=0.5, rely=1.0, y=-px(14), anchor="s")

    # ------------------------------------------------------------------
    # Screen 2: Back up
    # ------------------------------------------------------------------
    def start_backup(self):
        px = self.px
        screen = self._new_screen(top_bar_back=self.show_home)
        box = ttk.Frame(screen)
        box.place(relx=0.5, rely=0.42, anchor="center")
        ttk.Label(box, text="Looking for your 3D printing programs…",
                  style="H2.TLabel").pack()
        bar = ttk.Progressbar(box, mode="indeterminate", length=px(320))
        bar.pack(pady=px(16))
        bar.start(12)
        status = ttk.Label(box, text="", style="Muted.TLabel", font=self.f_small,
                           width=60, anchor="center")
        status.pack()

        def progress(msg):
            def update():
                if status.winfo_exists():
                    name = msg.replace("Reading ", "").split(" settings in ")[0]
                    status.configure(text=name)
            self._jobs.put(update)

        self._run_background(lambda: create_backup(self.scanner, progress=progress),
                             self._show_found)

    def _show_found(self, bk: Backup):
        px = self.px
        self.backup = bk
        screen = self._new_screen(top_bar_back=self.show_home)
        if not bk.apps:
            box = ttk.Frame(screen)
            box.place(relx=0.5, rely=0.42, anchor="center")
            ttk.Label(box, text="No 3D printing settings found", style="H2.TLabel").pack()
            ttk.Label(box, style="Muted.TLabel", justify="center",
                      text="None of the supported slicers or modelling programs\n"
                           "have saved settings on this computer yet.").pack(pady=px(8))
            ttk.Button(box, text="Back", style="Secondary.TButton",
                       command=self.show_home).pack(pady=px(10))
            return

        body = ttk.Frame(screen, padding=(px(32), px(8), px(32), px(24)))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Found on this computer", style="H2.TLabel").pack(anchor="w")
        ttk.Label(body, style="Muted.TLabel",
                  text=f"{bk.file_count} settings files from {len(bk.apps)} "
                       f"program{'s' if len(bk.apps) != 1 else ''} will be saved.").pack(
            anchor="w", pady=(px(2), px(14)))

        footer = ttk.Frame(body)
        footer.pack(side="bottom", fill="x", pady=(px(16), 0))
        ttk.Button(footer, text="Save backup…", style="Primary.TButton",
                   command=self._save_backup).pack(side="right")

        # A read-only text box makes a tidy list: bold name, grey summary.
        listing = tk.Text(body, font=self.f_body, background=SURFACE, foreground=MUTED,
                          relief="flat", borderwidth=0, highlightthickness=0,
                          padx=px(20), pady=px(14), cursor="arrow", wrap="none",
                          tabs=(px(250),), spacing1=px(6), spacing3=px(6))
        listing.tag_configure("check", foreground=SUCCESS, font=self.f_bold)
        listing.tag_configure("name", foreground=TEXT, font=self.f_bold)
        for app in bk.apps:
            listing.insert("end", "✓  ", "check")
            listing.insert("end", app.name, "name")
            listing.insert("end", f"\t{summarize(app)}\n")
        listing.configure(state="disabled")
        listing.pack(fill="both", expand=True)

    def _save_backup(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Save backup", initialfile=default_backup_name(),
            initialdir=str(Path.home() / "Documents") if (Path.home() / "Documents").is_dir() else None,
            defaultextension=FILE_EXTENSION,
            filetypes=[("3D Print Backup", f"*{FILE_EXTENSION}")])
        if not path:
            return
        try:
            saved = self.backup.save(path)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not save the backup:\n\n{exc}", parent=self)
            return
        self._show_saved(saved)

    def _show_saved(self, saved: Path):
        px = self.px
        screen = self._new_screen(top_bar_back=self.show_home)
        box = ttk.Frame(screen)
        box.place(relx=0.5, rely=0.42, anchor="center")
        check = tk.Canvas(box, width=px(56), height=px(56), background=BG, highlightthickness=0)
        self._draw_icon(check, "check", px(56))
        check.pack()
        ttk.Label(box, text="Backup saved", style="H2.TLabel").pack(pady=(px(12), px(4)))
        ttk.Label(box, text=str(saved), style="Muted.TLabel").pack()
        ttk.Label(box, style="Muted.TLabel", font=self.f_small, justify="center",
                  text="Keep a copy somewhere safe, like a USB stick or cloud drive.\n"
                       "It may contain printer passwords, so keep it private.").pack(pady=px(14))
        row = ttk.Frame(box)
        row.pack(pady=px(4))
        ttk.Button(row, text="Show in folder", style="Secondary.TButton",
                   command=lambda: _show_in_folder(saved)).pack(side="left", padx=px(4))
        ttk.Button(row, text="Done", style="Primary.TButton",
                   command=self.show_home).pack(side="left", padx=px(4))

    # ------------------------------------------------------------------
    # Screen 3: Viewer
    # ------------------------------------------------------------------
    def open_backup(self, path=None):
        path = path or filedialog.askopenfilename(
            parent=self, title="Open a backup",
            filetypes=[("3D Print Backup", f"*{FILE_EXTENSION}"), ("All files", "*")])
        if not path:
            return
        try:
            bk = Backup.load(path)
        except (BackupError, OSError) as exc:
            messagebox.showerror(APP_TITLE, f"Could not open this backup.\n\n{exc}", parent=self)
            return
        self.show_viewer(bk)
        damaged = sum(1 for a in bk.apps for f in a.files if not f.is_intact())
        if damaged:
            self.toast(f"{damaged} file(s) in this backup are damaged and can't be restored.",
                       error=True)

    def show_viewer(self, bk: Backup):
        px = self.px
        self.backup = bk
        self.items = {}         # tree row id -> (app, file or None)
        self.rows = []
        screen = self._new_screen(top_bar_back=self.show_home)

        # Top bar: which backup + the one action
        info = ttk.Frame(self.top_bar)
        info.pack(side="left", padx=(px(12), 0))
        ttk.Label(info, text=Path(bk.source).name, style="Bold.TLabel").pack(anchor="w")
        ttk.Label(info, style="Muted.TLabel", font=self.f_small,
                  text=f"Made {nice_date(bk.created)} on {bk.computer} · "
                       f"{bk.file_count} files").pack(anchor="w")
        self.restore_btn = ttk.Button(self.top_bar, text="Restore all…",
                                      style="Primary.TButton", command=self._restore)
        self.restore_btn.pack(side="right")

        panes = tk.PanedWindow(screen, orient="horizontal", sashwidth=px(6), background=BG,
                               borderwidth=0, showhandle=False)
        panes.pack(fill="both", expand=True, padx=px(16), pady=px(12))

        # Left: programs > categories > profiles
        left, self.tree = self._scrolled_tree(panes, show="tree", selectmode="browse")
        left.configure(padding=(px(6), px(8)))
        self.tree.tag_configure("app", font=self.f_bold)
        self.tree.tag_configure("cat", font=self.f_small_bold, foreground=MUTED)
        for i, app in enumerate(bk.apps):
            app_id = self.tree.insert("", "end", text=app.name, open=(i == 0), tags=("app",))
            self.items[app_id] = (app, None)
            for cat, files in app.categories().items():
                cat_id = self.tree.insert(app_id, "end", text=cat.upper(), open=True,
                                          tags=("cat",))
                self.items[cat_id] = (app, None)
                names = [profile_name(f.path) for f in files]
                for f, name in zip(files, names):
                    if names.count(name) > 1:      # same name twice: show the file type
                        name = f"{name}  ({f.name[len(name):].lstrip('.')})"
                    fid = self.tree.insert(cat_id, "end", text=name)
                    self.items[fid] = (app, f)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        panes.add(left, minsize=px(220), width=px(300))

        # Right: details of what is selected
        right = ttk.Frame(panes, padding=(px(14), 0, 0, 0))
        panes.add(right, minsize=px(300))
        self.heading = ttk.Label(right, style="H2.TLabel")
        self.heading.pack(anchor="w")
        self.subheading = ttk.Label(right, style="Muted.TLabel", font=self.f_small)
        self.subheading.pack(anchor="w", pady=(0, px(10)))

        self.search_var = tk.StringVar()
        self.search = ttk.Entry(right, textvariable=self.search_var, style="Search.TEntry")
        self._placeholder(self.search, self.search_var, "Search settings")
        self.search_var.trace_add("write", lambda *a: self._fill_table())
        self.bind_all("<Control-f>", lambda e: self.search.focus_set())

        self.body = ttk.Frame(right)          # holds the table OR the text view
        self.body.pack(fill="both", expand=True, pady=(px(8), 0))
        self.table_frame, self.table = self._scrolled_tree(
            self.body, columns=("setting", "value"), show="headings", selectmode="browse")
        self.table.heading("setting", text="SETTING", anchor="w")
        self.table.heading("value", text="VALUE", anchor="w")
        self.table.column("setting", width=px(240), stretch=False)
        self.table.column("value", width=px(360))
        self.table.bind("<<TreeviewSelect>>", lambda e: self._show_full_value())

        self.text = tk.Text(self.body, wrap="none", font=self.f_mono, background=SURFACE,
                            foreground=TEXT, relief="flat", padx=px(12), pady=px(10),
                            highlightthickness=0, borderwidth=0)
        self.detail = tk.Text(right, height=6, wrap="word", font=self.f_mono,
                              background=SURFACE, foreground=TEXT, relief="flat",
                              padx=px(12), pady=px(8), highlightthickness=1,
                              highlightbackground=BORDER, borderwidth=0)
        self.empty = ttk.Label(self.body, style="Muted.TLabel", anchor="center",
                               justify="center")

        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])
        else:
            self._show_empty("This backup is empty.")

    def _placeholder(self, entry, var, text):
        """Grey hint text inside a box that disappears when you click in it."""
        entry._placeholder_on = False

        def show(_=None):
            if not var.get():
                entry._placeholder_on = True
                entry.configure(style="Placeholder.Search.TEntry")
                var.set(text)

        def hide(_=None):
            if entry._placeholder_on:
                entry._placeholder_on = False
                var.set("")
                entry.configure(style="Search.TEntry")

        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        show()

    def _search_term(self) -> str:
        return "" if getattr(self.search, "_placeholder_on", False) else self.search_var.get().strip().lower()

    def _selection(self):
        sel = self.tree.selection()
        return self.items.get(sel[0], (None, None)) if sel else (None, None)

    def _on_select(self):
        app, f = self._selection()
        if f:
            self.restore_btn.configure(text="Restore this profile…")
            self._show_file(app, f)
        elif app:
            self.restore_btn.configure(text=f"Restore {app.name}…")
            self._show_app(app)

    def _show_app(self, app):
        self.heading.configure(text=app.name)
        self.subheading.configure(text=summarize(app))
        self.search.pack_forget()
        where = app.location
        msg = (f"Pick a profile on the left to see its settings.\n\n"
               f"Saved from: {where}")
        if app.note:
            msg += f"\n\n{app.note}"
        self._show_empty(msg)

    def _show_file(self, app, f):
        what = NOUNS.get(f.category, ("file",))[0]
        self.heading.configure(text=profile_name(f.path))
        self.subheading.configure(
            text=f"{app.name} · {what} · last changed {nice_date(f.modified)}")
        text = f.text()
        rows = parse(f.name, text) if text is not None else None
        if rows:
            self.search.pack(fill="x", before=self.body)
            self.rows = rows
            self._fill_table()
            self._show_widget(self.table_frame)
        elif text is not None:
            self.search.pack_forget()
            self._set_text(self.text, text)
            self._show_widget(self.text)
        else:
            self.search.pack_forget()
            self._show_empty("This file isn't text, so it can't be shown here.\n"
                             "It will still be restored exactly as it was.")

    def _show_widget(self, widget):
        for w in (self.table_frame, self.text, self.empty):
            if w is not widget:
                w.pack_forget()
        self.detail.pack_forget()
        widget.pack(fill="both", expand=True)

    def _show_empty(self, message):
        self.empty.configure(text=message, wraplength=self.px(420))
        self._show_widget(self.empty)

    def _fill_table(self):
        if not hasattr(self, "table"):
            return
        self.table.delete(*self.table.get_children())
        self.detail.pack_forget()
        term = self._search_term()
        for i, (k, v) in enumerate(self.rows):
            if term and term not in k.lower() and term not in v.lower():
                continue
            one_line = v.replace("\r", "").replace("\n", "  ⏎  ")
            if len(one_line) > 200:
                one_line = one_line[:200] + " …"
            self.table.insert("", "end", iid=str(i), values=(k, one_line))

    def _show_full_value(self):
        """Long values (like start G-code) are shown in full under the table."""
        sel = self.table.selection()
        if not sel:
            return
        _, value = self.rows[int(sel[0])]
        if "\n" in value or len(value) > 70:
            self._set_text(self.detail, value.replace("\r", ""))
            self.detail.pack(fill="x", pady=(self.px(8), 0))
        else:
            self.detail.pack_forget()

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # Restoring
    # ------------------------------------------------------------------
    def _restore(self):
        bk = self.backup
        app, f = self._selection()
        apps = [app] if app else bk.apps
        if f:
            title, count = f"Restore “{profile_name(f.path)}”?", 1
        elif app:
            title, count = f"Restore {app.name}?", len(app.files)
        else:
            title, count = "Restore everything?", bk.file_count
        places = []
        for a in apps:
            try:
                places.append(str(restore_target(a, self.scanner, bk.os)))
            except BackupError:
                places.append(f"{a.name}: unknown on this computer")
        names = " and ".join(sorted({a.name.split(" (")[0] for a in apps})[:3])
        body = (f"This puts {count} file{'s' if count != 1 else ''} back into:\n"
                + "\n".join(places[:4]) + ("\n…" if len(places) > 4 else "")
                + f"\n\nClose {names} first. Any file that gets replaced is kept as a copy.")
        choice = RestoreDialog(self, title, body).result
        if not choice:
            return
        to_folder = None
        if choice == "folder":
            to_folder = filedialog.askdirectory(parent=self, title="Choose a folder")
            if not to_folder:
                return
        indexes = {bk.apps.index(a) for a in apps}
        file_filter = (lambda a, x: x is f) if f else None
        self.restore_btn.configure(state="disabled")

        def done(results):
            self.restore_btn.configure(state="normal")
            bad = sum(1 for _, s in results if s.startswith("SKIPPED"))
            msg = f"✓  Restored {len(results) - bad} file{'s' if len(results) - bad != 1 else ''}"
            if to_folder:
                msg += " to the folder"
            if bad:
                msg += f" · {bad} damaged file(s) skipped"
            self.toast(msg, error=bool(bad))

        self._run_background(lambda: restore(bk, self.scanner, app_indexes=indexes,
                                             to_folder=to_folder, file_filter=file_filter),
                             done)


class RestoreDialog(tk.Toplevel):
    """A small pop-up: Cancel / Save to a folder instead / Restore.
    After it closes, .result is None, "folder" or "restore"."""

    def __init__(self, app: App, title, body):
        super().__init__(app)
        self.result = None
        px = app.px
        self.title(APP_TITLE)
        self.configure(background=BG)
        self.resizable(False, False)
        self.transient(app)
        box = ttk.Frame(self, padding=(px(24), px(20), px(24), px(18)))
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=title, style="H2.TLabel").pack(anchor="w")
        ttk.Label(box, text=body, style="Muted.TLabel", justify="left",
                  wraplength=px(460)).pack(anchor="w", pady=(px(8), px(20)))
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Button(row, text="Restore", style="Primary.TButton",
                   command=lambda: self._close("restore")).pack(side="right")
        ttk.Button(row, text="Save to a folder instead", style="Secondary.TButton",
                   command=lambda: self._close("folder")).pack(side="right", padx=px(8))
        ttk.Button(row, text="Cancel", style="Link.TButton",
                   command=lambda: self._close(None)).pack(side="left")
        self.bind("<Escape>", lambda e: self._close(None))
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_set()
        self.wait_window()

    def _close(self, result):
        self.result = result
        self.destroy()


def _show_in_folder(path: Path):
    """Open the file manager with the backup file selected."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def run(file=None, scanner=None):
    app = App(scanner)
    if file:
        app.after(50, lambda: app.open_backup(file))
    app.mainloop()
