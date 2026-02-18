"""
main_runner – Top-level automation controller.

Orchestrates the full shiny-hunting pipeline:
  1. Generate a legitimate seed via tid_engine.
  2. Produce the proper TID/SID.
  3. Start an emulator instance with that ID.
  4. Navigate to the encounter area using game_bot.
  5. Begin wild-encounter farming.
  6. On shiny detection → capture, save, log metadata.
  7. Destroy the instance and move to the next seed.

Supports many simultaneous emulator sessions via a thread pool.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from modules.config import (
    DATABASE_PATH,
    ENCOUNTER_AREAS,
    ENCOUNTER_TIMEOUT_SECONDS,
    FINAL_SAVE_DIR,
    MAX_CONCURRENT_INSTANCES,
    SAVE_DIR,
    GameVersion,
)
from modules.database import ShinyRecord, insert_shiny, total_shinies, get_unique_species
from modules.game_bot import GameBot, PokemonData
from modules.shiny_scan import ShinyScanner
from modules.tid_engine import TrainerID, enumerate_all_ids, seed_to_ids

logger = logging.getLogger(__name__)

# ── Globals for graceful shutdown ────────────────────────────────────────────

_shutdown_event = threading.Event()


def _signal_handler(sig, frame):
    logger.info("Shutdown signal received. Stopping all instances …")
    _shutdown_event.set()


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── Instance worker ──────────────────────────────────────────────────────────

@dataclass
class InstanceResult:
    """Outcome of a single emulator session."""
    instance_id: str = ""
    seed: int = 0
    tid: int = 0
    sid: int = 0
    shinies_found: List[PokemonData] = field(default_factory=list)
    encounters: int = 0
    save_path: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


def _run_instance(
    trainer_id: TrainerID,
    area: str,
    game_version: str,
    rom_path: Optional[Path],
) -> InstanceResult:
    """
    Worker function executed in a thread for a single emulator session.

    Loops encounter → check shiny → catch/run until a shiny is found
    or the shutdown event fires.
    """
    result = InstanceResult(seed=trainer_id.seed, tid=trainer_id.tid, sid=trainer_id.sid)
    bot = GameBot()
    scanner = ShinyScanner()
    start_time = time.monotonic()

    try:
        instance = bot.launch(
            seed=trainer_id.seed,
            tid=trainer_id.tid,
            sid=trainer_id.sid,
            game_version=game_version,
            rom_path=rom_path,
        )
        result.instance_id = instance.instance_id
        logger.info(
            "[%s] Started — seed=0x%04X TID=%d SID=%d",
            instance.instance_id, trainer_id.seed, trainer_id.tid, trainer_id.sid,
        )

        # Navigate to the target encounter area
        if not bot.navigate_to_area(area):
            result.error = f"Failed to navigate to {area}"
            return result

        # ── Encounter loop ───────────────────────────────────────────
        while not _shutdown_event.is_set():
            elapsed = time.monotonic() - start_time
            if elapsed > ENCOUNTER_TIMEOUT_SECONDS:
                logger.warning("[%s] Timeout after %.0fs", instance.instance_id, elapsed)
                break

            pokemon = bot.trigger_encounter()
            if pokemon is None:
                continue

            result.encounters += 1

            # Check shininess via memory
            scan = scanner.check_memory(
                personality_value=pokemon.personality_value,
                tid=trainer_id.tid,
                sid=trainer_id.sid,
            )

            if scan.is_shiny:
                logger.info(
                    "[%s] ✨ SHINY FOUND! PV=0x%08X after %d encounters",
                    instance.instance_id, pokemon.personality_value, result.encounters,
                )
                pokemon.is_shiny = True
                result.shinies_found.append(pokemon)

                # Catch and save
                bot.catch_pokemon()
                save_path = bot.save_game()
                result.save_path = save_path

                # Log to database
                record = ShinyRecord(
                    id=None,
                    tid=trainer_id.tid,
                    sid=trainer_id.sid,
                    seed=trainer_id.seed,
                    species=str(pokemon.species_id),
                    instance_id=instance.instance_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    save_path=str(save_path) if save_path else "",
                    game_version=game_version,
                    personality=pokemon.personality_value,
                )
                insert_shiny(record)

                # One shiny per instance is enough; move to next seed
                break
            else:
                bot.run_from_battle()

    except FileNotFoundError as exc:
        result.error = str(exc)
        logger.error("[%s] %s", result.instance_id or "???", exc)
    except Exception as exc:
        result.error = str(exc)
        logger.exception("[%s] Unexpected error", result.instance_id or "???")
    finally:
        bot.destroy()
        result.duration_seconds = time.monotonic() - start_time

    return result


# ── Controller ───────────────────────────────────────────────────────────────

class MainRunner:
    """
    Manages the pool of emulator instances and iterates through seeds.

    Usage::

        runner = MainRunner(max_workers=4, area="route1")
        runner.run()
    """

    def __init__(
        self,
        max_workers: int = MAX_CONCURRENT_INSTANCES,
        area: str = "route1",
        game_version: str = GameVersion.FIRE_RED,
        rom_path: Optional[Path] = None,
        start_seed: int = 0x0000,
    ) -> None:
        self.max_workers = max_workers
        self.area = area
        self.game_version = game_version
        self.rom_path = rom_path
        self.start_seed = start_seed
        self._results: List[InstanceResult] = []

    def run(self) -> List[InstanceResult]:
        """
        Main entry point.  Iterates through seeds, launching up to
        *max_workers* emulator instances concurrently.
        """
        logger.info(
            "MainRunner starting — workers=%d, area=%s, game=%s, start_seed=0x%04X",
            self.max_workers, self.area, self.game_version, self.start_seed,
        )

        FINAL_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        SAVE_DIR.mkdir(parents=True, exist_ok=True)

        seed_gen = enumerate_all_ids(self.game_version)
        # Skip to start_seed
        for _ in range(self.start_seed):
            next(seed_gen, None)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: Dict[Future, TrainerID] = {}

            for trainer_id in seed_gen:
                if _shutdown_event.is_set():
                    break

                # Wait if we're at capacity
                while len(futures) >= self.max_workers:
                    self._collect_done(futures)
                    if _shutdown_event.is_set():
                        break
                    time.sleep(0.5)

                if _shutdown_event.is_set():
                    break

                future = pool.submit(
                    _run_instance,
                    trainer_id,
                    self.area,
                    self.game_version,
                    self.rom_path,
                )
                futures[future] = trainer_id

            # Drain remaining futures
            while futures:
                self._collect_done(futures)
                time.sleep(0.5)

        logger.info(
            "MainRunner finished — %d sessions completed, %d total shinies in DB",
            len(self._results), total_shinies(),
        )
        return self._results

    def _collect_done(self, futures: Dict[Future, TrainerID]) -> None:
        """Collect completed futures and log their results."""
        done = [f for f in futures if f.done()]
        for f in done:
            trainer_id = futures.pop(f)
            try:
                result = f.result()
                self._results.append(result)
                if result.shinies_found:
                    logger.info(
                        "Seed 0x%04X → %d shiny(ies) in %d encounters (%.1fs)",
                        result.seed, len(result.shinies_found),
                        result.encounters, result.duration_seconds,
                    )
                else:
                    logger.debug(
                        "Seed 0x%04X → no shiny after %d encounters (%.1fs)",
                        result.seed, result.encounters, result.duration_seconds,
                    )
            except Exception as exc:
                logger.error("Seed 0x%04X raised: %s", trainer_id.seed, exc)

    def get_progress(self) -> dict:
        """Return a summary of progress so far."""
        return {
            "sessions_completed": len(self._results),
            "total_encounters": sum(r.encounters for r in self._results),
            "total_shinies": sum(len(r.shinies_found) for r in self._results),
            "unique_species_in_db": len(get_unique_species()),
            "errors": sum(1 for r in self._results if r.error),
        }


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gen 3 Shiny Automation – Main Runner",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=MAX_CONCURRENT_INSTANCES,
        help=f"Max concurrent emulator instances (default: {MAX_CONCURRENT_INSTANCES})",
    )
    parser.add_argument(
        "--area", "-a",
        type=str,
        default="route1",
        choices=list(ENCOUNTER_AREAS.keys()),
        help="Encounter area to farm (default: route1)",
    )
    parser.add_argument(
        "--game", "-g",
        type=str,
        default=GameVersion.FIRE_RED,
        help=f"Game version (default: {GameVersion.FIRE_RED})",
    )
    parser.add_argument(
        "--rom",
        type=str,
        default=None,
        help="Path to ROM file (default: emulator/firered.gba)",
    )
    parser.add_argument(
        "--start-seed",
        type=lambda x: int(x, 0),
        default=0x0000,
        help="Starting seed in hex (default: 0x0000)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    rom_path = Path(args.rom) if args.rom else None

    runner = MainRunner(
        max_workers=args.workers,
        area=args.area,
        game_version=args.game,
        rom_path=rom_path,
        start_seed=args.start_seed,
    )

    results = runner.run()

    # Print summary
    progress = runner.get_progress()
    print("\n" + "=" * 60)
    print("  Gen 3 Shiny Automation — Session Summary")
    print("=" * 60)
    for key, val in progress.items():
        print(f"  {key:.<40} {val}")
    print("=" * 60)


if __name__ == "__main__":
    main()
