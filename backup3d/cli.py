"""Command-line interface.

    python -m backup3d                 open the window (the easy way)
    python -m backup3d scan            list programs found on this computer
    python -m backup3d backup          make a backup file
    python -m backup3d view FILE       show what is inside a backup
    python -m backup3d restore FILE    put settings back
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .apps import APPS_BY_ID
from .backup import (Backup, BackupError, create_backup, default_backup_name,
                     describe_os, restore, restore_target)
from .detect import Scanner
from .settings import parse, profile_name


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Some Windows terminals can't show symbols like ✔ - print "?" instead
    # of crashing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if not argv:
        return _open_gui(None)

    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    scanner = Scanner(os_name=args.os, home=args.home)
    try:
        return args.func(args, scanner)
    except BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


def _build_parser():
    p = argparse.ArgumentParser(
        prog="3dbackup",
        description="Back up, view and restore your 3D printing settings.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--home", help="scan this folder as if it were the home folder "
                                  "(e.g. a copy of an old computer's user folder)")
    p.add_argument("--os", choices=["windows", "mac", "linux"],
                   help="pretend to be this kind of computer (use with --home)")
    sub = p.add_subparsers(dest="command", metavar="command")

    s = sub.add_parser("scan", help="list 3D printing programs found on this computer")
    s.add_argument("--all", action="store_true", help="also list programs NOT found")
    s.set_defaults(func=cmd_scan)

    b = sub.add_parser("backup", help="create a backup file")
    b.add_argument("-o", "--output", help="where to save the backup "
                                          f"(default: {default_backup_name()})")
    b.add_argument("--only", nargs="+", metavar="APP",
                   help="only back up these programs (ids from 'scan')")
    b.set_defaults(func=cmd_backup)

    v = sub.add_parser("view", help="show what is inside a backup file")
    v.add_argument("file")
    v.add_argument("--app", help="only show this program (id or name)")
    v.add_argument("--show", metavar="PATH",
                   help="print the settings in one file, e.g. 'filament/My PETG.ini'")
    v.add_argument("--raw", action="store_true", help="with --show: print the raw file")
    v.set_defaults(func=cmd_view)

    r = sub.add_parser("restore", help="put settings from a backup back on this computer")
    r.add_argument("file")
    r.add_argument("--app", nargs="+", help="only restore these programs (id or name)")
    r.add_argument("--to", metavar="FOLDER",
                   help="write the files into this folder instead of the programs' "
                        "settings folders (safe way to just look at them)")
    r.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    r.set_defaults(func=cmd_restore)

    g = sub.add_parser("gui", help="open the window")
    g.add_argument("file", nargs="?")
    g.set_defaults(func=lambda a, s: _open_gui(a.file, s))
    return p


# ----------------------------------------------------------------------
def cmd_scan(args, scanner) -> int:
    found = 0
    print(f"Looking for 3D printing programs on this {describe_os(scanner.os_name)} computer...\n")
    for det in scanner.detect():
        if not (det.has_settings or det.installed or args.all):
            continue
        found += det.has_settings
        mark = "✔" if det.has_settings else ("·" if det.installed else "✘")
        status = []
        status.append("installed" if det.installed else "program not found")
        status.append("settings found" if det.has_settings else "no settings found")
        print(f" {mark} {det.app.name:<32} [{det.app.id}]  {', '.join(status)}")
        print(f"      type: {det.app.kind}")
        for root in det.config_roots:
            files, _ = scanner.collect_files(det.app, root)
            print(f"      settings: {root}  ({len(files)} files)")
    if not found:
        print(" No 3D printing settings were found.")
    print(f"\n{found} program folder(s) with settings. Run 'backup' to save them.")
    return 0


def cmd_backup(args, scanner) -> int:
    if args.only:
        unknown = [a for a in args.only if a not in APPS_BY_ID]
        if unknown:
            raise BackupError(f"Unknown program id(s): {', '.join(unknown)}. "
                              "Run 'scan --all' to see the ids.")
    bk = create_backup(scanner, app_ids=args.only, progress=lambda m: print(" ", m))
    if not bk.apps:
        print("Nothing to back up - no 3D printing settings were found.")
        return 1
    out = bk.save(args.output or default_backup_name())
    print(f"\nSaved {bk.file_count} files ({_size(bk.total_bytes)}) to:\n  {out.resolve()}")
    print("\nKeep a copy somewhere safe (USB stick, cloud drive, email to yourself).")
    print("Note: the backup can contain printer network passwords/API keys - keep it private.")
    return 0


def cmd_view(args, scanner) -> int:
    bk = Backup.load(args.file)
    apps = _pick_apps(bk, [args.app] if args.app else None)
    if args.show:
        for app in apps:
            for f in app.files:
                if f.path == args.show or f.path.lower() == args.show.lower():
                    _print_file(app, f, args.raw)
                    return 0
        raise BackupError(f"No file called {args.show!r} in the backup.")

    print(f"Backup made {bk.created.replace('T', ' at ')} on '{bk.computer}' "
          f"({describe_os(bk.os)})")
    print(f"{bk.file_count} files, {_size(bk.total_bytes)}, {len(bk.apps)} program folder(s)\n")
    for app in apps:
        print(f"■ {app.name}   [{app.id}]  - {app.kind}")
        print(f"  from: {app.location}")
        for cat, files in app.categories().items():
            print(f"  ▸ {cat} ({len(files)})")
            for f in files:
                print(f"      {profile_name(f.path):<40} {f.path}")
        print()
    print("Tip: view one file's settings with   view FILE --show \"<path>\"")
    return 0


def cmd_restore(args, scanner) -> int:
    bk = Backup.load(args.file)
    apps = _pick_apps(bk, args.app)
    indexes = {bk.apps.index(a) for a in apps}
    print("This will restore:")
    for a in apps:
        dest = (Path(args.to) / a.name) if args.to else restore_target(a, scanner, bk.os)
        print(f"  {a.name}: {len(a.files)} files  ->  {dest}")
    if not args.to:
        print("\nClose these programs first! Existing files are kept as "
              "'<name>.before-restore-<date>'.")
    if not args.yes:
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
    results = restore(bk, scanner, app_indexes=indexes, to_folder=args.to)
    for path, status in results:
        print(f"  {path}  -  {status}")
    print(f"\nDone - {len(results)} files.")
    return 0


# ----------------------------------------------------------------------
def _pick_apps(bk: Backup, wanted):
    if not wanted:
        return bk.apps
    wanted_low = [w.lower() for w in wanted]
    apps = [a for a in bk.apps if a.id.lower() in wanted_low or a.name.lower() in wanted_low]
    if not apps:
        have = ", ".join(sorted({a.id for a in bk.apps}))
        raise BackupError(f"Program not in backup. This backup contains: {have}")
    return apps


def _print_file(app, f, raw):
    print(f"{app.name} › {f.path}   ({f.category}, {_size(f.size)}, changed {f.modified})\n")
    text = f.text()
    if text is None:
        print("(binary file - it will be restored exactly, but can't be shown as text)")
        return
    rows = None if raw else parse(f.name, text)
    if not rows:
        print(text)
        return
    width = min(45, max(len(k) for k, _ in rows))
    for key, value in rows:
        lines = value.splitlines() or [""]
        print(f"  {key:<{width}}  {lines[0]}")
        for extra in lines[1:]:
            print(f"  {'':<{width}}  {extra}")


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _open_gui(file, scanner=None) -> int:
    try:
        from .gui import run
    except ImportError as exc:   # tkinter is missing on some Linux systems
        print("Could not open the window: tkinter is not installed.\n"
              "On Ubuntu/Debian run:  sudo apt install python3-tk\n"
              "You can still use the commands - run with --help to see them.\n"
              f"({exc})", file=sys.stderr)
        return 1
    run(file, scanner)
    return 0
