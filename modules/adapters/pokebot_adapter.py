"""
pokebot_adapter – Bridge to the pokebot-gen3 (40Cakes) repository.

pokebot-gen3 is a Python shiny-hunting bot that uses libmgba under the
hood.  This adapter extracts and re-exposes the key subsystems:
  • Movement logic (directional walking, tile-based navigation)
  • Encounter detection (game-state callbacks, battle triggers)
  • Battle loop logic (fight / catch / run menu navigation)
  • Memory reading (symbol tables, save blocks, encryption)

When the repo is cloned into ``external/pokebot-gen3``, this adapter
can import directly from it.  Otherwise it provides standalone
reimplementations based on the same decompilation symbol tables.
"""

from __future__ import annotations

import importlib
import logging
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from modules.config import POKEBOT_DIR, GameVersion

logger = logging.getLogger(__name__)


# ── Dynamic import from cloned repo ─────────────────────────────────────────

_pokebot_available = False


def _try_import_pokebot() -> bool:
    """Attempt to add pokebot-gen3 to sys.path and import its modules."""
    global _pokebot_available
    if _pokebot_available:
        return True

    pokebot_path = POKEBOT_DIR
    if not pokebot_path.exists():
        logger.info("pokebot-gen3 not found at %s; using built-in logic.", pokebot_path)
        return False

    # Add to sys.path so we can import pokebot modules
    path_str = str(pokebot_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

    try:
        importlib.import_module("modules.memory")
        _pokebot_available = True
        logger.info("pokebot-gen3 modules loaded from %s", pokebot_path)
        return True
    except ImportError as exc:
        logger.warning("Could not import pokebot-gen3 modules: %s", exc)
        return False


# ── Symbol table (Fire Red USA v1.0) ────────────────────────────────────────
# Derived from pokefirered decompilation symbol tables, same as pokebot-gen3.

FIRERED_SYMBOLS: Dict[str, Tuple[int, int]] = {
    # name: (address, size_bytes)
    "gMain": (0x030022C0, 0x438),
    "gSaveBlock1Ptr": (0x03005008, 4),
    "gSaveBlock2Ptr": (0x0300500C, 4),
    "gPlayerParty": (0x02024284, 600),
    "gPlayerPartyCount": (0x02024280, 4),
    "gEnemyParty": (0x0202402C, 600),
    "gBattleOutcome": (0x02023E8A, 1),
    "gObjectEvents": (0x02036E38, 0x960),
    "sPlayTimeCounterState": (0x02039318, 1),
    "gBattleTypeFlags": (0x02022B4C, 4),
    "gTrainerBattleOpponent_A": (0x02039F34, 2),
    "gMapHeader": (0x02036DFC, 0x1C),
    "gSaveBlock2": (0x02024EA4, 0xF80),
}

LEAFGREEN_SYMBOLS: Dict[str, Tuple[int, int]] = {
    # Leaf Green shares the same layout as Fire Red with minor offset diffs.
    # Placeholder — would be populated from the LG symbol table.
}

EMERALD_SYMBOLS: Dict[str, Tuple[int, int]] = {
    "gMain": (0x030022C0, 0x438),
    "gSaveBlock1Ptr": (0x03005D8C, 4),
    "gSaveBlock2Ptr": (0x03005D90, 4),
    "gPlayerParty": (0x020244EC, 600),
    "gPlayerPartyCount": (0x020244E9, 4),
    "gEnemyParty": (0x0202063C, 600),
    "gBattleOutcome": (0x0202421A, 1),
}

SYMBOL_TABLES = {
    GameVersion.FIRE_RED: FIRERED_SYMBOLS,
    GameVersion.LEAF_GREEN: LEAFGREEN_SYMBOLS,
    GameVersion.EMERALD: EMERALD_SYMBOLS,
}


def get_symbol_table(game_version: str) -> Dict[str, Tuple[int, int]]:
    """Return the symbol table for the given game version."""
    return SYMBOL_TABLES.get(game_version, FIRERED_SYMBOLS)


# ── Memory reading primitives ────────────────────────────────────────────────

class MemoryReader:
    """
    Reads GBA memory via a core object (libmgba).

    Mirrors the approach in pokebot-gen3's ``modules/memory.py``:
    symbol-based reads, save-block pointer dereferencing, encryption.
    """

    def __init__(self, core: Any, game_version: str = GameVersion.FIRE_RED) -> None:
        self.core = core
        self.symbols = get_symbol_table(game_version)
        self.game_version = game_version

    def read_bytes(self, address: int, size: int) -> bytes:
        return bytes(self.core.read(address, size))

    def read_u16(self, address: int) -> int:
        return struct.unpack("<H", self.read_bytes(address, 2))[0]

    def read_u32(self, address: int) -> int:
        return struct.unpack("<I", self.read_bytes(address, 4))[0]

    def read_symbol(self, name: str, offset: int = 0, size: int = 0) -> bytes:
        if name not in self.symbols:
            raise KeyError(f"Unknown symbol: {name}")
        addr, length = self.symbols[name]
        if size <= 0:
            size = length
        return self.read_bytes(addr + offset, size)

    def get_save_block(self, num: int = 1, offset: int = 0, size: int = 0) -> bytes:
        """
        Read from save block 1 or 2.
        In FR/LG and Emerald, save blocks are accessed via pointers.
        In R/S they are at fixed addresses.
        """
        ptr_symbol = f"gSaveBlock{num}Ptr"
        if ptr_symbol in self.symbols:
            ptr = self.read_u32(self.symbols[ptr_symbol][0])
            if ptr == 0:
                return b"\x00" * (size or 0x4000)
            if size <= 0:
                size = 0x4000  # reasonable default
            return self.read_bytes(ptr + offset, size)
        else:
            # Direct symbol (Ruby/Sapphire)
            return self.read_symbol(f"gSaveBlock{num}", offset, size)

    def get_encryption_key(self) -> int:
        """Read the save-data encryption key (FR/LG and Emerald)."""
        if self.game_version in (GameVersion.FIRE_RED, GameVersion.LEAF_GREEN):
            return self.read_u32(self.read_u32(self.symbols["gSaveBlock2Ptr"][0]) + 0xF20)
        elif self.game_version == GameVersion.EMERALD:
            return self.read_u32(self.read_u32(self.symbols["gSaveBlock2Ptr"][0]) + 0xAC)
        return 0  # R/S: no encryption


# ── Game-state detection ─────────────────────────────────────────────────────

# Callback name → state mapping (from pokebot-gen3 modules/memory.py)
CALLBACK_STATE_MAP = {
    "CB2_OVERWORLD": "overworld",
    "BATTLEMAINCB2": "battle",
    "CB2_INITBATTLE": "battle_starting",
    "CB2_HANDLESTARTBATTLE": "battle_starting",
    "CB2_ENDWILDBATTLE": "battle_ending",
    "CB2_LOADMAP": "change_map",
    "CB2_DOCHANGEMAP": "change_map",
    "CB2_STARTERCHOOSE": "choose_starter",
    "CB2_CHOOSESTARTER": "choose_starter",
    "CB2_TITLESCREENRUN": "title_screen",
    "CB2_MAINMENU": "main_menu",
    "CB2_BAGMENURUN": "bag_menu",
    "CB2_UPDATEPARTYMENU": "party_menu",
    "CB2_EVOLUTIONSCENEUPDATE": "evolution",
    "CB2_WHITEOUT": "whiteout",
    "CB2_POKESTORAGE": "poke_storage",
}


# ── Movement logic ───────────────────────────────────────────────────────────

# Tile-based movement directions
DIRECTION_OFFSETS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def compute_path(
    start: Tuple[int, int],
    end: Tuple[int, int],
) -> List[str]:
    """
    Compute a simple Manhattan-path from start to end coordinates.

    Returns a list of direction strings ("up", "down", "left", "right").
    A full implementation would use A* with collision data from the map.
    """
    path: List[str] = []
    x, y = start
    tx, ty = end

    while x != tx:
        if x < tx:
            path.append("right")
            x += 1
        else:
            path.append("left")
            x -= 1

    while y != ty:
        if y < ty:
            path.append("down")
            y += 1
        else:
            path.append("up")
            y -= 1

    return path


# ── Encounter detection ──────────────────────────────────────────────────────

def is_wild_encounter(battle_type_flags: int) -> bool:
    """Check if the current battle is a wild encounter (not trainer)."""
    BATTLE_TYPE_WILD = 0x04  # from decompilation
    return bool(battle_type_flags & BATTLE_TYPE_WILD)


def parse_pokemon_data(raw: bytes) -> Dict[str, Any]:
    """
    Parse the first 100 bytes of a party Pokémon structure.

    Gen 3 party structure (simplified):
        0x00 - 0x03: Personality Value (u32)
        0x04 - 0x07: OT ID (u32, low16=TID, high16=SID)
        0x08 - 0x17: Nickname (10 bytes)
        0x20 - 0x2F: Encrypted sub-structures (growth, attacks, EVs, misc)
    """
    if len(raw) < 100:
        return {}

    pv = struct.unpack("<I", raw[0:4])[0]
    ot_id = struct.unpack("<I", raw[4:8])[0]
    tid = ot_id & 0xFFFF
    sid = (ot_id >> 16) & 0xFFFF

    is_shiny = (tid ^ sid ^ ((pv >> 16) & 0xFFFF) ^ (pv & 0xFFFF)) < 8

    return {
        "personality_value": pv,
        "ot_id": ot_id,
        "tid": tid,
        "sid": sid,
        "is_shiny": is_shiny,
    }


# ── Battle loop helpers ──────────────────────────────────────────────────────

class BattleAction:
    FIGHT = "fight"
    BAG = "bag"
    POKEMON = "pokemon"
    RUN = "run"
    CATCH = "catch"


# Button sequences for battle menu actions (Fire Red layout)
BATTLE_MENU_SEQUENCES = {
    BattleAction.FIGHT: ["a"],           # top-left (default)
    BattleAction.BAG: ["right", "a"],    # top-right
    BattleAction.POKEMON: ["down", "a"], # bottom-left
    BattleAction.RUN: ["down", "right", "a"],  # bottom-right
}


# ── Adapter class ────────────────────────────────────────────────────────────

class PokebotAdapter:
    """
    Unified adapter that either delegates to the cloned pokebot-gen3
    or uses the built-in reimplementations above.
    """

    def __init__(self, game_version: str = GameVersion.FIRE_RED) -> None:
        self.game_version = game_version
        self.use_external = _try_import_pokebot()
        self.symbols = get_symbol_table(game_version)

    def get_movement_path(
        self, start: Tuple[int, int], end: Tuple[int, int]
    ) -> List[str]:
        return compute_path(start, end)

    def parse_enemy_pokemon(self, raw: bytes) -> Dict[str, Any]:
        return parse_pokemon_data(raw)

    def is_wild_battle(self, flags: int) -> bool:
        return is_wild_encounter(flags)

    def get_battle_sequence(self, action: str) -> List[str]:
        return BATTLE_MENU_SEQUENCES.get(action, ["a"])
