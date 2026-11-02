# 3D Print Backup

A free tool that **finds the 3D printing programs on your computer**, **backs up all your
printer, filament, resin and slicing settings into one file**, and can **open that file
later to show you every setting** (or put them all back) after a reinstall, new computer,
or accident.

It works on **Windows, macOS and Linux** and needs only Python. Nothing else to install.

---

## What it does, in 4 steps

1. **Scan** – it looks in the places each program keeps its settings and lists what it finds.
2. **Back up** – it copies every settings file into **one `.3dbackup` file**.
3. **View** – open the backup at any time to browse your printers, filaments, resins and
   print profiles as a neat *Setting → Value* table. Handy for copying settings by hand.
4. **Restore** – put the files back where the program expects them (old files are never
   deleted; they get renamed to `…before-restore-<date>`).

## Programs it knows about

| Type | Programs |
|---|---|
| Filament slicers | PrusaSlicer, SuperSlicer, Slic3r, OrcaSlicer, Bambu Studio, UltiMaker Cura, Creality Print, ElegooSlicer, Anycubic Slicer Next, QIDI Studio, Snapmaker Orca, Orca‑Flashforge, ideaMaker, Simplify3D |
| Resin slicers | CHITUBOX, Lychee Slicer, PreForm (Formlabs), UVtools — plus PrusaSlicer's resin (SLA) profiles |
| 3D modelling / CAD | Blender (preferences & presets), FreeCAD, OpenSCAD |
| Printer hosts | Klipper / Moonraker (`printer.cfg`, macros), OctoPrint |

PrusaSlicer, Orca/Bambu and Cura are the most tested. The others are a "best guess" at
where those programs save settings. If one isn't found on your computer, see
[Adding a program](#adding-a-program-or-fixing-a-folder).

**Not included on purpose:** caches, logs, factory profiles (they come back when you
reinstall), downloaded plugins, and cloud login tokens.

Fusion 360, Tinkercad, Onshape and Bambu/Prusa *cloud* profiles live online, so there is
nothing on your computer to back up.

---

## How to use it

### 1. Install Python (one time)

* **Windows / Mac:** download it from <https://www.python.org/downloads/>. On Windows, tick
  **"Add Python to PATH"** during install.
* **Linux:** Python is already there. For the window version also run
  `sudo apt install python3-tk` (Ubuntu/Debian/Raspberry Pi OS).

### 2. Download this tool

Click the green **Code** button on GitHub → **Download ZIP**, then unzip it.

### 3. Open it

**The easy way (a window):** double‑click **`3dbackup.py`**, or in a terminal:

```
python 3dbackup.py
```

(On Mac/Linux you may need to type `python3` instead of `python`.)

The window scans your computer straight away. Then:

* **💾 Create backup…** – choose where to save the `.3dbackup` file.
* **📂 Open backup…** – open a backup to look through it.
* Click a program → a category → a profile on the left to see its settings on the right.
  Use **Search settings** to find e.g. `temperature`. Click a row to see long values
  (like start G‑code) in full.
* **↩ Restore…** – select a program (or a single file) and click Restore. Close the
  slicer first!
* **📤 Save file as…** – save just one profile file somewhere, e.g. to import it by hand.

**The terminal way (commands):**

```
python 3dbackup.py scan                       # what was found?
python 3dbackup.py backup                     # make a backup in the current folder
python 3dbackup.py backup -o D:/my.3dbackup   # ...or choose where
python 3dbackup.py backup --only prusaslicer cura   # just some programs

python 3dbackup.py view my.3dbackup           # list everything inside
python 3dbackup.py view my.3dbackup --show "filament/My PETG.ini"   # one profile's settings

python 3dbackup.py restore my.3dbackup                     # put everything back
python 3dbackup.py restore my.3dbackup --app orcaslicer    # just one program
python 3dbackup.py restore my.3dbackup --to Desktop/look   # copy into a folder to look at
```

Rescuing settings from an old drive? Point it at the old user folder:

```
python 3dbackup.py --home "E:/Users/OldName" --os windows backup
```

---

## What's inside a `.3dbackup` file?

It's a plain text file (in a format called **JSON**), so you can even open it in Notepad.
Each settings file is stored with its folder path, its category (printer, filament, …) and
its full contents:

```json
{
  "format": "3dbackup",
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
          "content": "temperature = 245\n...",
          "sha256": "…a fingerprint used to detect damage…"
        }
      ]
    }
  ]
}
```

The rare non‑text file (e.g. Blender's preferences) is stored as `base64` – a way of
writing any data using only letters and numbers.

> ⚠️ **Keep your backup private.** Printer configs can contain things like your OctoPrint
> API key or Wi‑Fi printer access codes.

---

## How the code is organised

| File | What it does |
|---|---|
| `3dbackup.py` | The file you run. It just starts the program. |
| `backup3d/apps.py` | **The list of programs** and where each keeps its settings. |
| `backup3d/detect.py` | Searches the computer: finds the folders and picks which files to keep. |
| `backup3d/backup.py` | Makes, saves, opens and restores `.3dbackup` files. Also sorts files into categories. |
| `backup3d/settings.py` | Turns a settings file into the *Setting → Value* table. |
| `backup3d/gui.py` | The window. |
| `backup3d/cli.py` | The terminal commands. |
| `tests/` | Automatic checks. Run them with `python -m unittest discover tests`. |

## Adding a program (or fixing a folder)

Open `backup3d/apps.py` and copy an existing entry. The important part is
`config_paths` – where the settings live on each system. For example:

```python
AppDef(
    id="myslicer",
    name="My Slicer",
    kind=KIND_FDM,
    config_paths={
        WINDOWS: ["{APPDATA}/MySlicer"],
        MAC: ["{MACAPP}/MySlicer"],
        LINUX: ["{XDG_CONFIG}/MySlicer"],
    },
    exclude=("cache", "logs"),
),
```

`{APPDATA}` etc. are filled in automatically (the list is at the top of `apps.py`), and
`*` means "anything" – useful for version folders like `cura/5.8`.
