"""
pokefinder_adapter – Bridge to the PokeFinder (Admiral-Fish) repository.

PokeFinder is a C++/Qt application for RNG manipulation in Pokémon games.
This adapter extracts the relevant Gen 3 RNG logic and exposes it as
Python-callable functions.  When the PokeFinder repo is cloned into
``external/PokeFinder``, this adapter can optionally shell out to the
built binary for cross-validation.

Key PokeFinder concepts used:
  • LCRNG (Linear Congruential RNG) — same constants as our tid_engine
  • Gen 3 ID generation: seed → LCRNG → TID (high16) → LCRNG → SID (high16)
  • Wild encounter RNG: method 1 PID generation
  • Initial seed search for a target TID/SID pair
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.config import POKEFINDER_DIR, GameVersion
from modules.tid_engine import (
    TrainerID,
    enumerate_all_ids,
    find_ids_for_tid,
    lcrng_advance,
    lcrng_next,
    high16,
    seed_to_ids,
)

logger = logging.getLogger(__name__)


# ── PokeFinder binary interface ──────────────────────────────────────────────

class PokeFinderBinary:
    """
    Optional wrapper around the compiled PokeFinder executable.
    Used for cross-validation of our pure-Python RNG implementation.
    """

    def __init__(self, pokefinder_dir: Path = POKEFINDER_DIR) -> None:
        self.root = pokefinder_dir
        self.binary = self._find_binary()

    def _find_binary(self) -> Optional[Path]:
        """Locate the PokeFinder executable."""
        candidates = [
            self.root / "build" / "release" / "PokeFinder.exe",
            self.root / "build" / "PokeFinder.exe",
            self.root / "PokeFinder.exe",
            self.root / "build" / "PokeFinder",
        ]
        for p in candidates:
            if p.exists():
                logger.info("Found PokeFinder binary: %s", p)
                return p
        logger.warning("PokeFinder binary not found in %s", self.root)
        return None

    @property
    def is_available(self) -> bool:
        return self.binary is not None and self.binary.exists()


# ── Gen 3 RNG methods (re-implemented from PokeFinder source) ────────────────

def method1_pokemon(seed: int) -> Dict[str, int]:
    """
    Generate a wild Pokémon using Method 1 (standard Gen 3 wild encounter).

    Method 1 sequence:
        seed → PID_low = high16(LCRNG(seed))
             → PID_high = high16(LCRNG²(seed))
             → PID = (PID_high << 16) | PID_low
             → IVs1 = high16(LCRNG³(seed))
             → IVs2 = high16(LCRNG⁴(seed))
    """
    s = seed
    s = lcrng_next(s)
    pid_low = high16(s)
    s = lcrng_next(s)
    pid_high = high16(s)
    pid = (pid_high << 16) | pid_low

    s = lcrng_next(s)
    iv1 = high16(s)
    s = lcrng_next(s)
    iv2 = high16(s)

    # Unpack IVs
    hp = iv1 & 0x1F
    atk = (iv1 >> 5) & 0x1F
    defense = (iv1 >> 10) & 0x1F
    speed = iv2 & 0x1F
    spa = (iv2 >> 5) & 0x1F
    spd = (iv2 >> 10) & 0x1F

    nature = pid % 25
    ability = pid & 1

    return {
        "pid": pid,
        "iv_hp": hp,
        "iv_atk": atk,
        "iv_def": defense,
        "iv_speed": speed,
        "iv_spa": spa,
        "iv_spd": spd,
        "nature": nature,
        "ability": ability,
        "final_seed": s,
    }


def method2_pokemon(seed: int) -> Dict[str, int]:
    """
    Generate a Pokémon using Method 2 (used in some static encounters).

    Method 2 differs from Method 1 in that there is an extra LCRNG call
    between the PID and the IVs.
    """
    s = seed
    s = lcrng_next(s)
    pid_low = high16(s)
    s = lcrng_next(s)
    pid_high = high16(s)
    pid = (pid_high << 16) | pid_low

    s = lcrng_next(s)  # extra call (skipped)
    s = lcrng_next(s)
    iv1 = high16(s)
    s = lcrng_next(s)
    iv2 = high16(s)

    return {
        "pid": pid,
        "iv_hp": iv1 & 0x1F,
        "iv_atk": (iv1 >> 5) & 0x1F,
        "iv_def": (iv1 >> 10) & 0x1F,
        "iv_speed": iv2 & 0x1F,
        "iv_spa": (iv2 >> 5) & 0x1F,
        "iv_spd": (iv2 >> 10) & 0x1F,
        "nature": pid % 25,
        "ability": pid & 1,
        "final_seed": s,
    }


def method4_pokemon(seed: int) -> Dict[str, int]:
    """
    Generate a Pokémon using Method 4 (rare, some wild encounters).

    Method 4: extra LCRNG call between the two IV calls.
    """
    s = seed
    s = lcrng_next(s)
    pid_low = high16(s)
    s = lcrng_next(s)
    pid_high = high16(s)
    pid = (pid_high << 16) | pid_low

    s = lcrng_next(s)
    iv1 = high16(s)
    s = lcrng_next(s)  # extra call (skipped)
    s = lcrng_next(s)
    iv2 = high16(s)

    return {
        "pid": pid,
        "iv_hp": iv1 & 0x1F,
        "iv_atk": (iv1 >> 5) & 0x1F,
        "iv_def": (iv1 >> 10) & 0x1F,
        "iv_speed": iv2 & 0x1F,
        "iv_spa": (iv2 >> 5) & 0x1F,
        "iv_spd": (iv2 >> 10) & 0x1F,
        "nature": pid % 25,
        "ability": pid & 1,
        "final_seed": s,
    }


# ── Seed search ─────────────────────────────────────────────────────────────

def search_initial_seed_for_tid_sid(
    target_tid: int,
    target_sid: int,
    game_version: str = GameVersion.FIRE_RED,
) -> Optional[int]:
    """
    Find the initial seed that produces the exact TID/SID pair.
    Returns the seed or None if no match exists in the 16-bit space.
    """
    for seed in range(0x10000):
        ids = seed_to_ids(seed, game_version)
        if ids.tid == target_tid and ids.sid == target_sid:
            return seed
    return None


def search_shiny_frames(
    tid: int,
    sid: int,
    initial_seed: int,
    max_advances: int = 100_000,
) -> List[Tuple[int, Dict[str, int]]]:
    """
    Search for RNG frames that produce a shiny PID for the given TID/SID.

    Returns a list of (frame_number, pokemon_data) tuples.
    """
    results = []
    seed = initial_seed
    for frame in range(max_advances):
        seed = lcrng_next(seed)
        poke = method1_pokemon(seed)
        pid = poke["pid"]
        pid_high = (pid >> 16) & 0xFFFF
        pid_low = pid & 0xFFFF
        if (tid ^ sid ^ pid_high ^ pid_low) < 8:
            results.append((frame, poke))
    return results


# ── Cross-validation ─────────────────────────────────────────────────────────

def validate_tid_engine(sample_size: int = 100) -> bool:
    """
    Validate our tid_engine output against the PokeFinder RNG logic.
    Since both use the same LCRNG constants, they should always agree.
    """
    for seed in range(sample_size):
        ids = seed_to_ids(seed)
        # Re-derive manually
        s = seed & 0xFFFF
        s = (s * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        expected_tid = (s >> 16) & 0xFFFF
        s = (s * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        expected_sid = (s >> 16) & 0xFFFF

        if ids.tid != expected_tid or ids.sid != expected_sid:
            logger.error(
                "Validation FAILED at seed 0x%04X: got TID=%d SID=%d, expected TID=%d SID=%d",
                seed, ids.tid, ids.sid, expected_tid, expected_sid,
            )
            return False

    logger.info("tid_engine validation passed for %d seeds.", sample_size)
    return True
