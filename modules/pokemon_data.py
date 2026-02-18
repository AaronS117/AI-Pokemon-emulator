"""
pokemon_data – Full Gen 3 Pokémon data structure decryption.

Implements the complete Gen 3 Pokémon data substructure decryption
as documented in Bulbapedia and used by pokebot-gen3/pret decompilation.

Handles:
  - Personality Value → substructure order lookup
  - XOR decryption of the 48-byte encrypted block
  - Growth, Attacks, EVs/Condition, Misc substructure parsing
  - IV extraction (packed 30-bit field)
  - Nature, ability, gender, shiny, hidden power calculation
  - Party Pokémon battle stats (level, HP, stats)
  - Full party and box Pokémon reading
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot


# ── Constants ───────────────────────────────────────────────────────────────

# Substructure order lookup table (PV % 24 → order of G, A, E, M)
# G=Growth(0), A=Attacks(1), E=EVs/Condition(2), M=Misc(3)
SUBSTRUCT_ORDER = [
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2),
    (0, 2, 3, 1), (0, 3, 2, 1), (1, 0, 2, 3), (1, 0, 3, 2),
    (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2),
    (2, 3, 0, 1), (3, 2, 0, 1), (1, 2, 3, 0), (1, 3, 2, 0),
    (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
]

# Nature names (PV % 25)
NATURES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]

# Nature stat modifiers: (boosted_stat, reduced_stat) where 0=Atk,1=Def,2=Spd,3=SpA,4=SpD
# Neutral natures have same boost/reduce
NATURE_MODIFIERS = {
    "Hardy": (0, 0), "Lonely": (0, 1), "Brave": (0, 2), "Adamant": (0, 3), "Naughty": (0, 4),
    "Bold": (1, 0), "Docile": (1, 1), "Relaxed": (1, 2), "Impish": (1, 3), "Lax": (1, 4),
    "Timid": (2, 0), "Hasty": (2, 1), "Serious": (2, 2), "Jolly": (2, 3), "Naive": (2, 4),
    "Modest": (3, 0), "Mild": (3, 1), "Quiet": (3, 2), "Bashful": (3, 3), "Rash": (3, 4),
    "Calm": (4, 0), "Gentle": (4, 1), "Sassy": (4, 2), "Careful": (4, 3), "Quirky": (4, 4),
}

# Hidden Power type lookup
HIDDEN_POWER_TYPES = [
    "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug",
    "Ghost", "Steel", "Fire", "Water", "Grass", "Electric",
    "Psychic", "Ice", "Dragon", "Dark",
]

# Species gender ratios (255 = genderless, 254 = always female, 0 = always male)
# Only a subset; full table would come from ROM data
GENDER_THRESHOLDS: Dict[int, int] = {
    # species_id: threshold (PV & 0xFF < threshold → female)
    # Default is 127 (50/50). Special cases:
    # Genderless: Magnemite line, Voltorb line, Staryu line, Unown, etc.
}

# Box Pokémon size (encrypted data only, no battle stats)
BOX_POKEMON_SIZE = 80
# Party Pokémon size (box data + 20 bytes of battle stats)
PARTY_POKEMON_SIZE = 100
# Encrypted substructure block size
ENCRYPTED_BLOCK_SIZE = 48
# Each substructure is 12 bytes
SUBSTRUCT_SIZE = 12
# Header size before encrypted block
HEADER_SIZE = 32


# ── Stat IDs ────────────────────────────────────────────────────────────────

class Stat(IntEnum):
    HP = 0
    ATTACK = 1
    DEFENSE = 2
    SPEED = 3
    SP_ATTACK = 4
    SP_DEFENSE = 5


# ── Substructure data classes ───────────────────────────────────────────────

@dataclass
class GrowthSubstruct:
    """Growth substructure (12 bytes)."""
    species: int = 0
    item: int = 0
    experience: int = 0
    pp_bonuses: int = 0
    friendship: int = 0
    unknown: int = 0


@dataclass
class AttacksSubstruct:
    """Attacks substructure (12 bytes)."""
    move1: int = 0
    move2: int = 0
    move3: int = 0
    move4: int = 0
    pp1: int = 0
    pp2: int = 0
    pp3: int = 0
    pp4: int = 0

    @property
    def moves(self) -> List[int]:
        return [self.move1, self.move2, self.move3, self.move4]

    @property
    def pp(self) -> List[int]:
        return [self.pp1, self.pp2, self.pp3, self.pp4]


@dataclass
class EVConditionSubstruct:
    """EVs and Condition substructure (12 bytes)."""
    hp_ev: int = 0
    attack_ev: int = 0
    defense_ev: int = 0
    speed_ev: int = 0
    sp_attack_ev: int = 0
    sp_defense_ev: int = 0
    coolness: int = 0
    beauty: int = 0
    cuteness: int = 0
    smartness: int = 0
    toughness: int = 0
    feel: int = 0

    @property
    def evs(self) -> Tuple[int, ...]:
        return (self.hp_ev, self.attack_ev, self.defense_ev,
                self.speed_ev, self.sp_attack_ev, self.sp_defense_ev)

    @property
    def ev_total(self) -> int:
        return sum(self.evs)


@dataclass
class MiscSubstruct:
    """Miscellaneous substructure (12 bytes)."""
    pokerus: int = 0
    met_location: int = 0
    origins_info: int = 0  # u16: level met, game of origin, ball
    iv_egg_ability: int = 0  # u32: packed IVs + egg flag + ability bit
    ribbons_obedience: int = 0  # u32

    @property
    def hp_iv(self) -> int:
        return self.iv_egg_ability & 0x1F

    @property
    def attack_iv(self) -> int:
        return (self.iv_egg_ability >> 5) & 0x1F

    @property
    def defense_iv(self) -> int:
        return (self.iv_egg_ability >> 10) & 0x1F

    @property
    def speed_iv(self) -> int:
        return (self.iv_egg_ability >> 15) & 0x1F

    @property
    def sp_attack_iv(self) -> int:
        return (self.iv_egg_ability >> 20) & 0x1F

    @property
    def sp_defense_iv(self) -> int:
        return (self.iv_egg_ability >> 25) & 0x1F

    @property
    def ivs(self) -> Tuple[int, ...]:
        return (self.hp_iv, self.attack_iv, self.defense_iv,
                self.speed_iv, self.sp_attack_iv, self.sp_defense_iv)

    @property
    def is_egg(self) -> bool:
        return bool(self.iv_egg_ability & (1 << 30))

    @property
    def ability_bit(self) -> int:
        return (self.iv_egg_ability >> 31) & 1

    @property
    def level_met(self) -> int:
        return self.origins_info & 0x7F

    @property
    def game_of_origin(self) -> int:
        return (self.origins_info >> 7) & 0xF

    @property
    def ball_caught(self) -> int:
        return (self.origins_info >> 11) & 0xF


# ── Full Pokémon data class ─────────────────────────────────────────────────

@dataclass
class Pokemon:
    """Complete decoded Pokémon data."""
    # Header (32 bytes)
    personality_value: int = 0
    ot_id: int = 0
    nickname: str = ""
    language: int = 0
    ot_name: str = ""
    markings: int = 0
    checksum: int = 0

    # Decoded substructures
    growth: GrowthSubstruct = field(default_factory=GrowthSubstruct)
    attacks: AttacksSubstruct = field(default_factory=AttacksSubstruct)
    ev_condition: EVConditionSubstruct = field(default_factory=EVConditionSubstruct)
    misc: MiscSubstruct = field(default_factory=MiscSubstruct)

    # Battle stats (party only, 20 bytes)
    status_condition: int = 0
    level: int = 0
    pokerus_remaining: int = 0
    current_hp: int = 0
    max_hp: int = 0
    attack: int = 0
    defense: int = 0
    speed: int = 0
    sp_attack: int = 0
    sp_defense: int = 0

    # Whether this is from party (has battle stats) or box
    is_party: bool = False

    # Raw data for re-encryption
    _raw: bytes = b""

    @property
    def tid(self) -> int:
        return self.ot_id & 0xFFFF

    @property
    def sid(self) -> int:
        return (self.ot_id >> 16) & 0xFFFF

    @property
    def species_id(self) -> int:
        return self.growth.species

    @property
    def held_item(self) -> int:
        return self.growth.item

    @property
    def nature(self) -> str:
        return NATURES[self.personality_value % 25]

    @property
    def nature_id(self) -> int:
        return self.personality_value % 25

    @property
    def is_shiny(self) -> bool:
        p = self.personality_value
        return (self.tid ^ self.sid ^ (p >> 16) ^ (p & 0xFFFF)) < 8

    @property
    def shiny_value(self) -> int:
        p = self.personality_value
        return self.tid ^ self.sid ^ (p >> 16) ^ (p & 0xFFFF)

    @property
    def is_egg(self) -> bool:
        return self.misc.is_egg

    @property
    def ability_slot(self) -> int:
        return self.misc.ability_bit

    @property
    def ivs(self) -> Tuple[int, ...]:
        return self.misc.ivs

    @property
    def iv_total(self) -> int:
        return sum(self.ivs)

    @property
    def is_perfect_ivs(self) -> bool:
        return all(iv == 31 for iv in self.ivs)

    @property
    def evs(self) -> Tuple[int, ...]:
        return self.ev_condition.evs

    @property
    def gender(self) -> str:
        """Determine gender from PV and species gender ratio."""
        threshold = GENDER_THRESHOLDS.get(self.species_id, 127)
        if threshold == 255:
            return "Genderless"
        if threshold == 254:
            return "Female"
        if threshold == 0:
            return "Male"
        return "Female" if (self.personality_value & 0xFF) < threshold else "Male"

    @property
    def hidden_power_type(self) -> str:
        hp, atk, dfn, spd, spa, spd_ = self.ivs
        type_val = ((hp & 1) | ((atk & 1) << 1) | ((dfn & 1) << 2) |
                    ((spd & 1) << 3) | ((spa & 1) << 4) | ((spd_ & 1) << 5))
        type_idx = (type_val * 15) // 63
        return HIDDEN_POWER_TYPES[type_idx]

    @property
    def hidden_power_power(self) -> int:
        hp, atk, dfn, spd, spa, spd_ = self.ivs
        power_val = (((hp >> 1) & 1) | (((atk >> 1) & 1) << 1) |
                     (((dfn >> 1) & 1) << 2) | (((spd >> 1) & 1) << 3) |
                     (((spa >> 1) & 1) << 4) | (((spd_ >> 1) & 1) << 5))
        return (power_val * 40) // 63 + 30

    @property
    def friendship(self) -> int:
        return self.growth.friendship

    @property
    def experience(self) -> int:
        return self.growth.experience

    @property
    def moves(self) -> List[int]:
        return self.attacks.moves

    @property
    def pp(self) -> List[int]:
        return self.attacks.pp

    @property
    def pokerus_strain(self) -> int:
        return (self.misc.pokerus >> 4) & 0xF

    @property
    def pokerus_days(self) -> int:
        return self.misc.pokerus & 0xF

    @property
    def has_pokerus(self) -> bool:
        return self.pokerus_strain > 0

    def iv_string(self) -> str:
        labels = ["HP", "Atk", "Def", "Spd", "SpA", "SpD"]
        return " / ".join(f"{labels[i]}:{iv}" for i, iv in enumerate(self.ivs))

    def ev_string(self) -> str:
        labels = ["HP", "Atk", "Def", "Spd", "SpA", "SpD"]
        return " / ".join(f"{labels[i]}:{ev}" for i, ev in enumerate(self.evs))

    def summary(self) -> str:
        shiny = " ★" if self.is_shiny else ""
        egg = " [EGG]" if self.is_egg else ""
        return (
            f"#{self.species_id}{shiny}{egg} Lv.{self.level} "
            f"{self.nature} {self.gender} "
            f"IVs({self.iv_total}): {self.iv_string()} "
            f"Ability:{self.ability_slot}"
        )


# ── Decryption functions ────────────────────────────────────────────────────

def _decrypt_substructs(raw: bytes, pv: int, ot_id: int) -> bytearray:
    """Decrypt the 48-byte encrypted block using PV XOR OTID as key."""
    key = pv ^ ot_id
    encrypted = raw[HEADER_SIZE:HEADER_SIZE + ENCRYPTED_BLOCK_SIZE]
    decrypted = bytearray(ENCRYPTED_BLOCK_SIZE)
    for i in range(0, ENCRYPTED_BLOCK_SIZE, 4):
        word = struct.unpack_from("<I", encrypted, i)[0]
        struct.pack_into("<I", decrypted, i, word ^ key)
    return decrypted


def _parse_growth(data: bytes) -> GrowthSubstruct:
    """Parse 12-byte growth substructure."""
    species, item, experience, pp_bonuses, friendship, unknown = struct.unpack_from(
        "<HHIBBh", data, 0)
    return GrowthSubstruct(species, item, experience, pp_bonuses, friendship, unknown)


def _parse_attacks(data: bytes) -> AttacksSubstruct:
    """Parse 12-byte attacks substructure."""
    m1, m2, m3, m4, pp1, pp2, pp3, pp4 = struct.unpack_from("<HHHHBBBB", data, 0)
    return AttacksSubstruct(m1, m2, m3, m4, pp1, pp2, pp3, pp4)


def _parse_ev_condition(data: bytes) -> EVConditionSubstruct:
    """Parse 12-byte EVs/Condition substructure."""
    vals = struct.unpack_from("<12B", data, 0)
    return EVConditionSubstruct(*vals)


def _parse_misc(data: bytes) -> MiscSubstruct:
    """Parse 12-byte misc substructure."""
    pokerus, met_location = struct.unpack_from("<BB", data, 0)
    origins_info = struct.unpack_from("<H", data, 2)[0]
    iv_egg_ability = struct.unpack_from("<I", data, 4)[0]
    ribbons = struct.unpack_from("<I", data, 8)[0]
    return MiscSubstruct(pokerus, met_location, origins_info, iv_egg_ability, ribbons)


def _parse_header(raw: bytes) -> dict:
    """Parse the 32-byte Pokémon header."""
    pv = struct.unpack_from("<I", raw, 0)[0]
    ot_id = struct.unpack_from("<I", raw, 4)[0]
    # Nickname: bytes 8-17 (10 bytes, game encoding)
    nickname_raw = raw[8:18]
    # Language: bytes 18-19
    language = struct.unpack_from("<H", raw, 18)[0]
    # OT Name: bytes 20-26 (7 bytes)
    ot_name_raw = raw[20:27]
    # Markings: byte 27
    markings = raw[27]
    # Checksum: bytes 28-29
    checksum = struct.unpack_from("<H", raw, 28)[0]
    # Padding: bytes 30-31

    return {
        "personality_value": pv,
        "ot_id": ot_id,
        "nickname": _decode_string(nickname_raw),
        "language": language,
        "ot_name": _decode_string(ot_name_raw),
        "markings": markings,
        "checksum": checksum,
    }


def _decode_string(raw: bytes) -> str:
    """Decode a Gen 3 encoded string to ASCII."""
    # Gen 3 uses a custom character encoding
    GEN3_CHARSET = {
        0xBB: "A", 0xBC: "B", 0xBD: "C", 0xBE: "D", 0xBF: "E",
        0xC0: "F", 0xC1: "G", 0xC2: "H", 0xC3: "I", 0xC4: "J",
        0xC5: "K", 0xC6: "L", 0xC7: "M", 0xC8: "N", 0xC9: "O",
        0xCA: "P", 0xCB: "Q", 0xCC: "R", 0xCD: "S", 0xCE: "T",
        0xCF: "U", 0xD0: "V", 0xD1: "W", 0xD2: "X", 0xD3: "Y",
        0xD4: "Z", 0xD5: "a", 0xD6: "b", 0xD7: "c", 0xD8: "d",
        0xD9: "e", 0xDA: "f", 0xDB: "g", 0xDC: "h", 0xDD: "i",
        0xDE: "j", 0xDF: "k", 0xE0: "l", 0xE1: "m", 0xE2: "n",
        0xE3: "o", 0xE4: "p", 0xE5: "q", 0xE6: "r", 0xE7: "s",
        0xE8: "t", 0xE9: "u", 0xEA: "v", 0xEB: "w", 0xEC: "x",
        0xED: "y", 0xEE: "z", 0xA1: "0", 0xA2: "1", 0xA3: "2",
        0xA4: "3", 0xA5: "4", 0xA6: "5", 0xA7: "6", 0xA8: "7",
        0xA9: "8", 0xAA: "9", 0xAB: "!", 0xAC: "?", 0xAD: ".",
        0xAE: "-", 0xB4: "'", 0x00: " ", 0xFF: "",
    }
    result = []
    for b in raw:
        if b == 0xFF:
            break
        result.append(GEN3_CHARSET.get(b, "?"))
    return "".join(result)


def decode_pokemon(raw: bytes, is_party: bool = True) -> Pokemon:
    """
    Decode a raw Pokémon data structure (80 or 100 bytes).

    Args:
        raw: Raw bytes (80 for box, 100 for party)
        is_party: Whether this includes battle stats (100 bytes)

    Returns:
        Fully decoded Pokemon object
    """
    if len(raw) < BOX_POKEMON_SIZE:
        return Pokemon()

    header = _parse_header(raw)
    pv = header["personality_value"]
    ot_id = header["ot_id"]

    # Empty slot check
    if pv == 0 and ot_id == 0:
        return Pokemon()

    # Decrypt substructures
    decrypted = _decrypt_substructs(raw, pv, ot_id)

    # Determine substructure order
    order = SUBSTRUCT_ORDER[pv % 24]

    # Parse each substructure at its position
    substruct_data = {}
    for position, substruct_id in enumerate(order):
        offset = position * SUBSTRUCT_SIZE
        substruct_data[substruct_id] = decrypted[offset:offset + SUBSTRUCT_SIZE]

    growth = _parse_growth(substruct_data[0])
    attacks = _parse_attacks(substruct_data[1])
    ev_condition = _parse_ev_condition(substruct_data[2])
    misc = _parse_misc(substruct_data[3])

    pokemon = Pokemon(
        personality_value=pv,
        ot_id=ot_id,
        nickname=header["nickname"],
        language=header["language"],
        ot_name=header["ot_name"],
        markings=header["markings"],
        checksum=header["checksum"],
        growth=growth,
        attacks=attacks,
        ev_condition=ev_condition,
        misc=misc,
        is_party=is_party,
        _raw=raw,
    )

    # Parse battle stats if party Pokémon
    if is_party and len(raw) >= PARTY_POKEMON_SIZE:
        pokemon.status_condition = struct.unpack_from("<I", raw, 80)[0]
        pokemon.level = raw[84]
        pokemon.pokerus_remaining = raw[85]
        pokemon.current_hp = struct.unpack_from("<H", raw, 86)[0]
        pokemon.max_hp = struct.unpack_from("<H", raw, 88)[0]
        pokemon.attack = struct.unpack_from("<H", raw, 90)[0]
        pokemon.defense = struct.unpack_from("<H", raw, 92)[0]
        pokemon.speed = struct.unpack_from("<H", raw, 94)[0]
        pokemon.sp_attack = struct.unpack_from("<H", raw, 96)[0]
        pokemon.sp_defense = struct.unpack_from("<H", raw, 98)[0]

    return pokemon


def verify_checksum(raw: bytes) -> bool:
    """Verify the Pokémon data checksum."""
    if len(raw) < BOX_POKEMON_SIZE:
        return False
    pv = struct.unpack_from("<I", raw, 0)[0]
    ot_id = struct.unpack_from("<I", raw, 4)[0]
    stored_checksum = struct.unpack_from("<H", raw, 28)[0]

    decrypted = _decrypt_substructs(raw, pv, ot_id)
    calculated = 0
    for i in range(0, ENCRYPTED_BLOCK_SIZE, 2):
        calculated = (calculated + struct.unpack_from("<H", decrypted, i)[0]) & 0xFFFF

    return calculated == stored_checksum


# ── High-level reading functions ────────────────────────────────────────────

def read_party(bot: GameBot) -> List[Pokemon]:
    """Read all Pokémon in the player's party."""
    count_raw = bot.read_bytes(0x02024280, 4)
    count = struct.unpack("<I", count_raw)[0]
    if count == 0 or count > 6:
        return []

    party = []
    for i in range(count):
        addr = 0x02024284 + (i * PARTY_POKEMON_SIZE)
        raw = bot.read_bytes(addr, PARTY_POKEMON_SIZE)
        pokemon = decode_pokemon(raw, is_party=True)
        if pokemon.species_id > 0:
            party.append(pokemon)
    return party


def read_party_slot(bot: GameBot, slot: int) -> Pokemon:
    """Read a specific party slot (0-5)."""
    if slot < 0 or slot > 5:
        return Pokemon()
    addr = 0x02024284 + (slot * PARTY_POKEMON_SIZE)
    raw = bot.read_bytes(addr, PARTY_POKEMON_SIZE)
    return decode_pokemon(raw, is_party=True)


def read_enemy_party(bot: GameBot) -> List[Pokemon]:
    """Read the enemy party (wild or trainer battle)."""
    party = []
    for i in range(6):
        addr = 0x0202402C + (i * PARTY_POKEMON_SIZE)
        raw = bot.read_bytes(addr, PARTY_POKEMON_SIZE)
        pokemon = decode_pokemon(raw, is_party=True)
        if pokemon.species_id > 0:
            party.append(pokemon)
    return party


def read_enemy_lead(bot: GameBot) -> Pokemon:
    """Read the lead Pokémon of the enemy party."""
    raw = bot.read_bytes(0x0202402C, PARTY_POKEMON_SIZE)
    return decode_pokemon(raw, is_party=True)


def read_box_pokemon(bot: GameBot, box: int, slot: int) -> Pokemon:
    """
    Read a Pokémon from PC storage.

    Fire Red box storage starts at save block 1 offset 0x0490.
    Each box holds 30 Pokémon × 80 bytes = 2400 bytes.
    """
    if box < 0 or box > 13 or slot < 0 or slot > 29:
        return Pokemon()

    sb1_ptr = bot.read_u32(0x03005008)
    if sb1_ptr == 0:
        return Pokemon()

    # PC storage offset in save block 1 for FR/LG
    PC_STORAGE_OFFSET = 0x0490
    box_offset = box * 30 * BOX_POKEMON_SIZE
    slot_offset = slot * BOX_POKEMON_SIZE
    addr = sb1_ptr + PC_STORAGE_OFFSET + box_offset + slot_offset

    raw = bot.read_bytes(addr, BOX_POKEMON_SIZE)
    return decode_pokemon(raw, is_party=False)


def get_party_count(bot: GameBot) -> int:
    """Read the current party count."""
    raw = bot.read_bytes(0x02024280, 4)
    count = struct.unpack("<I", raw)[0]
    return count if 0 <= count <= 6 else 0


def find_eggs_in_party(bot: GameBot) -> List[Tuple[int, Pokemon]]:
    """Find all eggs in the party. Returns list of (slot_index, pokemon)."""
    party = read_party(bot)
    return [(i, p) for i, p in enumerate(party) if p.is_egg]


def find_shinies_in_party(bot: GameBot) -> List[Tuple[int, Pokemon]]:
    """Find all shiny Pokémon in the party."""
    party = read_party(bot)
    return [(i, p) for i, p in enumerate(party) if p.is_shiny]


def get_party_species(bot: GameBot) -> List[int]:
    """Get species IDs of all party Pokémon."""
    return [p.species_id for p in read_party(bot)]
