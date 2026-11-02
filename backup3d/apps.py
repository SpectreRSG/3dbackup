"""The list of 3D printing programs this tool knows about.

Each program is described by an ``AppDef``: where it keeps its settings on
Windows, macOS and Linux, which files inside that folder are worth saving,
and where the program itself is usually installed.

Paths are written as *templates*. A word in curly brackets is swapped for a
real folder when the tool runs, for example ``{APPDATA}`` becomes
``C:/Users/you/AppData/Roaming`` on Windows. A ``*`` matches anything, which
is handy for folders that include a version number (``cura/5.8``).

The variables you can use are:

    {HOME}          your home folder (all systems)
    {DOCUMENTS}     your Documents folder (all systems)
    {APPDATA}       Windows: AppData/Roaming
    {LOCALAPPDATA}  Windows: AppData/Local
    {PROGRAMFILES}  Windows: C:/Program Files
    {PROGRAMFILES86} Windows: C:/Program Files (x86)
    {MACAPP}        macOS: ~/Library/Application Support
    {MACPREFS}      macOS: ~/Library/Preferences
    {XDG_CONFIG}    Linux: ~/.config
    {XDG_DATA}      Linux: ~/.local/share

To add a new program, copy one of the entries below and change it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WINDOWS = "windows"
MAC = "mac"
LINUX = "linux"

# Kinds of program. Used to group things in the viewer.
KIND_FDM = "Filament slicer"
KIND_RESIN = "Resin slicer"
KIND_MODELING = "3D modelling / CAD"
KIND_HOST = "Printer host / firmware"


@dataclass(frozen=True)
class AppDef:
    id: str                       # short name used on the command line
    name: str                     # friendly name shown to people
    kind: str                     # one of the KIND_* values above
    # Where settings live, per operating system. Each entry may be a folder
    # or a single file.
    config_paths: dict = field(default_factory=dict)
    # Where the program itself is usually installed (only used to say
    # "installed: yes/no"; nothing is copied from here).
    program_paths: dict = field(default_factory=dict)
    # Command names to look for on the PATH (mostly Linux).
    commands: tuple = ()
    # Which files to keep, relative to the settings folder. "*" = everything.
    include: tuple = ("*",)
    # Files or folders to leave out, relative to the settings folder.
    exclude: tuple = ()
    # Extra notes shown in the viewer.
    note: str = ""


def _flatpak(app_id: str) -> list:
    """Linux 'Flatpak' installs live in their own sandbox folder."""
    return [
        f"/var/lib/flatpak/app/{app_id}",
        f"{{XDG_DATA}}/flatpak/app/{app_id}",
    ]


# Things almost every program keeps that are NOT settings: big caches,
# logs, downloaded system profiles, network plugins and login tokens.
_PRUSA_FAMILY_EXCLUDE = ("cache", "logs", "log", "ota", "crashpad")
_ORCA_FAMILY_EXCLUDE = (
    "system",            # factory profiles - re-downloaded on install
    "cache", "log", "logs", "ota", "hms", "printers",
    "plugins",           # network plugin binaries (large, re-downloaded)
    "tmp", "web", "cameratools",
    "bambunetworkengine.conf",  # contains your cloud login token
)


def _orca_family(app_id, name, folder, exe_folder, exe, mac_app, cmd, flatpak_id=None, note=""):
    """OrcaSlicer, Bambu Studio and their many spin-offs share a layout:
    user/<account>/filament, user/<account>/machine, user/<account>/process."""
    linux = [f"{{XDG_CONFIG}}/{folder}"]
    programs_linux = []
    if flatpak_id:
        linux.append(f"{{HOME}}/.var/app/{flatpak_id}/config/{folder}")
        programs_linux = _flatpak(flatpak_id)
    return AppDef(
        id=app_id,
        name=name,
        kind=KIND_FDM,
        config_paths={
            WINDOWS: [f"{{APPDATA}}/{folder}"],
            MAC: [f"{{MACAPP}}/{folder}"],
            LINUX: linux,
        },
        program_paths={
            WINDOWS: [f"{{PROGRAMFILES}}/{exe_folder}/{exe}"],
            MAC: [f"/Applications/{mac_app}", f"{{HOME}}/Applications/{mac_app}"],
            LINUX: programs_linux,
        },
        commands=(cmd,) if cmd else (),
        exclude=_ORCA_FAMILY_EXCLUDE,
        note=note,
    )


def _prusa_family(app_id, name, folder, exe_folder, exe, mac_app, cmd, flatpak_id=None, note=""):
    """PrusaSlicer, SuperSlicer and Slic3r keep .ini files in folders
    called filament, print, printer, sla_print and sla_material."""
    linux = [f"{{XDG_CONFIG}}/{folder}", f"{{HOME}}/.{folder}"]
    programs_linux = []
    if flatpak_id:
        linux.append(f"{{HOME}}/.var/app/{flatpak_id}/config/{folder}")
        programs_linux = _flatpak(flatpak_id)
    return AppDef(
        id=app_id,
        name=name,
        kind=KIND_FDM,
        config_paths={
            WINDOWS: [f"{{APPDATA}}/{folder}"],
            MAC: [f"{{MACAPP}}/{folder}"],
            LINUX: linux,
        },
        program_paths={
            WINDOWS: [f"{{PROGRAMFILES}}/{exe_folder}/{exe}"],
            MAC: [f"/Applications/{mac_app}", f"{{HOME}}/Applications/{mac_app}"],
            LINUX: programs_linux,
        },
        commands=(cmd,) if cmd else (),
        exclude=_PRUSA_FAMILY_EXCLUDE,
        note=note,
    )


APPS: list = [
    # ------------------------------------------------------------------
    # Filament (FDM) slicers
    # ------------------------------------------------------------------
    _prusa_family("prusaslicer", "PrusaSlicer", "PrusaSlicer", "Prusa3D/PrusaSlicer",
                  "prusa-slicer.exe", "PrusaSlicer.app", "prusa-slicer",
                  flatpak_id="com.prusa3d.PrusaSlicer"),
    _prusa_family("superslicer", "SuperSlicer", "SuperSlicer", "SuperSlicer",
                  "superslicer.exe", "SuperSlicer.app", "superslicer"),
    _prusa_family("slic3r", "Slic3r", "Slic3r", "Slic3r", "slic3r.exe",
                  "Slic3r.app", "slic3r"),
    _orca_family("orcaslicer", "OrcaSlicer", "OrcaSlicer", "OrcaSlicer",
                 "orca-slicer.exe", "OrcaSlicer.app", "orca-slicer",
                 flatpak_id="io.github.softfever.OrcaSlicer"),
    _orca_family("bambustudio", "Bambu Studio", "BambuStudio", "Bambu Studio",
                 "bambu-studio.exe", "BambuStudio.app", "bambu-studio",
                 flatpak_id="com.bambulab.BambuStudio"),
    _orca_family("crealityprint", "Creality Print", "Creality/Creality Print/*",
                 "Creality/Creality Print*", "CrealityPrint.exe",
                 "CrealityPrint.app", "crealityprint",
                 note="Creality Print stores each version in its own folder."),
    _orca_family("crealityprint-old", "Creality Print (older versions)", "CrealityPrint",
                 "Creality Print*", "CrealityPrint.exe", "Creality Print.app", None),
    _orca_family("elegooslicer", "ElegooSlicer", "ElegooSlicer", "ElegooSlicer",
                 "elegoo-slicer.exe", "ElegooSlicer.app", "elegoo-slicer"),
    _orca_family("anycubicslicer", "Anycubic Slicer Next", "AnycubicSlicerNext",
                 "AnycubicSlicerNext", "AnycubicSlicerNext.exe",
                 "AnycubicSlicerNext.app", None),
    _orca_family("qidistudio", "QIDI Studio", "QIDIStudio", "QIDIStudio",
                 "qidi-studio.exe", "QIDIStudio.app", "qidi-studio"),
    _orca_family("snapmakerorca", "Snapmaker Orca", "Snapmaker_Orca", "Snapmaker_Orca",
                 "snapmaker-orca.exe", "Snapmaker_Orca.app", None),
    _orca_family("orcaflashforge", "Orca-Flashforge", "Orca-Flashforge", "Orca-Flashforge",
                 "orca-flashforge.exe", "Orca-Flashforge.app", None),
    AppDef(
        id="cura",
        name="UltiMaker Cura",
        kind=KIND_FDM,
        # Cura makes a new folder for every version (5.7, 5.8, ...). On Linux
        # it splits settings between ~/.config and ~/.local/share.
        config_paths={
            WINDOWS: ["{APPDATA}/cura/*"],
            MAC: ["{MACAPP}/cura/*"],
            LINUX: [
                "{XDG_CONFIG}/cura/*",
                "{XDG_DATA}/cura/*",
                "{HOME}/.var/app/com.ultimaker.cura/config/cura/*",
                "{HOME}/.var/app/com.ultimaker.cura/data/cura/*",
            ],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/UltiMaker Cura*/UltiMaker-Cura.exe",
                      "{PROGRAMFILES}/Ultimaker Cura*/Cura.exe"],
            MAC: ["/Applications/UltiMaker Cura.app", "/Applications/Ultimaker Cura.app"],
            LINUX: _flatpak("com.ultimaker.cura"),
        },
        commands=("cura", "ultimaker-cura"),
        exclude=("cache", "plugins", "packages", "scripts/__pycache__", "cura.log",
                 "stderr.log", "stdout.log", "*.log", "cura.cfg.backup"),
        note="Cura keeps one folder per version. Installed plugins are listed in "
             "packages.json but the plugins themselves are re-downloaded from the "
             "Marketplace.",
    ),
    AppDef(
        id="ideamaker",
        name="ideaMaker (Raise3D)",
        kind=KIND_FDM,
        config_paths={
            WINDOWS: ["{LOCALAPPDATA}/Raise3D/ideaMaker", "{APPDATA}/Raise3D/ideaMaker"],
            MAC: ["{MACAPP}/Raise3D/ideaMaker"],
            LINUX: ["{XDG_DATA}/Raise3D/ideaMaker", "{XDG_CONFIG}/Raise3D/ideaMaker"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/Raise3D/ideaMaker/ideaMaker.exe"],
            MAC: ["/Applications/ideaMaker.app"],
            LINUX: [],
        },
        commands=("ideamaker",),
        exclude=("cache", "log", "logs", "temp", "tmp"),
    ),
    AppDef(
        id="simplify3d",
        name="Simplify3D",
        kind=KIND_FDM,
        config_paths={
            WINDOWS: ["{LOCALAPPDATA}/Simplify3D", "{DOCUMENTS}/Simplify3D"],
            MAC: ["{MACAPP}/Simplify3D", "{DOCUMENTS}/Simplify3D"],
            LINUX: ["{XDG_DATA}/Simplify3D", "{DOCUMENTS}/Simplify3D"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/Simplify3D*/Simplify3D.exe"],
            MAC: ["/Applications/Simplify3D*/Simplify3D.app"],
            LINUX: ["/opt/Simplify3D*"],
        },
        include=("*.fff", "*.factory", "*.ini", "*.cfg", "*.json", "*.xml",
                 "profiles/*", "processes/*", "materials/*", "printers/*"),
        exclude=("cache", "logs"),
    ),

    # ------------------------------------------------------------------
    # Resin (SLA / MSLA) slicers
    # ------------------------------------------------------------------
    AppDef(
        id="chitubox",
        name="CHITUBOX",
        kind=KIND_RESIN,
        config_paths={
            WINDOWS: ["{APPDATA}/CHITUBOX*", "{LOCALAPPDATA}/CHITUBOX*"],
            MAC: ["{MACAPP}/CHITUBOX*"],
            LINUX: ["{XDG_CONFIG}/CHITUBOX*", "{XDG_DATA}/CHITUBOX*"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/CHITUBOX*"],
            MAC: ["/Applications/CHITUBOX*.app"],
            LINUX: [],
        },
        exclude=("cache", "log", "logs", "temp", "tmp", "update", "qtwebengine"),
    ),
    AppDef(
        id="lychee",
        name="Lychee Slicer",
        kind=KIND_RESIN,
        config_paths={
            WINDOWS: ["{APPDATA}/LycheeSlicer", "{APPDATA}/Lychee Slicer"],
            MAC: ["{MACAPP}/LycheeSlicer", "{MACAPP}/Lychee Slicer"],
            LINUX: ["{XDG_CONFIG}/LycheeSlicer", "{XDG_CONFIG}/Lychee Slicer"],
        },
        program_paths={
            WINDOWS: ["{LOCALAPPDATA}/Programs/lycheeslicer*", "{PROGRAMFILES}/Lychee*"],
            MAC: ["/Applications/Lychee*.app"],
            LINUX: [],
        },
        # Lychee is built on web technology; skip the browser junk.
        exclude=("cache", "code cache", "gpucache", "dawncache", "dawngraphitecache",
                 "dawnwebgpucache", "graphitedawncache", "shadercache",
                 "grshadercache", "blob_storage", "crashpad", "logs",
                 "service worker", "session storage", "network", "cookies*",
                 "*.log", "trust tokens*", "sharedstorage*"),
    ),
    AppDef(
        id="preform",
        name="PreForm (Formlabs)",
        kind=KIND_RESIN,
        config_paths={
            WINDOWS: ["{LOCALAPPDATA}/Formlabs", "{APPDATA}/Formlabs"],
            MAC: ["{MACAPP}/Formlabs", "{MACPREFS}/com.formlabs.PreForm.plist"],
            LINUX: [],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/Formlabs/PreForm/PreForm.exe"],
            MAC: ["/Applications/PreForm.app"],
            LINUX: [],
        },
        exclude=("cache", "logs", "log", "crashpad", "materials_cache", "downloads"),
    ),
    AppDef(
        id="uvtools",
        name="UVtools",
        kind=KIND_RESIN,
        config_paths={
            WINDOWS: ["{APPDATA}/UVtools", "{LOCALAPPDATA}/UVtools"],
            MAC: ["{MACAPP}/UVtools"],
            LINUX: ["{XDG_CONFIG}/UVtools"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/UVtools/UVtools.exe"],
            MAC: ["/Applications/UVtools.app"],
            LINUX: [],
        },
        commands=("uvtools",),
    ),

    # ------------------------------------------------------------------
    # 3D modelling / CAD programs
    # ------------------------------------------------------------------
    AppDef(
        id="blender",
        name="Blender",
        kind=KIND_MODELING,
        config_paths={
            WINDOWS: ["{APPDATA}/Blender Foundation/Blender/*"],
            MAC: ["{MACAPP}/Blender/*"],
            LINUX: ["{XDG_CONFIG}/blender/*"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/Blender Foundation/Blender*/blender.exe"],
            MAC: ["/Applications/Blender.app"],
            LINUX: _flatpak("org.blender.Blender") + ["/snap/blender"],
        },
        commands=("blender",),
        # Preferences and presets. Add-ons are skipped because they are
        # re-installed and can be very large.
        include=("config/*", "scripts/presets/*"),
        exclude=("config/cache",),
        note="Saves your Blender preferences, startup file and presets.",
    ),
    AppDef(
        id="freecad",
        name="FreeCAD",
        kind=KIND_MODELING,
        config_paths={
            WINDOWS: ["{APPDATA}/FreeCAD"],
            MAC: ["{MACAPP}/FreeCAD", "{HOME}/Library/Preferences/FreeCAD"],
            LINUX: ["{XDG_CONFIG}/FreeCAD", "{HOME}/.FreeCAD"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/FreeCAD*/bin/FreeCAD.exe"],
            MAC: ["/Applications/FreeCAD.app"],
            LINUX: _flatpak("org.freecad.FreeCAD"),
        },
        commands=("freecad", "FreeCAD"),
        include=("*.cfg", "*.fcmacro", "*.fcmat", "macro/*", "*.ini", "*.json"),
        exclude=("mod", "cache", "logs"),
    ),
    AppDef(
        id="openscad",
        name="OpenSCAD",
        kind=KIND_MODELING,
        config_paths={
            WINDOWS: ["{DOCUMENTS}/OpenSCAD"],
            MAC: ["{MACPREFS}/org.openscad.OpenSCAD.plist", "{DOCUMENTS}/OpenSCAD"],
            LINUX: ["{XDG_CONFIG}/OpenSCAD", "{XDG_DATA}/OpenSCAD"],
        },
        program_paths={
            WINDOWS: ["{PROGRAMFILES}/OpenSCAD/openscad.exe"],
            MAC: ["/Applications/OpenSCAD.app"],
            LINUX: _flatpak("org.openscad.OpenSCAD"),
        },
        commands=("openscad",),
        include=("*.conf", "*.plist", "*.json", "libraries/*", "templates/*"),
        note="On Windows OpenSCAD keeps its preferences in the registry, which "
             "this tool does not read. Your libraries are still saved.",
    ),

    # ------------------------------------------------------------------
    # Printer hosts / firmware (usually on a Raspberry Pi)
    # ------------------------------------------------------------------
    AppDef(
        id="klipper",
        name="Klipper / Moonraker config",
        kind=KIND_HOST,
        config_paths={
            WINDOWS: [],
            MAC: [],
            LINUX: ["{HOME}/printer_data/config", "{HOME}/klipper_config",
                    "{HOME}/printer_*_data/config"],
        },
        program_paths={LINUX: ["{HOME}/klipper"]},
        include=("*.cfg", "*.conf", "*.json", "*.txt"),
        exclude=("*.zip", "*.bkp"),
        note="Includes printer.cfg, macros and Moonraker settings.",
    ),
    AppDef(
        id="octoprint",
        name="OctoPrint",
        kind=KIND_HOST,
        config_paths={
            WINDOWS: ["{APPDATA}/OctoPrint"],
            MAC: ["{MACAPP}/OctoPrint"],
            LINUX: ["{HOME}/.octoprint"],
        },
        program_paths={LINUX: ["{HOME}/oprint", "{HOME}/OctoPrint"]},
        commands=("octoprint",),
        include=("config.yaml", "printerprofiles/*", "slicingprofiles/*",
                 "scripts/*", "data/*/*.yaml", "data/*/*.json"),
        exclude=("uploads", "timelapse", "logs", "generated", "plugins", "watched"),
        note="config.yaml contains your OctoPrint API key - keep this backup private.",
    ),
]


APPS_BY_ID = {app.id: app for app in APPS}
