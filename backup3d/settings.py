"""Turn a settings file into a simple list of (setting, value) rows so the
viewer can show it as a neat table instead of raw text.

Supported layouts:
  * INI / CFG / CONF  - PrusaSlicer, SuperSlicer, Cura, Klipper, ...
  * JSON              - OrcaSlicer, Bambu Studio, Creality Print, ...
  * XML               - Cura filament files (.xml.fdm_material)
  * PLIST             - macOS preference files
Anything else is shown as raw text only.
"""

from __future__ import annotations

import json
import plistlib
import xml.etree.ElementTree as ET

INI_EXT = (".ini", ".cfg", ".conf", ".inst.cfg", ".info")
JSON_EXT = (".json", ".bbsflmt")
XML_EXT = (".xml", ".fdm_material", ".fcmat")


def parse(name: str, text: str):
    """Return a list of (setting, value) rows, or None if the file can't be
    shown as a table. Never raises: a broken file just shows as raw text."""
    low = name.lower()
    try:
        if low.endswith(".plist"):
            return _flatten(plistlib.loads(text.encode("utf-8")))
        stripped = text.lstrip()
        if low.endswith(INI_EXT):
            return _parse_ini(text) or None
        if low.endswith(JSON_EXT) or stripped.startswith("{"):
            return _flatten(json.loads(text))
        if low.endswith(XML_EXT) or stripped.startswith("<"):
            return _parse_xml(text)
        if stripped.startswith("["):
            try:
                return _flatten(json.loads(text))
            except ValueError:
                pass
        if _looks_like_ini(text):
            return _parse_ini(text) or None
    except Exception:   # noqa: BLE001 - any parse problem = show raw text
        return None
    return None


def _looks_like_ini(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines()[:40]
             if ln.strip() and not ln.strip().startswith(("#", ";"))]
    if not lines:
        return False
    hits = sum(1 for ln in lines if "=" in ln or (ln.startswith("[") and ln.endswith("]")))
    return hits / len(lines) > 0.6


def _parse_ini(text: str):
    """Forgiving INI reader. Handles 'key = value', 'key: value',
    [sections] and Klipper-style indented multi-line values (gcode)."""
    rows = []
    section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if raw[:1] in " \t" and rows:
            # continuation of the previous value (e.g. a gcode macro)
            key, value = rows[-1]
            rows[-1] = (key, (value + "\n" + stripped) if value else stripped)
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            continue
        eq, colon = stripped.find("="), stripped.find(":")
        positions = [p for p in (eq, colon) if p > 0]
        if not positions:
            continue
        cut = min(positions)
        key = stripped[:cut].strip()
        value = stripped[cut + 1:].strip()
        rows.append((f"{section} › {key}" if section else key, value))
    return rows


def _flatten(obj, prefix=""):
    """Turn nested JSON into flat rows: {"a": {"b": 1}} -> ("a › b", "1")."""
    rows = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            name = f"{prefix} › {key}" if prefix else str(key)
            rows.extend(_flatten(value, name))
    elif isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            # Orca stores most values as ["220"] - show that as just 220.
            rows.append((prefix or "(list)", ", ".join(_scalar(v) for v in obj)))
        else:
            for i, value in enumerate(obj):
                rows.extend(_flatten(value, f"{prefix}[{i + 1}]"))
    else:
        rows.append((prefix or "(value)", _scalar(obj)))
    return rows


def _scalar(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, bytes):
        return f"<{len(v)} bytes of data>"
    return str(v)


def _parse_xml(text: str):
    root = ET.fromstring(text)
    rows = []

    def tag(el):
        return el.tag.split("}", 1)[-1]   # drop the {namespace} part

    def walk(el, path):
        name = tag(el)
        # Cura uses <setting key="print temperature">200</setting>
        label = el.attrib.get("key") or el.attrib.get("name") or el.attrib.get("id")
        here = f"{path} › {name}" if path else name
        if label:
            here = f"{here} [{label}]"
        children = list(el)
        txt = (el.text or "").strip()
        if txt and not children:
            rows.append((here, txt))
        elif not children and el.attrib and not label:
            rows.append((here, ", ".join(f"{k}={v}" for k, v in el.attrib.items())))
        for child in children:
            walk(child, here)

    for child in root:
        walk(child, "")
    return rows


def profile_name(path: str) -> str:
    """'filament/My PETG.ini' -> 'My PETG' (what the slicer calls it)."""
    name = path.rsplit("/", 1)[-1]
    for ext in (".inst.cfg", ".xml.fdm_material", ".fdm_material", ".ini",
                ".json", ".cfg", ".fff", ".info"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name
