#!/usr/bin/env python3
"""Double-click this file (or run `python 3dbackup.py`) to open 3D Print Backup.

Add a command after it to use the terminal version instead, for example:
    python 3dbackup.py scan
    python 3dbackup.py backup
    python 3dbackup.py view my-backup.3dbackup
"""

import os
import sys

# Make sure Python can find the backup3d folder next to this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backup3d.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
