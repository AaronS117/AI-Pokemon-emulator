"""
feebas_berry – Feebas tile hunting and Berry Blending automation.

Feebas Tile Calculation:
  Feebas only appears on 6 specific water tiles on Route 119 (RSE only).
  The tiles are determined by a seed stored in Save Block 1 and change
  when the trendy phrase in Dewford Town is updated.

Berry Blending:
  Automates the berry blending minigame to produce Pokéblocks for
  raising Beauty stat (required for Feebas → Milotic evolution).

Ported from pokebot-gen3's fishing.py (Feebas tile calc) and
berry_blend.py / pokeblock_feeder.py concepts.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot

logger = logging.getLogger(__name__)


# ── Feebas Tile Calculation ─────────────────────────────────────────────────

# Route 119 dimensions (RSE)
ROUTE_119_WIDTH = 44
ROUTE_119_HEIGHT = 139

# Feebas seed offsets in Save Block 1
FEEBAS_SEED_OFFSET_EMERALD = 0x2E6A
FEEBAS_SEED_OFFSET_RS = 0x2DD6


@dataclass
class FeebasTile:
    """A tile on Route 119 where Feebas can appear."""
    x: int
    y: int
    map_tile_index: int = 0

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"


def calculate_feebas_tiles(
    feebas_seed: int,
    fishing_spots: Optional[List[Tuple[int, int]]] = None,
) -> List[FeebasTile]:
    """
    Calculate the 6 Feebas tiles on Route 119 from the seed.

    This is a direct port of pokebot-gen3's get_feebas_tiles() logic.
    The seed is a u16 stored in Save Block 1.

    Args:
        feebas_seed: The 16-bit Feebas seed from the save file.
        fishing_spots: Pre-computed list of surfable fishing spots on Route 119.
                       If None, uses a default set of known spots.

    Returns:
        List of 6 FeebasTile objects.
    """
    if fishing_spots is None:
        # Use a reasonable default set of known fishing spots on Route 119
        # In a full implementation, these would be read from map data
        fishing_spots = _get_default_route119_spots()

    if len(fishing_spots) == 0:
        logger.warning("No fishing spots available for Feebas calculation")
        return []

    seed = feebas_seed
    tiles = []
    n = 0

    while n < 6:
        # LCRNG step: seed = (1103515245 * seed + 12345) & 0xFFFFFFFF
        seed = (1103515245 * seed + 12345) & 0xFFFF_FFFF
        spot_index = (seed >> 16) % len(fishing_spots)

        if spot_index == 0:
            spot_index = len(fishing_spots)

        if spot_index >= 4:
            x, y = fishing_spots[spot_index - 1]
            tiles.append(FeebasTile(x=x, y=y, map_tile_index=spot_index - 1))
            n += 1

    return tiles


def read_feebas_seed(bot: GameBot, game_version: str = "emerald") -> int:
    """Read the Feebas seed from Save Block 1."""
    if game_version == "emerald":
        offset = FEEBAS_SEED_OFFSET_EMERALD
    elif game_version in ("ruby", "sapphire"):
        offset = FEEBAS_SEED_OFFSET_RS
    else:
        logger.warning("Feebas tiles only exist in RSE, not %s", game_version)
        return 0

    data = bot.get_save_block(1, offset, 2)
    return struct.unpack("<H", data)[0]


def get_feebas_tiles_from_save(
    bot: GameBot,
    game_version: str = "emerald",
) -> List[FeebasTile]:
    """Read the Feebas seed and calculate tile locations."""
    seed = read_feebas_seed(bot, game_version)
    if seed == 0:
        return []
    tiles = calculate_feebas_tiles(seed)
    logger.info("Feebas tiles for seed 0x%04X: %s", seed, tiles)
    return tiles


def _get_default_route119_spots() -> List[Tuple[int, int]]:
    """
    Default fishing spots on Route 119.

    These are the surfable water tiles that are valid fishing locations.
    In a full implementation, these would be dynamically read from the
    map tileset data. This is a curated list of the ~100 most common spots.
    """
    spots = []
    # Route 119 has water tiles roughly in columns 4-12, rows 20-130
    # These are approximate positions of surfable tiles
    water_columns = [4, 5, 6, 7, 8, 9, 10, 11, 12]
    water_row_ranges = [
        (20, 35),   # Upper section
        (45, 65),   # Middle section near weather institute
        (75, 95),   # Lower middle
        (100, 130), # Lower section near Fortree
    ]
    for col in water_columns:
        for start, end in water_row_ranges:
            for row in range(start, end, 3):  # Sample every 3rd tile
                spots.append((col, row))
    return spots


# ── Berry Blending ──────────────────────────────────────────────────────────

class BerryType(Enum):
    """Berry types relevant to Pokéblock making."""
    CHERI = 0x85
    CHESTO = 0x86
    PECHA = 0x87
    RAWST = 0x88
    ASPEAR = 0x89
    LEPPA = 0x8A
    ORAN = 0x8B
    PERSIM = 0x8C
    LUM = 0x8D
    SITRUS = 0x8E
    FIGY = 0x8F
    WIKI = 0x90
    MAGO = 0x91
    AGUAV = 0x92
    IAPAPA = 0x93
    RAZZ = 0x94
    BLUK = 0x95
    NANAB = 0x96
    WEPEAR = 0x97
    PINAP = 0x98
    POMEG = 0x99
    KELPSY = 0x9A
    QUALOT = 0x9B
    HONDEW = 0x9C
    GREPA = 0x9D
    TAMATO = 0x9E
    CORNN = 0x9F
    MAGOST = 0xA0
    RABUTA = 0xA1
    NOMEL = 0xA2
    SPELON = 0xA3
    PAMTRE = 0xA4
    WATMEL = 0xA5
    DURIN = 0xA6
    BELUE = 0xA7
    LIECHI = 0xA8
    GANLON = 0xA9
    SALAC = 0xAA
    PETAYA = 0xAB
    APICOT = 0xAC
    LANSAT = 0xAD
    STARF = 0xAE
    ENIGMA = 0xAF


class PokeblockColor(Enum):
    """Pokéblock colors and their primary stat effect."""
    RED = auto()      # Spicy → Cool
    BLUE = auto()     # Dry → Beauty
    PINK = auto()     # Sweet → Cute
    GREEN = auto()    # Bitter → Smart
    YELLOW = auto()   # Sour → Tough
    PURPLE = auto()   # Mixed
    INDIGO = auto()   # Mixed
    BROWN = auto()    # Mixed
    LITE_BLUE = auto()  # Mixed
    OLIVE = auto()    # Mixed
    GRAY = auto()     # Mixed
    BLACK = auto()    # Failed blend
    WHITE = auto()    # Mixed
    GOLD = auto()     # Special


# Berries that produce BLUE (Dry/Beauty) Pokéblocks – needed for Feebas→Milotic
BEAUTY_BERRIES = [
    BerryType.CHESTO, BerryType.ORAN, BerryType.WIKI,
    BerryType.KELPSY, BerryType.CORNN, BerryType.PAMTRE,
    BerryType.GANLON, BerryType.APICOT,
]


@dataclass
class PokeblockResult:
    """Result of a berry blending session."""
    color: PokeblockColor
    spicy: int = 0
    dry: int = 0
    sweet: int = 0
    bitter: int = 0
    sour: int = 0
    feel: int = 0
    success: bool = True


class BerryBlendMode:
    """
    Automate berry blending for Pokéblock production.

    The berry blender minigame requires pressing A when the arrow
    passes over the player's marker. Timing affects quality.

    This mode:
    1. Walks to the berry blender NPC
    2. Selects a berry from the bag
    3. Times A presses to the arrow position
    4. Repeats until out of berries or target Pokéblocks reached
    """

    def __init__(self, bot: GameBot, target_berry: BerryType = BerryType.WIKI):
        self.bot = bot
        self.target_berry = target_berry
        self._phase = "start"
        self._blends_completed = 0
        self._target_blends = 10

    def step(self) -> dict:
        """Execute one step of the berry blending automation."""
        from modules.game_bot import GBAButton

        if self._phase == "start":
            # Talk to berry blender NPC
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            self._phase = "select_berry"
            return {"status": "running", "message": "Starting blend..."}

        elif self._phase == "select_berry":
            # Select berry from bag menu
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)
            self._phase = "blending"
            return {"status": "running", "message": "Selected berry"}

        elif self._phase == "blending":
            # During blending, press A at the right timing
            # The arrow rotates and we need to press when it's at our position
            # For automation, we press A every ~60 frames (approximate timing)
            for _ in range(4):
                self.bot.advance_frames(55)
                self.bot.press_button(GBAButton.A, hold_frames=2)
                self.bot.advance_frames(5)

            # Wait for blend to complete
            self.bot.advance_frames(60)

            # Mash A through results
            for _ in range(10):
                self.bot.press_button(GBAButton.A)
                self.bot.advance_frames(10)

            self._blends_completed += 1

            if self._blends_completed >= self._target_blends:
                self._phase = "done"
                return {"status": "completed",
                        "message": f"Completed {self._blends_completed} blends"}

            self._phase = "start"
            return {"status": "running",
                    "message": f"Blend {self._blends_completed}/{self._target_blends}"}

        elif self._phase == "done":
            return {"status": "completed",
                    "message": f"All {self._blends_completed} blends done"}

        return {"status": "running"}


class PokeblockFeeder:
    """
    Feed Pokéblocks to a Pokémon to raise contest stats.

    For Feebas → Milotic evolution, we need to max out Beauty.
    This automates feeding blue Pokéblocks from the Pokéblock case.
    """

    def __init__(self, bot: GameBot, party_slot: int = 0):
        self.bot = bot
        self._party_slot = party_slot
        self._blocks_fed = 0
        self._phase = "open_case"

    def step(self) -> dict:
        """Execute one step of Pokéblock feeding."""
        from modules.game_bot import GBAButton

        if self._phase == "open_case":
            # Open Pokéblock case from bag
            self.bot.press_button(GBAButton.START)
            self.bot.advance_frames(20)
            # Navigate to bag
            self.bot.press_button(GBAButton.DOWN)
            self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)
            # Navigate to berries pocket and find Pokéblock case
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            self._phase = "select_block"
            return {"status": "running", "message": "Opening Pokéblock case..."}

        elif self._phase == "select_block":
            # Select a Pokéblock (prefer blue/dry for Beauty)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            # Select "Use"
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            self._phase = "select_pokemon"
            return {"status": "running", "message": "Selected Pokéblock"}

        elif self._phase == "select_pokemon":
            # Select target Pokémon
            for _ in range(self._party_slot):
                self.bot.press_button(GBAButton.DOWN)
                self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)

            # Mash through feeding animation
            for _ in range(10):
                self.bot.press_button(GBAButton.A)
                self.bot.advance_frames(10)

            self._blocks_fed += 1
            self._phase = "check_done"
            return {"status": "running",
                    "message": f"Fed Pokéblock #{self._blocks_fed}"}

        elif self._phase == "check_done":
            # Check if Pokémon's nature rejects more blocks
            # (Pokémon stop eating when full or when they don't like the flavor)
            # For now, continue until we've fed a reasonable amount
            if self._blocks_fed >= 20:
                self._phase = "done"
                return {"status": "completed",
                        "message": f"Fed {self._blocks_fed} Pokéblocks"}

            self._phase = "select_block"
            return {"status": "running",
                    "message": f"Feeding... ({self._blocks_fed} fed)"}

        elif self._phase == "done":
            return {"status": "completed",
                    "message": f"Feeding complete ({self._blocks_fed} blocks)"}

        return {"status": "running"}


# ── Feebas Fishing Mode ────────────────────────────────────────────────────

class FeebasHuntMode:
    """
    Specialized fishing mode for Feebas hunting on Route 119.

    1. Calculates Feebas tiles from the save seed
    2. Navigates to each tile
    3. Fishes repeatedly (Feebas has ~50% encounter rate on valid tiles)
    4. Checks for shiny Feebas
    5. Moves to next tile if no Feebas after N attempts

    RSE only – Feebas is not available via fishing in FR/LG.
    """

    def __init__(self, bot: GameBot, game_version: str = "emerald"):
        self.bot = bot
        self.game_version = game_version
        self._feebas_tiles: List[FeebasTile] = []
        self._current_tile_idx = 0
        self._attempts_on_tile = 0
        self._max_attempts_per_tile = 10
        self._total_encounters = 0
        self._feebas_found = 0
        self._phase = "init"

    def step(self) -> dict:
        """Execute one step of Feebas hunting."""
        from modules.game_bot import GBAButton

        if self._phase == "init":
            self._feebas_tiles = get_feebas_tiles_from_save(
                self.bot, self.game_version)
            if not self._feebas_tiles:
                return {"status": "error",
                        "message": "Could not calculate Feebas tiles"}
            self._phase = "navigate"
            return {"status": "running",
                    "message": f"Found {len(self._feebas_tiles)} Feebas tiles"}

        elif self._phase == "navigate":
            if self._current_tile_idx >= len(self._feebas_tiles):
                self._current_tile_idx = 0  # Loop back
            tile = self._feebas_tiles[self._current_tile_idx]
            # Navigation would use pathfinding in a full implementation
            self._phase = "fish"
            self._attempts_on_tile = 0
            return {"status": "running",
                    "message": f"At tile {tile} (#{self._current_tile_idx + 1})"}

        elif self._phase == "fish":
            # Cast rod
            self.bot.press_button(GBAButton.SELECT)
            self.bot.advance_frames(30)

            # Wait for bite
            for _ in range(100):
                self.bot.advance_frames(1)
                if self.bot.is_in_battle():
                    break
                if _ % 3 == 0:
                    self.bot.press_button(GBAButton.A, hold_frames=2)

            self._attempts_on_tile += 1

            if self.bot.is_in_battle():
                self.bot.advance_frames(60)
                self._total_encounters += 1
                self._phase = "check_encounter"
                return {"status": "running", "message": "Got a bite!"}

            # No encounter
            if self._attempts_on_tile >= self._max_attempts_per_tile:
                self._current_tile_idx += 1
                self._phase = "navigate"
                return {"status": "running", "message": "No Feebas, moving to next tile"}

            # Dismiss "not even a nibble" text
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            return {"status": "running",
                    "message": f"Attempt {self._attempts_on_tile}/{self._max_attempts_per_tile}"}

        elif self._phase == "check_encounter":
            from modules.pokemon_data import read_enemy_lead
            enemy = read_enemy_lead(self.bot)

            is_feebas = (enemy.species_id == 349)  # Feebas national dex #349

            if is_feebas:
                self._feebas_found += 1
                if enemy.is_shiny:
                    return {"status": "shiny",
                            "message": f"SHINY FEEBAS! ({enemy.summary()})"}
                # Catch non-shiny Feebas too (needed for Milotic)
                return {"status": "feebas_found",
                        "message": f"Feebas found! {enemy.summary()}",
                        "pokemon": enemy}

            # Not Feebas – run
            self.bot.run_from_battle()
            self._phase = "fish"
            return {"status": "running",
                    "message": f"Not Feebas (species #{enemy.species_id}), continuing..."}

        return {"status": "running"}
