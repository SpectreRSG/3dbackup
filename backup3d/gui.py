"""The window version of the tool, built with tkinter (comes with Python).

Layout:
    +-------------------------------------------------------------+
    | [Scan] [Create backup] [Open backup] [Restore] [Export file] |
    | Viewing: ...                                                 |
    +--------------------+----------------------------------------+
    | Program            | Settings | Raw file                    |
    |  > Category        |  setting          value                |
    |     > file         |  ...                                   |
    +--------------------+----------------------------------------+
    | status bar                                                  |
    +-------------------------------------------------------------+
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .backup import (FILE_EXTENSION, Backup, BackupError, create_backup,
                     default_backup_name, describe_os, restore, restore_target)
from .detect import Scanner
from .settings import parse, profile_name

APP_TITLE = "3D Print Backup"


class App(tk.Tk):
    def __init__(self, scanner: Scanner | None = None):
        super().__init__()
        self.scanner = scanner or Scanner()
        self.backup: Backup | None = None      # what is shown right now
        self.is_live = False                   # True = a scan, False = a file
        self.items = {}                        # tree id -> (app, file)
        self.rows = []                         # rows in the settings table
        self._jobs = queue.Queue()

        self.title(APP_TITLE)
        self._set_icon()
        self.geometry("1150x720")
        self.minsize(760, 480)
        self._build()
        self.after(100, self._poll_jobs)

    def _set_icon(self):
        """Use our icon in the title bar. Inside the .exe it is unpacked to a
        temporary folder (sys._MEIPASS); when run from source it's in packaging/."""
        import sys
        here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "packaging"))
        icon = here / "icon.ico"
        try:
            if icon.exists() and sys.platform.startswith("win"):
                self.iconbitmap(default=str(icon))
        except tk.TclError:
            pass   # not important - just keep the standard icon

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------
    def _build(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names() and self.tk.call("tk", "windowingsystem") == "x11":
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("TkDefaultFont", 11, "bold"))

        bar = ttk.Frame(self, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        self.btn_scan = ttk.Button(bar, text="🔍  Scan this computer", command=self.scan)
        self.btn_backup = ttk.Button(bar, text="💾  Create backup…", command=self.make_backup)
        self.btn_open = ttk.Button(bar, text="📂  Open backup…", command=self.open_backup)
        self.btn_restore = ttk.Button(bar, text="↩  Restore…", command=self.restore_selected)
        self.btn_export = ttk.Button(bar, text="📤  Save file as…", command=self.export_file)
        for b in (self.btn_scan, self.btn_backup, self.btn_open, self.btn_restore, self.btn_export):
            b.pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="?", width=3, command=self.show_help).pack(side="right")

        self.header = ttk.Label(self, style="Title.TLabel", padding=(10, 2))
        self.header.pack(fill="x")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=4)

        # Left: the tree of programs, categories and files
        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.column("#0", width=340, minwidth=200)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected())
        panes.add(left, weight=1)

        # Right: details about whatever is selected
        right = ttk.Frame(panes)
        self.info = ttk.Label(right, padding=(6, 4), justify="left", anchor="w")
        self.info.pack(fill="x")
        # wrap long lines to the width of the panel
        self.info.bind("<Configure>", lambda e: self.info.configure(wraplength=e.width - 12))
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)

        table_tab = ttk.Frame(self.notebook)
        search_row = ttk.Frame(table_tab, padding=(0, 4))
        search_row.pack(fill="x")
        ttk.Label(search_row, text="Search settings:").pack(side="left", padx=(4, 4))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self._fill_table())
        ttk.Entry(search_row, textvariable=self.search).pack(side="left", fill="x", expand=True)
        self.count_label = ttk.Label(search_row, padding=(8, 0))
        self.count_label.pack(side="right")

        table_frame = ttk.Frame(table_tab)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("setting", "value"), show="headings")
        self.table.heading("setting", text="Setting")
        self.table.heading("value", text="Value")
        self.table.column("setting", width=280, stretch=False)
        self.table.column("value", width=500)
        tsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=tsb.set)
        self.table.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", lambda e: self._show_row())

        self.value_box = tk.Text(table_tab, height=5, wrap="word", relief="flat",
                                 background=self.cget("background"))
        self.value_box.pack(fill="x", pady=(4, 0))
        self._set_text(self.value_box, "Click a setting to see its full value here.")
        self.notebook.add(table_tab, text="Settings")

        raw_tab = ttk.Frame(self.notebook)
        self.raw = tk.Text(raw_tab, wrap="none", font=("TkFixedFont", 10))
        rsb_y = ttk.Scrollbar(raw_tab, orient="vertical", command=self.raw.yview)
        rsb_x = ttk.Scrollbar(raw_tab, orient="horizontal", command=self.raw.xview)
        self.raw.configure(yscrollcommand=rsb_y.set, xscrollcommand=rsb_x.set)
        rsb_y.pack(side="right", fill="y")
        rsb_x.pack(side="bottom", fill="x")
        self.raw.pack(fill="both", expand=True)
        self.notebook.add(raw_tab, text="Raw file")
        panes.add(right, weight=3)

        self.status = ttk.Label(self, relief="sunken", anchor="w", padding=(6, 2))
        self.status.pack(fill="x", side="bottom")
        self._update_buttons()

    # ------------------------------------------------------------------
    # Background work (so the window doesn't freeze while reading files)
    # ------------------------------------------------------------------
    def _run_background(self, work, done, busy_text):
        self._set_busy(True, busy_text)

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
                if callable(item):           # progress message
                    item()
                    continue
                done, result, error = item
                self._set_busy(False)
                if error:
                    messagebox.showerror(APP_TITLE, str(error), parent=self)
                    self.set_status("Something went wrong.")
                else:
                    done(result)
        except queue.Empty:
            pass
        self.after(100, self._poll_jobs)

    def _progress(self, msg):
        self._jobs.put(lambda: self.set_status(msg))

    def _set_busy(self, busy, text=""):
        state = "disabled" if busy else "normal"
        for b in (self.btn_scan, self.btn_backup, self.btn_open):
            b.configure(state=state)
        self.configure(cursor="watch" if busy else "")
        if busy:
            self.set_status(text)
        self._update_buttons(busy)

    def _update_buttons(self, busy=False):
        app, f = self._selection()
        can_restore = not busy and self.backup is not None and not self.is_live
        self.btn_restore.configure(state="normal" if can_restore else "disabled")
        self.btn_export.configure(state="normal" if (f and not busy) else "disabled")

    def set_status(self, text):
        self.status.configure(text=text)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def scan(self, then=None):
        def done(bk):
            self.show_backup(bk, live=True)
            n = len(bk.apps)
            self.set_status(f"Found settings for {n} program folder(s), "
                            f"{bk.file_count} files. Click 'Create backup' to save them.")
            if then:
                then()
        self._run_background(lambda: create_backup(self.scanner, progress=self._progress),
                             done, "Scanning this computer for 3D printing programs…")

    def make_backup(self):
        if self.backup is None or not self.is_live:
            # Show the live scan first, then ask where to save.
            return self.scan(then=self.make_backup)
        if not self.backup.apps:
            messagebox.showinfo(APP_TITLE, "No 3D printing settings were found on this "
                                "computer, so there is nothing to back up.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save backup as", initialfile=default_backup_name(),
            defaultextension=FILE_EXTENSION,
            filetypes=[("3D Print Backup", f"*{FILE_EXTENSION}"), ("All files", "*")])
        if not path:
            return
        saved = self.backup.save(path)
        self.set_status(f"Backup saved to {saved}")
        messagebox.showinfo(
            APP_TITLE,
            f"Backup saved!\n\n{saved}\n\n{self.backup.file_count} files from "
            f"{len(self.backup.apps)} program folder(s).\n\nCopy it somewhere safe "
            "(USB stick, cloud drive...). It may contain printer passwords or API "
            "keys, so keep it private.", parent=self)

    def open_backup(self, path=None):
        path = path or filedialog.askopenfilename(
            parent=self, title="Open a backup",
            filetypes=[("3D Print Backup", f"*{FILE_EXTENSION}"), ("All files", "*")])
        if not path:
            return
        try:
            bk = Backup.load(path)
        except (BackupError, OSError) as exc:
            messagebox.showerror(APP_TITLE, f"Could not open the backup:\n\n{exc}", parent=self)
            return
        self.show_backup(bk, live=False)
        damaged = sum(1 for a in bk.apps for f in a.files if not f.is_intact())
        msg = f"Opened {Path(path).name}: {bk.file_count} files."
        if damaged:
            msg += f"  WARNING: {damaged} file(s) are damaged."
        self.set_status(msg)

    def restore_selected(self):
        if not self.backup or self.is_live:
            return
        app, f = self._selection()
        apps = [app] if app else self.backup.apps
        what = (f"the file '{f.path}' from {app.name}" if f
                else f"{app.name} ({len(app.files)} files)" if app
                else f"ALL {len(apps)} programs ({self.backup.file_count} files)")
        lines = []
        for a in apps:
            try:
                lines.append(f"• {a.name} → {restore_target(a, self.scanner, self.backup.os)}")
            except BackupError as exc:
                lines.append(f"• {a.name} → {exc}")
        answer = messagebox.askyesnocancel(
            APP_TITLE,
            f"Restore {what}?\n\n"
            "YES = put them back where the program looks for them:\n"
            + "\n".join(lines[:8]) + ("\n…" if len(lines) > 8 else "") +
            "\n\nPlease CLOSE the programs first. Any file that would be replaced is "
            "kept with '.before-restore' added to its name.\n\n"
            "NO = save them into a folder of your choice instead (just to look at "
            "or copy by hand).", parent=self)
        if answer is None:
            return
        to_folder = None
        if answer is False:
            to_folder = filedialog.askdirectory(parent=self, title="Choose a folder to save into")
            if not to_folder:
                return
        indexes = {self.backup.apps.index(a) for a in apps}
        file_filter = (lambda a, x: x is f) if f else None
        bk = self.backup

        def work():
            return restore(bk, self.scanner, app_indexes=indexes, to_folder=to_folder,
                           file_filter=file_filter, progress=self._progress)

        def done(results):
            bad = [r for r in results if r[1].startswith("SKIPPED")]
            self.set_status(f"Restored {len(results) - len(bad)} file(s).")
            text = f"Finished: {len(results)} file(s) handled."
            if bad:
                text += f"\n\n{len(bad)} file(s) were damaged in the backup and skipped."
            if to_folder:
                text += f"\n\nFiles are in:\n{to_folder}"
            messagebox.showinfo(APP_TITLE, text, parent=self)

        self._run_background(work, done, "Restoring…")

    def export_file(self):
        app, f = self._selection()
        if not f:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Save this file as",
                                            initialfile=f.name)
        if path:
            Path(path).write_bytes(f.data())
            self.set_status(f"Saved {f.name} to {path}")

    def show_help(self):
        messagebox.showinfo(APP_TITLE, (
            f"{APP_TITLE} {__version__}\n\n"
            "1. 'Scan this computer' finds your slicers and modelling programs and "
            "shows their settings.\n\n"
            "2. 'Create backup' saves everything into ONE .3dbackup file. Keep it "
            "somewhere safe.\n\n"
            "3. After reinstalling, 'Open backup' shows everything that was saved. "
            "Click a profile to see its settings, so you can copy them by hand…\n\n"
            "4. …or select a program (or one file) and click 'Restore' to put the "
            "files back automatically."), parent=self)

    # ------------------------------------------------------------------
    # Showing things
    # ------------------------------------------------------------------
    def show_backup(self, bk: Backup, live: bool):
        self.backup, self.is_live = bk, live
        if live:
            self.header.configure(text=f"Viewing: settings found on this computer "
                                       f"({describe_os(bk.os)}) right now")
        else:
            self.header.configure(
                text=f"Viewing backup: {Path(bk.source).name}   •   made "
                     f"{bk.created.replace('T', ' at ')} on '{bk.computer}' "
                     f"({describe_os(bk.os)})")
        self.tree.delete(*self.tree.get_children())
        self.items.clear()
        for app in bk.apps:
            counts = ", ".join(f"{len(v)} {k.split(' /')[0].lower()}"
                               for k, v in list(app.categories().items())[:3])
            app_id = self.tree.insert("", "end", text=f"{app.name}   ({counts})", open=False)
            self.items[app_id] = (app, None)
            for cat, files in app.categories().items():
                cat_id = self.tree.insert(app_id, "end", text=f"{cat} ({len(files)})")
                self.items[cat_id] = (app, None)
                for f in files:
                    fid = self.tree.insert(cat_id, "end", text=profile_name(f.path))
                    self.items[fid] = (app, f)
        if not bk.apps:
            self.tree.insert("", "end", text="(nothing found)")
        self._show_overview()
        self._update_buttons()

    def _selection(self):
        sel = self.tree.selection() if hasattr(self, "tree") else ()
        return self.items.get(sel[0], (None, None)) if sel else (None, None)

    def show_selected(self):
        app, f = self._selection()
        self._update_buttons()
        if f:
            return self._show_file(app, f)
        if app:
            return self._show_app(app)
        self._show_overview()

    def _show_overview(self):
        bk = self.backup
        if not bk:
            self.info.configure(text="")
            return
        self.info.configure(text=f"{len(bk.apps)} program folder(s), {bk.file_count} files. "
                                 "Click a program on the left to see more.")
        rows = []
        for app in bk.apps:
            rows.append((app.name, f"{len(app.files)} files - {app.kind}"))
        self._set_rows(rows)
        self._set_text(self.raw, "")

    def _show_app(self, app):
        status = "installed" if app.installed else "program not found (settings only)"
        self.info.configure(text=f"{app.name}  •  {app.kind}  •  {status}\n"
                                 f"Settings folder: {app.location}"
                                 + (f"\nNote: {app.note}" if app.note else ""))
        rows = []
        for cat, files in app.categories().items():
            for f in files:
                rows.append((f"{cat} › {profile_name(f.path)}", f.path))
        self._set_rows(rows)
        skipped = "\n".join(f"  {s['path']}  ({s['reason']})" for s in app.skipped)
        self._set_text(self.raw, "Left out on purpose (caches, logs, factory profiles…):\n"
                       + (skipped or "  nothing"))

    def _show_file(self, app, f):
        ok = "" if f.is_intact() else "   ⚠ DAMAGED IN BACKUP"
        self.info.configure(text=f"{app.name} › {f.path}{ok}\n"
                                 f"{f.category}  •  {f.size:,} bytes  •  last changed "
                                 f"{f.modified.replace('T', ' ')}")
        text = f.text()
        if text is None:
            self._set_rows([("(binary file)", "This file can't be shown as text, but it "
                                              "will be restored exactly as it was.")])
            self._set_text(self.raw, f"(binary file, {f.size:,} bytes)")
            return
        rows = parse(f.name, text)
        if rows:
            self._set_rows(rows)
            self.notebook.select(0)
        else:
            self._set_rows([("(no table view)", "See the 'Raw file' tab.")])
            self.notebook.select(1)
        self._set_text(self.raw, text)

    def _set_rows(self, rows):
        self.rows = rows
        self._set_text(self.value_box, "Click a setting to see its full value here.")
        self._fill_table()

    def _fill_table(self):
        self.table.delete(*self.table.get_children())
        term = self.search.get().strip().lower()
        shown = 0
        for i, (k, v) in enumerate(self.rows):
            if term and term not in k.lower() and term not in v.lower():
                continue
            one_line = v.replace("\r", "").replace("\n", " ⏎ ")
            if len(one_line) > 300:
                one_line = one_line[:300] + " …"
            self.table.insert("", "end", iid=str(i), values=(k, one_line))
            shown += 1
        self.count_label.configure(
            text=f"{shown} of {len(self.rows)}" if term else f"{len(self.rows)} rows")

    def _show_row(self):
        sel = self.table.selection()
        if sel:
            k, v = self.rows[int(sel[0])]
            self._set_text(self.value_box, f"{k}\n{v.replace(chr(13), '')}")

    @staticmethod
    def _set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")


def run(file=None, scanner=None):
    app = App(scanner)
    if file:
        app.after(50, lambda: app.open_backup(file))
    else:
        app.after(50, app.scan)
    app.mainloop()
