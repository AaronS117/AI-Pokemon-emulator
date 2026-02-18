"""
game_bot – Emulator control and gameplay automation adapter.

Uses libmgba-py (the same engine as pokebot-gen3 by 40Cakes) for
headless, high-speed GBA emulation with direct memory access via
cffi/ffi.memmove.  No GUI overhead — runs at thousands of FPS.

Handles:
  • Launching / destroying mGBA emulator instances via libmgba
  • Associating each instance with a seed / TID / SID
  • GBA memory reading (game state, party, encounter data)
  • Movement & navigation to encounter areas
  • Encounter triggering and battle-loop execution
  • Frame-based deterministic inputs
  • Save-state management
"""

from __future__ import annotations

import logging
import struct
import sys
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.config import (
    EMULATOR_DIR,
    ENCOUNTER_AREAS,
    INPUT_HOLD_FRAMES,
    ROM_PATH,
    ROOT_DIR,
    SAVE_DIR,
    GameVersion,
)

logger = logging.getLogger(__name__)

# Ensure the workspace root is on sys.path so ``import mgba`` resolves
# to the bundled libmgba-py that was extracted into <root>/mgba/.
_root_str = str(ROOT_DIR)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

import mgba.core   # type: ignore[import-untyped]
import mgba.image  # type: ignore[import-untyped]
import mgba.log    # type: ignore[import-untyped]
import mgba.vfs    # type: ignore[import-untyped]
from mgba import ffi, lib  # type: ignore[import-untyped]

# Silence libmgba's verbose stdout logging
mgba.log.silence()


# ── GBA Button constants (bitfield values matching libmgba) ──────────────────

class GBAButton(IntEnum):
    A = 0
    B = 1
    SELECT = 2
    START = 3
    RIGHT = 4
    LEFT = 5
    UP = 6
    DOWN = 7
    R = 8
    L = 9

# String → bitfield map (matches pokebot-gen3 input_map)
INPUT_MAP: Dict[str, int] = {
    "A": 0x1, "B": 0x2, "Select": 0x4, "Start": 0x8,
    "Right": 0x10, "Left": 0x20, "Up": 0x40, "Down": 0x80,
    "R": 0x100, "L": 0x200,
}


# ── Game-state enum (mirrors pokebot-gen3 GameState) ────────────────────────

class GameState(IntEnum):
    TITLE_SCREEN = auto()
    MAIN_MENU = auto()
    OVERWORLD = auto()
    BATTLE_STARTING = auto()
    BATTLE = auto()
    BATTLE_ENDING = auto()
    CHANGE_MAP = auto()
    CHOOSE_STARTER = auto()
    BAG_MENU = auto()
    PARTY_MENU = auto()
    EVOLUTION = auto()
    EGG_HATCH = auto()
    WHITEOUT = auto()
    NAMING_SCREEN = auto()
    POKE_STORAGE = auto()
    QUEST_LOG = auto()
    UNKNOWN = auto()


# ── Symbol tables (Fire Red USA v1.0) ────────────────────────────────────────
# Sourced from pokefirered decompilation, same as pokebot-gen3.

FIRERED_SYMBOLS: Dict[str, Tuple[int, int]] = {
    # symbol_name: (address, size_bytes)
    "gMain": (0x030022C0, 0x438),
    "gSaveBlock1Ptr": (0x03005008, 4),
    "gSaveBlock2Ptr": (0x0300500C, 4),
    "gPlayerParty": (0x02024284, 600),
    "gPlayerPartyCount": (0x02024280, 4),
    "gEnemyParty": (0x0202402C, 600),
    "gBattleOutcome": (0x02023E8A, 1),
    "gBattleTypeFlags": (0x02022B4C, 4),
    "sPlayTimeCounterState": (0x02039318, 1),
    "gObjectEvents": (0x02036E38, 0x960),
}

# Callback pointer → GameState (used for state detection)
_CALLBACK_STATE: Dict[int, GameState] = {}  # populated at runtime via symbol lookup


# ── Pokemon data structures ─────────────────────────────────────────────────

@dataclass
class PokemonData:
    personality_value: int = 0
    ot_id: int = 0
    species_id: int = 0
    nickname: str = ""
    is_shiny: bool = False
    level: int = 0
    hp: int = 0
    ivs: Tuple[int, ...] = ()
    nature_id: int = 0


# ── Emulator instance ───────────────────────────────────────────────────────

@dataclass
class EmulatorInstance:
    """Represents a single running mGBA emulator session."""
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    seed: int = 0
    tid: int = 0
    sid: int = 0
    game_version: str = GameVersion.FIRE_RED
    rom_path: Path = ROM_PATH
    save_path: Optional[Path] = None
    _core: object = None       # mgba.gba.GBA (Core subclass)
    _native: object = None     # core._native  (raw C struct)
    _screen: object = None     # mgba.image.Image
    _running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    def __repr__(self) -> str:
        return (
            f"EmulatorInstance(id={self.instance_id}, seed=0x{self.seed:04X}, "
            f"TID={self.tid}, SID={self.sid}, running={self._running})"
        )


# ── Core bot class ───────────────────────────────────────────────────────────

class GameBot:
    """
    High-level controller for a single emulator instance.

    Uses libmgba-py for headless emulation at maximum speed.
    Memory is read via ffi.memmove (same technique as pokebot-gen3)
    for zero-copy, high-performance access.

    Usage::

        bot = GameBot()
        instance = bot.launch(seed=0x1234, tid=12345, sid=54321)
        bot.navigate_to_area("route1")
        while True:
            encounter = bot.trigger_encounter()
            if encounter and encounter.is_shiny:
                bot.catch_pokemon()
                bot.save_game()
                break
            bot.run_from_battle()
        bot.destroy()
    """

    def __init__(self) -> None:
        self.instance: Optional[EmulatorInstance] = None
        self._pressed_inputs: int = 0
        self._held_inputs: int = 0
        self._prev_pressed_inputs: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────────

    def launch(
        self,
        seed: int,
        tid: int,
        sid: int,
        game_version: str = GameVersion.FIRE_RED,
        rom_path: Optional[Path] = None,
    ) -> EmulatorInstance:
        """Start a headless emulator instance associated with the given seed/IDs."""
        rom = rom_path or ROM_PATH
        if not rom.exists():
            raise FileNotFoundError(
                f"ROM not found at {rom}. Place your legally-owned ROM in the emulator/ folder."
            )

        inst = EmulatorInstance(
            seed=seed, tid=tid, sid=sid,
            game_version=game_version, rom_path=rom,
        )

        # Prepare per-instance save directory
        save_dir = SAVE_DIR / inst.instance_id
        save_dir.mkdir(parents=True, exist_ok=True)
        inst.save_path = save_dir / f"{rom.stem}.sav"

        # Create an empty .sav if none exists (libmgba requires one)
        if not inst.save_path.exists():
            inst.save_path.write_bytes(b"")

        # Load ROM via libmgba
        core = mgba.core.load_path(str(rom))
        if core is None:
            raise RuntimeError(f"libmgba failed to load ROM: {rom}")

        # Attach save file
        save_vf = mgba.vfs.open_path(str(inst.save_path), "r+")
        core.load_save(save_vf)

        # Set up a minimal video buffer (required even headless)
        screen = mgba.image.Image(*core.desired_video_dimensions())
        core.set_video_buffer(screen)

        # Reset the core to start emulation
        core.reset()

        # Disable video rendering for maximum speed
        # (same technique as pokebot-gen3 LibmgbaEmulator.set_video_enabled)
        core._native.video.renderer.disableBG[0] = True
        core._native.video.renderer.disableBG[1] = True
        core._native.video.renderer.disableBG[2] = True
        core._native.video.renderer.disableBG[3] = True
        core._native.video.renderer.disableOBJ = True
        core._native.video.renderer.disableWIN[0] = True
        core._native.video.renderer.disableWIN[1] = True
        core._native.video.renderer.disableOBJWIN = True

        inst._core = core
        inst._native = core._native
        inst._screen = screen
        inst._running = True

        self.instance = inst
        logger.info("Launched headless emulator: %s", inst)
        return inst

    def destroy(self) -> None:
        """Shut down the current emulator instance."""
        if self.instance is None:
            return
        self.instance._running = False
        # Core will be garbage-collected by cffi destructor
        self.instance._core = None
        self.instance._native = None
        logger.info("Destroyed emulator instance: %s", self.instance.instance_id)
        self.instance = None

    # ── Memory access (ffi.memmove, matching pokebot-gen3) ───────────────

    def read_bytes(self, address: int, length: int) -> bytes:
        """
        Read *length* bytes from the GBA system bus at *address*.

        Uses ffi.memmove for direct, zero-copy access to the emulator's
        memory — the same approach as pokebot-gen3's LibmgbaEmulator.
        """
        inst = self.instance
        if inst is None or inst._native is None:
            raise RuntimeError("No active emulator core.")

        bank = address >> 0x18
        result = bytearray(length)

        if bank == 0x2:
            # EWRAM: 0x02000000 – 0x0203FFFF (256 KB)
            offset = address & 0x3FFFF
            ffi.memmove(result, ffi.cast("char*", inst._native.memory.wram) + offset, length)
        elif bank == 0x3:
            # IWRAM: 0x03000000 – 0x03007FFF (32 KB)
            offset = address & 0x7FFF
            ffi.memmove(result, ffi.cast("char*", inst._native.memory.iwram) + offset, length)
        elif bank >= 0x8:
            # ROM: 0x08000000+
            offset = address - 0x08000000
            ffi.memmove(result, ffi.cast("char*", inst._native.memory.rom) + offset, length)
        else:
            raise RuntimeError(f"Invalid memory address for reading: 0x{address:08X}")

        return bytes(result)

    def write_bytes(self, address: int, data: bytes) -> None:
        """Write *data* to the GBA system bus at *address* (EWRAM/IWRAM only)."""
        inst = self.instance
        if inst is None or inst._native is None:
            raise RuntimeError("No active emulator core.")

        bank = address >> 0x18
        length = len(data)

        if bank == 0x2:
            offset = address & 0x3FFFF
            ffi.memmove(ffi.cast("char*", inst._native.memory.wram) + offset, data, length)
        elif bank == 0x3:
            offset = address & 0x7FFF
            ffi.memmove(ffi.cast("char*", inst._native.memory.iwram) + offset, data, length)
        else:
            raise RuntimeError(f"Invalid memory address for writing: 0x{address:08X}")

    def read_u16(self, address: int) -> int:
        return struct.unpack("<H", self.read_bytes(address, 2))[0]

    def read_u32(self, address: int) -> int:
        return struct.unpack("<I", self.read_bytes(address, 4))[0]

    def read_symbol(self, name: str, offset: int = 0, size: int = 0) -> bytes:
        """Read a symbol from the Fire Red symbol table."""
        if name not in FIRERED_SYMBOLS:
            raise KeyError(f"Unknown symbol: {name}")
        addr, length = FIRERED_SYMBOLS[name]
        if size <= 0:
            size = length
        return self.read_bytes(addr + offset, size)

    def get_save_block(self, num: int = 1, offset: int = 0, size: int = 0) -> bytes:
        """Read from save block 1 or 2 (FR/LG uses pointer indirection)."""
        ptr = self.read_u32(FIRERED_SYMBOLS[f"gSaveBlock{num}Ptr"][0])
        if ptr == 0:
            return b"\x00" * max(size, 1)
        if size <= 0:
            size = 0x4000
        return self.read_bytes(ptr + offset, size)

    # ── Game state detection ─────────────────────────────────────────────

    def get_game_state(self) -> GameState:
        """
        Determine the current game state by reading gMain and save-block data.

        Detection priority:
          1. Battle flags / outcome  → BATTLE / BATTLE_ENDING
          2. play-time counter == 0  → TITLE_SCREEN (no save loaded yet)
          3. gSaveBlock2 player name all-zero → NAMING_SCREEN (new game, name entry)
          4. gSaveBlock1 map bank/map == 0 and save block valid → CHOOSE_STARTER
          5. Otherwise              → OVERWORLD
        """
        try:
            battle_outcome = self.read_bytes(FIRERED_SYMBOLS["gBattleOutcome"][0], 1)[0]
            battle_flags = self.read_u32(FIRERED_SYMBOLS["gBattleTypeFlags"][0])

            if battle_flags != 0 and battle_outcome == 0:
                return GameState.BATTLE
            if battle_outcome != 0:
                return GameState.BATTLE_ENDING

            # play-time counter: 0 = title/intro, 1 = in-game
            play_state = self.read_bytes(FIRERED_SYMBOLS["sPlayTimeCounterState"][0], 1)[0]
            if play_state == 0:
                return GameState.TITLE_SCREEN

            # Check gSaveBlock2 for player name (first 7 bytes at ptr+0)
            # All 0xFF = uninitialized save → naming screen / new game intro
            sb2_ptr = self.read_u32(FIRERED_SYMBOLS["gSaveBlock2Ptr"][0])
            if sb2_ptr != 0:
                name_bytes = self.read_bytes(sb2_ptr, 7)
                if all(b == 0xFF for b in name_bytes):
                    return GameState.NAMING_SCREEN
                # All zero also means unset
                if all(b == 0x00 for b in name_bytes):
                    return GameState.NAMING_SCREEN

            # Check map bank/map from gSaveBlock1 (offset 0x4 = mapGroup, 0x5 = mapNum)
            sb1_ptr = self.read_u32(FIRERED_SYMBOLS["gSaveBlock1Ptr"][0])
            if sb1_ptr != 0:
                map_group = self.read_bytes(sb1_ptr + 0x4, 1)[0]
                map_num = self.read_bytes(sb1_ptr + 0x5, 1)[0]
                # Pallet Town = bank 0, map 0 — player spawns here after intro
                # Oak's lab = bank 0, map 1
                if map_group == 0 and map_num in (0, 1):
                    return GameState.CHOOSE_STARTER

            return GameState.OVERWORLD
        except Exception:
            return GameState.UNKNOWN

    def is_in_battle(self) -> bool:
        state = self.get_game_state()
        return state in (GameState.BATTLE, GameState.BATTLE_STARTING)

    def is_in_overworld(self) -> bool:
        return self.get_game_state() == GameState.OVERWORLD

    # ── Input (matching pokebot-gen3 press/hold/release model) ───────────

    def _apply_inputs_and_run_frame(self) -> None:
        """Set current inputs on the core and advance one frame."""
        core = self.instance._core
        core._core.setKeys(core._core, self._pressed_inputs | self._held_inputs)
        core.run_frame()
        self._prev_pressed_inputs = self._pressed_inputs
        self._pressed_inputs = 0

    def press_button(self, button: GBAButton, hold_frames: int = INPUT_HOLD_FRAMES) -> None:
        """Press and hold a GBA button for the specified number of frames."""
        if self.instance is None or self.instance._core is None:
            logger.warning("No active core; button press ignored.")
            return
        bit = 1 << button.value
        for _ in range(hold_frames):
            self._pressed_inputs = bit
            self._apply_inputs_and_run_frame()
        # Release frame
        self._pressed_inputs = 0
        self._apply_inputs_and_run_frame()

    def hold_button(self, button: GBAButton) -> None:
        """Hold a button until explicitly released."""
        self._held_inputs |= (1 << button.value)

    def release_button(self, button: GBAButton) -> None:
        """Release a held button."""
        self._held_inputs &= ~(1 << button.value)

    def release_all(self) -> None:
        """Release all held buttons."""
        self._held_inputs = 0

    def press_sequence(self, buttons: List[GBAButton], delay_frames: int = 10) -> None:
        """Press a sequence of buttons with delays between them."""
        for btn in buttons:
            self.press_button(btn)
            self.advance_frames(delay_frames)

    def advance_frames(self, n: int) -> None:
        """Run the emulator forward by *n* frames with no button input."""
        if self.instance is None or self.instance._core is None:
            return
        self._pressed_inputs = 0
        for _ in range(n):
            self._apply_inputs_and_run_frame()

    @property
    def frame_count(self) -> int:
        """Total frames emulated since last reset."""
        if self.instance and self.instance._core:
            return self.instance._core.frame_counter
        return 0

    # ── Navigation ───────────────────────────────────────────────────────

    def navigate_to_area(self, area_name: str) -> bool:
        """
        Navigate the player character to the specified encounter area.

        A full implementation would read the player's current map
        coordinates and execute a movement sequence using pokebot-gen3's
        map data.  For now, we assume the save state is already positioned.
        """
        if area_name not in ENCOUNTER_AREAS:
            logger.error("Unknown encounter area: %s", area_name)
            return False

        target_bank, target_map = ENCOUNTER_AREAS[area_name]
        logger.info(
            "Navigating to %s (bank=%d, map=%d) …",
            area_name, target_bank, target_map,
        )
        return True

    # ── Encounter farming ────────────────────────────────────────────────

    def trigger_encounter(self) -> Optional[PokemonData]:
        """
        Walk in grass / surf / etc. until a wild encounter triggers.
        Returns the encountered Pokémon's data, or None on timeout.
        """
        for step in range(200):
            direction = GBAButton.UP if step % 2 == 0 else GBAButton.DOWN
            self.press_button(direction, hold_frames=16)
            self.advance_frames(4)

            if self.is_in_battle():
                return self._read_enemy_lead()

        logger.warning("No encounter triggered after 200 steps.")
        return None

    def _read_enemy_lead(self) -> PokemonData:
        """Read the lead Pokémon of the enemy party from memory."""
        try:
            raw = self.read_symbol("gEnemyParty", 0, 100)
            pv = struct.unpack("<I", raw[0:4])[0]
            ot = struct.unpack("<I", raw[4:8])[0]
            tid = ot & 0xFFFF
            sid = (ot >> 16) & 0xFFFF
            is_shiny = (tid ^ sid ^ (pv >> 16) ^ (pv & 0xFFFF)) < 8

            return PokemonData(
                personality_value=pv,
                ot_id=ot,
                is_shiny=is_shiny,
            )
        except Exception as exc:
            logger.error("Failed to read enemy party: %s", exc)
            return PokemonData()

    # ── Battle actions ───────────────────────────────────────────────────

    def run_from_battle(self) -> None:
        """Select 'Run' in the battle menu."""
        # Battle menu: Fight / Bag / Pokémon / Run
        # Run is bottom-right → DOWN, RIGHT, A
        self.press_sequence([GBAButton.DOWN, GBAButton.RIGHT, GBAButton.A])
        self.advance_frames(120)

    def catch_pokemon(self) -> bool:
        """
        Attempt to catch the current wild Pokémon using the best available ball.
        Returns True if the catch animation completes.
        """
        logger.info("Attempting to catch Pokémon …")
        # Open Bag (top-right in battle menu)
        self.press_sequence([GBAButton.RIGHT, GBAButton.A])
        self.advance_frames(30)
        # Select Poké Balls pocket
        self.press_button(GBAButton.A)
        self.advance_frames(20)
        # Use first ball
        self.press_button(GBAButton.A)
        self.advance_frames(20)
        self.press_button(GBAButton.A)  # confirm
        # Wait for catch animation
        self.advance_frames(300)
        return True

    def execute_battle_command(self, move_index: int = 0) -> None:
        """Select Fight and use the move at *move_index* (0-3)."""
        self.press_button(GBAButton.A)
        self.advance_frames(20)
        for _ in range(move_index):
            self.press_button(GBAButton.DOWN)
            self.advance_frames(5)
        self.press_button(GBAButton.A)
        self.advance_frames(60)

    # ── Save management ──────────────────────────────────────────────────

    def save_game(self) -> Optional[Path]:
        """Trigger an in-game save via the Start menu."""
        logger.info("Saving game …")
        self.press_button(GBAButton.START)
        self.advance_frames(30)
        self.press_button(GBAButton.DOWN)
        self.advance_frames(10)
        self.press_button(GBAButton.A)
        self.advance_frames(30)
        self.press_button(GBAButton.A)  # confirm
        self.advance_frames(120)

        if self.instance and self.instance.save_path:
            logger.info("Game saved to %s", self.instance.save_path)
            return self.instance.save_path
        return None

    def save_state(self, slot: int = 0) -> Optional[Path]:
        """Create an emulator save state (not an in-game save)."""
        if self.instance and self.instance._core is not None:
            state_path = SAVE_DIR / self.instance.instance_id / f"state_{slot}.ss1"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                state_data = self.instance._core.save_state()
                state_path.write_bytes(state_data)
                logger.info("Save state written to %s", state_path)
                return state_path
            except Exception as exc:
                logger.error("Failed to save state: %s", exc)
        return None

    def load_state(self, state_path: Path) -> bool:
        """Load an emulator save state."""
        if self.instance and self.instance._core is not None:
            try:
                data = state_path.read_bytes()
                vfile = mgba.vfs.VFile.fromEmpty()
                vfile.write(data, len(data))
                vfile.seek(0, whence=0)
                self.instance._core.load_state(vfile)
                logger.info("Loaded save state from %s", state_path)
                return True
            except Exception as exc:
                logger.error("Failed to load state: %s", exc)
        return False

    def get_screenshot(self):
        """
        Capture the current screen as a PIL Image.
        Temporarily enables video rendering for one frame.
        """
        if self.instance is None or self.instance._core is None:
            return None
        core = self.instance._core
        native = self.instance._native

        # Enable rendering
        for i in range(4):
            native.video.renderer.disableBG[i] = False
        native.video.renderer.disableOBJ = False

        # Save state, render one frame, capture, restore
        state = core.save_state()
        core.run_frame()
        img = self.instance._screen.to_pil().convert("RGB")

        # Restore state and disable rendering again
        vfile = mgba.vfs.VFile.fromEmpty()
        vfile.write(state, len(state))
        vfile.seek(0, whence=0)
        core.load_state(vfile)

        for i in range(4):
            native.video.renderer.disableBG[i] = True
        native.video.renderer.disableOBJ = True

        return img

    # ── Utility ──────────────────────────────────────────────────────────

    def soft_reset(self) -> None:
        """Perform a soft reset (A+B+Start+Select)."""
        if self.instance and self.instance._core is not None:
            keys = (
                (1 << GBAButton.A) | (1 << GBAButton.B)
                | (1 << GBAButton.START) | (1 << GBAButton.SELECT)
            )
            self.instance._core._core.setKeys(self.instance._core._core, keys)
            for _ in range(4):
                self.instance._core.run_frame()
            self.instance._core._core.setKeys(self.instance._core._core, 0)
            logger.info("Soft reset performed.")
