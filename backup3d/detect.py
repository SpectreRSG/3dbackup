"""Find which 3D printing programs are on this computer.

A program counts as *found* when its settings folder exists. We also look
for the program itself so we can tell the user "installed: yes", but a
settings folder on its own is enough to make a backup (for example after
the program was uninstalled but its settings were left behind).
"""

from __future__ import annotations

import fnmatch
import glob
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .apps import APPS, LINUX, MAC, WINDOWS, AppDef

# Files larger than this are skipped (settings files are tiny; anything
# this big is almost certainly a cache, a model or a log).
DEFAULT_MAX_FILE_MB = 25

# Folder names that never hold settings, skipped in every program.
SKIP_DIR_NAMES = {
    "cache", "caches", "gpucache", "code cache", "shadercache", "grshadercache",
    "log", "logs", "crashpad", "crash reports", "crashdumps", "__pycache__",
    "tmp", "temp", ".git",
}

# File name patterns that never hold settings, or hold private login data.
SKIP_FILE_PATTERNS = (
    "*.log", "*.log.*", "*.tmp", "*.lock", "lockfile", "*.dmp", "*.pyc",
    "*token*", "cookies", "cookies-journal", ".ds_store", "thumbs.db",
)


def current_os() -> str:
    """Return 'windows', 'mac' or 'linux'."""
    if sys.platform.startswith("win"):
        return WINDOWS
    if sys.platform == "darwin":
        return MAC
    return LINUX


def path_variables(os_name: str, home: Path, env: dict) -> dict:
    """Work out the real folders behind {APPDATA}, {MACAPP} and friends."""
    home = Path(home)
    v = {"HOME": home, "DOCUMENTS": home / "Documents"}
    if os_name == WINDOWS:
        v["APPDATA"] = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        v["LOCALAPPDATA"] = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        v["PROGRAMFILES"] = Path(env.get("ProgramFiles") or "C:/Program Files")
        v["PROGRAMFILES86"] = Path(env.get("ProgramFiles(x86)") or "C:/Program Files (x86)")
    elif os_name == MAC:
        v["MACAPP"] = home / "Library" / "Application Support"
        v["MACPREFS"] = home / "Library" / "Preferences"
    else:
        v["XDG_CONFIG"] = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        v["XDG_DATA"] = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return v


def expand(template: str, variables: dict) -> list:
    """Turn a template like '{APPDATA}/cura/*' into the real paths that
    exist on this computer. Returns an empty list if nothing matches."""
    pattern = template
    for name, value in variables.items():
        # glob.escape stops odd characters in folder names (like '[')
        # from being treated as wildcards.
        pattern = pattern.replace("{" + name + "}", glob.escape(str(value)))
    if "{" in pattern:  # variable that does not exist on this system
        return []
    has_wildcard = any(ch in template for ch in "*?[")
    found = []
    for match in sorted(glob.glob(pattern)):
        p = Path(match)
        # A wildcard is meant to pick version folders, not random files.
        if has_wildcard and not p.is_dir():
            continue
        found.append(p)
    return found


@dataclass
class Detection:
    """What we found for one program."""
    app: AppDef
    program_found: list = field(default_factory=list)   # where it is installed
    config_roots: list = field(default_factory=list)    # where settings live

    @property
    def installed(self) -> bool:
        return bool(self.program_found)

    @property
    def has_settings(self) -> bool:
        return bool(self.config_roots)


class Scanner:
    """Looks around one computer. ``home``/``os_name``/``env`` can be
    changed for testing, or to scan a copied-over old home folder."""

    def __init__(self, os_name=None, home=None, env=None, max_file_mb=DEFAULT_MAX_FILE_MB):
        self.os_name = os_name or current_os()
        self.home = Path(home) if home else Path.home()
        # If a pretend home is given, don't mix in this computer's real
        # environment variables.
        self.env = env if env is not None else ({} if home else dict(os.environ))
        self.vars = path_variables(self.os_name, self.home, self.env)
        self.max_bytes = int(max_file_mb * 1024 * 1024)

    # -- finding programs ------------------------------------------------
    def detect(self, apps=None) -> list:
        results = []
        for app in apps or APPS:
            det = Detection(app)
            for tpl in app.config_paths.get(self.os_name, []):
                for p in expand(tpl, self.vars):
                    if p not in det.config_roots:
                        det.config_roots.append(p)
            for tpl in app.program_paths.get(self.os_name, []):
                for p in expand(tpl, self.vars):
                    if p not in det.program_found:
                        det.program_found.append(p)
            for cmd in app.commands:
                found = shutil.which(cmd)
                if found and Path(found) not in det.program_found:
                    det.program_found.append(Path(found))
            results.append(det)
        return results

    # -- finding files inside a settings folder --------------------------
    def collect_files(self, app: AppDef, root: Path):
        """Return (files, skipped).

        files   = list of (relative_path, full_path)
        skipped = list of (full_path, reason) for things left out on purpose
        """
        files, skipped = [], []
        root = Path(root)
        if root.is_file():
            self._consider(app, root.name, root, files, skipped)
            return files, skipped

        excludes = [e.lower() for e in app.exclude]
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir + "/"
            keep = []
            for d in sorted(dirnames):
                rel = (rel_dir + d).lower()
                if d.lower() in SKIP_DIR_NAMES or _matches(rel, excludes):
                    skipped.append((Path(dirpath) / d, "folder not needed (cache/log/system)"))
                elif (Path(dirpath) / d).is_symlink():
                    skipped.append((Path(dirpath) / d, "shortcut/link to another folder"))
                else:
                    keep.append(d)
            dirnames[:] = keep  # tells os.walk not to go into skipped folders
            for name in sorted(filenames):
                self._consider(app, rel_dir + name, Path(dirpath) / name, files, skipped)
        return files, skipped

    def _consider(self, app, rel, full, files, skipped):
        low = rel.lower()
        name = low.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name, pat) for pat in SKIP_FILE_PATTERNS):
            return  # junk/private file - silently ignored
        if _matches(low, [e.lower() for e in app.exclude]):
            skipped.append((full, "not a settings file for this program"))
            return
        if not _matches(low, [i.lower() for i in app.include]):
            return
        try:
            if full.is_symlink() or not full.is_file():
                return
            size = full.stat().st_size
        except OSError as exc:
            skipped.append((full, f"could not read: {exc}"))
            return
        if size > self.max_bytes:
            skipped.append((full, f"too large ({size / 1024 / 1024:.1f} MB)"))
            return
        files.append((rel, full))

    def home_relative(self, path: Path):
        """'~/AppData/Roaming/PrusaSlicer' style path, or None if the folder
        is not inside the home folder."""
        try:
            return "~/" + Path(path).relative_to(self.home).as_posix()
        except ValueError:
            return None


def _matches(rel_path: str, patterns) -> bool:
    """True if the path, or any folder above it, matches one of the patterns.
    So the pattern 'cache' matches 'cache/abc/def.json' too."""
    parts = rel_path.split("/")
    for i in range(1, len(parts) + 1):
        prefix = "/".join(parts[:i])
        if any(fnmatch.fnmatch(prefix, pat) for pat in patterns):
            return True
    return False
