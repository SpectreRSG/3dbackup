"""Opens the 3D Print Backup window - no black terminal window.

This is the file turned into "3D Print Backup.exe". Windows passes a file
path to it when you double-click a .3dbackup file that is set to "Open
with" this program, so we open that backup straight away.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backup3d.gui import run  # noqa: E402

if __name__ == "__main__":
    file = sys.argv[1] if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else None
    run(file)
