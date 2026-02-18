"""Unit tests for modules.rng_pokemon – LCRNG, PID generation, shiny search."""
import pytest
from modules.rng_pokemon import (
    lcrng_next, lcrng_prev, lcrng_advance, lcrng_high16,
    generate_pid_method1, generate_pid_method2, generate_pid_method4,
    generate_ivs_method1,
    search_shiny_frames, find_nearest_shiny,
    determine_encounter_slot, recover_seed_from_pid,
    LCRNG_MULT, LCRNG_ADD,
)


class TestLCRNG:
    def test_next_deterministic(self):
        seed = 0x00000000
        result = lcrng_next(seed)
        assert result == LCRNG_ADD  # 0 * mult + add = add

    def test_next_known_value(self):
        seed = 0x00000001
        result = lcrng_next(seed)
        expected = (LCRNG_MULT + LCRNG_ADD) & 0xFFFF_FFFF
        assert result == expected

    def test_prev_reverses_next(self):
        for seed in [0, 1, 0x12345678, 0xDEADBEEF, 0xFFFFFFFF]:
            assert lcrng_prev(lcrng_next(seed)) == seed

    def test_next_reverses_prev(self):
        for seed in [0, 1, 0x12345678, 0xDEADBEEF, 0xFFFFFFFF]:
            assert lcrng_next(lcrng_prev(seed)) == seed

    def test_advance_zero(self):
        seed = 0xABCD1234
        assert lcrng_advance(seed, 0) == seed

    def test_advance_one(self):
        seed = 0xABCD1234
        assert lcrng_advance(seed, 1) == lcrng_next(seed)

    def test_advance_multiple(self):
        seed = 0x12345678
        manual = seed
        for _ in range(10):
            manual = lcrng_next(manual)
        assert lcrng_advance(seed, 10) == manual

    def test_high16(self):
        assert lcrng_high16(0xABCD0000) == 0xABCD
        assert lcrng_high16(0x0000FFFF) == 0x0000
        assert lcrng_high16(0xFFFF0000) == 0xFFFF

    def test_32bit_overflow(self):
        seed = 0xFFFFFFFF
        result = lcrng_next(seed)
        assert 0 <= result <= 0xFFFFFFFF


class TestPIDGeneration:
    def test_method1_returns_valid_pid(self):
        result = generate_pid_method1(0x12345678, tid=12345, sid=54321)
        assert 0 <= result.pid <= 0xFFFFFFFF
        assert 0 <= result.nature <= 24
        assert result.ability in (0, 1)
        assert result.frames_used == 2

    def test_method2_returns_valid_pid(self):
        result = generate_pid_method2(0x12345678, tid=12345, sid=54321)
        assert 0 <= result.pid <= 0xFFFFFFFF
        assert result.frames_used == 3

    def test_method4_returns_valid_pid(self):
        result = generate_pid_method4(0x12345678, tid=12345, sid=54321)
        assert 0 <= result.pid <= 0xFFFFFFFF
        assert result.frames_used == 3

    def test_shiny_detection(self):
        # Brute-force a known shiny: TID=0, SID=0 → PID where high^low < 8
        result = generate_pid_method1(0, tid=0, sid=0)
        # Verify shiny math is consistent
        pid = result.pid
        sv = 0 ^ 0 ^ (pid >> 16) ^ (pid & 0xFFFF)
        assert result.is_shiny == (sv < 8)
        assert result.shiny_value == sv

    def test_nature_from_pid(self):
        result = generate_pid_method1(0x12345678, tid=0, sid=0)
        assert result.nature == result.pid % 25

    def test_different_seeds_different_pids(self):
        r1 = generate_pid_method1(0x00000000, tid=0, sid=0)
        r2 = generate_pid_method1(0x00000001, tid=0, sid=0)
        assert r1.pid != r2.pid


class TestIVGeneration:
    def test_ivs_in_range(self):
        result = generate_ivs_method1(0x12345678)
        for iv in result.ivs:
            assert 0 <= iv <= 31

    def test_total(self):
        result = generate_ivs_method1(0x12345678)
        assert result.total == sum(result.ivs)

    def test_perfect_check(self):
        # Extremely unlikely to be perfect from a random seed
        result = generate_ivs_method1(0x12345678)
        assert result.is_perfect == all(iv == 31 for iv in result.ivs)

    def test_deterministic(self):
        r1 = generate_ivs_method1(0xDEADBEEF)
        r2 = generate_ivs_method1(0xDEADBEEF)
        assert r1.ivs == r2.ivs


class TestShinySearch:
    def test_finds_shinies(self):
        results = search_shiny_frames(0, tid=0, sid=0, max_frames=100000)
        assert len(results) > 0
        for r in results:
            pid = r.pid
            sv = 0 ^ 0 ^ (pid >> 16) ^ (pid & 0xFFFF)
            assert sv < 8

    def test_respects_max_frames(self):
        results = search_shiny_frames(0, tid=0, sid=0, max_frames=100)
        for r in results:
            assert r.frame < 100

    def test_nature_filter(self):
        results = search_shiny_frames(
            0, tid=0, sid=0, max_frames=200000, target_nature=0)
        for r in results:
            assert r.nature == 0  # Hardy

    def test_min_iv_filter(self):
        results = search_shiny_frames(
            0, tid=0, sid=0, max_frames=200000, min_iv_total=100)
        for r in results:
            assert r.iv_total >= 100

    def test_find_nearest(self):
        result = find_nearest_shiny(0, tid=0, sid=0, max_frames=200000)
        assert result is not None
        assert result.frame >= 0


class TestEncounterSlot:
    def test_land_slot_range(self):
        for seed in [0, 0x1234, 0xFFFF]:
            slot, _ = determine_encounter_slot(seed, "land")
            assert 0 <= slot <= 11

    def test_water_slot_range(self):
        slot, _ = determine_encounter_slot(0x5678, "water")
        assert 0 <= slot <= 4

    def test_fishing_slot_ranges(self):
        slot, _ = determine_encounter_slot(0, "old_rod")
        assert 0 <= slot <= 1
        slot, _ = determine_encounter_slot(0, "good_rod")
        assert 0 <= slot <= 2
        slot, _ = determine_encounter_slot(0, "super_rod")
        assert 0 <= slot <= 4

    def test_deterministic(self):
        s1, _ = determine_encounter_slot(0xABCD, "land")
        s2, _ = determine_encounter_slot(0xABCD, "land")
        assert s1 == s2


class TestSeedRecovery:
    def test_recover_known_pid(self):
        # Generate a PID, then try to recover the seed
        seed = 0x12345678
        pid_result = generate_pid_method1(seed, tid=0, sid=0)
        recovered = recover_seed_from_pid(pid_result.pid, tid=0, sid=0)
        # The original seed (2 steps before PID generation) should be recoverable
        assert len(recovered) > 0
