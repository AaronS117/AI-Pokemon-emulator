"""
emulator_api – Advanced mGBA API wrappers.

Exposes the full libmgba-py API surface beyond basic frame running:
  - Raw save states (fast in-memory snapshots)
  - Slot-based save states
  - Frame callbacks (per-frame hooks)
  - VRAM / OAM / Palette memory reads
  - RTC (Real Time Clock) control
  - SIO (Serial I/O) for link cable trades
  - Memory domain access (bus read/write)
  - Audio buffer access
  - Cheat file loading via mCoreAutoloadCheats

Wraps mgba.core.Core / mgba.gba.GBA methods with error handling
and type-safe Python interfaces.
"""

from __future__ import annotations

import datetime
import logging
import struct
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot

logger = logging.getLogger(__name__)


# ── GBA Memory Map ──────────────────────────────────────────────────────────

GBA_MEMORY_MAP = {
    "bios":    (0x0000_0000, 0x4000),
    "ewram":   (0x0200_0000, 0x40000),
    "iwram":   (0x0300_0000, 0x8000),
    "io":      (0x0400_0000, 0x3FF),
    "palette": (0x0500_0000, 0x400),
    "vram":    (0x0600_0000, 0x18000),
    "oam":     (0x0700_0000, 0x400),
    "rom":     (0x0800_0000, 0x2000000),
    "sram":    (0x0E00_0000, 0x10000),
}

# Palette sub-regions
PALETTE_BG_OFFSET = 0x0500_0000   # 256 bytes (128 colors)
PALETTE_OBJ_OFFSET = 0x0500_0200  # 256 bytes (128 colors)
PALETTE_SIZE = 0x200  # Each palette bank is 512 bytes total

# OAM structure
OAM_ENTRY_SIZE = 8  # Each OAM entry is 8 bytes
OAM_MAX_ENTRIES = 128


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class PaletteColor:
    """A single GBA color (15-bit BGR555)."""
    raw: int
    r: int  # 0-31
    g: int  # 0-31
    b: int  # 0-31

    @staticmethod
    def from_u16(value: int) -> PaletteColor:
        r = value & 0x1F
        g = (value >> 5) & 0x1F
        b = (value >> 10) & 0x1F
        return PaletteColor(raw=value, r=r, g=g, b=b)

    def to_rgb(self) -> Tuple[int, int, int]:
        """Convert to 8-bit RGB."""
        return (self.r << 3, self.g << 3, self.b << 3)


@dataclass
class OAMEntry:
    """A single OAM (Object Attribute Memory) sprite entry."""
    attr0: int = 0
    attr1: int = 0
    attr2: int = 0
    rotation: int = 0

    @property
    def y(self) -> int:
        return self.attr0 & 0xFF

    @property
    def x(self) -> int:
        return self.attr1 & 0x1FF

    @property
    def tile_index(self) -> int:
        return self.attr2 & 0x3FF

    @property
    def palette_num(self) -> int:
        return (self.attr2 >> 12) & 0xF

    @property
    def priority(self) -> int:
        return (self.attr2 >> 10) & 0x3

    @property
    def h_flip(self) -> bool:
        return bool(self.attr1 & (1 << 12))

    @property
    def v_flip(self) -> bool:
        return bool(self.attr1 & (1 << 13))

    @property
    def is_disabled(self) -> bool:
        return bool(self.attr0 & (1 << 9)) and not bool(self.attr0 & (1 << 8))

    @property
    def shape(self) -> int:
        return (self.attr0 >> 14) & 0x3

    @property
    def size(self) -> int:
        return (self.attr1 >> 14) & 0x3


@dataclass
class SaveStateSnapshot:
    """An in-memory save state snapshot for fast restore."""
    data: bytes
    frame_number: int
    label: str = ""


# ── Advanced Emulator API ───────────────────────────────────────────────────

class EmulatorAPI:
    """
    Advanced mGBA API wrapper providing access to features beyond
    basic frame running and memory read/write.
    """

    def __init__(self, bot: GameBot):
        self.bot = bot
        self._frame_callbacks: List[Callable] = []
        self._raw_state_cache: Dict[str, SaveStateSnapshot] = {}

    @property
    def _core(self):
        if self.bot.instance and self.bot.instance._core:
            return self.bot.instance._core
        raise RuntimeError("No active emulator core")

    @property
    def _native(self):
        if self.bot.instance and self.bot.instance._native:
            return self.bot.instance._native
        raise RuntimeError("No active emulator native")

    # ── Raw Save States (fast in-memory) ────────────────────────────────

    def save_raw_state(self, label: str = "") -> SaveStateSnapshot:
        """
        Save a raw state snapshot to memory (no disk I/O).
        Much faster than file-based save states.
        Uses core.save_raw_state() from mgba/core.py.
        """
        core = self._core
        raw = core.save_raw_state()
        if raw is None:
            raise RuntimeError("Failed to save raw state")
        snapshot = SaveStateSnapshot(
            data=bytes(raw),
            frame_number=core.frame_counter,
            label=label,
        )
        if label:
            self._raw_state_cache[label] = snapshot
        logger.debug("Saved raw state: frame=%d label=%s size=%d",
                     snapshot.frame_number, label, len(snapshot.data))
        return snapshot

    def load_raw_state(self, snapshot: SaveStateSnapshot) -> bool:
        """Load a raw state snapshot from memory."""
        core = self._core
        result = core.load_raw_state(snapshot.data)
        if result:
            logger.debug("Loaded raw state: frame=%d label=%s",
                         snapshot.frame_number, snapshot.label)
        return bool(result)

    def load_cached_state(self, label: str) -> bool:
        """Load a previously cached raw state by label."""
        snapshot = self._raw_state_cache.get(label)
        if snapshot is None:
            logger.warning("No cached state with label: %s", label)
            return False
        return self.load_raw_state(snapshot)

    def clear_state_cache(self) -> None:
        """Clear all cached raw states."""
        self._raw_state_cache.clear()

    # ── Slot Save States ────────────────────────────────────────────────

    def save_state_slot(self, slot: int) -> None:
        """Save state to a numbered slot (0-9)."""
        self._core.save_state_slot(slot)
        logger.debug("Saved state to slot %d", slot)

    def load_state_slot(self, slot: int) -> None:
        """Load state from a numbered slot (0-9)."""
        self._core.load_state_slot(slot)
        logger.debug("Loaded state from slot %d", slot)

    # ── Frame Callbacks ─────────────────────────────────────────────────

    def add_frame_callback(self, callback: Callable) -> None:
        """
        Register a callback to run after every video frame.
        Uses core.add_frame_callback() from mgba/core.py.
        """
        self._core.add_frame_callback(callback)
        self._frame_callbacks.append(callback)
        logger.debug("Added frame callback: %s", callback.__name__)

    @property
    def frame_counter(self) -> int:
        """Current frame counter."""
        return self._core.frame_counter

    @property
    def frame_cycles(self) -> int:
        """CPU cycles per frame."""
        return self._core.frame_cycles

    @property
    def frequency(self) -> int:
        """CPU frequency in Hz."""
        return self._core.frequency

    # ── VRAM / OAM / Palette Access ─────────────────────────────────────

    def read_palette(self, is_obj: bool = False) -> List[PaletteColor]:
        """
        Read the full BG or OBJ palette (256 colors).

        The GBA palette RAM is at 0x05000000 (BG) and 0x05000200 (OBJ).
        Each color is a 16-bit BGR555 value.
        """
        base = PALETTE_OBJ_OFFSET if is_obj else PALETTE_BG_OFFSET
        # Use bus read via the memory object if available
        colors = []
        try:
            mem = self._native.memory
            for i in range(256):
                addr = (base - 0x0500_0000) + (i * 2)
                # Read from palette RAM
                raw_bytes = bytearray(2)
                from mgba import ffi
                ffi.memmove(raw_bytes, ffi.cast("char*", mem.palette) + addr, 2)
                value = struct.unpack("<H", raw_bytes)[0]
                colors.append(PaletteColor.from_u16(value))
        except Exception as exc:
            logger.error("Failed to read palette: %s", exc)
        return colors

    def read_sprite_palette(self, pokemon_slot: int = 0) -> List[PaletteColor]:
        """
        Read the palette for a specific sprite slot.
        Useful for shiny detection via palette comparison.
        """
        # OBJ palettes start at 0x05000200, each palette is 32 bytes (16 colors)
        colors = self.read_palette(is_obj=True)
        start = pokemon_slot * 16
        end = start + 16
        return colors[start:end] if end <= len(colors) else []

    def read_oam(self) -> List[OAMEntry]:
        """Read all 128 OAM entries."""
        entries = []
        try:
            mem = self._native.memory
            from mgba import ffi
            raw = bytearray(OAM_MAX_ENTRIES * OAM_ENTRY_SIZE)
            ffi.memmove(raw, ffi.cast("char*", mem.oam), len(raw))
            for i in range(OAM_MAX_ENTRIES):
                offset = i * OAM_ENTRY_SIZE
                attr0 = struct.unpack_from("<H", raw, offset)[0]
                attr1 = struct.unpack_from("<H", raw, offset + 2)[0]
                attr2 = struct.unpack_from("<H", raw, offset + 4)[0]
                rotation = struct.unpack_from("<H", raw, offset + 6)[0]
                entries.append(OAMEntry(attr0, attr1, attr2, rotation))
        except Exception as exc:
            logger.error("Failed to read OAM: %s", exc)
        return entries

    def read_vram(self, offset: int = 0, size: int = 0x18000) -> bytes:
        """Read raw VRAM data."""
        try:
            mem = self._native.memory
            from mgba import ffi
            result = bytearray(size)
            ffi.memmove(result, ffi.cast("char*", mem.vram) + offset, size)
            return bytes(result)
        except Exception as exc:
            logger.error("Failed to read VRAM: %s", exc)
            return b""

    def read_io_register(self, register_offset: int) -> int:
        """Read a 16-bit I/O register."""
        try:
            mem = self._native.memory
            from mgba import ffi
            raw = bytearray(2)
            ffi.memmove(raw, ffi.cast("char*", mem.io) + register_offset, 2)
            return struct.unpack("<H", raw)[0]
        except Exception as exc:
            logger.error("Failed to read IO register 0x%04X: %s", register_offset, exc)
            return 0

    # ── RTC (Real Time Clock) ───────────────────────────────────────────

    def rtc_use_real_time(self) -> None:
        """Use real system time for RTC."""
        self._core.rtc.use_real_time()

    def rtc_use_fixed(self, dt: datetime.datetime) -> None:
        """Fix the RTC to a specific date/time (no progression)."""
        self._core.rtc.use_fixed(dt)

    def rtc_use_simulated(self, start: Optional[datetime.datetime] = None) -> None:
        """Use simulated time that advances with emulation speed."""
        self._core.rtc.use_simulated_time(start or datetime.datetime.now())

    def rtc_offset(self, seconds: int) -> None:
        """Offset the RTC by a number of seconds."""
        self._core.rtc.use_real_time_with_offset(seconds)

    def rtc_advance(self, milliseconds: int) -> None:
        """Advance the RTC by milliseconds."""
        self._core.rtc.advance_time(milliseconds)

    # ── Cheat Loading ───────────────────────────────────────────────────

    def autoload_cheats(self) -> bool:
        """Load cheat files from the standard mGBA cheat directory."""
        return self._core.autoload_cheats()

    # ── ROM Info ─────────────────────────────────────────────────────────

    @property
    def game_title(self) -> str:
        """ROM game title (up to 12 chars)."""
        return self._core.game_title

    @property
    def game_code(self) -> str:
        """ROM game code (4 chars, e.g. 'BPRE' for Fire Red)."""
        return self._core.game_code

    @property
    def video_dimensions(self) -> Tuple[int, int]:
        """Get the current video dimensions (width, height)."""
        return self._core.desired_video_dimensions()

    # ── Video Control ───────────────────────────────────────────────────

    def set_video_enabled(self, enabled: bool) -> None:
        """Enable or disable video rendering (disable for max speed)."""
        native = self._native
        for i in range(4):
            native.video.renderer.disableBG[i] = not enabled
        native.video.renderer.disableOBJ = not enabled
        native.video.renderer.disableWIN[0] = not enabled
        native.video.renderer.disableWIN[1] = not enabled
        native.video.renderer.disableOBJWIN = not enabled

    def set_layer_enabled(self, bg_layer: int, enabled: bool) -> None:
        """Enable/disable a specific BG layer (0-3)."""
        if 0 <= bg_layer <= 3:
            self._native.video.renderer.disableBG[bg_layer] = not enabled

    def set_sprites_enabled(self, enabled: bool) -> None:
        """Enable/disable sprite (OBJ) rendering."""
        self._native.video.renderer.disableOBJ = not enabled

    # ── Audio ───────────────────────────────────────────────────────────

    def set_audio_buffer_size(self, size: int) -> None:
        """Set the audio buffer size."""
        self._core.set_audio_buffer_size(size)

    @property
    def audio_buffer_size(self) -> int:
        return self._core.audio_buffer_size

    # ── Bus Read/Write (any address) ────────────────────────────────────

    def bus_read_8(self, address: int) -> int:
        """Read a single byte via the system bus."""
        try:
            if hasattr(self._core, 'memory') and self._core.memory:
                return self._core.memory.u8[address]
        except Exception:
            pass
        # Fallback to ffi.memmove
        data = self.bot.read_bytes(address, 1)
        return data[0]

    def bus_read_16(self, address: int) -> int:
        """Read a 16-bit value via the system bus."""
        try:
            if hasattr(self._core, 'memory') and self._core.memory:
                return self._core.memory.u16[address]
        except Exception:
            pass
        return self.bot.read_u16(address)

    def bus_read_32(self, address: int) -> int:
        """Read a 32-bit value via the system bus."""
        try:
            if hasattr(self._core, 'memory') and self._core.memory:
                return self._core.memory.u32[address]
        except Exception:
            pass
        return self.bot.read_u32(address)

    # ── Convenience ─────────────────────────────────────────────────────

    def get_rng_value(self, game_version: str = "firered") -> int:
        """Read the current RNG seed value."""
        from modules.symbol_tables import get_symbols
        symbols = get_symbols(game_version)
        addr = symbols["gRngValue"][0]
        return self.bot.read_u32(addr)

    def get_play_time(self) -> Tuple[int, int, int, int]:
        """Read play time as (hours, minutes, seconds, frames)."""
        from modules.symbol_tables import get_sb1_offsets
        offsets = get_sb1_offsets("firered")
        data = self.bot.get_save_block(1, offsets["play_time"], 8)
        hours = struct.unpack_from("<H", data, 0)[0]
        minutes = data[2]
        seconds = data[3]
        frames = data[4]
        return (hours, minutes, seconds, frames)
