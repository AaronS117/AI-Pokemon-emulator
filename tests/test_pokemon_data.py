"""Unit tests for modules.pokemon_data – Pokémon data decryption."""
import struct
import pytest
from modules.pokemon_data import (
    decode_pokemon, verify_checksum, _decrypt_substructs, _decode_string,
    SUBSTRUCT_ORDER, NATURES, HIDDEN_POWER_TYPES,
    Pokemon, GrowthSubstruct, AttacksSubstruct, EVConditionSubstruct, MiscSubstruct,
    BOX_POKEMON_SIZE, PARTY_POKEMON_SIZE, HEADER_SIZE, ENCRYPTED_BLOCK_SIZE,
)


def _build_raw_pokemon(
    pv=0x12345678, ot_id=0x00010002,
    species=25, item=4, exp=1000, friendship=70,
    moves=(33, 45, 0, 0), pp=(35, 25, 0, 0),
    hp_ev=10, atk_ev=20, def_ev=0, spd_ev=0, spa_ev=0, spd_ev2=0,
    iv_egg_ability=0x1F1F1F1F,  # packed IVs
    level=25, current_hp=60, max_hp=60,
    attack=40, defense=30, speed=50, sp_attack=35, sp_defense=35,
    is_party=True,
):
    """Build a synthetic raw Pokémon byte array for testing."""
    key = pv ^ ot_id

    # Header (32 bytes)
    header = struct.pack("<II", pv, ot_id)
    header += b'\xFF' * 10  # nickname (terminated)
    header += struct.pack("<H", 0x0201)  # language
    header += b'\xFF' * 7   # OT name
    header += bytes([0])    # markings
    # We'll compute checksum after building substructs
    header += struct.pack("<H", 0)  # placeholder checksum
    header += b'\x00\x00'  # padding
    assert len(header) == 32

    # Build substructures (each 12 bytes, unencrypted)
    # Growth (index 0)
    growth = struct.pack("<HHI", species, item, exp)
    growth += struct.pack("<BB", 0, friendship)
    growth += struct.pack("<h", 0)
    assert len(growth) == 12

    # Attacks (index 1)
    attacks = struct.pack("<HHHH", *moves)
    attacks += struct.pack("<BBBB", *pp)
    assert len(attacks) == 12

    # EVs/Condition (index 2)
    evs = struct.pack("<12B", hp_ev, atk_ev, def_ev, spd_ev, spa_ev, spd_ev2,
                      0, 0, 0, 0, 0, 0)
    assert len(evs) == 12

    # Misc (index 3)
    misc = struct.pack("<BB", 0, 0)  # pokerus, met_location
    misc += struct.pack("<H", 0)     # origins_info
    misc += struct.pack("<I", iv_egg_ability)
    misc += struct.pack("<I", 0)     # ribbons
    assert len(misc) == 12

    # Arrange substructures according to PV % 24 order
    order = SUBSTRUCT_ORDER[pv % 24]
    substruct_map = {0: growth, 1: attacks, 2: evs, 3: misc}
    ordered = bytearray()
    for pos in range(4):
        # order[pos] tells us which substruct_id is at this position
        substruct_id = order[pos]
        ordered += substruct_map[substruct_id]
    assert len(ordered) == 48

    # Compute checksum on unencrypted data
    checksum = 0
    for i in range(0, 48, 2):
        checksum = (checksum + struct.unpack_from("<H", ordered, i)[0]) & 0xFFFF

    # Patch checksum into header
    header = header[:28] + struct.pack("<H", checksum) + header[30:]

    # Encrypt
    encrypted = bytearray(48)
    for i in range(0, 48, 4):
        word = struct.unpack_from("<I", ordered, i)[0]
        struct.pack_into("<I", encrypted, i, word ^ key)

    raw = header + bytes(encrypted)
    assert len(raw) == 80

    if is_party:
        # Battle stats (20 bytes)
        battle = struct.pack("<I", 0)  # status condition
        battle += struct.pack("<BB", level, 0)  # level, pokerus_remaining
        battle += struct.pack("<HHHHHHH", current_hp, max_hp,
                              attack, defense, speed, sp_attack, sp_defense)
        assert len(battle) == 20
        raw += battle

    return bytes(raw)


class TestDecodeBasic:
    def test_empty_data_returns_empty_pokemon(self):
        p = decode_pokemon(b'\x00' * 100)
        assert p.species_id == 0

    def test_too_short_returns_empty(self):
        p = decode_pokemon(b'\x00' * 10)
        assert p.species_id == 0

    def test_decode_synthetic_pokemon(self):
        raw = _build_raw_pokemon(species=25, level=25)
        p = decode_pokemon(raw, is_party=True)
        assert p.species_id == 25
        assert p.level == 25
        assert p.personality_value == 0x12345678

    def test_decode_box_pokemon(self):
        raw = _build_raw_pokemon(is_party=False)
        p = decode_pokemon(raw, is_party=False)
        assert p.species_id == 25
        assert p.level == 0  # No battle stats for box Pokémon
        assert p.is_party is False


class TestShinyDetection:
    def test_non_shiny(self):
        # PV=0x12345678, TID=2, SID=1 → SV = 2^1^0x1234^0x5678 = far from 0
        raw = _build_raw_pokemon(pv=0x12345678, ot_id=0x00010002)
        p = decode_pokemon(raw)
        assert p.is_shiny is False

    def test_shiny_crafted(self):
        # Craft a shiny: TID=0, SID=0 → need PID where high^low < 8
        # PID = 0x00000000 → SV = 0^0^0^0 = 0 → shiny
        raw = _build_raw_pokemon(pv=0x00000000, ot_id=0x00000000)
        p = decode_pokemon(raw)
        assert p.is_shiny is True
        assert p.shiny_value == 0

    def test_shiny_value_math(self):
        raw = _build_raw_pokemon(pv=0xAABBCCDD, ot_id=0x11112222)
        p = decode_pokemon(raw)
        expected_sv = 0x2222 ^ 0x1111 ^ 0xAABB ^ 0xCCDD
        assert p.shiny_value == expected_sv
        assert p.is_shiny == (expected_sv < 8)


class TestNature:
    def test_nature_range(self):
        for pv in [0, 1, 24, 25, 100, 0xFFFFFFFF]:
            raw = _build_raw_pokemon(pv=pv)
            p = decode_pokemon(raw)
            assert 0 <= p.nature_id <= 24
            assert p.nature in NATURES

    def test_nature_deterministic(self):
        raw = _build_raw_pokemon(pv=0x12345678)
        p = decode_pokemon(raw)
        assert p.nature == NATURES[0x12345678 % 25]


class TestIVs:
    def test_ivs_extracted(self):
        # iv_egg_ability = 0x1F1F1F1F → specific IV pattern
        raw = _build_raw_pokemon(iv_egg_ability=0x1F1F1F1F)
        p = decode_pokemon(raw)
        # All IVs should be in range
        for iv in p.ivs:
            assert 0 <= iv <= 31

    def test_all_31s(self):
        # All 31s: bits 0-29 all set = 0x3FFFFFFF
        raw = _build_raw_pokemon(iv_egg_ability=0x3FFFFFFF)
        p = decode_pokemon(raw)
        assert p.ivs == (31, 31, 31, 31, 31, 31)
        assert p.iv_total == 186
        assert p.is_perfect_ivs is True

    def test_all_0s(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x00000000)
        p = decode_pokemon(raw)
        assert p.ivs == (0, 0, 0, 0, 0, 0)
        assert p.iv_total == 0

    def test_iv_string(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x3FFFFFFF)
        p = decode_pokemon(raw)
        s = p.iv_string()
        assert "HP:31" in s
        assert "Atk:31" in s


class TestEggFlag:
    def test_not_egg(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x3FFFFFFF)  # bit 30 = 0
        p = decode_pokemon(raw)
        assert p.is_egg is False

    def test_is_egg(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x7FFFFFFF)  # bit 30 = 1
        p = decode_pokemon(raw)
        assert p.is_egg is True


class TestAbility:
    def test_ability_bit_0(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x00000000)  # bit 31 = 0
        p = decode_pokemon(raw)
        assert p.ability_slot == 0

    def test_ability_bit_1(self):
        raw = _build_raw_pokemon(iv_egg_ability=0x80000000)  # bit 31 = 1
        p = decode_pokemon(raw)
        assert p.ability_slot == 1


class TestHiddenPower:
    def test_type_in_list(self):
        raw = _build_raw_pokemon()
        p = decode_pokemon(raw)
        assert p.hidden_power_type in HIDDEN_POWER_TYPES

    def test_power_range(self):
        raw = _build_raw_pokemon()
        p = decode_pokemon(raw)
        assert 30 <= p.hidden_power_power <= 70


class TestChecksum:
    def test_valid_checksum(self):
        raw = _build_raw_pokemon()
        assert verify_checksum(raw) is True

    def test_corrupted_fails(self):
        raw = bytearray(_build_raw_pokemon())
        raw[40] ^= 0xFF  # Corrupt a byte in the encrypted block
        assert verify_checksum(bytes(raw)) is False


class TestProperties:
    def test_tid_sid(self):
        raw = _build_raw_pokemon(ot_id=0x0003_0007)  # SID=3, TID=7
        p = decode_pokemon(raw)
        assert p.tid == 7
        assert p.sid == 3

    def test_held_item(self):
        raw = _build_raw_pokemon(item=4)
        p = decode_pokemon(raw)
        assert p.held_item == 4

    def test_experience(self):
        raw = _build_raw_pokemon(exp=1000)
        p = decode_pokemon(raw)
        assert p.experience == 1000

    def test_friendship(self):
        raw = _build_raw_pokemon(friendship=70)
        p = decode_pokemon(raw)
        assert p.friendship == 70

    def test_moves(self):
        raw = _build_raw_pokemon(moves=(33, 45, 0, 0))
        p = decode_pokemon(raw)
        assert p.moves == [33, 45, 0, 0]

    def test_evs(self):
        raw = _build_raw_pokemon(hp_ev=10, atk_ev=20)
        p = decode_pokemon(raw)
        assert p.evs[0] == 10
        assert p.evs[1] == 20

    def test_summary(self):
        raw = _build_raw_pokemon(species=25, level=25)
        p = decode_pokemon(raw)
        s = p.summary()
        assert "#25" in s
        assert "Lv.25" in s


class TestStringDecode:
    def test_empty(self):
        assert _decode_string(b'\xFF') == ""

    def test_known_chars(self):
        # 0xBB = A, 0xBC = B, 0xBD = C
        assert _decode_string(bytes([0xBB, 0xBC, 0xBD, 0xFF])) == "ABC"

    def test_numbers(self):
        # 0xA1 = 0, 0xA2 = 1, ... 0xAA = 9
        assert _decode_string(bytes([0xA1, 0xA2, 0xA3, 0xFF])) == "012"


class TestSubstructOrder:
    def test_24_orders(self):
        assert len(SUBSTRUCT_ORDER) == 24

    def test_each_order_has_all_4(self):
        for order in SUBSTRUCT_ORDER:
            assert sorted(order) == [0, 1, 2, 3]

    def test_all_unique(self):
        seen = set()
        for order in SUBSTRUCT_ORDER:
            seen.add(order)
        assert len(seen) == 24
