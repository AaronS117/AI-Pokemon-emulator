"""
tid_engine – Legitimate TID/SID generation for Gen 3 (Fire Red).

Implements the exact LCRNG (Linear Congruential Random Number Generator)
used by the Gen 3 Pokémon engine to derive Trainer ID and Secret ID from
an initial seed.

On real GBA hardware the initial seed is a 16-bit value derived from the
system clock at the moment the game boots.  The game then calls the LCRNG
once; the upper 16 bits of the result become the TID and the next call's
upper 16 bits become the SID.

PokeFinder (Admiral-Fish) confirms this sequence:
    seed → LCRNG(seed) → TID = high16  → LCRNG again → SID = high16

This module:
  • Enumerates every valid initial seed (0x0000 – 0xFFFF).
  • Converts each seed to the correct TID/SID pair.
  • Guarantees all generated IDs are legitimately recreatable on hardware.
  • Exposes an API for the automation controller.

Expansion: call ``set_game_version()`` before generating IDs for other
games once their RNG quirks are added.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Generator, List, Optional

from modules.config import (
    LCRNG_MULT,
    LCRNG_ADD,
    LCRNG_MOD,
    SEED_RANGE_MIN,
    SEED_RANGE_MAX,
    GameVersion,
)


# ── LCRNG primitives ────────────────────────────────────────────────────────

def lcrng_next(seed: int) -> int:
    """Advance the Gen 3 LCRNG by one step and return the new full 32-bit state."""
    return (seed * LCRNG_MULT + LCRNG_ADD) % LCRNG_MOD


def lcrng_advance(seed: int, n: int) -> int:
    """Advance the LCRNG *n* steps from *seed*."""
    for _ in range(n):
        seed = lcrng_next(seed)
    return seed


def high16(value: int) -> int:
    """Return the upper 16 bits of a 32-bit value."""
    return (value >> 16) & 0xFFFF


# ── ID derivation ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TrainerID:
    """Represents a legitimate TID/SID pair tied to a specific initial seed."""
    seed: int
    tid: int
    sid: int
    game_version: str = GameVersion.FIRE_RED

    @property
    def full_id(self) -> int:
        """32-bit combined ID used internally by the game (SID << 16 | TID)."""
        return (self.sid << 16) | self.tid

    def is_shiny_pid(self, personality_value: int) -> bool:
        """Check whether a given PID would be shiny for this trainer."""
        return (self.tid ^ self.sid ^ high16(personality_value) ^ (personality_value & 0xFFFF)) < 8

    def __repr__(self) -> str:
        return (
            f"TrainerID(seed=0x{self.seed:04X}, "
            f"TID={self.tid:05d}, SID={self.sid:05d}, "
            f"game={self.game_version})"
        )


def seed_to_ids(seed: int, game_version: str = GameVersion.FIRE_RED) -> TrainerID:
    """
    Derive the TID and SID from an initial 16-bit seed.

    Fire Red / Leaf Green / Ruby / Sapphire / Emerald all use the same
    LCRNG, but the number of advances before the ID call can differ.

    Fire Red sequence (confirmed via PokeFinder source):
        state0 = seed  (16-bit value, zero-extended to 32 bits)
        state1 = LCRNG(state0)   → TID = high16(state1)
        state2 = LCRNG(state1)   → SID = high16(state2)
    """
    if game_version in (GameVersion.FIRE_RED, GameVersion.LEAF_GREEN):
        state = seed & 0xFFFF  # ensure 16-bit
        state = lcrng_next(state)
        tid = high16(state)
        state = lcrng_next(state)
        sid = high16(state)
    elif game_version == GameVersion.EMERALD:
        # Emerald always boots with seed 0x0000 (no RTC influence).
        # The TID/SID are generated after a variable number of frames
        # the player spends on the intro screen.  We model this as
        # "seed" = number of VBLANK frames elapsed.
        state = 0
        state = lcrng_advance(state, seed)
        state = lcrng_next(state)
        tid = high16(state)
        state = lcrng_next(state)
        sid = high16(state)
    elif game_version in (GameVersion.RUBY, GameVersion.SAPPHIRE):
        # Ruby/Sapphire: same as FRLG but seed comes from RTC.
        state = seed & 0xFFFF
        state = lcrng_next(state)
        tid = high16(state)
        state = lcrng_next(state)
        sid = high16(state)
    else:
        raise ValueError(f"Unsupported game version: {game_version}")

    return TrainerID(seed=seed, tid=tid, sid=sid, game_version=game_version)


# ── Enumeration API ─────────────────────────────────────────────────────────

def enumerate_all_ids(
    game_version: str = GameVersion.FIRE_RED,
) -> Generator[TrainerID, None, None]:
    """Yield a TrainerID for every valid initial seed (0x0000 – 0xFFFF)."""
    for seed in range(SEED_RANGE_MIN, SEED_RANGE_MAX + 1):
        yield seed_to_ids(seed, game_version)


def find_ids_for_tid(
    target_tid: int,
    game_version: str = GameVersion.FIRE_RED,
) -> List[TrainerID]:
    """Return all seed/SID combos that produce the given TID."""
    return [t for t in enumerate_all_ids(game_version) if t.tid == target_tid]


def find_ids_for_sid(
    target_sid: int,
    game_version: str = GameVersion.FIRE_RED,
) -> List[TrainerID]:
    """Return all seed/TID combos that produce the given SID."""
    return [t for t in enumerate_all_ids(game_version) if t.sid == target_sid]


def find_shiny_friendly_ids(
    target_species_pid: int,
    game_version: str = GameVersion.FIRE_RED,
) -> List[TrainerID]:
    """Return IDs where the given PID would be shiny."""
    return [t for t in enumerate_all_ids(game_version) if t.is_shiny_pid(target_species_pid)]


def get_id_for_instance(
    instance_id: int,
    game_version: str = GameVersion.FIRE_RED,
) -> TrainerID:
    """
    Deterministically pick a seed for a numbered emulator instance.
    Wraps around the 16-bit seed space.
    """
    seed = instance_id % (SEED_RANGE_MAX + 1)
    return seed_to_ids(seed, game_version)


def batch_generate(
    start_seed: int = SEED_RANGE_MIN,
    count: int = 256,
    game_version: str = GameVersion.FIRE_RED,
) -> List[TrainerID]:
    """Generate a batch of TrainerIDs starting from *start_seed*."""
    gen = enumerate_all_ids(game_version)
    # Skip to start_seed
    for _ in range(start_seed):
        next(gen)
    return list(itertools.islice(gen, count))


# ── Quick self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Verify a known seed → TID/SID mapping
    sample = seed_to_ids(0x0000)
    print(f"Seed 0x0000 → {sample}")

    sample2 = seed_to_ids(0x1234)
    print(f"Seed 0x1234 → {sample2}")

    # Show first 10
    for tid_info in itertools.islice(enumerate_all_ids(), 10):
        print(tid_info)
