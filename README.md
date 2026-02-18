# Gen 3 Shiny Automation

Automated shiny hunting system for Pokémon Fire Red (Gen 3) with legitimate TID/SID generation, multi-instance emulator control, visual+memory shiny detection, and automated in-game trade merging.

## Architecture

```
gen3-shiny-automation/
├── modules/
│   ├── config.py              # Global configuration, paths, constants
│   ├── tid_engine.py          # Legitimate TID/SID generation from seeds (LCRNG)
│   ├── game_bot.py            # Emulator control, memory reading, battle automation
│   ├── shiny_scan.py          # Shiny detection (memory + visual palette comparison)
│   ├── database.py            # SQLite persistence layer (shiny_log.db)
│   ├── main_runner.py         # Top-level automation controller (multi-threaded)
│   ├── save_merger.py         # Trade automation for consolidating shinies
│   └── adapters/
│       ├── pokefinder_adapter.py  # Bridge to PokeFinder RNG logic
│       └── pokebot_adapter.py     # Bridge to pokebot-gen3 bot logic
├── emulator/                  # mGBA binary + ROM (user-supplied) + saves
├── sprites/
│   ├── normal/                # Normal sprite PNGs (e.g. bulbasaur.png)
│   └── shiny/                 # Shiny sprite PNGs
├── external/                  # Cloned repos (PokeFinder, pokebot-gen3)
├── analysis/                  # Data analysis scripts
├── training/                  # ML training data (future)
├── final_save/                # Master save with all shinies merged
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Prerequisites

1. **Python 3.10+**
2. **mGBA emulator** — place the binary in `emulator/` or install [libmgba-py](https://github.com/hanzi/libmgba-py/)
3. **Pokémon Fire Red ROM** — place your legally-owned ROM at `emulator/firered.gba`
4. **Git** — needed to clone the external repositories

## Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Clone external repositories into external/
cd external
git clone https://github.com/Admiral-Fish/PokeFinder.git
git clone https://github.com/40Cakes/pokebot-gen3.git
cd ..

# Add sprite references
# Place normal sprites in sprites/normal/<species>.png
# Place shiny sprites in sprites/shiny/<species>.png
```

## Usage

### Run the shiny hunter
```bash
python -m modules.main_runner --workers 4 --area route1 --verbose
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `--workers` / `-w` | 4 | Max concurrent emulator instances |
| `--area` / `-a` | route1 | Encounter area to farm |
| `--game` / `-g` | firered | Game version |
| `--rom` | emulator/firered.gba | Path to ROM |
| `--start-seed` | 0x0000 | Starting seed (hex) |
| `--verbose` / `-v` | off | Debug logging |

### Run the save merger (after all species found)
```bash
python -m modules.save_merger
```

### Test TID/SID generation
```bash
python -m modules.tid_engine
```

## Module Reference

### tid_engine
Implements the exact Gen 3 LCRNG to derive TID/SID from 16-bit initial seeds. Every generated ID pair is legitimately recreatable on real GBA hardware.

Key functions:
- `seed_to_ids(seed)` — Convert a seed to a TrainerID (TID + SID)
- `enumerate_all_ids()` — Yield all 65,536 valid seed→ID mappings
- `find_ids_for_tid(tid)` — Reverse-lookup seeds for a given TID
- `get_id_for_instance(n)` — Deterministic ID for emulator instance #n

### game_bot
Wraps mGBA (via libmgba-py or subprocess) for emulator lifecycle, memory reading, button input, navigation, encounter farming, and battle execution.

### shiny_scan
Dual detection: memory-based (PID⊕TID⊕SID formula, instant) and visual (palette comparison against reference sprites in `sprites/`).

### database
SQLite layer for `shiny_log.db`. Stores TID, SID, seed, species, instance_id, timestamp, save_path, and merge status for every shiny caught.

### main_runner
Orchestrates the full pipeline: seed generation → emulator launch → encounter farming → shiny capture → logging → teardown. Supports concurrent instances via ThreadPoolExecutor.

### save_merger
After all target species have shiny entries, launches linked emulator pairs and automates in-game trades to consolidate all shinies into one master save in `final_save/`.

### Adapters
- **pokefinder_adapter** — Re-implements PokeFinder's Gen 3 RNG methods (Method 1/2/4), seed search, and shiny frame search
- **pokebot_adapter** — Re-implements pokebot-gen3's memory reading, symbol tables, movement logic, encounter detection, and battle sequences

## Automation Flow

1. `tid_engine` generates a legitimate seed
2. Seed → TID/SID pair via LCRNG
3. `game_bot` launches an mGBA instance with that save
4. Bot navigates to the target encounter area
5. Encounter loop: walk → battle → check shiny → catch or run
6. On shiny: catch, save game, log to `shiny_log.db`
7. Destroy instance, advance to next seed
8. Repeat across multiple concurrent instances

## Expansion (Future Work)

The system is designed for easy expansion to:
- **Leaf Green** — same RNG, same adapters
- **Emerald** — seed=0 always, frame-count-based ID generation
- **Ruby / Sapphire** — RTC-based seeding

When adding a new game:
1. Update `tid_engine` with game-specific ID logic (already stubbed)
2. Add symbol tables in `pokebot_adapter.py`
3. Add sprite sets to `sprites/`
4. Add trade-room navigation in `save_merger.py`
5. Update `SUPPORTED_VERSIONS` in `config.py`

## Credits

- [PokeFinder](https://github.com/Admiral-Fish/PokeFinder) by Admiral-Fish — RNG tool and LCRNG reference
- [pokebot-gen3](https://github.com/40Cakes/pokebot-gen3) by 40Cakes — Shiny hunting bot, libmgba integration, symbol tables
- [pret decompilations](https://github.com/pret) — Game symbol tables and memory layouts
