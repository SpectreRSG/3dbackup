"""Create, save, load and restore backup files.

A backup is ONE text file (JSON format) ending in ``.3dbackup``. You can
open it in any text editor. It looks roughly like this::

    {
      "format": "3dbackup",
      "format_version": 1,
      "created": "2026-11-02T20:15:00",
      "computer": "my-pc",
      "os": "windows",
      "apps": [
        {
          "id": "prusaslicer",
          "name": "PrusaSlicer",
          "location": "C:/Users/me/AppData/Roaming/PrusaSlicer",
          "files": [
            {
              "path": "filament/My PETG.ini",
              "category": "Filament / Material",
              "encoding": "text",
              "content": "temperature = 240\\n..."
            }
          ]
        }
      ]
    }

Text files are stored as readable text. The odd binary file (for example
Blender's preferences) is stored as "base64", a way of writing any data
using only letters and numbers.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import platform
import socket
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import FORMAT_NAME, FORMAT_VERSION, __version__
from .apps import APPS_BY_ID, KIND_HOST, KIND_MODELING
from .detect import Scanner, expand

FILE_EXTENSION = ".3dbackup"

# Categories shown in the viewer, in the order they appear.
CAT_PRINTER = "Printers / Machines"
CAT_FILAMENT = "Filament / Material"
CAT_RESIN = "Resin / Material"
CAT_PRINT = "Print / Slice settings"
CAT_RESIN_PRINT = "Resin print settings"
CAT_VENDOR = "Vendor profiles"
CAT_SNAPSHOT = "Snapshots / History"
CAT_APP = "Program preferences"
CAT_HOST = "Printer firmware / host"
CAT_OTHER = "Other files"
CATEGORY_ORDER = [CAT_PRINTER, CAT_FILAMENT, CAT_RESIN, CAT_PRINT, CAT_RESIN_PRINT,
                  CAT_HOST, CAT_APP, CAT_VENDOR, CAT_SNAPSHOT, CAT_OTHER]

# Folder name -> category. Checked from the deepest folder upwards, so
# "user/1234/filament/x.json" is filament, not "user".
_FOLDER_CATEGORIES = {
    "sla_material": CAT_RESIN, "resin": CAT_RESIN, "resins": CAT_RESIN,
    "sla_print": CAT_RESIN_PRINT,
    "filament": CAT_FILAMENT, "filaments": CAT_FILAMENT,
    "material": CAT_FILAMENT, "materials": CAT_FILAMENT,
    "printer": CAT_PRINTER, "printers": CAT_PRINTER, "machine": CAT_PRINTER,
    "machines": CAT_PRINTER, "machine_instances": CAT_PRINTER,
    "physical_printer": CAT_PRINTER, "definition_changes": CAT_PRINTER,
    "extruders": CAT_PRINTER, "variants": CAT_PRINTER, "definitions": CAT_PRINTER,
    "printerprofiles": CAT_PRINTER,
    "print": CAT_PRINT, "process": CAT_PRINT, "processes": CAT_PRINT,
    "quality": CAT_PRINT, "quality_changes": CAT_PRINT, "template": CAT_PRINT,
    "templates": CAT_PRINT, "slicingprofiles": CAT_PRINT, "user": CAT_PRINT,
    "intent": CAT_PRINT, "setting_visibility": CAT_APP,
    "vendor": CAT_VENDOR, "vendors": CAT_VENDOR,
    "snapshots": CAT_SNAPSHOT,
}


def categorize(rel_path: str, kind: str) -> str:
    """Guess what a file is from its folder and name."""
    if kind == KIND_HOST:
        return CAT_HOST
    if kind == KIND_MODELING:
        return CAT_APP
    p = PurePosixPath(rel_path.lower())
    if p.name.endswith((".fdm_material", ".xml.fdm_material")):
        return CAT_FILAMENT
    for folder in reversed(p.parts[:-1]):
        if folder in _FOLDER_CATEGORIES:
            cat = _FOLDER_CATEGORIES[folder]
            # Orca/Bambu keep a "user" folder that holds everything else,
            # so only treat "user" as print settings for Cura-style files.
            if folder == "user" and not p.name.endswith(".cfg"):
                continue
            return cat
    if len(p.parts) == 1:
        return CAT_APP   # loose files next to the folder = program settings
    return CAT_OTHER


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------
@dataclass
class BackupFile:
    path: str                 # e.g. "filament/My PETG.ini" (always uses /)
    category: str
    size: int
    modified: str             # date the file was last changed
    sha256: str               # fingerprint, used to check nothing got damaged
    encoding: str             # "text" or "base64"
    content: str

    @classmethod
    def from_bytes(cls, path, category, data: bytes, modified: str):
        text = _as_text(data)
        if text is not None:
            enc, content = "text", text
        else:
            enc, content = "base64", base64.b64encode(data).decode("ascii")
        return cls(path=path, category=category, size=len(data), modified=modified,
                   sha256=hashlib.sha256(data).hexdigest(), encoding=enc, content=content)

    def data(self) -> bytes:
        """The original file contents, exactly as they were."""
        if self.encoding == "base64":
            return base64.b64decode(self.content)
        # newline="" style: we stored the text exactly, including \r\n
        return self.content.encode("utf-8")

    def text(self):
        """The file as text, or None if it is a binary file."""
        return self.content if self.encoding == "text" else None

    def is_intact(self) -> bool:
        return hashlib.sha256(self.data()).hexdigest() == self.sha256

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    def to_dict(self):
        return dict(path=self.path, category=self.category, size=self.size,
                    modified=self.modified, sha256=self.sha256,
                    encoding=self.encoding, content=self.content)

    @classmethod
    def from_dict(cls, d):
        return cls(path=d["path"], category=d.get("category", CAT_OTHER),
                   size=int(d.get("size", 0)), modified=d.get("modified", ""),
                   sha256=d.get("sha256", ""), encoding=d.get("encoding", "text"),
                   content=d.get("content", ""))


@dataclass
class AppBackup:
    id: str
    name: str
    kind: str
    location: str                  # full original path of the settings folder
    home_relative: str | None      # same path starting with "~/", if possible
    installed: bool = False
    files: list = field(default_factory=list)
    skipped: list = field(default_factory=list)   # [{"path", "reason"}]
    note: str = ""

    def categories(self) -> dict:
        """{category: [files]} in a sensible order."""
        groups = {}
        for f in sorted(self.files, key=lambda f: f.path.lower()):
            groups.setdefault(f.category, []).append(f)
        return {c: groups[c] for c in sorted(groups, key=_cat_sort_key)}

    def to_dict(self):
        return dict(id=self.id, name=self.name, kind=self.kind, location=self.location,
                    home_relative=self.home_relative, installed=self.installed,
                    note=self.note, skipped=self.skipped,
                    files=[f.to_dict() for f in self.files])

    @classmethod
    def from_dict(cls, d):
        return cls(id=d.get("id", "unknown"), name=d.get("name", d.get("id", "?")),
                   kind=d.get("kind", ""), location=d.get("location", ""),
                   home_relative=d.get("home_relative"), installed=d.get("installed", False),
                   note=d.get("note", ""), skipped=d.get("skipped", []),
                   files=[BackupFile.from_dict(f) for f in d.get("files", [])])


@dataclass
class Backup:
    created: str
    computer: str
    os: str
    tool_version: str = __version__
    apps: list = field(default_factory=list)
    source: str = ""   # where it was loaded from (not saved)

    @property
    def file_count(self) -> int:
        return sum(len(a.files) for a in self.apps)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for a in self.apps for f in a.files)

    def to_dict(self):
        return {
            "format": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "about": "3D printing settings backup. Open with the 3D Print Backup "
                     "tool to view or restore. Text files are stored as plain text.",
            "created": self.created,
            "computer": self.computer,
            "os": self.os,
            "tool_version": self.tool_version,
            "apps": [a.to_dict() for a in self.apps],
        }

    def save(self, path) -> Path:
        path = Path(path)
        if path.suffix.lower() != FILE_EXTENSION:
            path = path.with_name(path.name + FILE_EXTENSION)
        tmp = path.with_name(path.name + ".partial")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        tmp.replace(path)   # only replace the real file once fully written
        return path

    @classmethod
    def from_dict(cls, d, source=""):
        if not isinstance(d, dict) or d.get("format") != FORMAT_NAME:
            raise BackupError("This is not a 3D Print Backup file.")
        if int(d.get("format_version", 0)) > FORMAT_VERSION:
            raise BackupError("This backup was made by a newer version of the tool. "
                              "Please update to open it.")
        return cls(created=d.get("created", ""), computer=d.get("computer", ""),
                   os=d.get("os", ""), tool_version=d.get("tool_version", ""),
                   apps=[AppBackup.from_dict(a) for a in d.get("apps", [])],
                   source=source)

    @classmethod
    def load(cls, path):
        path = Path(path)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise BackupError(f"The backup file is damaged or not a backup "
                              f"(line {exc.lineno}): {exc.msg}") from exc
        except UnicodeDecodeError as exc:
            raise BackupError("This is not a 3D Print Backup file.") from exc
        return cls.from_dict(data, source=str(path))


class BackupError(Exception):
    """Something is wrong with a backup file. The message is user-friendly."""


# ----------------------------------------------------------------------
# Making a backup
# ----------------------------------------------------------------------
def create_backup(scanner: Scanner | None = None, app_ids=None, progress=None) -> Backup:
    """Scan the computer and read every settings file into a Backup.

    ``progress`` is an optional function called with a message string, so a
    window or the terminal can show what is happening.
    """
    scanner = scanner or Scanner()
    say = progress or (lambda msg: None)
    backup = Backup(created=_dt.datetime.now().isoformat(timespec="seconds"),
                    computer=socket.gethostname(), os=scanner.os_name)

    for det in scanner.detect():
        if app_ids and det.app.id not in app_ids:
            continue
        for root in det.config_roots:
            say(f"Reading {det.app.name} settings in {root}")
            name = det.app.name
            if len(det.config_roots) > 1:
                name = f"{det.app.name} ({root.name})"
            app_bk = AppBackup(id=det.app.id, name=name, kind=det.app.kind,
                               location=root.as_posix(),
                               home_relative=scanner.home_relative(root),
                               installed=det.installed, note=det.app.note)
            files, skipped = scanner.collect_files(det.app, root)
            for rel, full in files:
                try:
                    data = full.read_bytes()
                    mtime = _dt.datetime.fromtimestamp(full.stat().st_mtime)
                except OSError as exc:
                    skipped.append((full, f"could not read: {exc}"))
                    continue
                app_bk.files.append(BackupFile.from_bytes(
                    rel, categorize(rel, det.app.kind), data,
                    mtime.isoformat(timespec="seconds")))
            app_bk.skipped = [{"path": Path(p).as_posix(), "reason": r} for p, r in skipped]
            if app_bk.files:
                backup.apps.append(app_bk)
    say(f"Done: {backup.file_count} files from {len(backup.apps)} program folders.")
    return backup


def default_backup_name() -> str:
    host = "".join(c for c in socket.gethostname() if c.isalnum() or c in "-_") or "computer"
    return f"3d-print-backup-{host}-{_dt.date.today().isoformat()}{FILE_EXTENSION}"


# ----------------------------------------------------------------------
# Restoring
# ----------------------------------------------------------------------
def restore_target(app: AppBackup, scanner: Scanner, backup_os: str) -> Path:
    """Work out where an app's files should go on THIS computer."""
    if backup_os == scanner.os_name and app.home_relative:
        # Same kind of computer: same place in the (possibly new) home folder.
        return scanner.home / app.home_relative[2:]
    if backup_os == scanner.os_name and app.location:
        return Path(app.location)
    # Different kind of computer (e.g. Windows -> Mac): use where that
    # program keeps its settings on this system.
    app_def = APPS_BY_ID.get(app.id)
    templates = app_def.config_paths.get(scanner.os_name, []) if app_def else []
    if not templates:
        raise BackupError(f"Don't know where {app.name} keeps its settings on "
                          f"{scanner.os_name}. Use 'restore to folder' instead.")
    tpl = templates[0]
    if "*" in tpl:
        # e.g. cura/* -> cura/5.8 (use the version folder from the backup)
        tpl = tpl.replace("*", PurePosixPath(app.location).name, 1).replace("*", "")
    existing = expand(tpl, scanner.vars)
    if existing:
        return existing[0]
    for name, value in scanner.vars.items():
        tpl = tpl.replace("{" + name + "}", str(value))
    return Path(tpl)


def safe_join(base: Path, rel: str) -> Path:
    """Join a path from a backup onto a folder, refusing anything that tries
    to escape the folder (like '../../something')."""
    rel_p = PurePosixPath(rel.replace("\\", "/"))
    parts = rel_p.parts
    if (not parts or rel_p.is_absolute() or ".." in parts
            or any(":" in part for part in parts)):
        raise BackupError(f"Refusing unsafe path in backup: {rel!r}")
    return base.joinpath(*parts)


def restore(backup: Backup, scanner: Scanner | None = None, app_indexes=None,
            to_folder=None, file_filter=None, progress=None) -> list:
    """Write files from a backup back to disk.

    app_indexes  which apps (positions in backup.apps) to restore; None = all
    to_folder    if given, write everything under this folder instead of
                 the programs' real settings folders (safe "just let me
                 look" option)
    file_filter  optional function(app, file) -> bool to pick single files

    Existing files that would be replaced are first renamed to
    "<name>.before-restore-<date-time>" so nothing is ever lost.
    Returns a list of (path, what_happened) tuples.
    """
    scanner = scanner or Scanner()
    say = progress or (lambda msg: None)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    results = []
    for i, app in enumerate(backup.apps):
        if app_indexes is not None and i not in app_indexes:
            continue
        if to_folder:
            base = Path(to_folder) / _safe_name(app.name)
        else:
            base = restore_target(app, scanner, backup.os)
        is_single_file = (len(app.files) == 1 and PurePosixPath(app.location).name == app.files[0].path)
        say(f"Restoring {app.name} to {base}")
        for f in app.files:
            if file_filter and not file_filter(app, f):
                continue
            if not f.is_intact():
                results.append((f.path, "SKIPPED - damaged in backup file"))
                continue
            if is_single_file and not to_folder:
                dest = base   # settings "folder" was really one file (.plist)
            else:
                dest = safe_join(base, f.path)
            data = f.data()
            if dest.exists():
                if dest.read_bytes() == data:
                    results.append((str(dest), "already up to date"))
                    continue
                kept = dest.with_name(f"{dest.name}.before-restore-{stamp}")
                dest.replace(kept)
                status = f"restored (old file kept as {kept.name})"
            else:
                status = "restored"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            results.append((str(dest), status))
    return results


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _as_text(data: bytes):
    """Return the data as text if it is a normal text file, else None."""
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Make sure the text turns back into exactly the same bytes.
    return text if text.encode("utf-8") == data else None


def _cat_sort_key(cat):
    return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER), cat)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_.()" else "_" for c in name).strip() or "app"


def describe_os(os_name: str) -> str:
    return {"windows": "Windows", "mac": "macOS", "linux": "Linux"}.get(os_name, os_name or "?")


def this_computer() -> str:
    return f"{socket.gethostname()} ({platform.system()})"
