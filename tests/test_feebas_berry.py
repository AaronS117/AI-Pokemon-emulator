"""Unit tests for modules.feebas_berry – Feebas tile calc, berry data."""
import pytest
from modules.feebas_berry import (
    calculate_feebas_tiles, FeebasTile,
    BerryType, BEAUTY_BERRIES, PokeblockColor,
    FEEBAS_SEED_OFFSET_EMERALD, FEEBAS_SEED_OFFSET_RS,
)


class TestFeebasTileCalculation:
    def test_returns_6_tiles(self):
        tiles = calculate_feebas_tiles(0x1234)
        assert len(tiles) == 6

    def test_all_tiles_are_feebas_tile(self):
        tiles = calculate_feebas_tiles(0xABCD)
        for t in tiles:
            assert isinstance(t, FeebasTile)
            assert t.x >= 0
            assert t.y >= 0

    def test_deterministic(self):
        t1 = calculate_feebas_tiles(0x5678)
        t2 = calculate_feebas_tiles(0x5678)
        assert [(t.x, t.y) for t in t1] == [(t.x, t.y) for t in t2]

    def test_different_seeds_different_tiles(self):
        t1 = calculate_feebas_tiles(0x0001)
        t2 = calculate_feebas_tiles(0x0002)
        coords1 = [(t.x, t.y) for t in t1]
        coords2 = [(t.x, t.y) for t in t2]
        assert coords1 != coords2

    def test_zero_seed(self):
        tiles = calculate_feebas_tiles(0x0000)
        assert len(tiles) == 6

    def test_max_seed(self):
        tiles = calculate_feebas_tiles(0xFFFF)
        assert len(tiles) == 6

    def test_custom_fishing_spots(self):
        spots = [(5, 10), (6, 10), (7, 10), (8, 10), (9, 10),
                 (5, 20), (6, 20), (7, 20), (8, 20), (9, 20)]
        tiles = calculate_feebas_tiles(0x1234, fishing_spots=spots)
        assert len(tiles) == 6
        for t in tiles:
            assert (t.x, t.y) in spots

    def test_empty_spots_returns_empty(self):
        tiles = calculate_feebas_tiles(0x1234, fishing_spots=[])
        assert len(tiles) == 0

    def test_tile_str(self):
        t = FeebasTile(x=5, y=10)
        assert "(5, 10)" in str(t)


class TestSeedOffsets:
    def test_emerald_offset(self):
        assert FEEBAS_SEED_OFFSET_EMERALD == 0x2E6A

    def test_rs_offset(self):
        assert FEEBAS_SEED_OFFSET_RS == 0x2DD6


class TestBerryData:
    def test_berry_types_exist(self):
        assert len(BerryType) > 0

    def test_beauty_berries_are_valid(self):
        for berry in BEAUTY_BERRIES:
            assert isinstance(berry, BerryType)

    def test_beauty_berries_not_empty(self):
        assert len(BEAUTY_BERRIES) > 0

    def test_pokeblock_colors(self):
        assert PokeblockColor.BLUE is not None
        assert PokeblockColor.RED is not None

    def test_known_berries(self):
        assert BerryType.CHERI is not None
        assert BerryType.ORAN is not None
        assert BerryType.WIKI is not None
        assert BerryType.PAMTRE is not None
