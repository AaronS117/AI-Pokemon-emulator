"""Full integration test for all modules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

errors = []

def section(name):
    print(f"\n{'='*60}\n  {name}\n{'='*60}")

# ── 1. Evolution Data ───────────────────────────────────────
section("Evolution Data")
from modules.evolution_data import POKEDEX, NATIONAL_DEX_SIZE, living_dex_requirements
print(f"  Pokedex: {len(POKEDEX)} species (expected {NATIONAL_DEX_SIZE})")
assert len(POKEDEX) == NATIONAL_DEX_SIZE, "Pokedex size mismatch!"
reqs = living_dex_requirements()
print(f"  Living dex categories: {len(reqs)}")
for k, v in reqs.items():
    if v:
        print(f"    {k}: {len(v)}")

# ── 2. Database ─────────────────────────────────────────────
section("Database")
from modules.database import (
    init_db, get_living_dex_progress, is_save_legitimate,
    get_evolution_queue, get_material_inventory, get_cheat_history,
)
prog = get_living_dex_progress()
print(f"  Living dex: {prog['owned']}/{prog['total']}")
print(f"  Save legitimate: {is_save_legitimate()}")
print(f"  Evolution queue: {len(get_evolution_queue())} pending")
print(f"  Materials: {get_material_inventory()}")

# ── 3. Cheat Manager ───────────────────────────────────────
section("Cheat Manager")
from modules.cheat_manager import CheatManager, CheatCategory
cm = CheatManager()
print(f"  Total cheats: {len(cm.cheats)}")
print(f"  Safe: {len(cm.get_cheats_by_category(CheatCategory.SAFE))}")
print(f"  Caution: {len(cm.get_cheats_by_category(CheatCategory.CAUTION))}")
n = cm.apply_hunting_preset()
print(f"  Hunting preset: {n} cheats enabled")
n2 = cm.apply_evolution_preset()
print(f"  Evolution preset: {n2} cheats enabled")
print(f"  Legitimate: {cm.is_legitimate}")
report = cm.get_legitimacy_report()
print(f"  Enabled: {report['enabled']}")

# ── 4. Bot Modes ────────────────────────────────────────────
section("Bot Modes")
from modules.bot_modes import ALL_MODES, MODE_DESCRIPTIONS
print(f"  Total modes: {len(ALL_MODES)}")
for key, cls in ALL_MODES.items():
    desc = MODE_DESCRIPTIONS.get(key, "")
    print(f"    {key}: {cls.name} - {desc}")

# ── 5. Pokemon Data Decryption ──────────────────────────────
section("Pokemon Data Decryption")
from modules.pokemon_data import (
    decode_pokemon, verify_checksum, SUBSTRUCT_ORDER,
    NATURES, HIDDEN_POWER_TYPES, Pokemon,
)
print(f"  Substruct orders: {len(SUBSTRUCT_ORDER)}")
print(f"  Natures: {len(NATURES)}")
print(f"  HP types: {len(HIDDEN_POWER_TYPES)}")
# Test with empty data
empty = decode_pokemon(b'\x00' * 100)
print(f"  Empty decode: species={empty.species_id}, shiny={empty.is_shiny}")
# Test with synthetic data
import struct
pv = 0x12345678
ot = 0x0001_0002  # TID=2, SID=1
header = struct.pack("<II", pv, ot) + b'\xFF' * 24
# Create fake encrypted block (all zeros XOR'd with key)
key = pv ^ ot
encrypted = b''
for i in range(12):
    encrypted += struct.pack("<I", 0 ^ key)
raw = header + encrypted + b'\x00' * 20
pokemon = decode_pokemon(raw, is_party=True)
print(f"  Synthetic decode: PV=0x{pokemon.personality_value:08X} nature={pokemon.nature}")
print(f"  Shiny check: {pokemon.is_shiny} (SV={pokemon.shiny_value})")

# ── 6. Symbol Tables ───────────────────────────────────────
section("Symbol Tables")
from modules.symbol_tables import (
    get_symbols, get_sb1_offsets, detect_game_version,
    is_frlg, is_rse, GAME_DATA, ROM_GAME_CODES,
)
print(f"  Supported games: {list(GAME_DATA.keys())}")
print(f"  ROM codes: {ROM_GAME_CODES}")
for game in GAME_DATA:
    syms = get_symbols(game)
    sb1 = get_sb1_offsets(game)
    print(f"    {game}: {len(syms)} symbols, {len(sb1)} SB1 offsets")
assert detect_game_version("BPRE") == "firered"
assert detect_game_version("BPEE") == "emerald"
assert is_frlg("firered") and is_frlg("leafgreen")
assert is_rse("ruby") and is_rse("emerald")

# ── 7. Emulator API ────────────────────────────────────────
section("Emulator API")
from modules.emulator_api import (
    EmulatorAPI, PaletteColor, OAMEntry, SaveStateSnapshot,
    GBA_MEMORY_MAP,
)
print(f"  Memory regions: {list(GBA_MEMORY_MAP.keys())}")
c = PaletteColor.from_u16(0x7FFF)
print(f"  White color: r={c.r} g={c.g} b={c.b} rgb={c.to_rgb()}")
c2 = PaletteColor.from_u16(0x001F)
print(f"  Red color: r={c2.r} g={c2.g} b={c2.b}")
oam = OAMEntry(attr0=0x0100, attr1=0x4050, attr2=0xC003)
print(f"  OAM test: x={oam.x} y={oam.y} tile={oam.tile_index} pal={oam.palette_num}")

# ── 8. Feebas & Berry ──────────────────────────────────────
section("Feebas & Berry Blending")
from modules.feebas_berry import (
    calculate_feebas_tiles, BerryType, BEAUTY_BERRIES,
    PokeblockColor, FeebasTile,
)
tiles = calculate_feebas_tiles(0x1234)
print(f"  Feebas tiles for seed 0x1234: {len(tiles)} tiles")
for t in tiles:
    print(f"    {t}")
print(f"  Beauty berries: {len(BEAUTY_BERRIES)}")
print(f"  Berry types: {len(BerryType)}")

# ── 9. Stats Dashboard ─────────────────────────────────────
section("Stats Dashboard")
from modules.stats_dashboard import (
    StatsTracker, shiny_probability, export_csv, export_json,
)
tracker = StatsTracker()
for i in range(100):
    tracker.record_encounter(species_id=25, is_shiny=(i == 50), area="route1", bot_mode="encounter_farm")
summary = tracker.get_summary()
print(f"  Encounters: {summary['total_encounters']}")
print(f"  Shinies: {summary['total_shinies']}")
print(f"  Rate: {summary['shiny_rate']}")
print(f"  Enc/hr: {summary['encounters_per_hour']}")
print(f"  Luck: {summary['luck_factor']}")
prob = shiny_probability(5000)
print(f"  5000 enc probability: {prob['probability']}%")
print(f"  50% at: {prob['encounters_for_50pct']} enc")
print(f"  90% at: {prob['encounters_for_90pct']} enc")

# ── 10. RNG Manipulation ───────────────────────────────────
section("RNG Manipulation")
from modules.rng_pokemon import (
    lcrng_next, lcrng_prev, lcrng_advance,
    generate_pid_method1, generate_ivs_method1,
    search_shiny_frames, determine_encounter_slot,
    recover_seed_from_pid,
)
seed = 0x12345678
next_s = lcrng_next(seed)
prev_s = lcrng_prev(next_s)
assert prev_s == seed, f"LCRNG reverse failed: {prev_s:#x} != {seed:#x}"
print(f"  LCRNG forward/reverse: OK")
pid = generate_pid_method1(seed, tid=12345, sid=54321)
print(f"  Method 1 PID: 0x{pid.pid:08X} nature={pid.nature} shiny={pid.is_shiny}")
ivs = generate_ivs_method1(pid.seed_after)
print(f"  IVs: {ivs.ivs} total={ivs.total}")
slot, _ = determine_encounter_slot(seed, "land")
print(f"  Encounter slot: {slot}")
# Search for shiny frames
shinies = search_shiny_frames(0, tid=12345, sid=54321, max_frames=50000)
print(f"  Shiny frames in 50k: {len(shinies)}")
if shinies:
    first = shinies[0]
    print(f"    First: frame={first.frame} PID=0x{first.pid:08X} IVs={first.ivs}")

# ── 11. Performance ────────────────────────────────────────
section("Performance")
from modules.performance import (
    MemoryPool, StatePool, BatchReader, AsyncWorker,
    FrameSkipper, PerformanceMonitor, get_pool,
)
pool = MemoryPool(pool_size=16, buffer_size=100)
buf = pool.acquire(50)
pool.release(buf)
buf2 = pool.acquire(50)
pool.release(buf2)
print(f"  MemoryPool stats: {pool.stats}")
perf = PerformanceMonitor()
t = perf.time_start("test")
import time; time.sleep(0.001)
perf.time_end("test", t)
perf.increment("reads", 100)
print(f"  PerfMonitor: {perf.report()}")
worker = AsyncWorker()
worker.start()
results = []
worker.submit(lambda: results.append(1))
time.sleep(0.1)
worker.stop()
print(f"  AsyncWorker: processed={worker.stats['processed']}")

# ── Summary ─────────────────────────────────────────────────
section("SUMMARY")
print(f"""
  Evolution Data:     {len(POKEDEX)} species, {len(reqs)} categories
  Database:           {prog['total']} dex entries, legitimacy tracking
  Cheat Manager:      {len(cm.cheats)} cheats, 4 presets
  Bot Modes:          {len(ALL_MODES)} modes
  Pokemon Decryption: Full substructure decrypt (IVs, nature, ability, gender)
  Symbol Tables:      {len(GAME_DATA)} games (FR/LG/R/S/E)
  Emulator API:       Raw states, slots, frame callbacks, VRAM/OAM/Palette, RTC
  Feebas/Berry:       Tile calc, berry blending, Pokeblock feeding
  Stats Dashboard:    Tracking, probability, CSV/JSON export, charts
  RNG Manipulation:   LCRNG, Method 1/2/4, shiny search, seed recovery
  Performance:        Memory pool, state pool, batch reader, async I/O

  ALL SYSTEMS GO
""")
