"""
evolution_data – Complete Gen 3 Pokédex with evolution chains, methods,
and requirements for building a perfect shiny living dex.

Data sourced from pret/pokefirered decompilation and Bulbapedia.
Covers all 386 Pokémon obtainable across Gen 3 games.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── Evolution method types ──────────────────────────────────────────────────

class EvoMethod(str, Enum):
    LEVEL = "level"
    STONE = "stone"
    TRADE = "trade"
    TRADE_ITEM = "trade_item"
    FRIENDSHIP = "friendship"
    FRIENDSHIP_DAY = "friendship_day"
    FRIENDSHIP_NIGHT = "friendship_night"
    LEVEL_ATK_GT_DEF = "level_atk_gt_def"      # Tyrogue → Hitmonlee
    LEVEL_ATK_EQ_DEF = "level_atk_eq_def"      # Tyrogue → Hitmontop
    LEVEL_DEF_GT_ATK = "level_def_gt_atk"      # Tyrogue → Hitmonchan
    LEVEL_SILCOON = "level_silcoon"             # Wurmple → Silcoon (PV based)
    LEVEL_CASCOON = "level_cascoon"             # Wurmple → Cascoon (PV based)
    LEVEL_NINJASK = "level_ninjask"             # Nincada → Ninjask
    LEVEL_SHEDINJA = "level_shedinja"           # Nincada → Shedinja (extra slot)
    BEAUTY = "beauty"                           # Feebas → Milotic
    NONE = "none"                               # No evolution / base form


class EvoStone(str, Enum):
    FIRE_STONE = "Fire Stone"
    WATER_STONE = "Water Stone"
    THUNDER_STONE = "Thunder Stone"
    LEAF_STONE = "Leaf Stone"
    MOON_STONE = "Moon Stone"
    SUN_STONE = "Sun Stone"


class TradeItem(str, Enum):
    KINGS_ROCK = "King's Rock"
    METAL_COAT = "Metal Coat"
    DRAGON_SCALE = "Dragon Scale"
    DEEP_SEA_TOOTH = "Deep Sea Tooth"
    DEEP_SEA_SCALE = "Deep Sea Scale"
    UPGRADE = "Up-Grade"


class ObtainMethod(str, Enum):
    WILD = "wild"
    FISHING = "fishing"
    SURF = "surf"
    ROCK_SMASH = "rock_smash"
    EVOLUTION = "evolution"
    TRADE = "trade"
    BREEDING = "breeding"
    GIFT = "gift"
    STATIC = "static"
    SAFARI = "safari"
    GAME_CORNER = "game_corner"
    FOSSIL = "fossil"
    EVENT = "event"


# ── Pokemon species data ────────────────────────────────────────────────────

@dataclass
class EvolutionEntry:
    """A single evolution path from this species."""
    target_id: int
    method: EvoMethod
    level: int = 0
    stone: Optional[EvoStone] = None
    trade_item: Optional[TradeItem] = None
    condition: str = ""


@dataclass
class PokemonSpecies:
    """Core data for one Pokémon species."""
    id: int
    name: str
    types: Tuple[str, ...]
    evolution_stage: int              # 1=basic, 2=stage1, 3=stage2
    is_baby: bool = False
    evolutions: List[EvolutionEntry] = field(default_factory=list)
    pre_evolution_id: Optional[int] = None
    egg_groups: Tuple[str, ...] = ()
    obtain_methods_firered: List[ObtainMethod] = field(default_factory=list)
    obtain_methods_emerald: List[ObtainMethod] = field(default_factory=list)
    locations_firered: List[str] = field(default_factory=list)
    locations_emerald: List[str] = field(default_factory=list)
    base_friendship: int = 70
    hatch_cycles: int = 20
    gender_ratio: int = 127           # 0=all male, 254=all female, 255=genderless, 127=50/50


# ── Complete Gen 3 National Dex ─────────────────────────────────────────────
# Every Pokémon 1-386 with evolution chains, methods, and obtain info.

def _build_pokedex() -> Dict[int, PokemonSpecies]:
    dex: Dict[int, PokemonSpecies] = {}

    def add(pid, name, types, stage, evos=None, pre=None, baby=False,
            egg=(), fr_obtain=None, em_obtain=None, fr_loc=None, em_loc=None,
            friendship=70, hatch=20, gender=127):
        dex[pid] = PokemonSpecies(
            id=pid, name=name, types=types, evolution_stage=stage,
            is_baby=baby,
            evolutions=evos or [],
            pre_evolution_id=pre,
            egg_groups=egg,
            obtain_methods_firered=fr_obtain or [],
            obtain_methods_emerald=em_obtain or [],
            locations_firered=fr_loc or [],
            locations_emerald=em_loc or [],
            base_friendship=friendship,
            hatch_cycles=hatch,
            gender_ratio=gender,
        )

    E = EvolutionEntry

    # ── Gen 1: Kanto (#001-#151) ────────────────────────────────────────

    # Bulbasaur line
    add(1, "Bulbasaur", ("Grass", "Poison"), 1,
        evos=[E(2, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Grass"),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Pallet Town (starter)"],
        hatch=20, gender=31)
    add(2, "Ivysaur", ("Grass", "Poison"), 2,
        evos=[E(3, EvoMethod.LEVEL, level=32)], pre=1,
        egg=("Monster", "Grass"), gender=31)
    add(3, "Venusaur", ("Grass", "Poison"), 3, pre=2,
        egg=("Monster", "Grass"), gender=31)

    # Charmander line
    add(4, "Charmander", ("Fire",), 1,
        evos=[E(5, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Dragon"),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Pallet Town (starter)"],
        hatch=20, gender=31)
    add(5, "Charmeleon", ("Fire",), 2,
        evos=[E(6, EvoMethod.LEVEL, level=36)], pre=4,
        egg=("Monster", "Dragon"), gender=31)
    add(6, "Charizard", ("Fire", "Flying"), 3, pre=5,
        egg=("Monster", "Dragon"), gender=31)

    # Squirtle line
    add(7, "Squirtle", ("Water",), 1,
        evos=[E(8, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Water 1"),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Pallet Town (starter)"],
        hatch=20, gender=31)
    add(8, "Wartortle", ("Water",), 2,
        evos=[E(9, EvoMethod.LEVEL, level=36)], pre=7,
        egg=("Monster", "Water 1"), gender=31)
    add(9, "Blastoise", ("Water",), 3, pre=8,
        egg=("Monster", "Water 1"), gender=31)

    # Caterpie line
    add(10, "Caterpie", ("Bug",), 1,
        evos=[E(11, EvoMethod.LEVEL, level=7)],
        egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Viridian Forest", "Route 2", "Pattern Bush"],
        gender=127)
    add(11, "Metapod", ("Bug",), 2,
        evos=[E(12, EvoMethod.LEVEL, level=10)], pre=10,
        egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Viridian Forest", "Route 2", "Pattern Bush"])
    add(12, "Butterfree", ("Bug", "Flying"), 3, pre=11, egg=("Bug",))

    # Weedle line
    add(13, "Weedle", ("Bug", "Poison"), 1,
        evos=[E(14, EvoMethod.LEVEL, level=7)],
        egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Viridian Forest", "Route 2", "Pattern Bush"])
    add(14, "Kakuna", ("Bug", "Poison"), 2,
        evos=[E(15, EvoMethod.LEVEL, level=10)], pre=13,
        egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Viridian Forest", "Route 2", "Pattern Bush"])
    add(15, "Beedrill", ("Bug", "Poison"), 3, pre=14, egg=("Bug",))

    # Pidgey line
    add(16, "Pidgey", ("Normal", "Flying"), 1,
        evos=[E(17, EvoMethod.LEVEL, level=18)],
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 1", "Route 2", "Route 5-8", "Route 24-25"])
    add(17, "Pidgeotto", ("Normal", "Flying"), 2,
        evos=[E(18, EvoMethod.LEVEL, level=36)], pre=16,
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 13-15", "Berry Forest"])
    add(18, "Pidgeot", ("Normal", "Flying"), 3, pre=17, egg=("Flying",))

    # Rattata line
    add(19, "Rattata", ("Normal",), 1,
        evos=[E(20, EvoMethod.LEVEL, level=20)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 1", "Route 2", "Route 4", "Route 16-18"])
    add(20, "Raticate", ("Normal",), 2, pre=19, egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 16-18", "Pokemon Mansion"])

    # Spearow line
    add(21, "Spearow", ("Normal", "Flying"), 1,
        evos=[E(22, EvoMethod.LEVEL, level=20)],
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 3", "Route 4", "Route 9-11"])
    add(22, "Fearow", ("Normal", "Flying"), 2, pre=21, egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 17", "Route 18", "Treasure Beach"])

    # Ekans line
    add(23, "Ekans", ("Poison",), 1,
        evos=[E(24, EvoMethod.LEVEL, level=22)],
        egg=("Field", "Dragon"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 4", "Route 8-11", "Route 23"])
    add(24, "Arbok", ("Poison",), 2, pre=23, egg=("Field", "Dragon"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 23", "Victory Road"])

    # Pichu / Pikachu / Raichu
    add(172, "Pichu", ("Electric",), 1, baby=True,
        evos=[E(25, EvoMethod.FRIENDSHIP)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=10, gender=127)
    add(25, "Pikachu", ("Electric",), 2,
        evos=[E(26, EvoMethod.STONE, stone=EvoStone.THUNDER_STONE)], pre=172,
        egg=("Field", "Fairy"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Viridian Forest", "Power Plant"])
    add(26, "Raichu", ("Electric",), 3, pre=25, egg=("Field", "Fairy"))

    # Sandshrew line
    add(27, "Sandshrew", ("Ground",), 1,
        evos=[E(28, EvoMethod.LEVEL, level=22)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 4", "Route 8-11", "Route 23"])
    add(28, "Sandslash", ("Ground",), 2, pre=27, egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 23", "Victory Road"])

    # Nidoran♀ line
    add(29, "Nidoran♀", ("Poison",), 1,
        evos=[E(30, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 3", "Safari Zone"],
        gender=254)
    add(30, "Nidorina", ("Poison",), 2,
        evos=[E(31, EvoMethod.STONE, stone=EvoStone.MOON_STONE)], pre=29,
        egg=("No Eggs Discovered",), gender=254)
    add(31, "Nidoqueen", ("Poison", "Ground"), 3, pre=30,
        egg=("No Eggs Discovered",), gender=254)

    # Nidoran♂ line
    add(32, "Nidoran♂", ("Poison",), 1,
        evos=[E(33, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 3", "Safari Zone"],
        gender=0)
    add(33, "Nidorino", ("Poison",), 2,
        evos=[E(34, EvoMethod.STONE, stone=EvoStone.MOON_STONE)], pre=32,
        egg=("Monster", "Field"), gender=0)
    add(34, "Nidoking", ("Poison", "Ground"), 3, pre=33,
        egg=("Monster", "Field"), gender=0)

    # Cleffa / Clefairy / Clefable
    add(173, "Cleffa", ("Normal",), 1, baby=True,
        evos=[E(35, EvoMethod.FRIENDSHIP)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=10, gender=191)
    add(35, "Clefairy", ("Normal",), 2,
        evos=[E(36, EvoMethod.STONE, stone=EvoStone.MOON_STONE)], pre=173,
        egg=("Fairy",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Mt. Moon"], gender=191)
    add(36, "Clefable", ("Normal",), 3, pre=35, egg=("Fairy",), gender=191)

    # Vulpix line
    add(37, "Vulpix", ("Fire",), 1,
        evos=[E(38, EvoMethod.STONE, stone=EvoStone.FIRE_STONE)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion", "Mt. Ember"],
        gender=191)
    add(38, "Ninetales", ("Fire",), 2, pre=37, egg=("Field",), gender=191)

    # Igglybuff / Jigglypuff / Wigglytuff
    add(174, "Igglybuff", ("Normal",), 1, baby=True,
        evos=[E(39, EvoMethod.FRIENDSHIP)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=10, gender=191)
    add(39, "Jigglypuff", ("Normal",), 2,
        evos=[E(40, EvoMethod.STONE, stone=EvoStone.MOON_STONE)], pre=174,
        egg=("Fairy",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 3"], gender=191)
    add(40, "Wigglytuff", ("Normal",), 3, pre=39, egg=("Fairy",), gender=191)

    # Zubat line
    add(41, "Zubat", ("Poison", "Flying"), 1,
        evos=[E(42, EvoMethod.LEVEL, level=22)],
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Mt. Moon", "Rock Tunnel", "Seafoam Islands"])
    add(42, "Golbat", ("Poison", "Flying"), 2,
        evos=[E(169, EvoMethod.FRIENDSHIP)], pre=41,
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave", "Victory Road", "Lost Cave"])
    add(169, "Crobat", ("Poison", "Flying"), 3, pre=42, egg=("Flying",))

    # Oddish line
    add(43, "Oddish", ("Grass", "Poison"), 1,
        evos=[E(44, EvoMethod.LEVEL, level=21)],
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 5-7", "Route 12-15", "Route 24-25"],
        gender=127)
    add(44, "Gloom", ("Grass", "Poison"), 2,
        evos=[E(45, EvoMethod.STONE, stone=EvoStone.LEAF_STONE),
              E(182, EvoMethod.STONE, stone=EvoStone.SUN_STONE)], pre=43,
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 12-15", "Berry Forest", "Cape Brink"])
    add(45, "Vileplume", ("Grass", "Poison"), 3, pre=44, egg=("Grass",))
    add(182, "Bellossom", ("Grass",), 3, pre=44, egg=("Grass",))

    # Paras line
    add(46, "Paras", ("Bug", "Grass"), 1,
        evos=[E(47, EvoMethod.LEVEL, level=24)],
        egg=("Bug", "Grass"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Mt. Moon", "Safari Zone"])
    add(47, "Parasect", ("Bug", "Grass"), 2, pre=46, egg=("Bug", "Grass"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Safari Zone", "Cerulean Cave"])

    # Venonat line
    add(48, "Venonat", ("Bug", "Poison"), 1,
        evos=[E(49, EvoMethod.LEVEL, level=31)],
        egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 12-15", "Safari Zone"])
    add(49, "Venomoth", ("Bug", "Poison"), 2, pre=48, egg=("Bug",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Safari Zone", "Berry Forest"])

    # Diglett line
    add(50, "Diglett", ("Ground",), 1,
        evos=[E(51, EvoMethod.LEVEL, level=26)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Diglett's Cave"])
    add(51, "Dugtrio", ("Ground",), 2, pre=50, egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Diglett's Cave"])

    # Meowth line
    add(52, "Meowth", ("Normal",), 1,
        evos=[E(53, EvoMethod.LEVEL, level=28)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 5-8", "Pokemon Mansion"])
    add(53, "Persian", ("Normal",), 2, pre=52, egg=("Field",))

    # Psyduck line
    add(54, "Psyduck", ("Water",), 1,
        evos=[E(55, EvoMethod.LEVEL, level=33)],
        egg=("Water 1", "Field"),
        fr_obtain=[ObtainMethod.WILD, ObtainMethod.SURF],
        fr_loc=["Safari Zone", "Cerulean Cave", "Berry Forest"])
    add(55, "Golduck", ("Water",), 2, pre=54, egg=("Water 1", "Field"),
        fr_obtain=[ObtainMethod.SURF], fr_loc=["Cerulean Cave"])

    # Mankey line
    add(56, "Mankey", ("Fighting",), 1,
        evos=[E(57, EvoMethod.LEVEL, level=28)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 3", "Route 4", "Rock Tunnel"])
    add(57, "Primeape", ("Fighting",), 2, pre=56, egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave"])

    # Growlithe line
    add(58, "Growlithe", ("Fire",), 1,
        evos=[E(59, EvoMethod.STONE, stone=EvoStone.FIRE_STONE)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion", "Route 7-8"],
        gender=63)
    add(59, "Arcanine", ("Fire",), 2, pre=58, egg=("Field",), gender=63)

    # Poliwag line
    add(60, "Poliwag", ("Water",), 1,
        evos=[E(61, EvoMethod.LEVEL, level=25)],
        egg=("Water 1",),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Route 22-25", "Viridian City", "Cerulean City"])
    add(61, "Poliwhirl", ("Water",), 2,
        evos=[E(62, EvoMethod.STONE, stone=EvoStone.WATER_STONE),
              E(186, EvoMethod.TRADE_ITEM, trade_item=TradeItem.KINGS_ROCK)], pre=60,
        egg=("Water 1",),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Route 22-25", "Cerulean Cave"])
    add(62, "Poliwrath", ("Water", "Fighting"), 3, pre=61, egg=("Water 1",))
    add(186, "Politoed", ("Water",), 3, pre=61, egg=("Water 1",))

    # Abra line
    add(63, "Abra", ("Psychic",), 1,
        evos=[E(64, EvoMethod.LEVEL, level=16)],
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 24-25", "Game Corner"])
    add(64, "Kadabra", ("Psychic",), 2,
        evos=[E(65, EvoMethod.TRADE)], pre=63,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave"])
    add(65, "Alakazam", ("Psychic",), 3, pre=64, egg=("Human-Like",))

    # Machop line
    add(66, "Machop", ("Fighting",), 1,
        evos=[E(67, EvoMethod.LEVEL, level=28)],
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Rock Tunnel", "Victory Road"])
    add(67, "Machoke", ("Fighting",), 2,
        evos=[E(68, EvoMethod.TRADE)], pre=66,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave", "Victory Road"])
    add(68, "Machamp", ("Fighting",), 3, pre=67, egg=("Human-Like",))

    # Bellsprout line
    add(69, "Bellsprout", ("Grass", "Poison"), 1,
        evos=[E(70, EvoMethod.LEVEL, level=21)],
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 5-7", "Route 12-15", "Route 24-25"])
    add(70, "Weepinbell", ("Grass", "Poison"), 2,
        evos=[E(71, EvoMethod.STONE, stone=EvoStone.LEAF_STONE)], pre=69,
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 12-15", "Berry Forest", "Cape Brink"])
    add(71, "Victreebel", ("Grass", "Poison"), 3, pre=70, egg=("Grass",))

    # Tentacool line
    add(72, "Tentacool", ("Water", "Poison"), 1,
        evos=[E(73, EvoMethod.LEVEL, level=30)],
        egg=("Water 3",),
        fr_obtain=[ObtainMethod.SURF], fr_loc=["Most water routes"])
    add(73, "Tentacruel", ("Water", "Poison"), 2, pre=72, egg=("Water 3",),
        fr_obtain=[ObtainMethod.SURF], fr_loc=["Most water routes (rare)"])

    # Geodude line
    add(74, "Geodude", ("Rock", "Ground"), 1,
        evos=[E(75, EvoMethod.LEVEL, level=25)],
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Mt. Moon", "Rock Tunnel", "Victory Road"])
    add(75, "Graveler", ("Rock", "Ground"), 2,
        evos=[E(76, EvoMethod.TRADE)], pre=74,
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave", "Victory Road"])
    add(76, "Golem", ("Rock", "Ground"), 3, pre=75, egg=("Mineral",))

    # Ponyta line
    add(77, "Ponyta", ("Fire",), 1,
        evos=[E(78, EvoMethod.LEVEL, level=40)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Kindle Road", "Mt. Ember"])
    add(78, "Rapidash", ("Fire",), 2, pre=77, egg=("Field",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Kindle Road (rare)"])

    # Slowpoke line
    add(79, "Slowpoke", ("Water", "Psychic"), 1,
        evos=[E(80, EvoMethod.LEVEL, level=37),
              E(199, EvoMethod.TRADE_ITEM, trade_item=TradeItem.KINGS_ROCK)],
        egg=("Monster", "Water 1"),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Seafoam Islands", "Cape Brink"])
    add(80, "Slowbro", ("Water", "Psychic"), 2, pre=79, egg=("Monster", "Water 1"),
        fr_obtain=[ObtainMethod.SURF], fr_loc=["Seafoam Islands (rare)"])
    add(199, "Slowking", ("Water", "Psychic"), 2, pre=79, egg=("Monster", "Water 1"))

    # Magnemite line
    add(81, "Magnemite", ("Electric", "Steel"), 1,
        evos=[E(82, EvoMethod.LEVEL, level=30)],
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Power Plant"], gender=255)
    add(82, "Magneton", ("Electric", "Steel"), 2, pre=81, egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Power Plant (rare)"], gender=255)

    # Farfetch'd
    add(83, "Farfetch'd", ("Normal", "Flying"), 1,
        egg=("Flying", "Field"),
        fr_obtain=[ObtainMethod.TRADE], fr_loc=["Vermilion City (in-game trade)"])

    # Doduo line
    add(84, "Doduo", ("Normal", "Flying"), 1,
        evos=[E(85, EvoMethod.LEVEL, level=31)],
        egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 16-18", "Safari Zone"])
    add(85, "Dodrio", ("Normal", "Flying"), 2, pre=84, egg=("Flying",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Kindle Road"])

    # Seel line
    add(86, "Seel", ("Water",), 1,
        evos=[E(87, EvoMethod.LEVEL, level=34)],
        egg=("Water 1", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Seafoam Islands", "Icefall Cave"])
    add(87, "Dewgong", ("Water", "Ice"), 2, pre=86, egg=("Water 1", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Seafoam Islands"])

    # Grimer line
    add(88, "Grimer", ("Poison",), 1,
        evos=[E(89, EvoMethod.LEVEL, level=38)],
        egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion", "Celadon City"])
    add(89, "Muk", ("Poison",), 2, pre=88, egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion"])

    # Shellder line
    add(90, "Shellder", ("Water",), 1,
        evos=[E(91, EvoMethod.STONE, stone=EvoStone.WATER_STONE)],
        egg=("Water 3",),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Route 19-21", "Vermilion City"])
    add(91, "Cloyster", ("Water", "Ice"), 2, pre=90, egg=("Water 3",))

    # Gastly line
    add(92, "Gastly", ("Ghost", "Poison"), 1,
        evos=[E(93, EvoMethod.LEVEL, level=25)],
        egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Tower", "Lost Cave"])
    add(93, "Haunter", ("Ghost", "Poison"), 2,
        evos=[E(94, EvoMethod.TRADE)], pre=92,
        egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Tower (rare)", "Lost Cave"])
    add(94, "Gengar", ("Ghost", "Poison"), 3, pre=93, egg=("Amorphous",))

    # Onix
    add(95, "Onix", ("Rock", "Ground"), 1,
        evos=[E(208, EvoMethod.TRADE_ITEM, trade_item=TradeItem.METAL_COAT)],
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Rock Tunnel", "Victory Road"])
    add(208, "Steelix", ("Steel", "Ground"), 2, pre=95, egg=("Mineral",))

    # Drowzee line
    add(96, "Drowzee", ("Psychic",), 1,
        evos=[E(97, EvoMethod.LEVEL, level=26)],
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 11", "Berry Forest"])
    add(97, "Hypno", ("Psychic",), 2, pre=96, egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD, ObtainMethod.STATIC],
        fr_loc=["Berry Forest (static)", "Safari Zone"])

    # Krabby line
    add(98, "Krabby", ("Water",), 1,
        evos=[E(99, EvoMethod.LEVEL, level=28)],
        egg=("Water 3",),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Route 19-21", "Vermilion City", "One Island"])
    add(99, "Kingler", ("Water",), 2, pre=98, egg=("Water 3",))

    # Voltorb line
    add(100, "Voltorb", ("Electric",), 1,
        evos=[E(101, EvoMethod.LEVEL, level=30)],
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Power Plant", "Rocket Hideout"],
        gender=255)
    add(101, "Electrode", ("Electric",), 2, pre=100, egg=("Mineral",),
        fr_obtain=[ObtainMethod.WILD, ObtainMethod.STATIC],
        fr_loc=["Power Plant (static)"], gender=255)

    # Exeggcute line
    add(102, "Exeggcute", ("Grass", "Psychic"), 1,
        evos=[E(103, EvoMethod.STONE, stone=EvoStone.LEAF_STONE)],
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Safari Zone", "Berry Forest"])
    add(103, "Exeggutor", ("Grass", "Psychic"), 2, pre=102, egg=("Grass",))

    # Cubone line
    add(104, "Cubone", ("Ground",), 1,
        evos=[E(105, EvoMethod.LEVEL, level=28)],
        egg=("Monster",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Tower", "Sevault Canyon"])
    add(105, "Marowak", ("Ground",), 2, pre=104, egg=("Monster",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Sevault Canyon", "Victory Road"])

    # Tyrogue / Hitmonlee / Hitmonchan / Hitmontop
    add(236, "Tyrogue", ("Fighting",), 1, baby=True,
        evos=[E(106, EvoMethod.LEVEL_ATK_GT_DEF, level=20),
              E(107, EvoMethod.LEVEL_DEF_GT_ATK, level=20),
              E(237, EvoMethod.LEVEL_ATK_EQ_DEF, level=20)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=25, gender=0)
    add(106, "Hitmonlee", ("Fighting",), 2, pre=236,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Saffron City (Fighting Dojo)"], gender=0)
    add(107, "Hitmonchan", ("Fighting",), 2, pre=236,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Saffron City (Fighting Dojo)"], gender=0)
    add(237, "Hitmontop", ("Fighting",), 2, pre=236,
        egg=("Human-Like",), gender=0)

    # Lickitung
    add(108, "Lickitung", ("Normal",), 1,
        egg=("Monster",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 18 (rare)"])

    # Koffing line
    add(109, "Koffing", ("Poison",), 1,
        evos=[E(110, EvoMethod.LEVEL, level=35)],
        egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion"], gender=127)
    add(110, "Weezing", ("Poison",), 2, pre=109, egg=("Amorphous",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion"])

    # Rhyhorn line
    add(111, "Rhyhorn", ("Ground", "Rock"), 1,
        evos=[E(112, EvoMethod.LEVEL, level=42)],
        egg=("Monster", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Safari Zone", "Victory Road"])
    add(112, "Rhydon", ("Ground", "Rock"), 2, pre=111, egg=("Monster", "Field"),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Cerulean Cave"])

    # Chansey / Happiny / Blissey
    add(113, "Chansey", ("Normal",), 2,
        evos=[E(242, EvoMethod.FRIENDSHIP)],
        egg=("Fairy",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Safari Zone (rare)"],
        gender=254, friendship=140)
    add(242, "Blissey", ("Normal",), 3, pre=113, egg=("Fairy",),
        gender=254, friendship=140)

    # Tangela
    add(114, "Tangela", ("Grass",), 1,
        egg=("Grass",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Route 21", "Treasure Beach"])

    # Kangaskhan
    add(115, "Kangaskhan", ("Normal",), 1,
        egg=("Monster",),
        fr_obtain=[ObtainMethod.SAFARI], fr_loc=["Safari Zone (rare)"],
        gender=254)

    # Horsea line
    add(116, "Horsea", ("Water",), 1,
        evos=[E(117, EvoMethod.LEVEL, level=32)],
        egg=("Water 1", "Dragon"),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Seafoam Islands", "Treasure Beach"])
    add(117, "Seadra", ("Water",), 2,
        evos=[E(230, EvoMethod.TRADE_ITEM, trade_item=TradeItem.DRAGON_SCALE)], pre=116,
        egg=("Water 1", "Dragon"),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Seafoam Islands (rare)"])
    add(230, "Kingdra", ("Water", "Dragon"), 3, pre=117, egg=("Water 1", "Dragon"))

    # Goldeen line
    add(118, "Goldeen", ("Water",), 1,
        evos=[E(119, EvoMethod.LEVEL, level=33)],
        egg=("Water 2",),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Route 6", "Cerulean City", "Safari Zone"])
    add(119, "Seaking", ("Water",), 2, pre=118, egg=("Water 2",),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Safari Zone", "Cerulean Cave"])

    # Staryu line
    add(120, "Staryu", ("Water",), 1,
        evos=[E(121, EvoMethod.STONE, stone=EvoStone.WATER_STONE)],
        egg=("Water 3",),
        fr_obtain=[ObtainMethod.FISHING, ObtainMethod.SURF],
        fr_loc=["Vermilion City", "Pallet Town"], gender=255)
    add(121, "Starmie", ("Water", "Psychic"), 2, pre=120, egg=("Water 3",), gender=255)

    # Mr. Mime
    add(122, "Mr. Mime", ("Psychic",), 1,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.TRADE], fr_loc=["Route 2 (in-game trade)"])

    # Scyther
    add(123, "Scyther", ("Bug", "Flying"), 1,
        evos=[E(212, EvoMethod.TRADE_ITEM, trade_item=TradeItem.METAL_COAT)],
        egg=("Bug",),
        fr_obtain=[ObtainMethod.SAFARI, ObtainMethod.GAME_CORNER],
        fr_loc=["Safari Zone", "Game Corner"])
    add(212, "Scizor", ("Bug", "Steel"), 2, pre=123, egg=("Bug",))

    # Jynx / Smoochum
    add(238, "Smoochum", ("Ice", "Psychic"), 1, baby=True,
        evos=[E(124, EvoMethod.LEVEL, level=30)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=25, gender=254)
    add(124, "Jynx", ("Ice", "Psychic"), 2, pre=238,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.TRADE], fr_loc=["Cerulean City (in-game trade)"],
        gender=254)

    # Electabuzz / Elekid
    add(239, "Elekid", ("Electric",), 1, baby=True,
        evos=[E(125, EvoMethod.LEVEL, level=30)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=25, gender=63)
    add(125, "Electabuzz", ("Electric",), 2, pre=239,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Power Plant"], gender=63)

    # Magmar / Magby
    add(240, "Magby", ("Fire",), 1, baby=True,
        evos=[E(126, EvoMethod.LEVEL, level=30)],
        egg=("No Eggs Discovered",),
        fr_obtain=[ObtainMethod.BREEDING], hatch=25, gender=63)
    add(126, "Magmar", ("Fire",), 2, pre=240,
        egg=("Human-Like",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Mt. Ember"], gender=63)

    # Pinsir
    add(127, "Pinsir", ("Bug",), 1,
        egg=("Bug",),
        fr_obtain=[ObtainMethod.SAFARI], fr_loc=["Safari Zone"])

    # Tauros
    add(128, "Tauros", ("Normal",), 1,
        egg=("Field",),
        fr_obtain=[ObtainMethod.SAFARI], fr_loc=["Safari Zone"],
        gender=0)

    # Magikarp line
    add(129, "Magikarp", ("Water",), 1,
        evos=[E(130, EvoMethod.LEVEL, level=20)],
        egg=("Water 2", "Dragon"),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Almost any water body"])
    add(130, "Gyarados", ("Water", "Flying"), 2, pre=129, egg=("Water 2", "Dragon"))

    # Lapras
    add(131, "Lapras", ("Water", "Ice"), 1,
        egg=("Monster", "Water 1"),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Silph Co."])

    # Ditto
    add(132, "Ditto", ("Normal",), 1,
        egg=("Ditto",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Pokemon Mansion", "Cerulean Cave"],
        gender=255)

    # Eevee line
    add(133, "Eevee", ("Normal",), 1,
        evos=[E(134, EvoMethod.STONE, stone=EvoStone.WATER_STONE),
              E(135, EvoMethod.STONE, stone=EvoStone.THUNDER_STONE),
              E(136, EvoMethod.STONE, stone=EvoStone.FIRE_STONE),
              E(196, EvoMethod.FRIENDSHIP_DAY),
              E(197, EvoMethod.FRIENDSHIP_NIGHT)],
        egg=("Field",),
        fr_obtain=[ObtainMethod.GIFT], fr_loc=["Celadon Mansion"],
        gender=31, friendship=70)
    add(134, "Vaporeon", ("Water",), 2, pre=133, egg=("Field",), gender=31)
    add(135, "Jolteon", ("Electric",), 2, pre=133, egg=("Field",), gender=31)
    add(136, "Flareon", ("Fire",), 2, pre=133, egg=("Field",), gender=31)
    add(196, "Espeon", ("Psychic",), 2, pre=133, egg=("Field",), gender=31)
    add(197, "Umbreon", ("Dark",), 2, pre=133, egg=("Field",), gender=31)

    # Porygon line
    add(137, "Porygon", ("Normal",), 1,
        evos=[E(233, EvoMethod.TRADE_ITEM, trade_item=TradeItem.UPGRADE)],
        egg=("Mineral",),
        fr_obtain=[ObtainMethod.GAME_CORNER], fr_loc=["Game Corner"],
        gender=255)
    add(233, "Porygon2", ("Normal",), 2, pre=137, egg=("Mineral",), gender=255)

    # Omanyte line
    add(138, "Omanyte", ("Rock", "Water"), 1,
        evos=[E(139, EvoMethod.LEVEL, level=40)],
        egg=("Water 1", "Water 3"),
        fr_obtain=[ObtainMethod.FOSSIL], fr_loc=["Cinnabar Lab (Helix Fossil)"])
    add(139, "Omastar", ("Rock", "Water"), 2, pre=138, egg=("Water 1", "Water 3"))

    # Kabuto line
    add(140, "Kabuto", ("Rock", "Water"), 1,
        evos=[E(141, EvoMethod.LEVEL, level=40)],
        egg=("Water 1", "Water 3"),
        fr_obtain=[ObtainMethod.FOSSIL], fr_loc=["Cinnabar Lab (Dome Fossil)"])
    add(141, "Kabutops", ("Rock", "Water"), 2, pre=140, egg=("Water 1", "Water 3"))

    # Aerodactyl
    add(142, "Aerodactyl", ("Rock", "Flying"), 1,
        egg=("Flying",),
        fr_obtain=[ObtainMethod.FOSSIL], fr_loc=["Cinnabar Lab (Old Amber)"])

    # Snorlax / Munchlax
    add(143, "Snorlax", ("Normal",), 1,
        egg=("Monster",),
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Route 12", "Route 16"],
        friendship=70)

    # Articuno / Zapdos / Moltres
    add(144, "Articuno", ("Ice", "Flying"), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Seafoam Islands B4F"],
        gender=255)
    add(145, "Zapdos", ("Electric", "Flying"), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Power Plant"],
        gender=255)
    add(146, "Moltres", ("Fire", "Flying"), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Mt. Ember Summit"],
        gender=255)

    # Dratini line
    add(147, "Dratini", ("Dragon",), 1,
        evos=[E(148, EvoMethod.LEVEL, level=30)],
        egg=("Water 1", "Dragon"),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Safari Zone (Super Rod)"])
    add(148, "Dragonair", ("Dragon",), 2,
        evos=[E(149, EvoMethod.LEVEL, level=55)], pre=147,
        egg=("Water 1", "Dragon"),
        fr_obtain=[ObtainMethod.FISHING], fr_loc=["Safari Zone (Super Rod, rare)"])
    add(149, "Dragonite", ("Dragon", "Flying"), 3, pre=148, egg=("Water 1", "Dragon"))

    # Mewtwo / Mew
    add(150, "Mewtwo", ("Psychic",), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Cerulean Cave B1F"],
        gender=255)
    add(151, "Mew", ("Psychic",), 1,
        fr_obtain=[ObtainMethod.EVENT], fr_loc=["Event only"],
        gender=255)

    # ── Gen 2: Johto (#152-#251) ────────────────────────────────────────

    # Chikorita line
    add(152, "Chikorita", ("Grass",), 1,
        evos=[E(153, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Grass"), gender=31)
    add(153, "Bayleef", ("Grass",), 2,
        evos=[E(154, EvoMethod.LEVEL, level=32)], pre=152,
        egg=("Monster", "Grass"), gender=31)
    add(154, "Meganium", ("Grass",), 3, pre=153, egg=("Monster", "Grass"), gender=31)

    # Cyndaquil line
    add(155, "Cyndaquil", ("Fire",), 1,
        evos=[E(156, EvoMethod.LEVEL, level=14)],
        egg=("Field",), gender=31)
    add(156, "Quilava", ("Fire",), 2,
        evos=[E(157, EvoMethod.LEVEL, level=36)], pre=155,
        egg=("Field",), gender=31)
    add(157, "Typhlosion", ("Fire",), 3, pre=156, egg=("Field",), gender=31)

    # Totodile line
    add(158, "Totodile", ("Water",), 1,
        evos=[E(159, EvoMethod.LEVEL, level=18)],
        egg=("Monster", "Water 1"), gender=31)
    add(159, "Croconaw", ("Water",), 2,
        evos=[E(160, EvoMethod.LEVEL, level=30)], pre=158,
        egg=("Monster", "Water 1"), gender=31)
    add(160, "Feraligatr", ("Water",), 3, pre=159, egg=("Monster", "Water 1"), gender=31)

    # Sentret line
    add(161, "Sentret", ("Normal",), 1,
        evos=[E(162, EvoMethod.LEVEL, level=15)], egg=("Field",))
    add(162, "Furret", ("Normal",), 2, pre=161, egg=("Field",))

    # Hoothoot line
    add(163, "Hoothoot", ("Normal", "Flying"), 1,
        evos=[E(164, EvoMethod.LEVEL, level=20)], egg=("Flying",))
    add(164, "Noctowl", ("Normal", "Flying"), 2, pre=163, egg=("Flying",))

    # Ledyba line
    add(165, "Ledyba", ("Bug", "Flying"), 1,
        evos=[E(166, EvoMethod.LEVEL, level=18)], egg=("Bug",))
    add(166, "Ledian", ("Bug", "Flying"), 2, pre=165, egg=("Bug",))

    # Spinarak line
    add(167, "Spinarak", ("Bug", "Poison"), 1,
        evos=[E(168, EvoMethod.LEVEL, level=22)], egg=("Bug",))
    add(168, "Ariados", ("Bug", "Poison"), 2, pre=167, egg=("Bug",))

    # Crobat already added above (169)

    # Chinchou line
    add(170, "Chinchou", ("Water", "Electric"), 1,
        evos=[E(171, EvoMethod.LEVEL, level=27)], egg=("Water 2",))
    add(171, "Lanturn", ("Water", "Electric"), 2, pre=170, egg=("Water 2",))

    # Pichu already added above (172)
    # Cleffa already added above (173)
    # Igglybuff already added above (174)

    # Togepi line
    add(175, "Togepi", ("Normal",), 1, baby=True,
        evos=[E(176, EvoMethod.FRIENDSHIP)],
        egg=("No Eggs Discovered",), hatch=10, gender=31)
    add(176, "Togetic", ("Normal", "Flying"), 2, pre=175, egg=("Flying", "Fairy"), gender=31)

    # Natu line
    add(177, "Natu", ("Psychic", "Flying"), 1,
        evos=[E(178, EvoMethod.LEVEL, level=25)], egg=("Flying",))
    add(178, "Xatu", ("Psychic", "Flying"), 2, pre=177, egg=("Flying",))

    # Mareep line
    add(179, "Mareep", ("Electric",), 1,
        evos=[E(180, EvoMethod.LEVEL, level=15)], egg=("Monster", "Field"))
    add(180, "Flaaffy", ("Electric",), 2,
        evos=[E(181, EvoMethod.LEVEL, level=30)], pre=179, egg=("Monster", "Field"))
    add(181, "Ampharos", ("Electric",), 3, pre=180, egg=("Monster", "Field"))

    # Bellossom already added above (182)

    # Marill line / Azurill
    add(298, "Azurill", ("Normal",), 1, baby=True,
        evos=[E(183, EvoMethod.FRIENDSHIP)],
        egg=("No Eggs Discovered",), hatch=10, gender=191)
    add(183, "Marill", ("Water",), 2,
        evos=[E(184, EvoMethod.LEVEL, level=18)], pre=298,
        egg=("Water 1", "Fairy"), gender=191)
    add(184, "Azumarill", ("Water",), 3, pre=183, egg=("Water 1", "Fairy"), gender=191)

    # Sudowoodo / Bonsly
    add(185, "Sudowoodo", ("Rock",), 1,
        egg=("Mineral",),
        em_obtain=[ObtainMethod.STATIC], em_loc=["Battle Frontier"])

    # Politoed already added above (186)

    # Hoppip line
    add(187, "Hoppip", ("Grass", "Flying"), 1,
        evos=[E(188, EvoMethod.LEVEL, level=18)], egg=("Fairy", "Grass"))
    add(188, "Skiploom", ("Grass", "Flying"), 2,
        evos=[E(189, EvoMethod.LEVEL, level=27)], pre=187, egg=("Fairy", "Grass"))
    add(189, "Jumpluff", ("Grass", "Flying"), 3, pre=188, egg=("Fairy", "Grass"))

    # Aipom
    add(190, "Aipom", ("Normal",), 1, egg=("Field",))

    # Sunkern line
    add(191, "Sunkern", ("Grass",), 1,
        evos=[E(192, EvoMethod.STONE, stone=EvoStone.SUN_STONE)], egg=("Grass",))
    add(192, "Sunflora", ("Grass",), 2, pre=191, egg=("Grass",))

    # Yanma
    add(193, "Yanma", ("Bug", "Flying"), 1, egg=("Bug",))

    # Wooper line
    add(194, "Wooper", ("Water", "Ground"), 1,
        evos=[E(195, EvoMethod.LEVEL, level=20)], egg=("Water 1", "Field"))
    add(195, "Quagsire", ("Water", "Ground"), 2, pre=194, egg=("Water 1", "Field"))

    # Espeon/Umbreon already added above (196, 197)

    # Murkrow
    add(198, "Murkrow", ("Dark", "Flying"), 1, egg=("Flying",))

    # Slowking already added above (199)

    # Misdreavus
    add(200, "Misdreavus", ("Ghost",), 1, egg=("Amorphous",))

    # Unown
    add(201, "Unown", ("Psychic",), 1,
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Tanoby Chambers"],
        em_obtain=[ObtainMethod.WILD], em_loc=["Tanoby Chambers"],
        gender=255)

    # Wobbuffet / Wynaut
    add(360, "Wynaut", ("Psychic",), 1, baby=True,
        evos=[E(202, EvoMethod.LEVEL, level=15)],
        egg=("No Eggs Discovered",), hatch=20)
    add(202, "Wobbuffet", ("Psychic",), 2, pre=360, egg=("Amorphous",))

    # Girafarig
    add(203, "Girafarig", ("Normal", "Psychic"), 1, egg=("Field",))

    # Pineco line
    add(204, "Pineco", ("Bug",), 1,
        evos=[E(205, EvoMethod.LEVEL, level=31)], egg=("Bug",))
    add(205, "Forretress", ("Bug", "Steel"), 2, pre=204, egg=("Bug",))

    # Dunsparce
    add(206, "Dunsparce", ("Normal",), 1, egg=("Field",))

    # Gligar
    add(207, "Gligar", ("Ground", "Flying"), 1, egg=("Bug",))

    # Steelix already added above (208)

    # Snubbull line
    add(209, "Snubbull", ("Normal",), 1,
        evos=[E(210, EvoMethod.LEVEL, level=23)], egg=("Field", "Fairy"), gender=191)
    add(210, "Granbull", ("Normal",), 2, pre=209, egg=("Field", "Fairy"), gender=191)

    # Qwilfish
    add(211, "Qwilfish", ("Water", "Poison"), 1, egg=("Water 2",))

    # Scizor already added above (212)

    # Shuckle
    add(213, "Shuckle", ("Bug", "Rock"), 1, egg=("Bug",))

    # Heracross
    add(214, "Heracross", ("Bug", "Fighting"), 1, egg=("Bug",))

    # Sneasel
    add(215, "Sneasel", ("Dark", "Ice"), 1, egg=("Field",))

    # Teddiursa line
    add(216, "Teddiursa", ("Normal",), 1,
        evos=[E(217, EvoMethod.LEVEL, level=30)], egg=("Field",))
    add(217, "Ursaring", ("Normal",), 2, pre=216, egg=("Field",))

    # Slugma line
    add(218, "Slugma", ("Fire",), 1,
        evos=[E(219, EvoMethod.LEVEL, level=38)], egg=("Amorphous",))
    add(219, "Magcargo", ("Fire", "Rock"), 2, pre=218, egg=("Amorphous",))

    # Swinub line
    add(220, "Swinub", ("Ice", "Ground"), 1,
        evos=[E(221, EvoMethod.LEVEL, level=33)], egg=("Field",))
    add(221, "Piloswine", ("Ice", "Ground"), 2, pre=220, egg=("Field",))

    # Corsola
    add(222, "Corsola", ("Water", "Rock"), 1, egg=("Water 1", "Water 3"))

    # Remoraid line
    add(223, "Remoraid", ("Water",), 1,
        evos=[E(224, EvoMethod.LEVEL, level=25)], egg=("Water 1", "Water 2"))
    add(224, "Octillery", ("Water",), 2, pre=223, egg=("Water 1", "Water 2"))

    # Delibird
    add(225, "Delibird", ("Ice", "Flying"), 1, egg=("Water 1", "Field"))

    # Mantine / Mantyke
    add(226, "Mantine", ("Water", "Flying"), 1, egg=("Water 1",))

    # Skarmory
    add(227, "Skarmory", ("Steel", "Flying"), 1, egg=("Flying",))

    # Houndour line
    add(228, "Houndour", ("Dark", "Fire"), 1,
        evos=[E(229, EvoMethod.LEVEL, level=24)], egg=("Field",))
    add(229, "Houndoom", ("Dark", "Fire"), 2, pre=228, egg=("Field",))

    # Kingdra already added above (230)

    # Phanpy line
    add(231, "Phanpy", ("Ground",), 1,
        evos=[E(232, EvoMethod.LEVEL, level=25)], egg=("Field",))
    add(232, "Donphan", ("Ground",), 2, pre=231, egg=("Field",))

    # Porygon2 already added above (233)

    # Stantler
    add(234, "Stantler", ("Normal",), 1, egg=("Field",))

    # Smeargle
    add(235, "Smeargle", ("Normal",), 1, egg=("Field",))

    # Tyrogue/Hitmonlee/Hitmonchan/Hitmontop already added above (236, 106, 107, 237)

    # Smoochum/Elekid/Magby already added above (238, 239, 240)

    # Miltank
    add(241, "Miltank", ("Normal",), 1, egg=("Field",), gender=254)

    # Blissey already added above (242)

    # Raikou / Entei / Suicune
    add(243, "Raikou", ("Electric",), 1, gender=255)
    add(244, "Entei", ("Fire",), 1, gender=255)
    add(245, "Suicune", ("Water",), 1, gender=255)

    # Larvitar line
    add(246, "Larvitar", ("Rock", "Ground"), 1,
        evos=[E(247, EvoMethod.LEVEL, level=30)], egg=("Monster",),
        fr_obtain=[ObtainMethod.WILD], fr_loc=["Sevault Canyon"])
    add(247, "Pupitar", ("Rock", "Ground"), 2,
        evos=[E(248, EvoMethod.LEVEL, level=55)], pre=246, egg=("Monster",))
    add(248, "Tyranitar", ("Rock", "Dark"), 3, pre=247, egg=("Monster",))

    # Lugia / Ho-Oh
    add(249, "Lugia", ("Psychic", "Flying"), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Navel Rock"],
        gender=255)
    add(250, "Ho-Oh", ("Fire", "Flying"), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Navel Rock"],
        gender=255)

    # Celebi
    add(251, "Celebi", ("Psychic", "Grass"), 1,
        fr_obtain=[ObtainMethod.EVENT], fr_loc=["Event only"],
        gender=255)

    # ── Gen 3: Hoenn (#252-#386) ────────────────────────────────────────

    # Treecko line
    add(252, "Treecko", ("Grass",), 1,
        evos=[E(253, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Dragon"), gender=31,
        em_obtain=[ObtainMethod.GIFT], em_loc=["Littleroot Town (starter)"])
    add(253, "Grovyle", ("Grass",), 2,
        evos=[E(254, EvoMethod.LEVEL, level=36)], pre=252,
        egg=("Monster", "Dragon"), gender=31)
    add(254, "Sceptile", ("Grass",), 3, pre=253, egg=("Monster", "Dragon"), gender=31)

    # Torchic line
    add(255, "Torchic", ("Fire",), 1,
        evos=[E(256, EvoMethod.LEVEL, level=16)],
        egg=("Field",), gender=31,
        em_obtain=[ObtainMethod.GIFT], em_loc=["Littleroot Town (starter)"])
    add(256, "Combusken", ("Fire", "Fighting"), 2,
        evos=[E(257, EvoMethod.LEVEL, level=36)], pre=255,
        egg=("Field",), gender=31)
    add(257, "Blaziken", ("Fire", "Fighting"), 3, pre=256, egg=("Field",), gender=31)

    # Mudkip line
    add(258, "Mudkip", ("Water",), 1,
        evos=[E(259, EvoMethod.LEVEL, level=16)],
        egg=("Monster", "Water 1"), gender=31,
        em_obtain=[ObtainMethod.GIFT], em_loc=["Littleroot Town (starter)"])
    add(259, "Marshtomp", ("Water", "Ground"), 2,
        evos=[E(260, EvoMethod.LEVEL, level=36)], pre=258,
        egg=("Monster", "Water 1"), gender=31)
    add(260, "Swampert", ("Water", "Ground"), 3, pre=259, egg=("Monster", "Water 1"), gender=31)

    # Poochyena line
    add(261, "Poochyena", ("Dark",), 1,
        evos=[E(262, EvoMethod.LEVEL, level=18)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 101-103"])
    add(262, "Mightyena", ("Dark",), 2, pre=261, egg=("Field",))

    # Zigzagoon line
    add(263, "Zigzagoon", ("Normal",), 1,
        evos=[E(264, EvoMethod.LEVEL, level=20)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 101-103"])
    add(264, "Linoone", ("Normal",), 2, pre=263, egg=("Field",))

    # Wurmple line
    add(265, "Wurmple", ("Bug",), 1,
        evos=[E(266, EvoMethod.LEVEL_SILCOON, level=7),
              E(268, EvoMethod.LEVEL_CASCOON, level=7)], egg=("Bug",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Petalburg Woods"])
    add(266, "Silcoon", ("Bug",), 2,
        evos=[E(267, EvoMethod.LEVEL, level=10)], pre=265, egg=("Bug",))
    add(267, "Beautifly", ("Bug", "Flying"), 3, pre=266, egg=("Bug",))
    add(268, "Cascoon", ("Bug",), 2,
        evos=[E(269, EvoMethod.LEVEL, level=10)], pre=265, egg=("Bug",))
    add(269, "Dustox", ("Bug", "Poison"), 3, pre=268, egg=("Bug",))

    # Lotad line
    add(270, "Lotad", ("Water", "Grass"), 1,
        evos=[E(271, EvoMethod.LEVEL, level=14)], egg=("Water 1", "Grass"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 102-103"])
    add(271, "Lombre", ("Water", "Grass"), 2,
        evos=[E(272, EvoMethod.STONE, stone=EvoStone.WATER_STONE)], pre=270,
        egg=("Water 1", "Grass"))
    add(272, "Ludicolo", ("Water", "Grass"), 3, pre=271, egg=("Water 1", "Grass"))

    # Seedot line
    add(273, "Seedot", ("Grass",), 1,
        evos=[E(274, EvoMethod.LEVEL, level=14)], egg=("Field", "Grass"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 102"])
    add(274, "Nuzleaf", ("Grass", "Dark"), 2,
        evos=[E(275, EvoMethod.STONE, stone=EvoStone.LEAF_STONE)], pre=273,
        egg=("Field", "Grass"))
    add(275, "Shiftry", ("Grass", "Dark"), 3, pre=274, egg=("Field", "Grass"))

    # Taillow line
    add(276, "Taillow", ("Normal", "Flying"), 1,
        evos=[E(277, EvoMethod.LEVEL, level=22)], egg=("Flying",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 104", "Petalburg Woods"])
    add(277, "Swellow", ("Normal", "Flying"), 2, pre=276, egg=("Flying",))

    # Wingull line
    add(278, "Wingull", ("Water", "Flying"), 1,
        evos=[E(279, EvoMethod.LEVEL, level=25)], egg=("Water 1", "Flying"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 103-110"])
    add(279, "Pelipper", ("Water", "Flying"), 2, pre=278, egg=("Water 1", "Flying"))

    # Ralts line
    add(280, "Ralts", ("Psychic",), 1,
        evos=[E(281, EvoMethod.LEVEL, level=20)], egg=("Amorphous",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 102"])
    add(281, "Kirlia", ("Psychic",), 2,
        evos=[E(282, EvoMethod.LEVEL, level=30)], pre=280, egg=("Amorphous",))
    add(282, "Gardevoir", ("Psychic",), 3, pre=281, egg=("Amorphous",))

    # Surskit line
    add(283, "Surskit", ("Bug", "Water"), 1,
        evos=[E(284, EvoMethod.LEVEL, level=22)], egg=("Water 1", "Bug"))
    add(284, "Masquerain", ("Bug", "Flying"), 2, pre=283, egg=("Water 1", "Bug"))

    # Shroomish line
    add(285, "Shroomish", ("Grass",), 1,
        evos=[E(286, EvoMethod.LEVEL, level=23)], egg=("Fairy", "Grass"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Petalburg Woods"])
    add(286, "Breloom", ("Grass", "Fighting"), 2, pre=285, egg=("Fairy", "Grass"))

    # Slakoth line
    add(287, "Slakoth", ("Normal",), 1,
        evos=[E(288, EvoMethod.LEVEL, level=18)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Petalburg Woods"])
    add(288, "Vigoroth", ("Normal",), 2,
        evos=[E(289, EvoMethod.LEVEL, level=36)], pre=287, egg=("Field",))
    add(289, "Slaking", ("Normal",), 3, pre=288, egg=("Field",))

    # Nincada line (special: Shedinja)
    add(290, "Nincada", ("Bug", "Ground"), 1,
        evos=[E(291, EvoMethod.LEVEL_NINJASK, level=20),
              E(292, EvoMethod.LEVEL_SHEDINJA, level=20)], egg=("Bug",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 116"])
    add(291, "Ninjask", ("Bug", "Flying"), 2, pre=290, egg=("Bug",))
    add(292, "Shedinja", ("Bug", "Ghost"), 2, pre=290, gender=255)

    # Whismur line
    add(293, "Whismur", ("Normal",), 1,
        evos=[E(294, EvoMethod.LEVEL, level=20)], egg=("Monster", "Field"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Rusturf Tunnel"])
    add(294, "Loudred", ("Normal",), 2,
        evos=[E(295, EvoMethod.LEVEL, level=40)], pre=293, egg=("Monster", "Field"))
    add(295, "Exploud", ("Normal",), 3, pre=294, egg=("Monster", "Field"))

    # Makuhita line
    add(296, "Makuhita", ("Fighting",), 1,
        evos=[E(297, EvoMethod.LEVEL, level=24)], egg=("Human-Like",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Granite Cave"])
    add(297, "Hariyama", ("Fighting",), 2, pre=296, egg=("Human-Like",))

    # Azurill already added above (298)

    # Nosepass
    add(299, "Nosepass", ("Rock",), 1, egg=("Mineral",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Granite Cave"])

    # Skitty line
    add(300, "Skitty", ("Normal",), 1,
        evos=[E(301, EvoMethod.STONE, stone=EvoStone.MOON_STONE)], egg=("Field", "Fairy"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 116"], gender=191)
    add(301, "Delcatty", ("Normal",), 2, pre=300, egg=("Field", "Fairy"), gender=191)

    # Sableye
    add(302, "Sableye", ("Dark", "Ghost"), 1, egg=("Human-Like",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Granite Cave"])

    # Mawile
    add(303, "Mawile", ("Steel",), 1, egg=("Field", "Fairy"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Granite Cave"])

    # Aron line
    add(304, "Aron", ("Steel", "Rock"), 1,
        evos=[E(305, EvoMethod.LEVEL, level=32)], egg=("Monster",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Granite Cave"])
    add(305, "Lairon", ("Steel", "Rock"), 2,
        evos=[E(306, EvoMethod.LEVEL, level=42)], pre=304, egg=("Monster",))
    add(306, "Aggron", ("Steel", "Rock"), 3, pre=305, egg=("Monster",))

    # Meditite line
    add(307, "Meditite", ("Fighting", "Psychic"), 1,
        evos=[E(308, EvoMethod.LEVEL, level=37)], egg=("Human-Like",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Mt. Pyre"])
    add(308, "Medicham", ("Fighting", "Psychic"), 2, pre=307, egg=("Human-Like",))

    # Electrike line
    add(309, "Electrike", ("Electric",), 1,
        evos=[E(310, EvoMethod.LEVEL, level=26)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 110"])
    add(310, "Manectric", ("Electric",), 2, pre=309, egg=("Field",))

    # Plusle / Minun
    add(311, "Plusle", ("Electric",), 1, egg=("Fairy",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 110"])
    add(312, "Minun", ("Electric",), 1, egg=("Fairy",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 110"])

    # Volbeat / Illumise
    add(313, "Volbeat", ("Bug",), 1, egg=("Bug", "Human-Like"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 117"], gender=0)
    add(314, "Illumise", ("Bug",), 1, egg=("Bug", "Human-Like"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 117"], gender=254)

    # Roselia
    add(315, "Roselia", ("Grass", "Poison"), 1, egg=("Fairy", "Grass"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 117"])

    # Gulpin line
    add(316, "Gulpin", ("Poison",), 1,
        evos=[E(317, EvoMethod.LEVEL, level=26)], egg=("Amorphous",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 110"])
    add(317, "Swalot", ("Poison",), 2, pre=316, egg=("Amorphous",))

    # Carvanha line
    add(318, "Carvanha", ("Water", "Dark"), 1,
        evos=[E(319, EvoMethod.LEVEL, level=30)], egg=("Water 2",),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 118-119"])
    add(319, "Sharpedo", ("Water", "Dark"), 2, pre=318, egg=("Water 2",))

    # Wailmer line
    add(320, "Wailmer", ("Water",), 1,
        evos=[E(321, EvoMethod.LEVEL, level=40)], egg=("Field", "Water 2"),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 122"])
    add(321, "Wailord", ("Water",), 2, pre=320, egg=("Field", "Water 2"))

    # Numel line
    add(322, "Numel", ("Fire", "Ground"), 1,
        evos=[E(323, EvoMethod.LEVEL, level=33)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 112", "Fiery Path"])
    add(323, "Camerupt", ("Fire", "Ground"), 2, pre=322, egg=("Field",))

    # Torkoal
    add(324, "Torkoal", ("Fire",), 1, egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Fiery Path"])

    # Spoink line
    add(325, "Spoink", ("Psychic",), 1,
        evos=[E(326, EvoMethod.LEVEL, level=32)], egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Jagged Pass"])
    add(326, "Grumpig", ("Psychic",), 2, pre=325, egg=("Field",))

    # Spinda
    add(327, "Spinda", ("Normal",), 1, egg=("Field", "Human-Like"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 113"])

    # Trapinch line
    add(328, "Trapinch", ("Ground",), 1,
        evos=[E(329, EvoMethod.LEVEL, level=35)], egg=("Bug",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 111 (desert)"])
    add(329, "Vibrava", ("Ground", "Dragon"), 2,
        evos=[E(330, EvoMethod.LEVEL, level=45)], pre=328, egg=("Bug",))
    add(330, "Flygon", ("Ground", "Dragon"), 3, pre=329, egg=("Bug",))

    # Cacnea line
    add(331, "Cacnea", ("Grass",), 1,
        evos=[E(332, EvoMethod.LEVEL, level=32)], egg=("Grass", "Human-Like"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 111 (desert)"])
    add(332, "Cacturne", ("Grass", "Dark"), 2, pre=331, egg=("Grass", "Human-Like"))

    # Swablu line
    add(333, "Swablu", ("Normal", "Flying"), 1,
        evos=[E(334, EvoMethod.LEVEL, level=35)], egg=("Flying", "Dragon"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 114-115"])
    add(334, "Altaria", ("Dragon", "Flying"), 2, pre=333, egg=("Flying", "Dragon"))

    # Zangoose / Seviper
    add(335, "Zangoose", ("Normal",), 1, egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 114"])
    add(336, "Seviper", ("Poison",), 1, egg=("Field", "Dragon"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 114"])

    # Lunatone / Solrock
    add(337, "Lunatone", ("Rock", "Psychic"), 1, egg=("Mineral",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Meteor Falls"], gender=255)
    add(338, "Solrock", ("Rock", "Psychic"), 1, egg=("Mineral",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Meteor Falls"], gender=255)

    # Barboach line
    add(339, "Barboach", ("Water", "Ground"), 1,
        evos=[E(340, EvoMethod.LEVEL, level=30)], egg=("Water 2",),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 111", "Meteor Falls"])
    add(340, "Whiscash", ("Water", "Ground"), 2, pre=339, egg=("Water 2",))

    # Corphish line
    add(341, "Corphish", ("Water",), 1,
        evos=[E(342, EvoMethod.LEVEL, level=30)], egg=("Water 1", "Water 3"),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 102-103"])
    add(342, "Crawdaunt", ("Water", "Dark"), 2, pre=341, egg=("Water 1", "Water 3"))

    # Baltoy line
    add(343, "Baltoy", ("Ground", "Psychic"), 1,
        evos=[E(344, EvoMethod.LEVEL, level=36)], egg=("Mineral",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 111 (desert)"], gender=255)
    add(344, "Claydol", ("Ground", "Psychic"), 2, pre=343, egg=("Mineral",), gender=255)

    # Lileep line
    add(345, "Lileep", ("Rock", "Grass"), 1,
        evos=[E(346, EvoMethod.LEVEL, level=40)], egg=("Water 3",),
        em_obtain=[ObtainMethod.FOSSIL], em_loc=["Rustboro City (Root Fossil)"])
    add(346, "Cradily", ("Rock", "Grass"), 2, pre=345, egg=("Water 3",))

    # Anorith line
    add(347, "Anorith", ("Rock", "Bug"), 1,
        evos=[E(348, EvoMethod.LEVEL, level=40)], egg=("Water 3",),
        em_obtain=[ObtainMethod.FOSSIL], em_loc=["Rustboro City (Claw Fossil)"])
    add(348, "Armaldo", ("Rock", "Bug"), 2, pre=347, egg=("Water 3",))

    # Feebas line
    add(349, "Feebas", ("Water",), 1,
        evos=[E(350, EvoMethod.BEAUTY)], egg=("Water 1", "Dragon"),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 119 (6 specific tiles)"])
    add(350, "Milotic", ("Water",), 2, pre=349, egg=("Water 1", "Dragon"))

    # Castform
    add(351, "Castform", ("Normal",), 1, egg=("Fairy", "Amorphous"),
        em_obtain=[ObtainMethod.GIFT], em_loc=["Weather Institute"])

    # Kecleon
    add(352, "Kecleon", ("Normal",), 1, egg=("Field",),
        em_obtain=[ObtainMethod.STATIC], em_loc=["Route 119-120"])

    # Shuppet line
    add(353, "Shuppet", ("Ghost",), 1,
        evos=[E(354, EvoMethod.LEVEL, level=37)], egg=("Amorphous",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Mt. Pyre"])
    add(354, "Banette", ("Ghost",), 2, pre=353, egg=("Amorphous",))

    # Duskull line
    add(355, "Duskull", ("Ghost",), 1,
        evos=[E(356, EvoMethod.LEVEL, level=37)], egg=("Amorphous",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Mt. Pyre"])
    add(356, "Dusclops", ("Ghost",), 2, pre=355, egg=("Amorphous",))

    # Tropius
    add(357, "Tropius", ("Grass", "Flying"), 1, egg=("Monster", "Grass"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 119"])

    # Chimecho
    add(358, "Chimecho", ("Psychic",), 1, egg=("Amorphous",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Mt. Pyre (rare)"])

    # Absol
    add(359, "Absol", ("Dark",), 1, egg=("Field",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Route 120"])

    # Wynaut already added above (360)

    # Snorunt line
    add(361, "Snorunt", ("Ice",), 1,
        evos=[E(362, EvoMethod.LEVEL, level=42)], egg=("Fairy", "Mineral"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Shoal Cave"])
    add(362, "Glalie", ("Ice",), 2, pre=361, egg=("Fairy", "Mineral"))

    # Spheal line
    add(363, "Spheal", ("Ice", "Water"), 1,
        evos=[E(364, EvoMethod.LEVEL, level=32)], egg=("Water 1", "Field"),
        em_obtain=[ObtainMethod.WILD], em_loc=["Shoal Cave"])
    add(364, "Sealeo", ("Ice", "Water"), 2,
        evos=[E(365, EvoMethod.LEVEL, level=44)], pre=363, egg=("Water 1", "Field"))
    add(365, "Walrein", ("Ice", "Water"), 3, pre=364, egg=("Water 1", "Field"))

    # Clamperl line
    add(366, "Clamperl", ("Water",), 1,
        evos=[E(367, EvoMethod.TRADE_ITEM, trade_item=TradeItem.DEEP_SEA_TOOTH),
              E(368, EvoMethod.TRADE_ITEM, trade_item=TradeItem.DEEP_SEA_SCALE)],
        egg=("Water 1",),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Underwater"])
    add(367, "Huntail", ("Water",), 2, pre=366, egg=("Water 1",))
    add(368, "Gorebyss", ("Water",), 2, pre=366, egg=("Water 1",))

    # Relicanth
    add(369, "Relicanth", ("Water", "Rock"), 1, egg=("Water 1", "Water 2"),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Underwater"])

    # Luvdisc
    add(370, "Luvdisc", ("Water",), 1, egg=("Water 2",),
        em_obtain=[ObtainMethod.FISHING], em_loc=["Route 128"])

    # Bagon line
    add(371, "Bagon", ("Dragon",), 1,
        evos=[E(372, EvoMethod.LEVEL, level=30)], egg=("Dragon",),
        em_obtain=[ObtainMethod.WILD], em_loc=["Meteor Falls (back room)"])
    add(372, "Shelgon", ("Dragon",), 2,
        evos=[E(373, EvoMethod.LEVEL, level=50)], pre=371, egg=("Dragon",))
    add(373, "Salamence", ("Dragon", "Flying"), 3, pre=372, egg=("Dragon",))

    # Beldum line
    add(374, "Beldum", ("Steel", "Psychic"), 1,
        evos=[E(375, EvoMethod.LEVEL, level=20)], egg=("Mineral",),
        em_obtain=[ObtainMethod.GIFT], em_loc=["Steven's house (post-E4)"],
        gender=255)
    add(375, "Metang", ("Steel", "Psychic"), 2,
        evos=[E(376, EvoMethod.LEVEL, level=45)], pre=374, egg=("Mineral",), gender=255)
    add(376, "Metagross", ("Steel", "Psychic"), 3, pre=375, egg=("Mineral",), gender=255)

    # Regirock / Regice / Registeel
    add(377, "Regirock", ("Rock",), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Desert Ruins"], gender=255)
    add(378, "Regice", ("Ice",), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Island Cave"], gender=255)
    add(379, "Registeel", ("Steel",), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Ancient Tomb"], gender=255)

    # Latias / Latios
    add(380, "Latias", ("Dragon", "Psychic"), 1,
        em_obtain=[ObtainMethod.WILD], em_loc=["Roaming (Emerald/Sapphire)"],
        gender=254)
    add(381, "Latios", ("Dragon", "Psychic"), 1,
        em_obtain=[ObtainMethod.WILD], em_loc=["Roaming (Emerald/Ruby)"],
        gender=0)

    # Kyogre / Groudon / Rayquaza
    add(382, "Kyogre", ("Water",), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Cave of Origin / Marine Cave"],
        gender=255)
    add(383, "Groudon", ("Ground",), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Cave of Origin / Terra Cave"],
        gender=255)
    add(384, "Rayquaza", ("Dragon", "Flying"), 1,
        em_obtain=[ObtainMethod.STATIC], em_loc=["Sky Pillar"],
        gender=255)

    # Jirachi / Deoxys
    add(385, "Jirachi", ("Steel", "Psychic"), 1,
        fr_obtain=[ObtainMethod.EVENT], fr_loc=["Event only"],
        gender=255)
    add(386, "Deoxys", ("Psychic",), 1,
        fr_obtain=[ObtainMethod.STATIC], fr_loc=["Birth Island"],
        em_obtain=[ObtainMethod.STATIC], em_loc=["Birth Island"],
        gender=255)

    return dex


# ── Module-level singleton ──────────────────────────────────────────────────

POKEDEX: Dict[int, PokemonSpecies] = _build_pokedex()
POKEDEX_BY_NAME: Dict[str, PokemonSpecies] = {p.name.lower(): p for p in POKEDEX.values()}
NATIONAL_DEX_SIZE = 386


# ── Helper functions ────────────────────────────────────────────────────────

def get_species(pid: int) -> Optional[PokemonSpecies]:
    return POKEDEX.get(pid)


def get_species_by_name(name: str) -> Optional[PokemonSpecies]:
    return POKEDEX_BY_NAME.get(name.lower())


def get_evolution_chain(pid: int) -> List[int]:
    """Return the full evolution chain starting from the base form."""
    species = POKEDEX.get(pid)
    if species is None:
        return []
    # Walk back to base
    base = species
    while base.pre_evolution_id is not None:
        parent = POKEDEX.get(base.pre_evolution_id)
        if parent is None:
            break
        base = parent
    # Walk forward collecting all forms
    chain = []
    _collect_chain(base.id, chain)
    return chain


def _collect_chain(pid: int, chain: List[int]) -> None:
    if pid in chain:
        return
    chain.append(pid)
    species = POKEDEX.get(pid)
    if species:
        for evo in species.evolutions:
            _collect_chain(evo.target_id, chain)


def get_all_trade_evolutions() -> List[Tuple[int, int, Optional[TradeItem]]]:
    """Return all (source_id, target_id, trade_item) for trade evolutions."""
    results = []
    for pid, species in POKEDEX.items():
        for evo in species.evolutions:
            if evo.method in (EvoMethod.TRADE, EvoMethod.TRADE_ITEM):
                results.append((pid, evo.target_id, evo.trade_item))
    return results


def get_all_stone_evolutions() -> List[Tuple[int, int, EvoStone]]:
    """Return all (source_id, target_id, stone) for stone evolutions."""
    results = []
    for pid, species in POKEDEX.items():
        for evo in species.evolutions:
            if evo.method == EvoMethod.STONE and evo.stone:
                results.append((pid, evo.target_id, evo.stone))
    return results


def get_all_friendship_evolutions() -> List[Tuple[int, int, EvoMethod]]:
    """Return all (source_id, target_id, method) for friendship evolutions."""
    results = []
    for pid, species in POKEDEX.items():
        for evo in species.evolutions:
            if evo.method in (EvoMethod.FRIENDSHIP, EvoMethod.FRIENDSHIP_DAY,
                              EvoMethod.FRIENDSHIP_NIGHT):
                results.append((pid, evo.target_id, evo.method))
    return results


def get_baby_pokemon() -> List[int]:
    """Return IDs of all baby Pokémon."""
    return [pid for pid, sp in POKEDEX.items() if sp.is_baby]


def get_fishing_pokemon(game: str = "firered") -> List[int]:
    """Return IDs of all Pokémon obtainable by fishing."""
    key = "obtain_methods_firered" if game == "firered" else "obtain_methods_emerald"
    return [pid for pid, sp in POKEDEX.items()
            if ObtainMethod.FISHING in getattr(sp, key, [])]


def get_static_encounters(game: str = "firered") -> List[int]:
    """Return IDs of all static encounter Pokémon."""
    key = "obtain_methods_firered" if game == "firered" else "obtain_methods_emerald"
    return [pid for pid, sp in POKEDEX.items()
            if ObtainMethod.STATIC in getattr(sp, key, [])]


def living_dex_requirements() -> Dict[str, List[int]]:
    """
    Return a breakdown of what's needed for a complete shiny living dex.
    Groups by evolution method.
    """
    result = {
        "wild_catch": [],
        "fishing": [],
        "surf": [],
        "evolution_level": [],
        "evolution_stone": [],
        "evolution_trade": [],
        "evolution_friendship": [],
        "evolution_special": [],
        "breeding_baby": [],
        "static_encounter": [],
        "gift": [],
        "fossil": [],
        "safari": [],
        "game_corner": [],
        "event": [],
    }
    for pid, sp in sorted(POKEDEX.items()):
        if sp.evolution_stage == 1 and not sp.is_baby:
            # Base form: how do we get it?
            methods = sp.obtain_methods_firered + sp.obtain_methods_emerald
            if ObtainMethod.FISHING in methods:
                result["fishing"].append(pid)
            elif ObtainMethod.SURF in methods:
                result["surf"].append(pid)
            elif ObtainMethod.STATIC in methods:
                result["static_encounter"].append(pid)
            elif ObtainMethod.GIFT in methods:
                result["gift"].append(pid)
            elif ObtainMethod.FOSSIL in methods:
                result["fossil"].append(pid)
            elif ObtainMethod.SAFARI in methods:
                result["safari"].append(pid)
            elif ObtainMethod.GAME_CORNER in methods:
                result["game_corner"].append(pid)
            elif ObtainMethod.EVENT in methods:
                result["event"].append(pid)
            elif ObtainMethod.WILD in methods:
                result["wild_catch"].append(pid)
        elif sp.is_baby:
            result["breeding_baby"].append(pid)
        elif sp.evolution_stage > 1:
            # Evolved form: how do we evolve it?
            parent = POKEDEX.get(sp.pre_evolution_id)
            if parent:
                for evo in parent.evolutions:
                    if evo.target_id == pid:
                        if evo.method == EvoMethod.LEVEL:
                            result["evolution_level"].append(pid)
                        elif evo.method == EvoMethod.STONE:
                            result["evolution_stone"].append(pid)
                        elif evo.method in (EvoMethod.TRADE, EvoMethod.TRADE_ITEM):
                            result["evolution_trade"].append(pid)
                        elif evo.method in (EvoMethod.FRIENDSHIP, EvoMethod.FRIENDSHIP_DAY,
                                            EvoMethod.FRIENDSHIP_NIGHT):
                            result["evolution_friendship"].append(pid)
                        else:
                            result["evolution_special"].append(pid)
                        break
    return result
