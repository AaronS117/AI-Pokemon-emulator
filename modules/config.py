"""
Global configuration for gen3-shiny-automation.
All paths, constants, and tunable parameters live here.
"""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT_DIR / "modules"
EXTERNAL_DIR = ROOT_DIR / "external"
SPRITES_DIR = ROOT_DIR / "sprites"
EMULATOR_DIR = ROOT_DIR / "emulator"
ANALYSIS_DIR = ROOT_DIR / "analysis"
TRAINING_DIR = ROOT_DIR / "training"
FINAL_SAVE_DIR = ROOT_DIR / "final_save"
DATABASE_PATH = ROOT_DIR / "shiny_log.db"

# External repo paths (populated after cloning)
POKEFINDER_DIR = EXTERNAL_DIR / "PokeFinder"
POKEBOT_DIR = EXTERNAL_DIR / "pokebot-gen3"

# ── Emulator ─────────────────────────────────────────────────────────────────
MGBA_PATH = EMULATOR_DIR / "mgba"  # path to mGBA binary or libmgba
ROM_PATH = EMULATOR_DIR / "firered.gba"  # user must supply ROM
SAVE_DIR = EMULATOR_DIR / "saves"

# ── RNG Constants (Gen 3 LCRNG – Pokémon Fire Red) ──────────────────────────
LCRNG_MULT = 0x41C64E6D
LCRNG_ADD = 0x00006073
LCRNG_MOD = 0x100000000  # 2^32

# Fire Red / Leaf Green use the same LCRNG as Ruby/Sapphire/Emerald.
# On real hardware the initial seed is derived from the system clock at boot.
# Seed range: 0x0000 – 0xFFFF (16-bit value from the RTC).

SEED_RANGE_MIN = 0x0000
SEED_RANGE_MAX = 0xFFFF

# ── Game Versions ────────────────────────────────────────────────────────────
class GameVersion:
    FIRE_RED = "firered"
    LEAF_GREEN = "leafgreen"
    EMERALD = "emerald"
    RUBY = "ruby"
    SAPPHIRE = "sapphire"

SUPPORTED_VERSIONS = [GameVersion.FIRE_RED]  # expand later

# ── Automation ───────────────────────────────────────────────────────────────
MAX_CONCURRENT_INSTANCES = 4
ENCOUNTER_TIMEOUT_SECONDS = 300
FRAME_DELAY_MS = 16  # ~60 fps
INPUT_HOLD_FRAMES = 4

# ── Shiny Detection ─────────────────────────────────────────────────────────
SHINY_PALETTE_THRESHOLD = 0.92  # similarity threshold for palette comparison
SPRITE_MATCH_THRESHOLD = 0.95  # template-match confidence

# ── Fire Red Encounter Areas ─────────────────────────────────────────────────
# Map bank/map pairs for common farming locations
ENCOUNTER_AREAS = {
    "route1": (3, 19),
    "route2": (3, 20),
    "route3": (3, 21),
    "viridian_forest": (3, 60),
    "mt_moon_1f": (3, 61),
    "cerulean_cave_1f": (3, 82),
    "safari_zone_center": (3, 91),
}

# ── Trade / Link Cable ──────────────────────────────────────────────────────
TRADE_ROOM_MAP = (2, 3)  # Pokémon Center 2F trade room (bank, map)
LINK_TIMEOUT_SECONDS = 60
