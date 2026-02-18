"""
modules/app_utils.py
────────────────────
Shared utilities used by both app.py and the UI sub-modules.
Nothing here imports from app.py, so there is no circular dependency.

Exports
-------
C                           – colour palette dict
SETTINGS_FILE               – Path to settings.json
DEFAULT_SETTINGS            – dict of factory defaults
BOT_MODES                   – ordered dict of bot-mode metadata
load_settings()
save_settings(settings)
detect_rom_in_dir(directory)
detect_game_version_from_path(rom_path)
detect_monitors()
get_secondary_monitor_origin()
"""
from __future__ import annotations

import json
import logging
import platform
import re
from pathlib import Path
from typing import Optional

from modules.config import ENCOUNTER_AREAS, SAVE_DIR

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent

# ── Colour palette ────────────────────────────────────────────────────────────
C: dict = {
    "bg_dark":   "#0f0f0f",
    "bg_card":   "#1a1a2e",
    "bg_input":  "#16213e",
    "accent":    "#7c3aed",
    "accent_h":  "#6d28d9",
    "green":     "#22c55e",
    "red":       "#ef4444",
    "yellow":    "#eab308",
    "gold":      "#fbbf24",
    "text":      "#e2e8f0",
    "text_dim":  "#94a3b8",
    "border":    "#334155",
}

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE = ROOT_DIR / "settings.json"

DEFAULT_SETTINGS: dict = {
    "rom_path": "",
    "save_directory": str(SAVE_DIR),
    "speed_multiplier": 0,
    "max_instances": 1,
    "target_area": "none",
    "video_enabled": False,
    "bot_mode": "manual",
    "window_geometry": "",
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ── ROM detection ─────────────────────────────────────────────────────────────
_GAME_PATTERNS = {
    "firered":  re.compile(r"fire.?red",   re.IGNORECASE),
    "leafgreen": re.compile(r"leaf.?green", re.IGNORECASE),
    "emerald":  re.compile(r"emerald",     re.IGNORECASE),
    "ruby":     re.compile(r"\bruby\b",    re.IGNORECASE),
    "sapphire": re.compile(r"sapphire",    re.IGNORECASE),
}


def detect_rom_in_dir(directory: Path) -> Optional[Path]:
    """Scan *directory* for a .gba file matching a known game name."""
    if not directory.exists():
        return None
    for gba in sorted(directory.glob("*.gba")):
        for version, pat in _GAME_PATTERNS.items():
            if pat.search(gba.stem):
                logger.info("Auto-detected ROM: %s (version=%s)", gba.name, version)
                return gba
    fallback = next(directory.glob("*.gba"), None)
    if fallback:
        logger.info("Auto-detected ROM (unknown version): %s", fallback.name)
    return fallback


def detect_game_version_from_path(rom_path: Path) -> str:
    """Infer game version string from ROM filename."""
    for version, pat in _GAME_PATTERNS.items():
        if pat.search(rom_path.stem):
            return version
    return "firered"


# ── Monitor detection ─────────────────────────────────────────────────────────

def detect_monitors() -> list:
    """
    Return a list of monitor dicts: {x, y, width, height, is_primary, name}.
    Primary monitor is always first.
    """
    monitors = []
    try:
        import screeninfo
        for m in screeninfo.get_monitors():
            monitors.append({
                "x": m.x, "y": m.y,
                "width": m.width, "height": m.height,
                "is_primary": getattr(m, "is_primary", m.x == 0 and m.y == 0),
                "name": getattr(m, "name", ""),
            })
    except Exception:
        pass

    if not monitors:
        try:
            import ctypes
            u32 = ctypes.windll.user32
            monitors.append({
                "x": 0, "y": 0,
                "width": u32.GetSystemMetrics(0),
                "height": u32.GetSystemMetrics(1),
                "is_primary": True, "name": "Primary",
            })
        except Exception:
            monitors.append({"x": 0, "y": 0, "width": 1920, "height": 1080,
                             "is_primary": True, "name": "Primary"})

    monitors.sort(key=lambda m: (not m["is_primary"], m["x"]))
    return monitors


def get_secondary_monitor_origin() -> Optional[tuple]:
    """Return (x, y) of the second monitor's top-left, or None if only one."""
    for m in detect_monitors():
        if not m["is_primary"]:
            return (m["x"], m["y"])
    return None


# ── Bot modes ─────────────────────────────────────────────────────────────────
BOT_MODES: dict = {
    "manual": {
        "label": "Manual Control",
        "desc": "Take full keyboard control of the emulator. No automation.",
        "status": "Ready",
    },
    "encounter_farm": {
        "label": "Wild Encounter Farm",
        "desc": "Walk in grass to trigger random encounters.",
        "status": "Ready",
    },
    "starter_reset": {
        "label": "Starter Soft Reset",
        "desc": "Soft-reset and check starter for shininess.",
        "status": "Ready",
    },
    "static_encounter": {
        "label": "Static Encounter",
        "desc": "Soft-reset in front of a legendary/gift.",
        "status": "Ready",
    },
    "fishing": {
        "label": "Fishing",
        "desc": "Fish with registered rod for shiny water Pokémon.",
        "status": "Ready",
    },
    "sweet_scent": {
        "label": "Sweet Scent",
        "desc": "Guaranteed encounters via Sweet Scent field move.",
        "status": "Ready",
    },
    "breeding": {
        "label": "Breeding / Egg Hatch",
        "desc": "Hatch daycare eggs and check for shinies.",
        "status": "Ready",
    },
    "safari_zone": {
        "label": "Safari Zone",
        "desc": "Hunt shinies in the Safari Zone.",
        "status": "Ready",
    },
    "rock_smash": {
        "label": "Rock Smash",
        "desc": "Smash rocks for encounters (Geodude, etc.).",
        "status": "Ready",
    },
    "level_evolution": {
        "label": "Level Evolution",
        "desc": "Level a Pokémon to its evolution threshold.",
        "status": "Ready",
    },
    "stone_evolution": {
        "label": "Stone Evolution",
        "desc": "Apply evolution stones from bag.",
        "status": "Ready",
    },
    "trade_evolution": {
        "label": "Trade Evolution",
        "desc": "Coordinate trade evolutions between instances.",
        "status": "Planned",
    },
}
