"""
symbol_tables – Full symbol tables from pret decompilation projects.

Provides memory addresses and sizes for all game versions:
  - Fire Red (USA v1.0)
  - Leaf Green (USA v1.0)
  - Ruby (USA v1.0)
  - Sapphire (USA v1.0)
  - Emerald (USA)

Sourced from:
  - pokefirered: https://github.com/pret/pokefirered
  - pokeemerald: https://github.com/pret/pokeemerald
  - pokeruby: https://github.com/pret/pokeruby
  - pokebot-gen3 symbol tables
"""

from __future__ import annotations

from typing import Dict, Tuple


# Type alias: symbol_name → (address, size_bytes)
SymbolTable = Dict[str, Tuple[int, int]]


# ═══════════════════════════════════════════════════════════════════════════════
#  FIRE RED (USA v1.0)
# ═══════════════════════════════════════════════════════════════════════════════

FIRERED_SYMBOLS: SymbolTable = {
    # ── Core state ──
    "gMain":                    (0x030022C0, 0x438),
    "gSaveBlock1Ptr":           (0x03005008, 4),
    "gSaveBlock2Ptr":           (0x0300500C, 4),
    "gPokemonStoragePtr":       (0x03005010, 4),

    # ── Party ──
    "gPlayerParty":             (0x02024284, 600),
    "gPlayerPartyCount":        (0x02024280, 4),
    "gEnemyParty":              (0x0202402C, 600),

    # ── Battle ──
    "gBattleOutcome":           (0x02023E8A, 1),
    "gBattleTypeFlags":         (0x02022B4C, 4),
    "gBattleMons":              (0x02023BE4, 0x160),
    "gActiveBattler":           (0x02023D6B, 1),
    "gBattlerAttacker":         (0x02023D6C, 1),
    "gBattlerTarget":           (0x02023D6D, 1),
    "gMoveResultFlags":         (0x02023DCC, 4),
    "gCurrentMove":             (0x02023D4E, 2),
    "gLastUsedMove":            (0x02023D72, 2),
    "gBattleWeather":           (0x02023F1C, 2),
    "gBattleTerrain":           (0x02022B50, 1),
    "gBattleCommunication":     (0x02023E82, 8),
    "gBattleScripting":         (0x02023FC4, 0x20),
    "gMultiHitCounter":         (0x02023D74, 1),
    "gBattleMoveDamage":        (0x02023D50, 4),
    "gHpDealt":                 (0x02023D54, 4),
    "gTakenDmg":                (0x02023D58, 16),
    "gBattleResults":           (0x03004F50, 0x24),

    # ── Overworld ──
    "gObjectEvents":            (0x02036E38, 0x960),
    "gMapHeader":               (0x02036DFC, 0x1C),
    "gCamera":                  (0x02037360, 8),
    "gTasks":                   (0x03005090, 0x400),
    "sPlayTimeCounterState":    (0x02039318, 1),
    "gSpecialVar_Result":       (0x020375F0, 2),
    "gSpecialVar_0x8000":       (0x020375D8, 2),
    "gSpecialVar_0x8001":       (0x020375DA, 2),
    "gSpecialVar_0x8002":       (0x020375DC, 2),
    "gSpecialVar_0x8003":       (0x020375DE, 2),
    "gSpecialVar_0x8004":       (0x020375E0, 2),

    # ── RNG ──
    "gRngValue":                (0x03005000, 4),

    # ── Bag / Items ──
    # Save block 1 offsets for FR/LG bag pockets:
    #   Items:     0x0310 (42 slots × 4 bytes)
    #   KeyItems:  0x03B8 (30 slots × 4 bytes)
    #   PokeBalls: 0x0430 (13 slots × 4 bytes)
    #   TMs/HMs:   0x0464 (58 slots × 4 bytes)
    #   Berries:   0x054C (43 slots × 4 bytes)

    # ── Daycare ──
    # Save block 1 offset for daycare data in FR/LG
    # Daycare: 0x2F80 (contains 2 Pokémon + step counter + egg)

    # ── PC Storage ──
    # gPokemonStoragePtr → PC boxes (14 boxes × 30 slots × 80 bytes)

    # ── Flags / Vars ──
    # Save block 1: flags at 0x0EE0, vars at 0x1000

    # ── Player ──
    "gPlayerAvatar":            (0x02037078, 0x18),
    "gQuestLogState":           (0x03005E88, 1),
}

# Save Block 1 offsets for Fire Red / Leaf Green
FRLG_SB1_OFFSETS = {
    "player_name":      0x0000,
    "player_gender":    0x0008,
    "player_id":        0x000A,  # TID at +0, SID at +2
    "play_time":        0x000E,
    "options":          0x0013,
    "money":            0x0290,  # u32, XOR encrypted
    "coins":            0x0294,  # u16, XOR encrypted
    "registered_item":  0x0296,
    "pc_items":         0x0298,  # 30 slots × 4 bytes
    "bag_items":        0x0310,  # 42 slots × 4 bytes
    "bag_key_items":    0x03B8,  # 30 slots × 4 bytes
    "bag_pokeballs":    0x0430,  # 13 slots × 4 bytes
    "bag_tms_hms":      0x0464,  # 58 slots × 4 bytes
    "bag_berries":      0x054C,  # 43 slots × 4 bytes
    "encryption_key":   0x0F20,  # u32 used to XOR money/coins
    "flags":            0x0EE0,
    "vars":             0x1000,
    "warp_data":        0x1080,
    "map_data":         0x1098,
    "daycare":          0x2F80,
    "roamer":           0x3144,
    "berry_trees":      0x3168,
}

# Save Block 2 offsets for Fire Red / Leaf Green
FRLG_SB2_OFFSETS = {
    "player_name":      0x0000,
    "player_gender":    0x0008,
    "player_id":        0x000A,
    "play_time":        0x000E,
    "options":          0x0013,
    "pokedex_owned":    0x0028,
    "pokedex_seen":     0x005C,
    "national_dex":     0x0090,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  LEAF GREEN (USA v1.0) – Same as Fire Red (identical engine)
# ═══════════════════════════════════════════════════════════════════════════════

LEAFGREEN_SYMBOLS: SymbolTable = dict(FIRERED_SYMBOLS)
LEAFGREEN_SB1_OFFSETS = dict(FRLG_SB1_OFFSETS)
LEAFGREEN_SB2_OFFSETS = dict(FRLG_SB2_OFFSETS)


# ═══════════════════════════════════════════════════════════════════════════════
#  EMERALD (USA)
# ═══════════════════════════════════════════════════════════════════════════════

EMERALD_SYMBOLS: SymbolTable = {
    # ── Core state ──
    "gMain":                    (0x030022C0, 0x438),
    "gSaveBlock1Ptr":           (0x03005D8C, 4),
    "gSaveBlock2Ptr":           (0x03005D90, 4),
    "gPokemonStoragePtr":       (0x03005D94, 4),

    # ── Party ──
    "gPlayerParty":             (0x020244EC, 600),
    "gPlayerPartyCount":        (0x020244E9, 1),
    "gEnemyParty":              (0x0202402C, 600),

    # ── Battle ──
    "gBattleOutcome":           (0x0202421C, 1),
    "gBattleTypeFlags":         (0x02022FEC, 4),
    "gBattleMons":              (0x02024084, 0x160),
    "gActiveBattler":           (0x02024064, 1),
    "gBattlerAttacker":         (0x02024065, 1),
    "gBattlerTarget":           (0x02024066, 1),
    "gBattleWeather":           (0x020243CC, 2),
    "gCurrentMove":             (0x020241EA, 2),

    # ── Overworld ──
    "gObjectEvents":            (0x02036E38, 0x960),
    "gMapHeader":               (0x02037318, 0x1C),
    "gTasks":                   (0x03005E00, 0x400),
    "sPlayTimeCounterState":    (0x0300500C, 1),
    "gSpecialVar_Result":       (0x020375F0, 2),

    # ── RNG ──
    "gRngValue":                (0x03005D80, 4),

    # ── Player ──
    "gPlayerAvatar":            (0x02037078, 0x18),
}

# Save Block 1 offsets for Emerald
EMERALD_SB1_OFFSETS = {
    "player_name":      0x0000,
    "player_gender":    0x0008,
    "player_id":        0x000A,
    "play_time":        0x000E,
    "money":            0x0490,  # u32, XOR encrypted
    "coins":            0x0494,  # u16, XOR encrypted
    "registered_item":  0x0496,
    "bag_items":        0x0560,  # 30 slots × 4 bytes
    "bag_key_items":    0x05D8,  # 30 slots × 4 bytes
    "bag_pokeballs":    0x0650,  # 16 slots × 4 bytes
    "bag_tms_hms":      0x0690,  # 64 slots × 4 bytes
    "bag_berries":      0x0790,  # 46 slots × 4 bytes
    "encryption_key":   0x00AC,
    "flags":            0x1270,
    "vars":             0x139C,
    "daycare":          0x3030,
    "roamer":           0x3144,
    "berry_trees":      0x31B4,
    "feebas_seed":      0x2E6A,  # u16 for Feebas tile calculation
    "contest_winners":  0x2E04,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  RUBY / SAPPHIRE (USA v1.0)
# ═══════════════════════════════════════════════════════════════════════════════

RUBY_SYMBOLS: SymbolTable = {
    # ── Core state ──
    "gMain":                    (0x030022C0, 0x438),
    "gSaveBlock1Ptr":           (0x03005D8C, 4),
    "gSaveBlock2Ptr":           (0x03005D90, 4),
    "gPokemonStoragePtr":       (0x03005D94, 4),

    # ── Party ──
    "gPlayerParty":             (0x03004360, 600),
    "gPlayerPartyCount":        (0x03004350, 4),
    "gEnemyParty":              (0x030045C0, 600),

    # ── Battle ──
    "gBattleOutcome":           (0x02023E8A, 1),
    "gBattleTypeFlags":         (0x02022B4C, 4),

    # ── Overworld ──
    "gObjectEvents":            (0x02036E38, 0x960),
    "sPlayTimeCounterState":    (0x0300500C, 1),

    # ── RNG ──
    "gRngValue":                (0x03004818, 4),
}

SAPPHIRE_SYMBOLS: SymbolTable = dict(RUBY_SYMBOLS)

# Save Block 1 offsets for Ruby/Sapphire
RS_SB1_OFFSETS = {
    "player_name":      0x0000,
    "player_gender":    0x0008,
    "player_id":        0x000A,
    "play_time":        0x000E,
    "money":            0x0490,
    "coins":            0x0494,
    "bag_items":        0x0560,  # 20 slots × 4 bytes
    "bag_key_items":    0x05B0,  # 20 slots × 4 bytes
    "bag_pokeballs":    0x0600,  # 16 slots × 4 bytes
    "bag_tms_hms":      0x0640,  # 64 slots × 4 bytes
    "bag_berries":      0x0740,  # 46 slots × 4 bytes
    "encryption_key":   0x00AC,
    "flags":            0x1220,
    "vars":             0x1340,
    "daycare":          0x2F20,
    "roamer":           0x3094,
    "feebas_seed":      0x2DD6,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Game version detection & lookup
# ═══════════════════════════════════════════════════════════════════════════════

# Game code → (symbols, sb1_offsets, sb2_offsets_or_none)
GAME_DATA = {
    "firered":   (FIRERED_SYMBOLS,   FRLG_SB1_OFFSETS,    FRLG_SB2_OFFSETS),
    "leafgreen": (LEAFGREEN_SYMBOLS, LEAFGREEN_SB1_OFFSETS, LEAFGREEN_SB2_OFFSETS),
    "emerald":   (EMERALD_SYMBOLS,   EMERALD_SB1_OFFSETS, None),
    "ruby":      (RUBY_SYMBOLS,      RS_SB1_OFFSETS,      None),
    "sapphire":  (SAPPHIRE_SYMBOLS,  RS_SB1_OFFSETS,      None),
}

# ROM game codes for auto-detection
ROM_GAME_CODES = {
    "BPRE": "firered",
    "BPGE": "leafgreen",
    "BPEE": "emerald",
    "AXVE": "ruby",
    "AXPE": "sapphire",
}


def get_symbols(game_version: str) -> SymbolTable:
    """Get the symbol table for a game version."""
    data = GAME_DATA.get(game_version)
    if data is None:
        raise ValueError(f"Unknown game version: {game_version}")
    return data[0]


def get_sb1_offsets(game_version: str) -> dict:
    """Get Save Block 1 offsets for a game version."""
    data = GAME_DATA.get(game_version)
    if data is None:
        raise ValueError(f"Unknown game version: {game_version}")
    return data[1]


def get_sb2_offsets(game_version: str) -> dict:
    """Get Save Block 2 offsets for a game version (FR/LG only)."""
    data = GAME_DATA.get(game_version)
    if data is None:
        raise ValueError(f"Unknown game version: {game_version}")
    return data[2] or {}


def detect_game_version(game_code: str) -> str:
    """Detect game version from ROM game code (4 chars)."""
    code = game_code.strip().upper()[:4]
    return ROM_GAME_CODES.get(code, "firered")


def is_frlg(game_version: str) -> bool:
    return game_version in ("firered", "leafgreen")


def is_rse(game_version: str) -> bool:
    return game_version in ("ruby", "sapphire", "emerald")


def is_emerald(game_version: str) -> bool:
    return game_version == "emerald"
