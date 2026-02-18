"""Unit tests for modules.symbol_tables – multi-game symbol lookups."""
import pytest
from modules.symbol_tables import (
    get_symbols, get_sb1_offsets, get_sb2_offsets,
    detect_game_version, is_frlg, is_rse, is_emerald,
    GAME_DATA, ROM_GAME_CODES,
    FIRERED_SYMBOLS, EMERALD_SYMBOLS, RUBY_SYMBOLS,
    FRLG_SB1_OFFSETS, EMERALD_SB1_OFFSETS, RS_SB1_OFFSETS,
)


class TestGameDetection:
    def test_firered(self):
        assert detect_game_version("BPRE") == "firered"

    def test_leafgreen(self):
        assert detect_game_version("BPGE") == "leafgreen"

    def test_emerald(self):
        assert detect_game_version("BPEE") == "emerald"

    def test_ruby(self):
        assert detect_game_version("AXVE") == "ruby"

    def test_sapphire(self):
        assert detect_game_version("AXPE") == "sapphire"

    def test_unknown_defaults_firered(self):
        assert detect_game_version("XXXX") == "firered"

    def test_case_insensitive(self):
        assert detect_game_version("bpre") == "firered"

    def test_strips_whitespace(self):
        assert detect_game_version("BPRE  ") == "firered"


class TestGameClassification:
    def test_frlg(self):
        assert is_frlg("firered") is True
        assert is_frlg("leafgreen") is True
        assert is_frlg("emerald") is False
        assert is_frlg("ruby") is False

    def test_rse(self):
        assert is_rse("ruby") is True
        assert is_rse("sapphire") is True
        assert is_rse("emerald") is True
        assert is_rse("firered") is False

    def test_emerald(self):
        assert is_emerald("emerald") is True
        assert is_emerald("ruby") is False
        assert is_emerald("firered") is False


class TestSymbolTables:
    @pytest.mark.parametrize("game", list(GAME_DATA.keys()))
    def test_get_symbols(self, game):
        syms = get_symbols(game)
        assert isinstance(syms, dict)
        assert len(syms) > 0

    @pytest.mark.parametrize("game", list(GAME_DATA.keys()))
    def test_get_sb1_offsets(self, game):
        offsets = get_sb1_offsets(game)
        assert isinstance(offsets, dict)
        assert "money" in offsets
        assert "daycare" in offsets

    def test_invalid_game_raises(self):
        with pytest.raises(ValueError):
            get_symbols("pokemon_yellow")
        with pytest.raises(ValueError):
            get_sb1_offsets("pokemon_yellow")

    def test_frlg_has_sb2(self):
        sb2 = get_sb2_offsets("firered")
        assert isinstance(sb2, dict)
        assert len(sb2) > 0

    def test_rse_sb2_empty(self):
        sb2 = get_sb2_offsets("emerald")
        assert sb2 == {}


class TestCriticalSymbols:
    """Verify essential symbols exist in every game's table."""

    ESSENTIAL = ["gMain", "gSaveBlock1Ptr", "gPlayerParty",
                 "gEnemyParty", "gBattleOutcome", "gRngValue"]

    @pytest.mark.parametrize("game", list(GAME_DATA.keys()))
    def test_essential_symbols_present(self, game):
        syms = get_symbols(game)
        for name in self.ESSENTIAL:
            assert name in syms, f"{name} missing from {game}"

    @pytest.mark.parametrize("game", list(GAME_DATA.keys()))
    def test_symbol_addresses_valid(self, game):
        syms = get_symbols(game)
        for name, (addr, size) in syms.items():
            assert addr > 0, f"{name} in {game} has zero address"
            assert size > 0, f"{name} in {game} has zero size"
            # GBA addresses should be in valid memory regions
            bank = addr >> 24
            assert bank in (0x02, 0x03, 0x08), \
                f"{name} in {game} has unusual bank 0x{bank:02X}"


class TestSB1Offsets:
    ESSENTIAL_OFFSETS = ["money", "player_id", "daycare", "flags"]

    @pytest.mark.parametrize("game", list(GAME_DATA.keys()))
    def test_essential_offsets_present(self, game):
        offsets = get_sb1_offsets(game)
        for key in self.ESSENTIAL_OFFSETS:
            assert key in offsets, f"{key} missing from {game} SB1"

    def test_firered_bag_pockets(self):
        offsets = get_sb1_offsets("firered")
        assert "bag_items" in offsets
        assert "bag_key_items" in offsets
        assert "bag_pokeballs" in offsets

    def test_emerald_feebas_seed(self):
        offsets = get_sb1_offsets("emerald")
        assert "feebas_seed" in offsets

    def test_rs_feebas_seed(self):
        offsets = get_sb1_offsets("ruby")
        assert "feebas_seed" in offsets
