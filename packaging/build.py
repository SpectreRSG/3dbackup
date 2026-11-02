"""Build the stand-alone programs (Python included - nothing to install).

Run on the computer you want to build for:
    pip install pyinstaller
    python packaging/build.py

PyInstaller can only build for the system it runs on: run it on Windows to
get .exe files, on a Mac to get Mac programs, and so on. GitHub does this
for us automatically (see .github/workflows/build.yml).

Results end up in the "dist" folder:
    3D Print Backup(.exe)   the window version - this is what most people want
    3dbackup-cli(.exe)      the terminal version, for typed commands
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "packaging" / "icon.ico"


def pyinstaller(*args):
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile",                      # everything in ONE file
           "--distpath", str(ROOT / "dist"),
           "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"),
           *args]
    if ICON.exists():
        # --icon sets the .exe's icon; --add-data puts a copy inside so the
        # window's title bar can use it too.
        cmd += ["--icon", str(ICON), "--add-data", f"{ICON}{os.pathsep}."]
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    # The window version: --windowed hides the black terminal window.
    pyinstaller("--windowed", "--name", "3D Print Backup", str(ROOT / "3dbackup_gui.pyw"))
    # The terminal version keeps the terminal so it can print results.
    pyinstaller("--console", "--name", "3dbackup-cli", str(ROOT / "3dbackup.py"))
    print("\nDone! Look in:", ROOT / "dist")


if __name__ == "__main__":
    main()
