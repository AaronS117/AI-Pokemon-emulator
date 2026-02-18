"""
rng_pokemon – RNG manipulation and seed prediction for Gen 3.

Integrates PokeFinder-style RNG logic for:
  - LCRNG (Linear Congruential RNG) seed prediction
  - Frame-precise shiny target calculation
  - Wild encounter slot determination
  - IV spread prediction from seed
  - Method 1/2/4 PID generation
  - Optimal seed search for specific shiny targets
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot

logger = logging.getLogger(__name__)


# ── Gen 3 LCRNG Constants ──────────────────────────────────────────────────

LCRNG_MULT = 0x41C64E6D
LCRNG_ADD = 0x00006073
LCRNG_MULT_INV = 0xEEB9EB65  # Inverse multiplier for reverse stepping
LCRNG_ADD_INV = 0x0A3561A1   # Inverse addend


# ── LCRNG Functions ─────────────────────────────────────────────────────────

def lcrng_next(seed: int) -> int:
    """Advance the LCRNG by one step."""
    return (seed * LCRNG_MULT + LCRNG_ADD) & 0xFFFF_FFFF


def lcrng_prev(seed: int) -> int:
    """Reverse the LCRNG by one step."""
    return (seed * LCRNG_MULT_INV + LCRNG_ADD_INV) & 0xFFFF_FFFF


def lcrng_advance(seed: int, frames: int) -> int:
    """Advance the LCRNG by N frames."""
    for _ in range(frames):
        seed = lcrng_next(seed)
    return seed


def lcrng_high16(seed: int) -> int:
    """Extract the high 16 bits (the 'random number')."""
    return (seed >> 16) & 0xFFFF


# ── PID Generation Methods ─────────────────────────────────────────────────

@dataclass
class PIDResult:
    """Result of a PID generation."""
    pid: int
    seed_after: int
    frames_used: int
    nature: int
    ability: int
    gender_value: int
    is_shiny: bool = False
    shiny_value: int = 0


def generate_pid_method1(seed: int, tid: int, sid: int) -> PIDResult:
    """
    Generate a PID using Method 1 (most common for wild encounters).

    Method 1: seed → high16 = PID_low, next → high16 = PID_high
    """
    s1 = lcrng_next(seed)
    s2 = lcrng_next(s1)
    pid_low = lcrng_high16(s1)
    pid_high = lcrng_high16(s2)
    pid = (pid_high << 16) | pid_low

    sv = tid ^ sid ^ pid_high ^ pid_low
    return PIDResult(
        pid=pid,
        seed_after=s2,
        frames_used=2,
        nature=pid % 25,
        ability=pid & 1,
        gender_value=pid & 0xFF,
        is_shiny=sv < 8,
        shiny_value=sv,
    )


def generate_pid_method2(seed: int, tid: int, sid: int) -> PIDResult:
    """
    Generate a PID using Method 2 (some static encounters).

    Method 2: seed → high16 = PID_low, next → (skip), next → high16 = PID_high
    """
    s1 = lcrng_next(seed)
    s2 = lcrng_next(s1)
    s3 = lcrng_next(s2)
    pid_low = lcrng_high16(s1)
    pid_high = lcrng_high16(s3)
    pid = (pid_high << 16) | pid_low

    sv = tid ^ sid ^ pid_high ^ pid_low
    return PIDResult(
        pid=pid,
        seed_after=s3,
        frames_used=3,
        nature=pid % 25,
        ability=pid & 1,
        gender_value=pid & 0xFF,
        is_shiny=sv < 8,
        shiny_value=sv,
    )


def generate_pid_method4(seed: int, tid: int, sid: int) -> PIDResult:
    """
    Generate a PID using Method 4 (some wild encounters).

    Method 4: seed → (skip), next → high16 = PID_low, next → high16 = PID_high
    """
    s1 = lcrng_next(seed)
    s2 = lcrng_next(s1)
    s3 = lcrng_next(s2)
    pid_low = lcrng_high16(s2)
    pid_high = lcrng_high16(s3)
    pid = (pid_high << 16) | pid_low

    sv = tid ^ sid ^ pid_high ^ pid_low
    return PIDResult(
        pid=pid,
        seed_after=s3,
        frames_used=3,
        nature=pid % 25,
        ability=pid & 1,
        gender_value=pid & 0xFF,
        is_shiny=sv < 8,
        shiny_value=sv,
    )


# ── IV Generation ───────────────────────────────────────────────────────────

@dataclass
class IVResult:
    """Result of IV generation from RNG."""
    hp: int
    attack: int
    defense: int
    speed: int
    sp_attack: int
    sp_defense: int
    seed_after: int

    @property
    def ivs(self) -> Tuple[int, ...]:
        return (self.hp, self.attack, self.defense,
                self.speed, self.sp_attack, self.sp_defense)

    @property
    def total(self) -> int:
        return sum(self.ivs)

    @property
    def is_perfect(self) -> bool:
        return all(iv == 31 for iv in self.ivs)


def generate_ivs_method1(seed: int) -> IVResult:
    """
    Generate IVs using Method 1.

    After PID generation (2 calls), IVs use 2 more calls:
      call 3 → high16 bits [0:4]=HP, [5:9]=Atk, [10:14]=Def
      call 4 → high16 bits [0:4]=Spd, [5:9]=SpA, [10:14]=SpD
    """
    s1 = lcrng_next(seed)
    s2 = lcrng_next(s1)
    iv1 = lcrng_high16(s1)
    iv2 = lcrng_high16(s2)

    return IVResult(
        hp=iv1 & 0x1F,
        attack=(iv1 >> 5) & 0x1F,
        defense=(iv1 >> 10) & 0x1F,
        speed=iv2 & 0x1F,
        sp_attack=(iv2 >> 5) & 0x1F,
        sp_defense=(iv2 >> 10) & 0x1F,
        seed_after=s2,
    )


# ── Encounter Slot Determination ────────────────────────────────────────────

# Wild encounter slot probabilities (cumulative)
WILD_SLOTS_LAND = [20, 40, 50, 60, 70, 80, 85, 90, 94, 98, 99, 100]
WILD_SLOTS_WATER = [60, 90, 95, 99, 100]
WILD_SLOTS_FISHING_OLD = [70, 100]
WILD_SLOTS_FISHING_GOOD = [60, 80, 100]
WILD_SLOTS_FISHING_SUPER = [40, 80, 95, 99, 100]
WILD_SLOTS_ROCK_SMASH = [60, 90, 95, 99, 100]


def determine_encounter_slot(
    seed: int,
    encounter_type: str = "land",
) -> Tuple[int, int]:
    """
    Determine which encounter slot is selected.

    Args:
        seed: Current RNG seed.
        encounter_type: "land", "water", "old_rod", "good_rod", "super_rod", "rock_smash"

    Returns:
        (slot_index, seed_after)
    """
    s = lcrng_next(seed)
    rand = lcrng_high16(s) % 100

    slot_table = {
        "land": WILD_SLOTS_LAND,
        "water": WILD_SLOTS_WATER,
        "old_rod": WILD_SLOTS_FISHING_OLD,
        "good_rod": WILD_SLOTS_FISHING_GOOD,
        "super_rod": WILD_SLOTS_FISHING_SUPER,
        "rock_smash": WILD_SLOTS_ROCK_SMASH,
    }

    slots = slot_table.get(encounter_type, WILD_SLOTS_LAND)
    for i, threshold in enumerate(slots):
        if rand < threshold:
            return (i, s)

    return (len(slots) - 1, s)


# ── Shiny Frame Search ─────────────────────────────────────────────────────

@dataclass
class ShinyFrame:
    """A frame that produces a shiny Pokémon."""
    frame: int
    seed: int
    pid: int
    nature: int
    ability: int
    ivs: Tuple[int, ...]
    iv_total: int
    method: str


def search_shiny_frames(
    initial_seed: int,
    tid: int,
    sid: int,
    max_frames: int = 100000,
    method: str = "method1",
    min_iv_total: int = 0,
    target_nature: Optional[int] = None,
) -> List[ShinyFrame]:
    """
    Search for frames that produce shiny Pokémon.

    Args:
        initial_seed: Starting RNG seed.
        tid: Trainer ID.
        sid: Secret ID.
        max_frames: Maximum frames to search.
        method: PID generation method ("method1", "method2", "method4").
        min_iv_total: Minimum IV total to include.
        target_nature: If set, only include this nature (0-24).

    Returns:
        List of ShinyFrame results.
    """
    results = []
    seed = initial_seed

    pid_generators = {
        "method1": generate_pid_method1,
        "method2": generate_pid_method2,
        "method4": generate_pid_method4,
    }
    gen_pid = pid_generators.get(method, generate_pid_method1)

    for frame in range(max_frames):
        pid_result = gen_pid(seed, tid, sid)

        if pid_result.is_shiny:
            # Generate IVs from the seed after PID
            iv_result = generate_ivs_method1(pid_result.seed_after)

            if iv_result.total >= min_iv_total:
                if target_nature is None or pid_result.nature == target_nature:
                    results.append(ShinyFrame(
                        frame=frame,
                        seed=seed,
                        pid=pid_result.pid,
                        nature=pid_result.nature,
                        ability=pid_result.ability,
                        ivs=iv_result.ivs,
                        iv_total=iv_result.total,
                        method=method,
                    ))

        seed = lcrng_next(seed)

    return results


def find_nearest_shiny(
    initial_seed: int,
    tid: int,
    sid: int,
    max_frames: int = 100000,
) -> Optional[ShinyFrame]:
    """Find the nearest shiny frame from the current seed."""
    results = search_shiny_frames(initial_seed, tid, sid, max_frames)
    return results[0] if results else None


# ── Seed Recovery ───────────────────────────────────────────────────────────

def recover_seed_from_pid(pid: int, tid: int, sid: int) -> List[int]:
    """
    Attempt to recover the RNG seed that produced a given PID.

    Brute-forces the low 16 bits of the seed to find matches.
    """
    pid_low = pid & 0xFFFF
    pid_high = (pid >> 16) & 0xFFFF
    results = []

    for low in range(0x10000):
        seed = (pid_low << 16) | low
        prev_seed = lcrng_prev(seed)
        next_seed = lcrng_next(seed)
        next_high = lcrng_high16(next_seed)

        if next_high == pid_high:
            results.append(lcrng_prev(prev_seed))

    return results


# ── Live RNG Reading ────────────────────────────────────────────────────────

def read_current_rng(bot: GameBot, game_version: str = "firered") -> int:
    """Read the current RNG value from the emulator."""
    from modules.symbol_tables import get_symbols
    symbols = get_symbols(game_version)
    addr = symbols["gRngValue"][0]
    return bot.read_u32(addr)


def predict_next_shiny(
    bot: GameBot,
    tid: int,
    sid: int,
    game_version: str = "firered",
    max_frames: int = 50000,
) -> Optional[ShinyFrame]:
    """Read current RNG and predict the next shiny frame."""
    seed = read_current_rng(bot, game_version)
    return find_nearest_shiny(seed, tid, sid, max_frames)


def frames_until_shiny(
    bot: GameBot,
    tid: int,
    sid: int,
    game_version: str = "firered",
    max_frames: int = 100000,
) -> int:
    """Calculate how many frames until the next shiny encounter."""
    result = predict_next_shiny(bot, tid, sid, game_version, max_frames)
    return result.frame if result else -1
