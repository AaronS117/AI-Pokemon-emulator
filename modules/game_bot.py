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

import ctypes
import logging
import struct
import sys
import time as _time_mod
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Windows high-resolution timer (1 ms precision for time.sleep) ────────────
# On Windows, the default timer resolution is ~15 ms, which makes sleep-based
# frame throttling wildly inaccurate at 59.7 fps (16.74 ms/frame).
# timeBeginPeriod(1) sets the system timer to 1 ms resolution globally.
# Reference: BizHawk uses the same technique in its throttle loop.
_winmm = None
try:
    _winmm = ctypes.WinDLL("winmm")
    _winmm.timeBeginPeriod(1)
    logging.getLogger(__name__).debug("Windows timer resolution set to 1 ms (timeBeginPeriod)")
except (OSError, AttributeError):
    pass  # Non-Windows or winmm unavailable – sleep precision unchanged

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


# ── Symbol table loader (matches pokebot-gen3 modules/game.py) ───────────────

_SYM_DIR = ROOT_DIR / "external" / "pokebot-gen3" / "modules" / "data" / "symbols"

# Maps game_code → primary .sym filename
_SYM_FILES: Dict[str, str] = {
    "BPR": "pokefirered.sym",      # Fire Red rev0
    "BPR1": "pokefirered_rev1.sym", # Fire Red rev1
    "BPG": "pokeleafgreen.sym",
    "BPG1": "pokeleafgreen_rev1.sym",
    "BPE": "pokeemerald.sym",
    "AXV": "pokeruby.sym",
    "AXP": "pokesapphire.sym",
}

# name.upper() → (address, size)
_symbols: Dict[str, Tuple[int, int]] = {}
# address → name (for reverse lookup of callback pointers)
_reverse_symbols: Dict[int, str] = {}


def _load_sym_file(sym_filename: str) -> None:
    """Parse a .sym file and populate _symbols / _reverse_symbols."""
    global _symbols, _reverse_symbols
    _symbols.clear()
    _reverse_symbols.clear()

    for sym_dir in (_SYM_DIR, _SYM_DIR / "patches"):
        sym_path = sym_dir / sym_filename
        if not sym_path.exists():
            continue
        with open(sym_path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                try:
                    addr = int(parts[0], 16)
                    size = int(parts[2], 16)
                    name = parts[3].strip()
                except ValueError:
                    continue
                if name in (".gcc2_compiled", ".gcc2_compiled."):
                    continue
                _symbols[name.upper()] = (addr, size)
                # Keep the first (lowest-address) mapping for reverse lookup
                if addr not in _reverse_symbols:
                    _reverse_symbols[addr] = name.upper()

    logger.info("Loaded %d symbols from %s", len(_symbols), sym_filename)


def get_symbol(name: str) -> Tuple[int, int]:
    """Return (address, size) for a symbol name (case-insensitive)."""
    key = name.upper()
    if key not in _symbols:
        raise KeyError(f"Unknown symbol: {name}")
    return _symbols[key]


def get_symbol_name(address: int) -> str:
    """Reverse-lookup: return the symbol name for an address, or '' if not found."""
    return _reverse_symbols.get(address, "")


def get_symbol_name_before(address: int) -> str:
    """
    Return the nearest symbol whose address is <= the given address.
    Matches pokebot-gen3's get_symbol_name_before() used for callback resolution.
    """
    # Exact match first
    if address in _reverse_symbols:
        return _reverse_symbols[address]
    # Walk backwards up to 0x200 bytes
    for delta in range(1, 0x200):
        candidate = address - delta
        if candidate in _reverse_symbols:
            return _reverse_symbols[candidate]
    return ""


# ── Hardcoded fallback symbol table (Fire Red USA rev0) ───────────────────────
# Used when the .sym file cannot be loaded.  Addresses verified against
# the pokefirered decompilation and pokebot-gen3's pokefirered.sym.

FIREREED_SYMBOLS: Dict[str, Tuple[int, int]] = {
    "GMAIN":               (0x030030F0, 0x43C),   # corrected from sym file
    "GSAVEBLOCK1PTR":      (0x03005008, 4),
    "GSAVEBLOCK2PTR":      (0x0300500C, 4),
    "GPLAYERPARTY":        (0x02024284, 600),
    "GPLAYERPARTYCOUNT":   (0x02024280, 4),
    "GENEMYPARTY":         (0x0202402C, 600),
    "GBATTLEOUTCOME":      (0x02023E8A, 1),
    "GBATTLETYPEFLAGS":    (0x02022B4C, 4),
    "SPLAYTIMECOUNTERSTATE": (0x03000E7C, 1),     # corrected from sym file
    "GOBJECTEVENTS":       (0x02036E38, 0x240),
}


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

    # GBA hardware constants (from ARM7TDMI / GBA hardware reference)
    # Clock:        16,777,216 Hz
    # H-blank:      308 cycles/line  × 228 lines/frame = 70,224 cycles/frame
    # Wait:         68 cycles/line   × 228 lines/frame (h-blank portion)
    # Total/frame:  280,896 cycles  (16,777,216 / 280,896 = 59.7275560... fps)
    GBA_CLOCK_HZ: int   = 16_777_216
    GBA_CYCLES_PER_FRAME: int = 280_896
    GBA_FPS: float      = GBA_CLOCK_HZ / GBA_CYCLES_PER_FRAME  # 59.7275560...
    GBA_FRAME_MS: float = 1000.0 / GBA_FPS                     # 16.7427... ms

    def __init__(self) -> None:
        self.instance: Optional[EmulatorInstance] = None
        self._pressed_inputs: int = 0
        self._held_inputs: int = 0
        self._prev_pressed_inputs: int = 0
        self._speed: int = 0
        self._frame_budget: float = 0.0  # seconds per frame; 0 = unthrottled
        self._last_frame_time: float = 0.0
        self._video_enabled: bool = True   # always capture frames for preview
        self._render_every: int = 4        # capture 1 frame every N frames (15fps preview)
        self._frames_since_render: int = 0
        # Real-time FPS tracking (updated every second)
        self._fps_wall_t0: float = 0.0
        self._fps_frame0: int = 0
        self.real_fps: float = 0.0         # measured fps, readable from outside
        self._sleep_overrun_ms: float = 0.0  # last sleep overrun in ms (debug)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def launch(
        self,
        seed: int,
        tid: int,
        sid: int,
        game_version: str = GameVersion.FIRE_RED,
        rom_path: Optional[Path] = None,
        instance_id: Optional[int] = None,
        speed: int = 0,
    ) -> EmulatorInstance:
        """Start a headless emulator instance associated with the given seed/IDs.

        :param instance_id: Integer instance number (1, 2, 3…). Used as the save
                            directory name so saves land in saves/1/rom.sav etc.
                            If None, falls back to a UUID-based directory.
        :param speed: Speed multiplier: 1=1x, 2=2x, 4=4x, 0=unthrottled max.
        """
        rom = rom_path or ROM_PATH
        if not rom.exists():
            raise FileNotFoundError(
                f"ROM not found at {rom}. Place your legally-owned ROM in the emulator/ folder."
            )

        inst = EmulatorInstance(
            seed=seed, tid=tid, sid=sid,
            game_version=game_version, rom_path=rom,
        )

        # Use integer instance_id for save dir so saves/1/rom.sav is predictable.
        # Falls back to UUID if not provided (backwards compat).
        save_folder = str(instance_id) if instance_id is not None else inst.instance_id
        save_dir = SAVE_DIR / save_folder
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

        # mGBA always renders to the video buffer on run_frame() – we just
        # control how often we READ the buffer for the UI preview.
        self._video_enabled = True
        self._frames_since_render = 0

        inst._core = core
        inst._native = core._native
        inst._screen = screen
        inst._running = True

        self.instance = inst

        # Load the correct symbol table from the .sym file
        # Detect game from ROM filename (case-insensitive)
        rom_stem = rom.stem.upper()
        if "FIRERED" in rom_stem or "FIRE" in rom_stem:
            sym_file = "pokefirered.sym"
        elif "LEAFGREEN" in rom_stem or "LEAF" in rom_stem:
            sym_file = "pokeleafgreen.sym"
        elif "EMERALD" in rom_stem:
            sym_file = "pokeemerald.sym"
        elif "RUBY" in rom_stem:
            sym_file = "pokeruby.sym"
        elif "SAPPHIRE" in rom_stem:
            sym_file = "pokesapphire.sym"
        else:
            sym_file = "pokefirered.sym"  # default
        try:
            _load_sym_file(sym_file)
            logger.info("Loaded symbol table: %s (%d symbols)", sym_file, len(_symbols))
        except Exception as exc:
            logger.warning("Could not load sym file %s: %s – using fallback addresses", sym_file, exc)

        # Apply speed setting
        # speed=0 → unthrottled (max), speed=N → N× throttled
        self.set_speed(speed)
        logger.info("Launched headless emulator: %s  speed=%s  save=%s",
                    inst, f"{speed}x" if speed > 0 else "max", inst.save_path)
        return inst

    def set_video_enabled(self, enabled: bool) -> None:
        """Control how often the video buffer is read for the UI preview.
        enabled=True  → capture every _render_every frames (live preview)
        enabled=False → same rate; mGBA always renders internally regardless.
        This no longer disables BG layers (which caused a black screen).
        """
        self._video_enabled = enabled

    def set_speed(self, speed: int) -> None:
        """
        Set emulation speed for headless (no-audio) mode.
        speed=0 → unthrottled max
        speed=1 → ~60 fps via sleep-based throttle
        speed=N → ~N*60 fps via sleep-based throttle

        libmgba-py's GBA object has no set_sync/set_throttle method –
        throttling is done by sleeping between run_frame() calls.
        """
        import time as _time
        self._speed = speed
        # _frame_budget: seconds per frame budget (0 = no sleep)
        if speed > 0:
            self._frame_budget = 1.0 / (self.GBA_FPS * speed)
        else:
            self._frame_budget = 0.0
        # Initialise the timer NOW so the very first frame doesn't see
        # elapsed = (now - 0.0) = huge and skip the sleep entirely.
        self._last_frame_time = _time_mod.perf_counter()
        self._fps_wall_t0 = _time_mod.perf_counter()
        self._fps_frame0 = self.frame_count
        self.real_fps = 0.0

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

    def _sym(self, name: str) -> Tuple[int, int]:
        """
        Look up a symbol address+size.
        Prefers the loaded .sym table; falls back to FIREREED_SYMBOLS.
        """
        key = name.upper()
        if key in _symbols:
            return _symbols[key]
        if key in FIREREED_SYMBOLS:
            return FIREREED_SYMBOLS[key]
        raise KeyError(f"Unknown symbol: {name}")

    def read_symbol(self, name: str, offset: int = 0, size: int = 0) -> bytes:
        """Read a named symbol from GBA memory using the loaded symbol table."""
        addr, length = self._sym(name)
        if size <= 0:
            size = length
        return self.read_bytes(addr + offset, size)

    def get_save_block(self, num: int = 1, offset: int = 0, size: int = 0) -> bytes:
        """Read from save block 1 or 2 (FR/LG uses pointer indirection)."""
        ptr_addr, _ = self._sym(f"gSaveBlock{num}Ptr")
        ptr = self.read_u32(ptr_addr)
        if ptr == 0:
            return b"\x00" * max(size, 1)
        if size <= 0:
            size = 0x4000
        return self.read_bytes(ptr + offset, size)

    # ── Game state detection (matches pokebot-gen3 modules/memory.py) ────────────────

    def get_game_state_symbol(self) -> str:
        """
        Read gMain.callback2 (gMain+4) and resolve it to a symbol name.
        Matches pokebot-gen3's get_game_state_symbol() exactly.
        """
        try:
            gmain_addr, _ = self._sym("gMain")
            cb2_ptr = self.read_u32(gmain_addr + 4)
            # pokebot-gen3 subtracts 1 from the pointer before lookup
            return get_symbol_name_before(cb2_ptr - 1)
        except Exception:
            return ""

    def get_game_state(self) -> GameState:
        """
        Determine the current game state by resolving gMain.callback2 to a
        symbol name and matching it — identical to pokebot-gen3's get_game_state().
        """
        try:
            cb = self.get_game_state_symbol()
            # Only log when the state symbol changes (avoids flooding at 80fps)
            if not hasattr(self, "_last_cb2") or self._last_cb2 != cb:
                logger.debug("get_game_state: callback2=%s", cb)
                self._last_cb2 = cb

            match cb:
                case "CB2_OVERWORLD":
                    return GameState.OVERWORLD
                case "BATTLEMAINCB2":
                    return GameState.BATTLE
                case "CB2_BAGMENURUN":
                    return GameState.BAG_MENU
                case "CB2_UPDATEPARTYMENU" | "CB2_PARTYMENUMAIN":
                    return GameState.PARTY_MENU
                case "CB2_INITBATTLE" | "CB2_HANDLESTARTBATTLE" | "CB2_OVERWORLDBASIC":
                    return GameState.BATTLE_STARTING
                case "CB2_ENDWILDBATTLE":
                    return GameState.BATTLE_ENDING
                case "CB2_LOADMAP" | "CB2_LOADMAP2" | "CB2_DOCHANGEMAP":
                    return GameState.CHANGE_MAP
                case "CB2_STARTERCHOOSE" | "CB2_CHOOSESTARTER":
                    return GameState.CHOOSE_STARTER
                case (
                    "CB2_INITCOPYRIGHTSCREENAFTERBOOTUP"
                    | "CB2_WAITFADEBEFORESETUPINTRO"
                    | "CB2_SETUPINTRO"
                    | "CB2_INTRO"
                    | "CB2_INITTITLESCREEN"
                    | "CB2_TITLESCREENRUN"
                    | "CB2_INITCOPYRIGHTSCREENAFTERTITLESCREEN"
                    | "CB2_INITMAINMENU"
                    | "MAINCB2"
                    | "MAINCB2_INTRO"
                ):
                    return GameState.TITLE_SCREEN
                case "CB2_MAINMENU":
                    return GameState.MAIN_MENU
                case "CB2_EVOLUTIONSCENEUPDATE":
                    return GameState.EVOLUTION
                case "CB2_EGGHATCH" | "CB2_LOADEGGHATCH" | "CB2_EGGHATCH_0" | "CB2_EGGHATCH_1":
                    return GameState.EGG_HATCH
                case "CB2_WHITEOUT":
                    return GameState.WHITEOUT
                case "CB2_LOADNAMINGSCREEN" | "CB2_NAMINGSCREEN":
                    return GameState.NAMING_SCREEN
                case "CB2_POKESTORAGE":
                    return GameState.POKE_STORAGE
                case _:
                    return GameState.UNKNOWN
        except Exception as exc:
            logger.debug("get_game_state exception: %s", exc)
            return GameState.UNKNOWN

    def game_has_started(self) -> bool:
        """
        Reports whether the game has progressed past the main menu.
        Matches pokebot-gen3's game_has_started() exactly:
          sPlayTimeCounterState != 0  AND  gObjectEvents[0x10:0x19] != 0
        """
        try:
            pts_addr, _ = self._sym("sPlayTimeCounterState")
            if self.read_bytes(pts_addr, 1)[0] == 0:
                return False
            obj_addr, _ = self._sym("gObjectEvents")
            obj_data = self.read_bytes(obj_addr + 0x10, 9)
            return int.from_bytes(obj_data, "little") != 0
        except Exception:
            return False

    def is_in_battle(self) -> bool:
        state = self.get_game_state()
        return state in (GameState.BATTLE, GameState.BATTLE_STARTING)

    def is_in_overworld(self) -> bool:
        return self.get_game_state() == GameState.OVERWORLD

    # ── Input (matching pokebot-gen3 press/hold/release model) ───────────

    def _apply_inputs_and_run_frame(self) -> None:
        """Set current inputs on the core and advance one frame.
        mGBA always renders to the video buffer on every run_frame() call –
        we just throttle how often we READ it for the UI preview.
        Applies sleep-based throttle when _frame_budget > 0 (speed=1x etc.).
        """
        core = self.instance._core

        # Run one GBA frame (mGBA always renders internally)
        core._core.setKeys(core._core, self._pressed_inputs | self._held_inputs)
        core.run_frame()

        # Read the video buffer periodically for the UI preview
        self._frames_since_render += 1
        if self._frames_since_render >= self._render_every:
            try:
                self.instance._last_rendered = self.instance._screen.to_pil().convert("RGB")
            except Exception:
                pass
            self._frames_since_render = 0

        self._prev_pressed_inputs = self._pressed_inputs
        self._pressed_inputs = 0

        # Sleep-based throttle to hit the target frame rate
        if self._frame_budget > 0:
            now = _time_mod.perf_counter()
            elapsed = now - self._last_frame_time
            remaining = self._frame_budget - elapsed
            if remaining > 0:
                _time_mod.sleep(remaining)
                # Measure overrun (how much longer we slept than requested)
                actual = _time_mod.perf_counter() - now
                self._sleep_overrun_ms = (actual - remaining) * 1000.0
            else:
                self._sleep_overrun_ms = 0.0
            self._last_frame_time = _time_mod.perf_counter()

        # Update real_fps every ~60 frames
        fc = self.frame_count
        if fc - self._fps_frame0 >= 60:
            now = _time_mod.perf_counter()
            elapsed = now - self._fps_wall_t0
            if elapsed > 0:
                self.real_fps = (fc - self._fps_frame0) / elapsed
            self._fps_wall_t0 = now
            self._fps_frame0 = fc

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
        Return the most recently rendered frame as a PIL Image.

        No extra run_frame() call – the image was captured inside
        _apply_inputs_and_run_frame() every _render_every frames.
        Returns None if no frame has been rendered yet.
        """
        if self.instance is None:
            return None
        return getattr(self.instance, "_last_rendered", None)

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
