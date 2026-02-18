"""
Gen 3 Shiny Automation – Desktop Application
=============================================
Run with:  python app.py

Modern dark-themed GUI for managing headless mGBA emulator instances
that hunt for shiny Pokemon in Generation 3 games.

Features:
  - Modern dark UI via customtkinter
  - CPU generation detection with per-core thread affinity
  - ROM browser with validation
  - Multiple bot modes (encounter farm, starter reset, static encounter)
  - Per-instance speed, frame counter, live screen preview
  - Start / stop / pause individual or all instances
  - Shiny encounter log with live counter
  - Persistent settings (settings.json)
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ── Ensure project root is importable ────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import customtkinter as ctk
import psutil
from PIL import Image, ImageTk

# Project modules
from modules.config import (
    ENCOUNTER_AREAS,
    GameVersion,
    SAVE_DIR,
)
from modules.database import (
    init_db, log_shiny, total_shinies, recent_shinies,
    get_living_dex_progress, mark_pokemon_owned, log_cheat as db_log_cheat,
    is_save_legitimate,
)
from modules.tid_engine import seed_to_ids
from modules.bot_modes import ALL_MODES, MODE_DESCRIPTIONS, ModeResult, ModeStatus, BotMode
from modules.cheat_manager import CheatManager, CheatCategory
from modules.evolution_data import POKEDEX, NATIONAL_DEX_SIZE, living_dex_requirements
from modules.stats_dashboard import StatsTracker, shiny_probability
from modules.performance import get_async_worker, PerformanceMonitor, perf_monitor
from modules.notifications import NotificationManager

# AI subsystem (optional – private paid module)
try:
    from ai.ai_bridge import AIBridge, AIConfig, AIFrameResult
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    AIBridge = None  # type: ignore[assignment,misc]
    AIConfig = None   # type: ignore[assignment,misc]
    AIFrameResult = None  # type: ignore[assignment,misc]

# ── Logging ──────────────────────────────────────────────────────────────────

# Thread-safe queue that feeds the live log window
_log_queue: queue.Queue = queue.Queue(maxsize=5000)


class _QueueHandler(logging.Handler):
    """Logging handler that pushes records into _log_queue for the GUI."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_queue.put_nowait(self.format(record))
        except queue.Full:
            pass  # drop oldest if full


_queue_handler = _QueueHandler()
_queue_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                      datefmt="%H:%M:%S")
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger().addHandler(_queue_handler)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger("app")

# ── Color palette ────────────────────────────────────────────────────────────
C = {
    "bg_dark":    "#0f0f0f",
    "bg_card":    "#1a1a2e",
    "bg_input":   "#16213e",
    "accent":     "#7c3aed",
    "accent_h":   "#6d28d9",
    "green":      "#22c55e",
    "red":        "#ef4444",
    "yellow":     "#eab308",
    "gold":       "#fbbf24",
    "text":       "#e2e8f0",
    "text_dim":   "#94a3b8",
    "border":     "#334155",
}

# ── Settings persistence ─────────────────────────────────────────────────────
SETTINGS_FILE = ROOT_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "rom_path": "",
    "save_directory": str(SAVE_DIR),
    "speed_multiplier": 0,
    "max_instances": 1,
    "target_area": "route1",
    "video_enabled": False,
    "bot_mode": "encounter_farm",
    "window_geometry": "1360x820",
}


_GAME_PATTERNS = {
    "firered":   re.compile(r"fire.?red", re.IGNORECASE),
    "leafgreen":  re.compile(r"leaf.?green", re.IGNORECASE),
    "emerald":   re.compile(r"emerald", re.IGNORECASE),
    "ruby":      re.compile(r"\bruby\b", re.IGNORECASE),
    "sapphire":  re.compile(r"sapphire", re.IGNORECASE),
}


def detect_rom_in_dir(directory: Path) -> Optional[Path]:
    """Scan *directory* for any .gba file matching a known game name (case-insensitive)."""
    if not directory.exists():
        return None
    for gba in sorted(directory.glob("*.gba")):
        stem = gba.stem
        for version, pat in _GAME_PATTERNS.items():
            if pat.search(stem):
                logger.info("Auto-detected ROM: %s  (version=%s)", gba.name, version)
                return gba
    # Fallback: return any .gba found
    fallback = next(directory.glob("*.gba"), None)
    if fallback:
        logger.info("Auto-detected ROM (unknown version): %s", fallback.name)
    return fallback


def detect_game_version_from_path(rom_path: Path) -> str:
    """Infer game version string from ROM filename."""
    stem = rom_path.stem
    for version, pat in _GAME_PATTERNS.items():
        if pat.search(stem):
            return version
    return "firered"


def save_exists_for_instance(instance_id: int, rom_path: Path) -> bool:
    """Return True if a non-empty .sav file exists for this instance."""
    from modules.config import SAVE_DIR as _SD
    sav = _SD / str(instance_id) / f"{rom_path.stem}.sav"
    return sav.exists() and sav.stat().st_size > 0


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ── CPU Generation Detection ─────────────────────────────────────────────────

def detect_cpu_details() -> dict:
    """Detect CPU vendor, generation, microarchitecture, and capabilities."""
    proc = platform.processor()
    cpu_physical = psutil.cpu_count(logical=False) or 1
    cpu_logical = psutil.cpu_count(logical=True) or 1
    freq = psutil.cpu_freq()
    freq_ghz = round(freq.current / 1000, 2) if freq else 0
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)

    # Parse vendor / family / model from platform.processor()
    vendor = "Unknown"
    family = 0
    model = 0
    stepping = 0
    arch_name = "Unknown"
    gen_label = ""

    if "AuthenticAMD" in proc or "AMD" in proc:
        vendor = "AMD"
        parts = proc.split()
        for i, p in enumerate(parts):
            if p == "Family" and i + 1 < len(parts):
                try: family = int(parts[i + 1])
                except ValueError: pass
            elif p == "Model" and i + 1 < len(parts):
                try: model = int(parts[i + 1])
                except ValueError: pass
            elif p == "Stepping" and i + 1 < len(parts):
                try: stepping = int(parts[i + 1].rstrip(","))
                except ValueError: pass

        # AMD family → microarchitecture
        amd_families = {
            23: ("Zen / Zen+ / Zen 2", "Ryzen 1000-3000"),
            25: ("Zen 3 / Zen 3+", "Ryzen 5000"),
            26: ("Zen 5", "Ryzen 9000"),
        }
        if family in amd_families:
            arch_name, gen_label = amd_families[family]
        elif family == 25 and model >= 96:
            arch_name, gen_label = "Zen 4", "Ryzen 7000"

    elif "GenuineIntel" in proc or "Intel" in proc:
        vendor = "Intel"
        parts = proc.split()
        for i, p in enumerate(parts):
            if p == "Family" and i + 1 < len(parts):
                try: family = int(parts[i + 1])
                except ValueError: pass
            elif p == "Model" and i + 1 < len(parts):
                try: model = int(parts[i + 1])
                except ValueError: pass

        # Intel model → generation (simplified)
        intel_gens = {
            (6, 151): ("Alder Lake", "12th Gen"),
            (6, 154): ("Alder Lake", "12th Gen"),
            (6, 183): ("Raptor Lake", "13th Gen"),
            (6, 186): ("Raptor Lake", "14th Gen"),
            (6, 189): ("Arrow Lake", "15th Gen"),
        }
        key = (family, model)
        if key in intel_gens:
            arch_name, gen_label = intel_gens[key]

    # Determine optimal instance count based on CPU
    # Each mGBA instance uses ~1 core at full speed
    # Reserve 1 core for OS + GUI
    max_by_cpu = max(1, cpu_physical - 1)
    max_by_ram = max(1, int(ram_gb // 1.5))
    suggested_max = min(max_by_cpu, max_by_ram, 8)

    # Performance tier
    if freq_ghz >= 4.0 and cpu_physical >= 6:
        perf_tier = "Excellent"
        perf_note = "Can run max instances at full speed"
    elif freq_ghz >= 3.5 and cpu_physical >= 4:
        perf_tier = "Good"
        perf_note = "Comfortable multi-instance hunting"
    else:
        perf_tier = "Moderate"
        perf_note = "Recommend 1-2 instances"

    return {
        "vendor": vendor,
        "family": family,
        "model": model,
        "stepping": stepping,
        "arch_name": arch_name,
        "gen_label": gen_label,
        "cpu_physical": cpu_physical,
        "cpu_logical": cpu_logical,
        "freq_ghz": freq_ghz,
        "ram_gb": ram_gb,
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "suggested_max": suggested_max,
        "perf_tier": perf_tier,
        "perf_note": perf_note,
        "smt": cpu_logical > cpu_physical,
    }


def set_thread_affinity(thread_index: int, cpu_count: int) -> None:
    """Pin the current thread to a specific CPU core (Windows only)."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        handle = ctypes.windll.kernel32.GetCurrentThread()
        core = (thread_index + 1) % cpu_count  # skip core 0 (GUI)
        mask = 1 << core
        ctypes.windll.kernel32.SetThreadAffinityMask(handle, mask)
    except Exception:
        pass


# ── Bot Modes ────────────────────────────────────────────────────────────────

BOT_MODES = {
    "encounter_farm": {
        "label": "Wild Encounter Farm",
        "desc": "Walk in grass to trigger random encounters.",
        "status": "Ready",
    },
    "starter_reset": {
        "label": "Starter Soft Reset",
        "desc": "Soft-reset and check starter for shininess.",
        "status": "Ready",
    },
    "static_encounter": {
        "label": "Static Encounter",
        "desc": "Soft-reset in front of a legendary/gift.",
        "status": "Ready",
    },
    "fishing": {
        "label": "Fishing",
        "desc": "Fish with registered rod for shiny water Pokémon.",
        "status": "Ready",
    },
    "sweet_scent": {
        "label": "Sweet Scent",
        "desc": "Guaranteed encounters via Sweet Scent field move.",
        "status": "Ready",
    },
    "breeding": {
        "label": "Breeding / Egg Hatch",
        "desc": "Hatch daycare eggs and check for shinies.",
        "status": "Ready",
    },
    "safari_zone": {
        "label": "Safari Zone",
        "desc": "Hunt shinies in the Safari Zone.",
        "status": "Ready",
    },
    "rock_smash": {
        "label": "Rock Smash",
        "desc": "Smash rocks for encounters (Geodude, etc.).",
        "status": "Ready",
    },
    "level_evolution": {
        "label": "Level Evolution",
        "desc": "Level a Pokémon to its evolution threshold.",
        "status": "Ready",
    },
    "stone_evolution": {
        "label": "Stone Evolution",
        "desc": "Apply evolution stones from bag.",
        "status": "Ready",
    },
    "trade_evolution": {
        "label": "Trade Evolution",
        "desc": "Coordinate trade evolutions between instances.",
        "status": "Planned",
    },
}


# ── Emulator worker ─────────────────────────────────────────────────────────

@dataclass
class InstanceState:
    instance_id: int = 0
    status: str = "idle"
    seed: int = 0
    tid: int = 0
    sid: int = 0
    encounters: int = 0
    frame_count: int = 0
    fps: float = 0.0
    speed_multiplier: int = 0
    bot_mode: str = "encounter_farm"
    last_screenshot: Optional[Image.Image] = None
    shiny_pokemon: str = ""
    error: str = ""
    cpu_core: int = -1
    manual_control: bool = False  # True = user has taken over, bot pauses
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _pause_event: threading.Event = field(default_factory=threading.Event)
    _input_queue: "queue.Queue" = field(default_factory=lambda: __import__('queue').Queue())

    def request_stop(self):
        self._stop_event.set()
        self._pause_event.set()  # unblock any pause-wait immediately

    def request_pause(self):
        if self._pause_event.is_set() and not self._stop_event.is_set():
            self._pause_event.clear()
        else:
            self._pause_event.set()

    def send_input(self, button_name: str):
        """Queue a manual button press from the GUI thread."""
        self._input_queue.put(button_name)

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set() and not self._stop_event.is_set()

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()


# Global stats tracker shared across all workers
_global_stats = StatsTracker()
_notifier = NotificationManager()
_ai_bridge: "AIBridge | None" = None


def get_global_stats() -> StatsTracker:
    return _global_stats


def get_ai_bridge():
    return _ai_bridge


def _worker_capture_screen(bot, state) -> None:
    """Grab a screenshot from the emulator and store it in state."""
    try:
        sc = bot.get_screenshot()
        if sc:
            state.last_screenshot = sc
    except Exception:
        pass


def _worker_new_game_intro(bot, state, GBAButton, GState, player_name: str = "RED") -> bool:
    """
    Attempt to navigate the new-game intro sequence for Fire Red.
    Types the player name and advances through Oak's speech.
    Returns True if we reach OVERWORLD/CHOOSE_STARTER, False on timeout.
    """
    iid = state.instance_id
    logger.info("[Instance %d] Fresh save detected – starting new-game intro sequence", iid)
    logger.info("[Instance %d] Will type player name: %s", iid, player_name)

    # GBA character map for the naming screen (Fire Red A-Z row)
    CHAR_MAP = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
    # Fire Red naming screen layout: 9 chars per row, A=col0 row0
    CHARS_PER_ROW = 9

    def _press_stop():
        return state.should_stop

    # Step 1: Advance through intro (Game Freak logo, title screen)
    logger.info("[Instance %d] Advancing through intro screens (pressing A)…", iid)
    for _ in range(300):
        if _press_stop():
            return False
        bot.press_button(GBAButton.A)
        bot.advance_frames(8)
        state.frame_count = bot.frame_count
        gs = bot.get_game_state()
        if gs == GState.MAIN_MENU:
            break

    # Step 2: Start new game from main menu
    logger.info("[Instance %d] Selecting 'New Game' from main menu", iid)
    for _ in range(60):
        if _press_stop():
            return False
        bot.press_button(GBAButton.A)
        bot.advance_frames(10)
        state.frame_count = bot.frame_count

    # Step 3: Skip Oak's intro speech (keep pressing A/B)
    logger.info("[Instance %d] Skipping Oak's intro speech…", iid)
    for _ in range(400):
        if _press_stop():
            return False
        bot.press_button(GBAButton.A)
        bot.advance_frames(6)
        state.frame_count = bot.frame_count
        gs = bot.get_game_state()
        if gs == GState.NAMING_SCREEN:
            logger.info("[Instance %d] Reached naming screen", iid)
            break

    # Step 4: Type player name on naming screen
    logger.info("[Instance %d] Typing player name '%s'…", iid, player_name)
    cur_col, cur_row = 0, 0
    for ch in player_name.upper():
        if _press_stop():
            return False
        if ch not in CHAR_MAP:
            continue
        target_idx = CHAR_MAP[ch]
        target_col = target_idx % CHARS_PER_ROW
        target_row = target_idx // CHARS_PER_ROW
        # Navigate to character
        dc = target_col - cur_col
        dr = target_row - cur_row
        for _ in range(abs(dr)):
            btn = GBAButton.DOWN if dr > 0 else GBAButton.UP
            bot.press_button(btn)
            bot.advance_frames(4)
        for _ in range(abs(dc)):
            btn = GBAButton.RIGHT if dc > 0 else GBAButton.LEFT
            bot.press_button(btn)
            bot.advance_frames(4)
        bot.press_button(GBAButton.A)
        bot.advance_frames(6)
        cur_col, cur_row = target_col, target_row
        state.frame_count = bot.frame_count
        logger.debug("[Instance %d] Typed '%s'", iid, ch)

    # Confirm name (navigate to OK button – bottom row)
    logger.info("[Instance %d] Confirming name", iid)
    for _ in range(5):
        bot.press_button(GBAButton.DOWN)
        bot.advance_frames(4)
    bot.press_button(GBAButton.A)
    bot.advance_frames(30)

    # Step 5: Skip remaining cutscenes until overworld/choose starter
    logger.info("[Instance %d] Skipping post-name cutscenes…", iid)
    for _ in range(600):
        if _press_stop():
            return False
        bot.press_button(GBAButton.A)
        bot.advance_frames(8)
        state.frame_count = bot.frame_count
        _worker_capture_screen(bot, state)
        gs = bot.get_game_state()
        if gs in (GState.OVERWORLD, GState.CHOOSE_STARTER):
            logger.info("[Instance %d] Reached playable state: %s", iid, gs.name)
            return True

    logger.warning("[Instance %d] New-game intro timed out – switching to manual mode", iid)
    return False


def emulator_worker(
    state: InstanceState,
    rom_path: str,
    area: str,
    speed: int,
    cpu_count: int,
):
    """Background thread running one emulator instance."""
    iid = state.instance_id
    wlog = logging.getLogger(f"worker.{iid}")
    set_thread_affinity(iid, cpu_count)
    state.cpu_core = (iid + 1) % cpu_count

    wlog.info("=" * 60)
    wlog.info("Instance %d starting  |  ROM: %s", iid, rom_path)
    wlog.info("Instance %d  seed=0x%04X  TID=%d  SID=%d  mode=%s",
              iid, state.seed, state.tid, state.sid, state.bot_mode)

    # ── Shiny math summary ────────────────────────────────────────────────
    from modules.tid_engine import TrainerID as _TID
    _tid_obj = _TID(seed=state.seed, tid=state.tid, sid=state.sid)
    wlog.info("Instance %d  Shiny check: TID^SID = 0x%04X  (threshold <8 = shiny)",
              iid, state.tid ^ state.sid)
    wlog.info("Instance %d  Any PID where (TID^SID^PID_high^PID_low) < 8 is SHINY", iid)
    # Show a few example shiny PIDs
    _examples = []
    for _pv in range(0, 0xFFFFFFFF, 0x10000):
        if _tid_obj.is_shiny_pid(_pv):
            _examples.append(f"0x{_pv:08X}")
        if len(_examples) >= 4:
            break
    wlog.info("Instance %d  Example shiny PIDs: %s", iid, ", ".join(_examples) or "none in first scan")

    try:
        from modules.game_bot import GameBot, GBAButton, GameState as GState
        state.status = "booting"
        state.speed_multiplier = speed

        # ── Check save file ───────────────────────────────────────────────
        _rom_p = Path(rom_path)
        _has_save = save_exists_for_instance(iid, _rom_p)
        if _has_save:
            wlog.info("Instance %d  Save file found – will boot into existing game", iid)
        else:
            wlog.warning("Instance %d  NO SAVE FILE found at emulator/saves/%d/%s.sav",
                         iid, iid, _rom_p.stem)
            wlog.warning("Instance %d  Will attempt new-game intro sequence, then fall back to MANUAL mode", iid)

        bot = GameBot()
        bot.launch(seed=state.seed, tid=state.tid, sid=state.sid, rom_path=_rom_p)
        wlog.info("Instance %d  Emulator launched (headless mGBA)", iid)

        # ── Boot sequence ─────────────────────────────────────────────────
        if not _has_save:
            # Try to play through the new-game intro automatically
            _reached_game = _worker_new_game_intro(bot, state, GBAButton, GState)
            if not _reached_game:
                wlog.warning("Instance %d  Could not complete intro – enabling MANUAL mode", iid)
                state.manual_control = True
                state.status = "manual"
                wlog.info("Instance %d  Manual mode active. Use the Control button in the instance window.", iid)
                wlog.info("Instance %d  Default keys: A=a  B=s  Start=Enter  Select=Backspace  D-pad=Arrows", iid)
        else:
            # Existing save: advance frames pressing A to skip title
            wlog.info("Instance %d  Booting from save – advancing past title screen…", iid)
            for bf in range(600):
                if state.should_stop:
                    bot.destroy()
                    state.status = "stopped"
                    return
                if bf % 30 == 0:
                    bot.press_button(GBAButton.A)
                else:
                    bot.advance_frames(1)
                state.frame_count = bot.frame_count
                if bf % 60 == 0:
                    _worker_capture_screen(bot, state)
                if bf > 60:
                    gs = bot.get_game_state()
                    if gs in (GState.OVERWORLD, GState.BATTLE,
                              GState.CHOOSE_STARTER, GState.MAIN_MENU):
                        wlog.info("Instance %d  Reached game state: %s", iid, gs.name)
                        break

        state.status = "running"
        wlog.info("Instance %d  Boot complete – entering main loop (mode=%s)", iid, state.bot_mode)

        # Navigate to area for encounter-based modes
        if state.bot_mode in ("encounter_farm", "sweet_scent", "rock_smash",
                              "safari_zone", "fishing"):
            wlog.info("Instance %d  Navigating to area: %s", iid, area)
            try:
                bot.navigate_to_area(area)
            except Exception as exc:
                wlog.warning("Instance %d  Navigation failed (continuing): %s", iid, exc)

        # Instantiate the correct BotMode
        mode = _create_mode(state.bot_mode, bot)
        mode.start()

        # Async worker for non-blocking DB writes
        async_worker = get_async_worker()

        # FPS tracking
        fps_timer = time.time()
        fps_frame_start = bot.frame_count

        # Main loop: call mode.step() repeatedly
        while not state.should_stop:
            # Handle pause / manual control
            while (state.is_paused or state.manual_control) and not state.should_stop:
                if state.manual_control:
                    state.status = "manual"
                    # Drain queued manual inputs and send to emulator
                    import queue as _queue
                    while True:
                        try:
                            btn_name = state._input_queue.get_nowait()
                            _btn_map = {
                                "a": GBAButton.A, "b": GBAButton.B,
                                "start": GBAButton.START, "select": GBAButton.SELECT,
                                "up": GBAButton.UP, "down": GBAButton.DOWN,
                                "left": GBAButton.LEFT, "right": GBAButton.RIGHT,
                                "l": GBAButton.L, "r": GBAButton.R,
                            }
                            gbtn = _btn_map.get(btn_name.lower())
                            if gbtn is not None:
                                bot.press_button(gbtn, hold_frames=4)
                                state.frame_count = bot.frame_count
                                # Capture screenshot after input
                                try:
                                    sc = bot.get_screenshot()
                                    if sc:
                                        state.last_screenshot = sc
                                except Exception:
                                    pass
                        except _queue.Empty:
                            break
                    time.sleep(0.016)  # ~60fps polling
                else:
                    state.status = "paused"
                    time.sleep(0.05)
            if state.should_stop:
                break
            state.status = "running"

            # Execute one mode step
            t_start = perf_monitor.time_start("mode_step")
            result = mode.step()
            perf_monitor.time_end("mode_step", t_start)

            # Update state from result
            state.frame_count = bot.frame_count
            state.encounters = mode.encounters

            # FPS calculation
            now = time.time()
            if now - fps_timer >= 1.0:
                state.fps = (bot.frame_count - fps_frame_start) / (now - fps_timer)
                fps_timer = now
                fps_frame_start = bot.frame_count

            # Live screen capture for GUI preview (every 30 frames ~= 0.5s at 60fps)
            if state.frame_count % 30 == 0:
                try:
                    screenshot = bot.get_screenshot()
                    if screenshot is not None:
                        state.last_screenshot = screenshot
                except Exception:
                    pass

            # AI vision processing (Layer 1 – runs every Nth frame)
            if _ai_bridge and state.frame_count % 5 == 0:
                try:
                    frame = bot.get_screenshot()
                    if frame is not None:
                        mem_hint = "battle_wild" if getattr(bot, "in_battle", False) else "overworld"
                        ai_result = _ai_bridge.process_frame(
                            frame, memory_state_hint=mem_hint)
                        if ai_result.is_stuck:
                            logger.warning("Instance %d: AI detected STUCK state",
                                           state.instance_id)
                except Exception:
                    pass

            # Record encounter in stats tracker (async)
            if result.encounter is not None:
                species_id = getattr(result.encounter, "species_id", 0) or 0
                pv = getattr(result.encounter, "personality_value", 0) or 0
                async_worker.submit(
                    _global_stats.record_encounter,
                    species_id=species_id,
                    is_shiny=result.is_shiny,
                    area=area,
                    instance_id=str(state.instance_id),
                    bot_mode=state.bot_mode,
                    personality_value=pv,
                )
                perf_monitor.increment("encounters")

                # AI visual shiny verification (Layer 1 backup check)
                if _ai_bridge and not result.is_shiny and species_id > 0:
                    try:
                        frame = bot.get_screenshot()
                        if frame is not None:
                            check = _ai_bridge.verify_shiny(
                                frame, species_id, memory_says_shiny=False)
                            if check and check.get("is_shiny") and check.get("confidence", 0) > 0.85:
                                logger.warning(
                                    "AI VISUAL OVERRIDE: shiny detected for #%d "
                                    "(conf=%.2f, method=%s) but memory said no!",
                                    species_id, check["confidence"], check["method"])
                                result = ModeResult(
                                    status=result.status,
                                    encounter=result.encounter,
                                    is_shiny=True,
                                    message="AI visual shiny override",
                                )
                    except Exception:
                        pass

            # Handle shiny
            if result.is_shiny:
                _handle_shiny(state, bot, result.encounter, async_worker)
                break

            # Handle mode completion (evolution modes, etc.)
            if result.status == ModeStatus.COMPLETED:
                state.status = "completed"
                logger.info("Mode %s completed: %s", state.bot_mode, result.message)
                break

            if result.status == ModeStatus.ERROR:
                state.status = "error"
                state.error = result.message
                logger.error("Mode %s error: %s", state.bot_mode, result.message)
                break

        mode.stop()
        bot.destroy()
        if state.status not in ("shiny_found", "completed", "error"):
            state.status = "stopped"

    except Exception as e:
        state.status = "error"
        state.error = str(e)
        logger.exception("Worker error in instance %d", state.instance_id)


def _create_mode(mode_key: str, bot) -> BotMode:
    """Instantiate the correct BotMode subclass from a mode key string."""
    mode_cls = ALL_MODES.get(mode_key)
    if mode_cls is None:
        logger.warning("Unknown mode '%s', falling back to encounter_farm", mode_key)
        mode_cls = ALL_MODES["encounter_farm"]
    return mode_cls(bot)


def _handle_shiny(state, bot, encounter, async_worker=None):
    """Handle a shiny encounter: catch, save, log, screenshot."""
    state.status = "shiny_found"
    pv = getattr(encounter, "personality_value", 0) or 0
    species_id = getattr(encounter, "species_id", 0) or 0
    state.shiny_pokemon = f"#{species_id} PV=0x{pv:08X}"

    bot.catch_pokemon()
    bot.save_game()

    try:
        state.last_screenshot = bot.get_screenshot()
    except Exception:
        pass

    # Log to database (async if worker available, sync otherwise)
    log_fn = lambda: log_shiny(
        species_id=species_id,
        personality_value=pv,
        tid=state.tid, sid=state.sid, seed=state.seed,
        encounter_count=state.encounters,
        instance_id=str(state.instance_id),
    )
    if async_worker:
        async_worker.submit(log_fn)
    else:
        try:
            log_fn()
        except Exception:
            pass

    # Mark in living dex (async)
    if species_id > 0:
        mark_fn = lambda sid=species_id: mark_pokemon_owned(sid, method="shiny_hunt")
        if async_worker:
            async_worker.submit(mark_fn)
        else:
            try:
                mark_fn()
            except Exception:
                pass

    # Fire notifications (sound + toast + discord) in background threads
    _notifier.notify_shiny(
        species_id=species_id,
        personality_value=pv,
        encounters=state.encounters,
        instance_id=str(state.instance_id),
    )

    logger.info("SHINY FOUND! Instance %d: species #%d PV=0x%08X after %d encounters",
                state.instance_id, species_id, pv, state.encounters)


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.settings = load_settings()
        self.hw = detect_cpu_details()
        self.instances: Dict[int, InstanceState] = {}
        self.threads: Dict[int, threading.Thread] = {}
        self._next_id = 1
        self._photo_cache: Dict[int, ImageTk.PhotoImage] = {}
        self._start_time: Optional[float] = None
        self.cheat_mgr = CheatManager()

        self.title("Gen 3 Shiny Hunter – Living Dex Edition")
        self.geometry(self.settings.get("window_geometry", "1440x900"))
        self.minsize(1024, 640)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        init_db()
        self._build_ui()
        self._refresh_gui()

    # ─────────────────────────────────────────────────────────────────────
    #  UI
    # ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Title bar ────────────────────────────────────────────────────
        title_bar = ctk.CTkFrame(self, fg_color=C["bg_card"], corner_radius=0, height=56)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        ctk.CTkLabel(
            title_bar, text="GEN 3 SHINY HUNTER",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["accent"],
        ).pack(side="left", padx=20)

        # CPU badge
        cpu_text = f"{self.hw['vendor']} {self.hw['arch_name']}"
        if self.hw["gen_label"]:
            cpu_text += f" ({self.hw['gen_label']})"
        cpu_text += f"  {self.hw['cpu_physical']}C/{self.hw['cpu_logical']}T @ {self.hw['freq_ghz']}GHz"
        cpu_text += f"  |  {self.hw['ram_gb']}GB RAM"

        tier_colors = {"Excellent": C["green"], "Good": C["yellow"], "Moderate": C["red"]}
        tier_color = tier_colors.get(self.hw["perf_tier"], C["text_dim"])

        hw_frame = ctk.CTkFrame(title_bar, fg_color="transparent")
        hw_frame.pack(side="right", padx=20)

        ctk.CTkButton(
            hw_frame, text="📋 Log", width=70, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=C["bg_dark"], hover_color="#1a3a1a",
            border_width=1, border_color=C["border"],
            command=self._open_log_window,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            hw_frame, text="✨ Shiny Math", width=100, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=C["bg_dark"], hover_color="#2a1a3a",
            border_width=1, border_color=C["border"],
            command=self._open_shiny_math,
        ).pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            hw_frame, text="⚙ Settings", width=90, height=30,
            font=ctk.CTkFont(size=12),
            fg_color=C["bg_dark"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=self._open_settings,
        ).pack(side="left", padx=(0, 12))

        ctk.CTkLabel(
            hw_frame, text=cpu_text,
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            hw_frame, text=f"[{self.hw['perf_tier']}]",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=tier_color,
        ).pack(side="left")

        # ── Main content ─────────────────────────────────────────────────
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=12)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # Left sidebar (scrollable)
        sidebar = ctk.CTkScrollableFrame(
            main, width=320, fg_color=C["bg_card"], corner_radius=12,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self._build_sidebar(sidebar)

        # Right content area
        content = ctk.CTkFrame(main, fg_color=C["bg_card"], corner_radius=12)
        content.grid(row=0, column=1, sticky="nsew")
        self._build_content(content)

    def _build_sidebar(self, parent):
        pad = {"padx": 16, "pady": (0, 4)}

        # ── ROM ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="ROM", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(16, 4))

        rom_frame = ctk.CTkFrame(parent, fg_color="transparent")
        rom_frame.pack(fill="x", **pad)

        # Auto-detect ROM: prefer saved path, then scan emulator/ for any known game ROM
        _saved_rom = self.settings.get("rom_path", "")
        if not _saved_rom or not Path(_saved_rom).exists():
            from modules.config import EMULATOR_DIR
            _found_rom = detect_rom_in_dir(EMULATOR_DIR)
            if _found_rom:
                _saved_rom = str(_found_rom)
                # Also auto-set game version from filename
                _detected_ver = detect_game_version_from_path(_found_rom)
                self.settings["game_version"] = _detected_ver
                logger.info("Auto-detected game version: %s from %s", _detected_ver, _found_rom.name)
            if _saved_rom:
                self.settings["rom_path"] = _saved_rom
                save_settings(self.settings)

        self._rom_var = ctk.StringVar(value=_saved_rom)
        rom_entry = ctk.CTkEntry(
            rom_frame, textvariable=self._rom_var,
            placeholder_text="Select ROM file...",
            fg_color=C["bg_input"], border_color=C["border"],
            width=220,
        )
        rom_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            rom_frame, text="...", width=36,
            fg_color=C["accent"], hover_color=C["accent_h"],
            command=self._browse_rom,
        ).pack(side="right", padx=(6, 0))

        self._rom_status = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=11),
            text_color=C["text_dim"],
        )
        self._rom_status.pack(anchor="w", **pad)
        self._validate_rom_display()

        # ── Game Version ────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="GAME VERSION", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self._game_version_var = ctk.StringVar(
            value=self.settings.get("game_version", "firered"))
        ctk.CTkOptionMenu(
            parent, variable=self._game_version_var,
            values=["firered", "leafgreen", "emerald", "ruby", "sapphire"],
            fg_color=C["bg_input"], button_color=C["accent"],
            button_hover_color=C["accent_h"],
            dropdown_fg_color=C["bg_card"],
            width=200,
        ).pack(anchor="w", padx=16, pady=(0, 4))

        # ── Bot Mode ─────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="BOT MODE", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self._mode_var = ctk.StringVar(value=self.settings.get("bot_mode", ""))
        self._mode_buttons: dict = {}

        def _make_mode_toggle(key):
            def _toggle():
                if self._mode_var.get() == key:
                    # Clicking the already-selected mode deselects it
                    self._mode_var.set("")
                else:
                    self._mode_var.set(key)
                _refresh_mode_buttons()
            return _toggle

        def _refresh_mode_buttons():
            selected = self._mode_var.get()
            for k, btn in self._mode_buttons.items():
                if k == selected:
                    btn.configure(fg_color=C["accent"], text_color="#fff",
                                  border_color=C["accent"])
                else:
                    btn.configure(fg_color=C["bg_dark"], text_color=C["text"],
                                  border_color=C["border"])

        for key, info in BOT_MODES.items():
            is_ready = info["status"] == "Ready"
            btn = ctk.CTkButton(
                parent,
                text=info["label"],
                font=ctk.CTkFont(size=12),
                fg_color=C["accent"] if self._mode_var.get() == key else C["bg_dark"],
                text_color="#fff" if self._mode_var.get() == key else C["text"],
                hover_color=C["accent_h"],
                border_width=1,
                border_color=C["accent"] if self._mode_var.get() == key else C["border"],
                height=28,
                anchor="w",
                command=_make_mode_toggle(key) if is_ready else None,
                state="normal" if is_ready else "disabled",
            )
            btn.pack(fill="x", padx=20, pady=2)
            self._mode_buttons[key] = btn

        # ── Area ─────────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="TARGET AREA", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self._area_var = ctk.StringVar(value=self.settings.get("target_area", "route1"))
        ctk.CTkOptionMenu(
            parent, variable=self._area_var,
            values=list(ENCOUNTER_AREAS.keys()),
            fg_color=C["bg_input"], button_color=C["accent"],
            button_hover_color=C["accent_h"],
            dropdown_fg_color=C["bg_card"],
            width=200,
        ).pack(anchor="w", padx=16, pady=(0, 4))

        # ── Speed ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="SPEED", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        speed_frame = ctk.CTkFrame(parent, fg_color="transparent")
        speed_frame.pack(fill="x", padx=16, pady=(0, 4))

        self._speed_var = ctk.IntVar(value=self.settings.get("speed_multiplier", 0))
        for label, val in [("1x", 1), ("2x", 2), ("4x", 4), ("Max", 0)]:
            ctk.CTkRadioButton(
                speed_frame, text=label, variable=self._speed_var, value=val,
                font=ctk.CTkFont(size=12), text_color=C["text"],
                fg_color=C["accent"], hover_color=C["accent_h"],
                border_color=C["border"], width=60,
            ).pack(side="left", padx=(0, 8))

        # ── Instances ────────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="INSTANCES", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        inst_frame = ctk.CTkFrame(parent, fg_color="transparent")
        inst_frame.pack(fill="x", padx=16, pady=(0, 4))

        self._inst_var = ctk.IntVar(value=self.settings.get("max_instances", 1))
        self._inst_slider = ctk.CTkSlider(
            inst_frame, from_=1, to=max(1, self.hw["suggested_max"]),
            number_of_steps=max(1, self.hw["suggested_max"] - 1),
            variable=self._inst_var,
            fg_color=C["border"], progress_color=C["accent"],
            button_color=C["accent"], button_hover_color=C["accent_h"],
            command=lambda v: self._inst_label.configure(text=f"{int(v)} / {self.hw['suggested_max']} max"),
        )
        self._inst_slider.pack(side="left", fill="x", expand=True)
        self._inst_label = ctk.CTkLabel(
            inst_frame,
            text=f"{self._inst_var.get()} / {self.hw['suggested_max']} max",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"], width=80,
        )
        self._inst_label.pack(side="right", padx=(8, 0))

        # ── Video toggle ─────────────────────────────────────────────────
        self._video_var = ctk.BooleanVar(value=self.settings.get("video_enabled", False))
        ctk.CTkCheckBox(
            parent, text="Screen preview (reduces speed)",
            variable=self._video_var,
            font=ctk.CTkFont(size=12), text_color=C["text_dim"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        # ── Action buttons ───────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(16, 8))

        self._start_btn = ctk.CTkButton(
            btn_frame, text="START HUNTING",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C["green"], hover_color="#16a34a",
            text_color="#000000", height=42,
            command=self._start_all,
        )
        self._start_btn.pack(fill="x", pady=(0, 6))

        sub_btns = ctk.CTkFrame(btn_frame, fg_color="transparent")
        sub_btns.pack(fill="x")

        self._stop_btn = ctk.CTkButton(
            sub_btns, text="Stop All",
            fg_color=C["red"], hover_color="#dc2626",
            text_color="#ffffff", height=32, width=120,
            command=self._stop_all, state="disabled",
        )
        self._stop_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

        self._pause_btn = ctk.CTkButton(
            sub_btns, text="Pause All",
            fg_color=C["yellow"], hover_color="#ca8a04",
            text_color="#000000", height=32, width=120,
            command=self._pause_all, state="disabled",
        )
        self._pause_btn.pack(side="right", expand=True, fill="x", padx=(3, 0))

        # ── Stats ────────────────────────────────────────────────────────
        stats_frame = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=8)
        stats_frame.pack(fill="x", padx=16, pady=(8, 16))

        self._stat_enc = ctk.CTkLabel(stats_frame, text="Encounters: 0", font=ctk.CTkFont(size=12), text_color=C["text"])
        self._stat_enc.pack(anchor="w", padx=12, pady=(8, 0))
        self._stat_shiny = ctk.CTkLabel(stats_frame, text="Shinies: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color=C["gold"])
        self._stat_shiny.pack(anchor="w", padx=12)
        self._stat_enc_rate = ctk.CTkLabel(stats_frame, text="Enc/hr: 0", font=ctk.CTkFont(size=12), text_color=C["text"])
        self._stat_enc_rate.pack(anchor="w", padx=12)
        self._stat_probability = ctk.CTkLabel(stats_frame, text="Shiny chance: 0%", font=ctk.CTkFont(size=12), text_color=C["accent"])
        self._stat_probability.pack(anchor="w", padx=12)
        self._stat_fps = ctk.CTkLabel(stats_frame, text="FPS: 0", font=ctk.CTkFont(size=12), text_color=C["text_dim"])
        self._stat_fps.pack(anchor="w", padx=12)
        self._stat_time = ctk.CTkLabel(stats_frame, text="Uptime: 0:00:00", font=ctk.CTkFont(size=12), text_color=C["text_dim"])
        self._stat_time.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Living Dex Progress ───────────────────────────────────────
        ctk.CTkLabel(
            parent, text="LIVING DEX", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 4))

        dex_frame = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=8)
        dex_frame.pack(fill="x", padx=16, pady=(0, 4))

        self._dex_progress_label = ctk.CTkLabel(
            dex_frame, text="0 / 386 (0%)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C["gold"],
        )
        self._dex_progress_label.pack(anchor="w", padx=12, pady=(8, 2))

        self._dex_bar = ctk.CTkProgressBar(
            dex_frame, height=10,
            fg_color=C["border"], progress_color=C["gold"],
        )
        self._dex_bar.pack(fill="x", padx=12, pady=(0, 4))
        self._dex_bar.set(0)

        self._dex_detail = ctk.CTkLabel(
            dex_frame, text="Base: 0  |  Evolved: 0  |  Final: 0",
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        )
        self._dex_detail.pack(anchor="w", padx=12, pady=(0, 4))

        self._legit_label = ctk.CTkLabel(
            dex_frame, text="Legitimacy: CLEAN",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=C["green"],
        )
        self._legit_label.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Cheat Presets ─────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="CHEAT PRESETS", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        cheat_frame = ctk.CTkFrame(parent, fg_color="transparent")
        cheat_frame.pack(fill="x", padx=16, pady=(0, 8))

        presets = [
            ("Hunting", self._apply_hunting_cheats, C["accent"]),
            ("Breeding", self._apply_breeding_cheats, C["accent"]),
            ("Evolution", self._apply_evolution_cheats, C["accent"]),
            ("Fishing", self._apply_fishing_cheats, C["accent"]),
        ]
        for i, (label, cmd, color) in enumerate(presets):
            ctk.CTkButton(
                cheat_frame, text=label, width=70, height=26,
                font=ctk.CTkFont(size=11),
                fg_color=color, hover_color=C["accent_h"],
                command=cmd,
            ).grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")
        cheat_frame.grid_columnconfigure(0, weight=1)
        cheat_frame.grid_columnconfigure(1, weight=1)

        self._cheat_status = ctk.CTkLabel(
            parent, text="No cheats active",
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        )
        self._cheat_status.pack(anchor="w", padx=16, pady=(0, 8))

        # ── Data Export ─────────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="DATA EXPORT", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        export_frame = ctk.CTkFrame(parent, fg_color="transparent")
        export_frame.pack(fill="x", padx=16, pady=(0, 4))

        ctk.CTkButton(
            export_frame, text="Export CSV", width=90, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=C["bg_input"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=self._export_csv,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            export_frame, text="Export JSON", width=90, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=C["bg_input"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=self._export_json,
        ).pack(side="left")

        self._export_status = ctk.CTkLabel(
            parent, text="",
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        )
        self._export_status.pack(anchor="w", padx=16, pady=(0, 4))

        # ── Notifications ──────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="NOTIFICATIONS", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        notif_frame = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=8)
        notif_frame.pack(fill="x", padx=16, pady=(0, 4))

        self._notif_sound_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            notif_frame, text="Sound alert",
            variable=self._notif_sound_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_notif_settings,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        self._notif_toast_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            notif_frame, text="Desktop notification",
            variable=self._notif_toast_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_notif_settings,
        ).pack(anchor="w", padx=12, pady=2)

        self._notif_discord_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            notif_frame, text="Discord webhook",
            variable=self._notif_discord_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_notif_settings,
        ).pack(anchor="w", padx=12, pady=2)

        self._discord_url_var = ctk.StringVar(
            value=self.settings.get("discord_webhook_url", ""))
        self._discord_entry = ctk.CTkEntry(
            notif_frame, textvariable=self._discord_url_var,
            placeholder_text="Discord webhook URL",
            fg_color=C["bg_dark"], border_color=C["border"],
            font=ctk.CTkFont(size=10), height=26, width=240,
        )
        self._discord_entry.pack(anchor="w", padx=12, pady=(0, 4))

        test_frame = ctk.CTkFrame(notif_frame, fg_color="transparent")
        test_frame.pack(anchor="w", padx=12, pady=(0, 8))
        ctk.CTkButton(
            test_frame, text="Test Sound", width=75, height=24,
            font=ctk.CTkFont(size=10),
            fg_color=C["bg_dark"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=lambda: _notifier.test_sound(),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            test_frame, text="Test Toast", width=75, height=24,
            font=ctk.CTkFont(size=10),
            fg_color=C["bg_dark"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=lambda: _notifier.test_toast(),
        ).pack(side="left")

        # ── AI / Training Mode ─────────────────────────────────────────
        ai_header_text = "AI SYSTEM" if AI_AVAILABLE else "AI SYSTEM (not installed)"
        ctk.CTkLabel(
            parent, text=ai_header_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"] if AI_AVAILABLE else C["text_dim"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        ai_frame = ctk.CTkFrame(parent, fg_color=C["bg_input"], corner_radius=8)
        ai_frame.pack(fill="x", padx=16, pady=(0, 4))

        self._ai_enabled_var = ctk.BooleanVar(
            value=self.settings.get("ai", {}).get("enabled", False))
        ctk.CTkCheckBox(
            ai_frame, text="Enable AI layers",
            variable=self._ai_enabled_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_ai_settings,
            state="normal" if AI_AVAILABLE else "disabled",
        ).pack(anchor="w", padx=12, pady=(8, 2))

        self._ai_training_var = ctk.BooleanVar(
            value=self.settings.get("ai", {}).get("training_mode", False))
        ctk.CTkCheckBox(
            ai_frame, text="Training mode (collect data)",
            variable=self._ai_training_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_ai_settings,
            state="normal" if AI_AVAILABLE else "disabled",
        ).pack(anchor="w", padx=12, pady=2)

        self._ai_llm_var = ctk.BooleanVar(
            value=self.settings.get("ai", {}).get("llm_enabled", False))
        ctk.CTkCheckBox(
            ai_frame, text="LLM battle advisor",
            variable=self._ai_llm_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_ai_settings,
            state="normal" if AI_AVAILABLE else "disabled",
        ).pack(anchor="w", padx=12, pady=2)

        self._ai_rl_var = ctk.BooleanVar(
            value=self.settings.get("ai", {}).get("rl_enabled", False))
        ctk.CTkCheckBox(
            ai_frame, text="RL navigation agent",
            variable=self._ai_rl_var,
            font=ctk.CTkFont(size=11), text_color=C["text"],
            fg_color=C["accent"], hover_color=C["accent_h"],
            border_color=C["border"],
            command=self._update_ai_settings,
            state="normal" if AI_AVAILABLE else "disabled",
        ).pack(anchor="w", padx=12, pady=(2, 4))

        self._ai_status = ctk.CTkLabel(
            ai_frame, text="",
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        )
        self._ai_status.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Recent Encounters ───────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="RECENT ENCOUNTERS", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(8, 4))

        self._encounter_log_text = ctk.CTkTextbox(
            parent, height=120, fg_color=C["bg_input"],
            font=ctk.CTkFont(size=10, family="Consolas"),
            text_color=C["text_dim"], corner_radius=8,
            border_width=1, border_color=C["border"],
        )
        self._encounter_log_text.pack(fill="x", padx=16, pady=(0, 16))
        self._encounter_log_text.configure(state="disabled")

    def _export_csv(self):
        try:
            from modules.stats_dashboard import export_csv
            path = export_csv(_global_stats)
            self._export_status.configure(
                text=f"Saved: {path.name}", text_color=C["green"])
        except Exception as exc:
            self._export_status.configure(
                text=f"Error: {exc}", text_color=C["red"])

    def _export_json(self):
        try:
            from modules.stats_dashboard import export_json
            path = export_json(_global_stats)
            self._export_status.configure(
                text=f"Saved: {path.name}", text_color=C["green"])
        except Exception as exc:
            self._export_status.configure(
                text=f"Error: {exc}", text_color=C["red"])

    def _update_notif_settings(self):
        _notifier.sound_enabled = self._notif_sound_var.get()
        _notifier.toast_enabled = self._notif_toast_var.get()
        _notifier.discord_enabled = self._notif_discord_var.get()
        _notifier.discord_webhook_url = self._discord_url_var.get().strip()
        self.settings["discord_webhook_url"] = _notifier.discord_webhook_url
        save_settings(self.settings)

    def _update_ai_settings(self):
        global _ai_bridge
        ai_settings = {
            "enabled": self._ai_enabled_var.get(),
            "training_mode": self._ai_training_var.get(),
            "vision_enabled": True,
            "llm_enabled": self._ai_llm_var.get(),
            "rl_enabled": self._ai_rl_var.get(),
        }
        self.settings["ai"] = ai_settings
        save_settings(self.settings)

        if not AI_AVAILABLE:
            self._ai_status.configure(text="AI module not installed")
            return

        if ai_settings["enabled"]:
            try:
                config = AIConfig.from_settings(self.settings)
                _ai_bridge = AIBridge(config)
                _ai_bridge.initialize()
                layers = ", ".join(_ai_bridge._initialized_layers) or "none"
                self._ai_status.configure(
                    text=f"Active layers: {layers}", text_color=C["green"])
            except Exception as exc:
                self._ai_status.configure(
                    text=f"Error: {exc}", text_color=C["red"])
        else:
            if _ai_bridge:
                _ai_bridge.shutdown()
                _ai_bridge = None
            self._ai_status.configure(text="Disabled", text_color=C["text_dim"])

    def _apply_hunting_cheats(self):
        n = self.cheat_mgr.apply_hunting_preset()
        self._cheat_status.configure(
            text=f"Hunting preset: {n} cheats enabled",
            text_color=C["green"])
        self._log_cheats("hunting")

    def _apply_breeding_cheats(self):
        n = self.cheat_mgr.apply_breeding_preset()
        self._cheat_status.configure(
            text=f"Breeding preset: {n} cheats enabled",
            text_color=C["green"])
        self._log_cheats("breeding")

    def _apply_evolution_cheats(self):
        n = self.cheat_mgr.apply_evolution_preset()
        self._cheat_status.configure(
            text=f"Evolution preset: {n} cheats enabled",
            text_color=C["green"])
        self._log_cheats("evolution")

    def _apply_fishing_cheats(self):
        n = self.cheat_mgr.apply_fishing_preset()
        self._cheat_status.configure(
            text=f"Fishing preset: {n} cheats enabled",
            text_color=C["green"])
        self._log_cheats("fishing")

    def _log_cheats(self, preset: str):
        for cid in self.cheat_mgr.get_enabled_cheats():
            cheat = self.cheat_mgr.cheats[cid]
            try:
                db_log_cheat(cheat.name, cid, cheat.category.value,
                             affects_legitimacy=cheat.affects_legitimacy)
            except Exception:
                pass

    def _build_content(self, parent):
        # Header
        header = ctk.CTkFrame(parent, fg_color="transparent", height=40)
        header.pack(fill="x", padx=16, pady=(12, 0))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="EMULATOR INSTANCES",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"],
        ).pack(side="left")

        self._active_label = ctk.CTkLabel(
            header, text="0 active",
            font=ctk.CTkFont(size=12), text_color=C["text_dim"],
        )
        self._active_label.pack(side="right")

        # Scrollable instance area
        self._scroll_frame = ctk.CTkScrollableFrame(
            parent, fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        self._scroll_frame.pack(fill="both", expand=True, padx=12, pady=12)

        self._instance_widgets: Dict[int, dict] = {}

        # Save-file requirement notice
        notice = ctk.CTkFrame(
            self._scroll_frame, fg_color="#1a2a1a",
            corner_radius=8, border_width=1, border_color="#2d5a2d",
        )
        notice.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            notice,
            text="⚠️  IMPORTANT: Each instance needs a save file already past the new-game intro.",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#7aba7a",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(
            notice,
            text="Place your .sav file in emulator/saves/<instance_id>/ before starting.\n"
                 "The bot cannot play through the intro — it needs an existing save in the overworld.",
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
            anchor="w", justify="left",
        ).pack(fill="x", padx=12, pady=(0, 6))

        # Placeholder / instance status list
        self._placeholder = ctk.CTkLabel(
            self._scroll_frame,
            text="No instances running\n\nSelect a ROM and Bot Mode, then click START HUNTING.",
            font=ctk.CTkFont(size=13), text_color=C["text_dim"],
            justify="center",
        )
        self._placeholder.pack(pady=40)

        # Live instance rows (populated by _refresh_gui)
        self._inst_rows: Dict[int, ctk.CTkFrame] = {}

    # ─────────────────────────────────────────────────────────────────────
    #  INSTANCE CARDS
    # ─────────────────────────────────────────────────────────────────────

    def _create_inst_row(self, inst_id: int, state: InstanceState):
        """Create a compact status row in the scroll frame for this instance."""
        row_frame = ctk.CTkFrame(
            self._scroll_frame, fg_color=C["bg_input"],
            corner_radius=6, border_width=1, border_color=C["border"],
        )
        row_frame.pack(fill="x", pady=3)

        status_lbl = ctk.CTkLabel(
            row_frame, text="BOOTING", width=72,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=C["yellow"],
        )
        status_lbl.pack(side="left", padx=(8, 0), pady=5)

        info_lbl = ctk.CTkLabel(
            row_frame,
            text=f"Instance #{inst_id}  |  TID:{state.tid}  SID:{state.sid}  |  {BOT_MODES.get(state.bot_mode, {}).get('label', state.bot_mode)}",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        )
        info_lbl.pack(side="left", padx=8)

        metrics_lbl = ctk.CTkLabel(
            row_frame, text="Enc: 0  |  FPS: 0",
            font=ctk.CTkFont(size=11), text_color=C["text"],
        )
        metrics_lbl.pack(side="right", padx=8)

        focus_btn = ctk.CTkButton(
            row_frame, text="Focus Window", width=90, height=22,
            font=ctk.CTkFont(size=10),
            fg_color=C["bg_dark"], hover_color=C["accent"],
            border_width=1, border_color=C["border"],
            command=lambda: self._focus_instance_window(inst_id),
        )
        focus_btn.pack(side="right", padx=(0, 8))

        self._inst_rows[inst_id] = {
            "frame": row_frame,
            "status": status_lbl,
            "metrics": metrics_lbl,
        }

    def _focus_instance_window(self, inst_id: int):
        """Bring the Toplevel window for this instance to the front."""
        w = self._instance_widgets.get(inst_id)
        if w:
            try:
                win = w["win"]
                win.deiconify()
                win.lift()
                win.focus_set()
            except Exception:
                pass

    def _create_card(self, inst_id: int, state: InstanceState):
        """Open a dedicated Toplevel window for this emulator instance."""
        self._create_inst_row(inst_id, state)
        # Tile windows: 4 per row, each 320px wide (instances always start at 1)
        col = (inst_id - 1) % 4
        row = (inst_id - 1) // 4
        x_off = 20 + col * 340
        y_off = 60 + row * 340

        win = ctk.CTkToplevel(self)
        win.title(f"Instance #{inst_id}  –  {BOT_MODES.get(state.bot_mode, {}).get('label', state.bot_mode)}")
        win.geometry(f"320x330+{x_off}+{y_off}")
        win.configure(fg_color=C["bg_dark"])
        win.resizable(False, False)

        # Closing the window stops this instance and destroys the window
        def _on_close():
            state.request_stop()
            try:
                win.after(200, win.destroy)
            except Exception:
                pass
        win.protocol("WM_DELETE_WINDOW", _on_close)

        # ── Title bar row ────────────────────────────────────────────────
        title_row = ctk.CTkFrame(win, fg_color=C["bg_input"], corner_radius=0)
        title_row.pack(fill="x")

        status_label = ctk.CTkLabel(
            title_row, text="BOOTING", width=80,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["yellow"],
        )
        status_label.pack(side="left", padx=(8, 0), pady=6)

        info_text = f"#{inst_id}  TID:{state.tid}  SID:{state.sid}"
        info_label = ctk.CTkLabel(
            title_row, text=info_text,
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        )
        info_label.pack(side="left", padx=6)

        btn_box = ctk.CTkFrame(title_row, fg_color="transparent")
        btn_box.pack(side="right", padx=6)

        pause_btn = ctk.CTkButton(
            btn_box, text="Pause", width=50, height=24,
            font=ctk.CTkFont(size=10),
            fg_color=C["yellow"], hover_color="#ca8a04", text_color="#000",
            command=lambda: state.request_pause(),
        )
        pause_btn.pack(side="left", padx=2)

        stop_btn = ctk.CTkButton(
            btn_box, text="Stop", width=50, height=24,
            font=ctk.CTkFont(size=10),
            fg_color=C["red"], hover_color="#dc2626", text_color="#fff",
            command=lambda: state.request_stop(),
        )
        stop_btn.pack(side="left", padx=2)

        # Take Control toggle button
        ctrl_btn_ref = [None]

        def _toggle_control():
            state.manual_control = not state.manual_control
            if state.manual_control:
                ctrl_btn_ref[0].configure(
                    text="Bot", fg_color=C["accent"], text_color="#fff")
                win.focus_set()
            else:
                ctrl_btn_ref[0].configure(
                    text="Control", fg_color="#1e3a5f", text_color=C["text"])

        ctrl_btn = ctk.CTkButton(
            btn_box, text="Control", width=58, height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#1e3a5f", hover_color=C["accent"], text_color=C["text"],
            command=_toggle_control,
        )
        ctrl_btn.pack(side="left", padx=(2, 0))
        ctrl_btn_ref[0] = ctrl_btn

        # ── Live game screen (240×160 scaled 1.25x → 300×200) ───────────
        screen_label = ctk.CTkLabel(win, text="", fg_color=C["bg_dark"])
        screen_label.pack(pady=(4, 0))

        # Placeholder while waiting for first frame
        placeholder = ctk.CTkLabel(
            win,
            text="Booting game…\n\nPress A/Start to advance\nor wait for auto-boot",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
            fg_color="#111111", width=300, height=200,
        )
        placeholder.pack()
        placeholder_ref = [placeholder]  # mutable ref so update can hide it

        # ── Keyboard bindings (active when window is focused) ────────────
        _keybinds = self.settings.get("keybinds", {
            "a": "a", "s": "b", "Return": "start", "BackSpace": "select",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "q": "l", "w": "r",
        })

        def _on_key(event):
            if not state.manual_control:
                return
            key = event.keysym
            btn = _keybinds.get(key)
            if btn:
                state.send_input(btn)

        win.bind("<KeyPress>", _on_key)
        # Click on screen to focus window for keyboard input
        screen_label.bind("<Button-1>", lambda e: win.focus_set())

        # ── Metrics row ──────────────────────────────────────────────────
        metrics_row = ctk.CTkFrame(win, fg_color=C["bg_input"], corner_radius=0)
        metrics_row.pack(fill="x", side="bottom")

        enc_label = ctk.CTkLabel(
            metrics_row, text="Enc: 0",
            font=ctk.CTkFont(size=11), text_color=C["text"], width=90,
        )
        enc_label.pack(side="left", padx=(8, 0), pady=4)

        fps_label = ctk.CTkLabel(
            metrics_row, text="FPS: 0",
            font=ctk.CTkFont(size=11), text_color=C["text"], width=90,
        )
        fps_label.pack(side="left")

        frame_label = ctk.CTkLabel(
            metrics_row, text="Frames: 0",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"], width=110,
        )
        frame_label.pack(side="left")

        progress = ctk.CTkProgressBar(
            metrics_row, width=60, height=6,
            fg_color=C["border"], progress_color=C["accent"],
        )
        progress.pack(side="right", padx=8)
        progress.set(0)

        self._instance_widgets[inst_id] = {
            "win": win,
            "status": status_label,
            "info": info_label,
            "screen": screen_label,
            "placeholder": placeholder_ref,
            "enc": enc_label,
            "fps": fps_label,
            "frames": frame_label,
            "progress": progress,
            "pause": pause_btn,
            "stop": stop_btn,
        }

    def _update_card(self, inst_id: int, state: InstanceState):
        w = self._instance_widgets.get(inst_id)
        if not w:
            return

        win = w.get("win")
        if win is None:
            return

        # Status label + window title color
        status_map = {
            "running":    ("RUNNING",  C["green"]),
            "booting":    ("BOOTING",  C["yellow"]),
            "paused":     ("PAUSED",   C["yellow"]),
            "manual":     ("MANUAL",   C["accent"]),
            "shiny_found":("SHINY!",   C["gold"]),
            "stopped":    ("STOPPED",  C["red"]),
            "error":      ("ERROR",    C["red"]),
            "idle":       ("IDLE",     C["text_dim"]),
            "completed":  ("DONE",     C["green"]),
        }
        text, color = status_map.get(state.status, ("...", C["text_dim"]))
        w["status"].configure(text=text, text_color=color)

        # Window title reflects status
        mode_label = BOT_MODES.get(state.bot_mode, {}).get("label", state.bot_mode)
        win.title(f"[{text}] Instance #{inst_id} – {mode_label}")

        # Error: show in frame_label
        if state.status == "error" and state.error:
            w["frames"].configure(
                text=state.error[:60], text_color=C["red"])
        else:
            w["frames"].configure(
                text=f"Frames: {state.frame_count:,}", text_color=C["text_dim"])

        # Metrics
        w["enc"].configure(text=f"Enc: {state.encounters:,}")
        w["fps"].configure(text=f"FPS: {state.fps:,.0f}")

        # Info bar: seed + core
        info_text = f"#{inst_id}  TID:{state.tid}  SID:{state.sid}"
        if state.cpu_core >= 0:
            info_text += f"  Core:{state.cpu_core}"
        w["info"].configure(text=info_text)

        # Progress bar
        if state.status == "running":
            p = (state.frame_count % 1000) / 1000
            w["progress"].set(p)
            w["progress"].configure(progress_color=C["accent"])
        elif state.status == "shiny_found":
            w["progress"].set(1.0)
            w["progress"].configure(progress_color=C["gold"])
        elif state.status == "error":
            w["progress"].set(1.0)
            w["progress"].configure(progress_color=C["red"])

        # Buttons
        w["pause"].configure(text="Resume" if state.is_paused else "Pause")
        if state.status in ("stopped", "shiny_found", "error"):
            w["pause"].configure(state="disabled")
            w["stop"].configure(state="disabled")

        # Live screen: update from screenshot captured by worker
        if state.last_screenshot is not None:
            try:
                # Hide placeholder on first real frame
                ph_ref = w.get("placeholder")
                if ph_ref and ph_ref[0] is not None:
                    ph_ref[0].pack_forget()
                    ph_ref[0] = None

                # Scale 240×160 → 300×200 (1.25x) for visibility
                img = state.last_screenshot.resize((300, 200), Image.NEAREST)
                photo = ImageTk.PhotoImage(img)
                self._photo_cache[inst_id] = photo
                w["screen"].configure(image=photo, text="")
            except Exception:
                pass

        # Flash window border gold on shiny
        if state.status == "shiny_found":
            try:
                win.configure(fg_color=C["gold"])
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────
    #  LOG WINDOW
    # ─────────────────────────────────────────────────────────────────────

    def _open_log_window(self):
        """Open a floating live log window showing all app/AI/bot activity."""
        if hasattr(self, "_log_win"):
            try:
                if self._log_win.winfo_exists():
                    self._log_win.lift()
                    self._log_win.focus_set()
                    return
            except Exception:
                pass

        win = ctk.CTkToplevel(self)
        win.title("Live Log – Gen 3 Shiny Hunter")
        win.geometry("900x560+60+60")
        win.configure(fg_color=C["bg_dark"])
        self._log_win = win

        toolbar = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=40)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        ctk.CTkLabel(toolbar, text="LIVE LOG",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["accent"]).pack(side="left", padx=12)

        _level_var = ctk.StringVar(value="ALL")
        ctk.CTkLabel(toolbar, text="Level:", font=ctk.CTkFont(size=11),
                     text_color=C["text_dim"]).pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(toolbar, variable=_level_var,
                          values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR"],
                          width=90, height=26,
                          fg_color=C["bg_input"], button_color=C["accent"],
                          button_hover_color=C["accent_h"],
                          dropdown_fg_color=C["bg_card"],
                          font=ctk.CTkFont(size=11)).pack(side="left")

        _search_var = ctk.StringVar()
        ctk.CTkLabel(toolbar, text="Filter:", font=ctk.CTkFont(size=11),
                     text_color=C["text_dim"]).pack(side="left", padx=(12, 4))
        ctk.CTkEntry(toolbar, textvariable=_search_var, width=160, height=26,
                     fg_color=C["bg_input"], border_color=C["border"],
                     font=ctk.CTkFont(size=11)).pack(side="left")

        _autoscroll = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(toolbar, text="Auto-scroll", variable=_autoscroll,
                        font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                        fg_color=C["accent"], hover_color=C["accent_h"],
                        border_color=C["border"], width=20).pack(side="left", padx=12)

        txt = ctk.CTkTextbox(win, fg_color="#0a0a0a", text_color=C["text"],
                             font=ctk.CTkFont(family="Courier New", size=11),
                             wrap="word", state="disabled")

        def _clear_log():
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.configure(state="disabled")
            _line_count[0] = 0

        ctk.CTkButton(toolbar, text="Clear", width=60, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=C["bg_dark"], hover_color=C["red"],
                      border_width=1, border_color=C["border"],
                      command=_clear_log).pack(side="right", padx=8)

        def _export_log():
            import tkinter.filedialog as _fd
            path = _fd.asksaveasfilename(
                title="Export Log", defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
            if path:
                txt.configure(state="normal")
                content = txt.get("1.0", "end")
                txt.configure(state="disabled")
                Path(path).write_text(content, encoding="utf-8")

        ctk.CTkButton(toolbar, text="Export", width=65, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=C["bg_dark"], hover_color=C["accent"],
                      border_width=1, border_color=C["border"],
                      command=_export_log).pack(side="right", padx=(0, 4))

        txt.pack(fill="both", expand=True)

        # Color tags
        txt.tag_config("DEBUG",    foreground="#6b7280")
        txt.tag_config("INFO",     foreground="#e2e8f0")
        txt.tag_config("WARNING",  foreground="#eab308")
        txt.tag_config("ERROR",    foreground="#ef4444")
        txt.tag_config("CRITICAL", foreground="#ff0000")
        txt.tag_config("SHINY",    foreground="#fbbf24")
        txt.tag_config("WORKER",   foreground="#a78bfa")
        txt.tag_config("AI",       foreground="#22c55e")

        status_bar = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=24)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        _line_count_lbl = ctk.CTkLabel(status_bar, text="0 lines",
                                       font=ctk.CTkFont(size=10), text_color=C["text_dim"])
        _line_count_lbl.pack(side="right", padx=8)
        _queue_lbl = ctk.CTkLabel(status_bar, text="Queue: 0",
                                  font=ctk.CTkFont(size=10), text_color=C["text_dim"])
        _queue_lbl.pack(side="left", padx=8)

        _line_count = [0]
        MAX_LINES = 2000

        def _get_tag(line: str) -> str:
            if "DEBUG" in line:
                return "DEBUG"
            if "WARNING" in line:
                return "WARNING"
            if "ERROR" in line or "CRITICAL" in line:
                return "ERROR"
            if "worker." in line or "Worker" in line or "Instance" in line:
                return "WORKER"
            if "ai." in line or " AI " in line:
                return "AI"
            if "SHINY" in line or "shiny" in line:
                return "SHINY"
            return "INFO"

        def _poll_log():
            if not win.winfo_exists():
                return
            level_filter = _level_var.get()
            search_filter = _search_var.get().lower()
            added = 0
            txt.configure(state="normal")
            try:
                for _ in range(300):
                    line = _log_queue.get_nowait()
                    if level_filter != "ALL":
                        if level_filter not in line:
                            continue
                    if search_filter and search_filter not in line.lower():
                        continue
                    tag = _get_tag(line)
                    txt.insert("end", line + "\n", tag)
                    _line_count[0] += 1
                    added += 1
            except queue.Empty:
                pass
            if _line_count[0] > MAX_LINES:
                txt.delete("1.0", f"{_line_count[0] - MAX_LINES}.0")
                _line_count[0] = MAX_LINES
            txt.configure(state="disabled")
            if added and _autoscroll.get():
                txt.see("end")
            _line_count_lbl.configure(text=f"{_line_count[0]:,} lines")
            _queue_lbl.configure(text=f"Queue: {_log_queue.qsize()}")
            win.after(150, _poll_log)

        _poll_log()
        logger.info("Log window opened – all logging output captured here")

    # ─────────────────────────────────────────────────────────────────────
    #  SHINY MATH WINDOW
    # ─────────────────────────────────────────────────────────────────────

    def _open_shiny_math(self):
        """Show shiny/perfect IV math for all running instances."""
        win = ctk.CTkToplevel(self)
        win.title("Shiny & Perfect IV Math")
        win.geometry("720x580")
        win.configure(fg_color=C["bg_dark"])
        win.resizable(True, True)

        ctk.CTkLabel(win, text="SHINY & PERFECT IV CALCULATOR",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=C["accent"]).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(win,
                     text="Gen 3 shiny formula:  (TID XOR SID XOR PID_high16 XOR PID_low16) < 8\n"
                          "Perfect IVs require specific PID+nature combos — use PokeFinder with TID/SID.",
                     font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                     justify="left").pack(anchor="w", padx=16, pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(win, fg_color=C["bg_dark"])
        scroll.pack(fill="both", expand=True, padx=8, pady=4)

        from modules.tid_engine import TrainerID as _TID

        instances_to_show = self.instances if self.instances else {
            0: type("S", (), {"seed": 0x1234, "tid": 0, "sid": 0,
                              "bot_mode": "encounter_farm"})()
        }

        for iid, state in instances_to_show.items():
            tid_obj = _TID(seed=state.seed, tid=state.tid, sid=state.sid)
            xor_val = state.tid ^ state.sid

            card = ctk.CTkFrame(scroll, fg_color=C["bg_card"],
                                corner_radius=8, border_width=1, border_color=C["border"])
            card.pack(fill="x", pady=4, padx=4)

            hdr = ctk.CTkFrame(card, fg_color=C["bg_input"], corner_radius=0)
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr,
                         text=f"Instance #{iid}  |  seed=0x{state.seed:04X}  "
                              f"TID={state.tid:05d}  SID={state.sid:05d}",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["text"]).pack(side="left", padx=12, pady=6)
            ctk.CTkLabel(hdr, text=f"TID^SID = 0x{xor_val:04X}",
                         font=ctk.CTkFont(size=11),
                         text_color=C["accent"]).pack(side="right", padx=12)

            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(fill="x", padx=12, pady=8)

            ctk.CTkLabel(body,
                         text=f"Shiny:  (0x{state.tid:04X} ^ 0x{state.sid:04X} ^ PID>>16 ^ PID&0xFFFF) < 8",
                         font=ctk.CTkFont(family="Courier New", size=11),
                         text_color=C["text_dim"]).pack(anchor="w")
            ctk.CTkLabel(body,
                         text=f"Base odds: 1 in 8,192  ({100/8192:.4f}%)  "
                              f"|  With Shiny Charm: 1 in 1,365",
                         font=ctk.CTkFont(size=11),
                         text_color=C["yellow"]).pack(anchor="w", pady=(4, 0))

            # Scan for shiny PIDs
            shiny_pids = []
            for _hi in range(0, 0x10000):
                for _lo in range(max(0, _hi - 7), min(0x10000, _hi + 8)):
                    pv = (_hi << 16) | _lo
                    if tid_obj.is_shiny_pid(pv):
                        shiny_pids.append(f"0x{pv:08X}")
                if len(shiny_pids) >= 16:
                    break

            ctk.CTkLabel(body, text="Sample shiny PIDs (first 16):",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=C["text"]).pack(anchor="w", pady=(8, 2))
            pid_grid = ctk.CTkFrame(body, fg_color="transparent")
            pid_grid.pack(anchor="w")
            for i, pid_str in enumerate(shiny_pids[:16]):
                ctk.CTkLabel(pid_grid, text=pid_str,
                             font=ctk.CTkFont(family="Courier New", size=10),
                             text_color=C["gold"],
                             width=110).grid(row=i // 4, column=i % 4, padx=4, pady=1, sticky="w")

            ctk.CTkLabel(body,
                         text="For perfect IVs: use PokeFinder → Stationary/Wild RNG → enter TID/SID above.",
                         font=ctk.CTkFont(size=10), text_color=C["text_dim"]).pack(anchor="w", pady=(8, 0))

        def _copy_all():
            lines = [f"Instance {iid}: TID={s.tid} SID={s.sid} seed=0x{s.seed:04X}"
                     for iid, s in self.instances.items()]
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines) if lines else "No instances running")

        ctk.CTkButton(win, text="Copy all TID/SID to clipboard", width=220, height=30,
                      font=ctk.CTkFont(size=12),
                      fg_color=C["accent"], hover_color=C["accent_h"],
                      command=_copy_all).pack(pady=8)

    # ─────────────────────────────────────────────────────────────────────
    #  SETTINGS WINDOW
    # ─────────────────────────────────────────────────────────────────────

    def _open_settings(self):
        """Open mGBA-style settings window with tabs."""
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("560x520")
        win.configure(fg_color=C["bg_dark"])
        win.resizable(False, False)
        win.grab_set()  # modal

        # ── Tab bar ──────────────────────────────────────────────────────
        tab_names = ["ROM / Paths", "Keybinds", "Audio", "Display"]
        tab_frames: Dict[str, ctk.CTkFrame] = {}
        tab_btns: Dict[str, ctk.CTkButton] = {}

        tab_bar = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=40)
        tab_bar.pack(fill="x")
        tab_bar.pack_propagate(False)

        content_area = ctk.CTkFrame(win, fg_color=C["bg_dark"])
        content_area.pack(fill="both", expand=True, padx=0, pady=0)

        for name in tab_names:
            f = ctk.CTkScrollableFrame(content_area, fg_color=C["bg_dark"])
            tab_frames[name] = f

        def _switch_tab(name):
            for n, f in tab_frames.items():
                f.pack_forget()
            tab_frames[name].pack(fill="both", expand=True, padx=16, pady=12)
            for n, b in tab_btns.items():
                b.configure(
                    fg_color=C["accent"] if n == name else "transparent",
                    text_color="#fff" if n == name else C["text_dim"],
                )

        for name in tab_names:
            b = ctk.CTkButton(
                tab_bar, text=name, width=120, height=38,
                font=ctk.CTkFont(size=12),
                fg_color="transparent", hover_color=C["bg_input"],
                text_color=C["text_dim"], corner_radius=0,
                command=lambda n=name: _switch_tab(n),
            )
            b.pack(side="left")
            tab_btns[name] = b

        # ── ROM / Paths tab ──────────────────────────────────────────────
        rf = tab_frames["ROM / Paths"]

        def _lbl(parent, text, bold=False):
            ctk.CTkLabel(parent, text=text,
                         font=ctk.CTkFont(size=12, weight="bold" if bold else "normal"),
                         text_color=C["text"] if bold else C["text_dim"],
                         anchor="w").pack(fill="x", pady=(8, 2))

        _lbl(rf, "GBA ROM File", bold=True)
        rom_row = ctk.CTkFrame(rf, fg_color="transparent")
        rom_row.pack(fill="x")
        rom_entry_var = ctk.StringVar(value=self.settings.get("rom_path", ""))
        rom_entry = ctk.CTkEntry(rom_row, textvariable=rom_entry_var,
                                 fg_color=C["bg_input"], border_color=C["border"])
        rom_entry.pack(side="left", fill="x", expand=True)

        def _browse_rom_settings():
            path = ctk.filedialog.askopenfilename(
                title="Select GBA ROM",
                filetypes=[("GBA ROMs", "*.gba *.bin"), ("All files", "*.*")])
            if not path:
                return
            src = Path(path)
            from modules.config import EMULATOR_DIR
            EMULATOR_DIR.mkdir(parents=True, exist_ok=True)
            dest = EMULATOR_DIR / "firered.gba"
            if src.resolve() != dest.resolve():
                try:
                    shutil.copy2(src, dest)
                except Exception:
                    dest = src
            rom_entry_var.set(str(dest))

        ctk.CTkButton(rom_row, text="Browse", width=70,
                      fg_color=C["accent"], hover_color=C["accent_h"],
                      command=_browse_rom_settings).pack(side="right", padx=(6, 0))

        def _clear_rom():
            rom_entry_var.set("")
        ctk.CTkButton(rf, text="Clear ROM selection", width=160, height=26,
                      font=ctk.CTkFont(size=11),
                      fg_color=C["bg_input"], hover_color=C["red"],
                      border_width=1, border_color=C["border"],
                      command=_clear_rom).pack(anchor="w", pady=(4, 0))

        _lbl(rf, "Save Directory", bold=True)
        from modules.config import EMULATOR_DIR as _EMUDIR
        ctk.CTkLabel(rf, text=str(_EMUDIR / "saves"),
                     font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                     anchor="w").pack(fill="x")

        # ── Keybinds tab ─────────────────────────────────────────────────
        kf = tab_frames["Keybinds"]
        _keybinds = self.settings.get("keybinds", {
            "a": "a", "s": "b", "Return": "start", "BackSpace": "select",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "q": "l", "w": "r",
        })

        ctk.CTkLabel(kf, text="GBA Button → Keyboard Key",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(kf, text="Click a field and press any key to rebind.",
                     font=ctk.CTkFont(size=11), text_color=C["text_dim"]).pack(anchor="w", pady=(0, 12))

        gba_buttons = [
            ("A", "a"), ("B", "s"), ("Start", "Return"), ("Select", "BackSpace"),
            ("Up", "Up"), ("Down", "Down"), ("Left", "Left"), ("Right", "Right"),
            ("L", "q"), ("R", "w"),
        ]
        # Reverse map: gba_name -> current keyboard key
        _rev = {v: k for k, v in _keybinds.items()}
        bind_vars: Dict[str, ctk.StringVar] = {}

        grid = ctk.CTkFrame(kf, fg_color="transparent")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        for row_i, (gba_name, default_key) in enumerate(gba_buttons):
            gba_lower = gba_name.lower()
            cur_key = _rev.get(gba_lower, default_key)
            var = ctk.StringVar(value=cur_key)
            bind_vars[gba_lower] = var

            ctk.CTkLabel(grid, text=f"GBA {gba_name}",
                         font=ctk.CTkFont(size=12), text_color=C["text"],
                         width=100, anchor="w").grid(
                row=row_i, column=0, padx=(0, 12), pady=3, sticky="w")

            entry = ctk.CTkEntry(grid, textvariable=var, width=120,
                                 fg_color=C["bg_input"], border_color=C["border"])
            entry.grid(row=row_i, column=1, pady=3, sticky="w")

            def _make_capture(e, v):
                def _cap(event):
                    v.set(event.keysym)
                    e.configure(border_color=C["accent"])
                    e.after(500, lambda: e.configure(border_color=C["border"]))
                    return "break"
                e.bind("<KeyPress>", _cap)
            _make_capture(entry, var)

        # ── Audio tab ────────────────────────────────────────────────────
        af = tab_frames["Audio"]
        ctk.CTkLabel(af, text="Audio Settings",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(0, 12))

        _audio = self.settings.get("audio", {})

        mute_var = ctk.BooleanVar(value=_audio.get("mute", True))
        ctk.CTkCheckBox(af, text="Mute emulator audio",
                        variable=mute_var,
                        font=ctk.CTkFont(size=12), text_color=C["text"],
                        fg_color=C["accent"], hover_color=C["accent_h"],
                        border_color=C["border"]).pack(anchor="w", pady=4)

        ctk.CTkLabel(af, text="Master Volume",
                     font=ctk.CTkFont(size=12), text_color=C["text_dim"]).pack(anchor="w", pady=(12, 2))
        vol_var = ctk.IntVar(value=_audio.get("volume", 50))
        vol_slider = ctk.CTkSlider(af, from_=0, to=100, variable=vol_var,
                                   button_color=C["accent"], button_hover_color=C["accent_h"],
                                   progress_color=C["accent"])
        vol_slider.pack(fill="x", pady=(0, 4))
        vol_lbl = ctk.CTkLabel(af, text=f"{vol_var.get()}%",
                               font=ctk.CTkFont(size=11), text_color=C["text_dim"])
        vol_lbl.pack(anchor="w")
        vol_slider.configure(command=lambda v: vol_lbl.configure(text=f"{int(v)}%"))

        ctk.CTkLabel(af, text="Notification Sound Volume",
                     font=ctk.CTkFont(size=12), text_color=C["text_dim"]).pack(anchor="w", pady=(12, 2))
        notif_vol_var = ctk.IntVar(value=_audio.get("notif_volume", 80))
        notif_slider = ctk.CTkSlider(af, from_=0, to=100, variable=notif_vol_var,
                                     button_color=C["accent"], button_hover_color=C["accent_h"],
                                     progress_color=C["accent"])
        notif_slider.pack(fill="x", pady=(0, 4))
        notif_lbl = ctk.CTkLabel(af, text=f"{notif_vol_var.get()}%",
                                 font=ctk.CTkFont(size=11), text_color=C["text_dim"])
        notif_lbl.pack(anchor="w")
        notif_slider.configure(command=lambda v: notif_lbl.configure(text=f"{int(v)}%"))

        # ── Display tab ──────────────────────────────────────────────────
        df = tab_frames["Display"]
        ctk.CTkLabel(df, text="Display Settings",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(0, 12))

        _display = self.settings.get("display", {})

        ctk.CTkLabel(df, text="Instance Window Scale",
                     font=ctk.CTkFont(size=12), text_color=C["text_dim"]).pack(anchor="w", pady=(0, 2))
        scale_var = ctk.StringVar(value=_display.get("scale", "1.25x"))
        ctk.CTkOptionMenu(df, variable=scale_var,
                          values=["1x (240×160)", "1.25x (300×200)", "1.5x (360×240)", "2x (480×320)"],
                          fg_color=C["bg_input"], button_color=C["accent"],
                          button_hover_color=C["accent_h"],
                          dropdown_fg_color=C["bg_card"]).pack(anchor="w", pady=(0, 12))

        video_var = ctk.BooleanVar(value=self.settings.get("video_enabled", True))
        ctk.CTkCheckBox(df, text="Show live game screen in instance windows",
                        variable=video_var,
                        font=ctk.CTkFont(size=12), text_color=C["text"],
                        fg_color=C["accent"], hover_color=C["accent_h"],
                        border_color=C["border"]).pack(anchor="w", pady=4)

        fps_cap_var = ctk.BooleanVar(value=_display.get("fps_cap", False))
        ctk.CTkCheckBox(df, text="Cap screen refresh to 30 FPS (saves CPU)",
                        variable=fps_cap_var,
                        font=ctk.CTkFont(size=12), text_color=C["text"],
                        fg_color=C["accent"], hover_color=C["accent_h"],
                        border_color=C["border"]).pack(anchor="w", pady=4)

        dark_var = ctk.BooleanVar(value=_display.get("dark_mode", True))
        ctk.CTkCheckBox(df, text="Dark mode",
                        variable=dark_var,
                        font=ctk.CTkFont(size=12), text_color=C["text"],
                        fg_color=C["accent"], hover_color=C["accent_h"],
                        border_color=C["border"]).pack(anchor="w", pady=4)

        # ── Save / Cancel buttons ─────────────────────────────────────────
        btn_row = ctk.CTkFrame(win, fg_color=C["bg_card"], corner_radius=0, height=50)
        btn_row.pack(fill="x", side="bottom")
        btn_row.pack_propagate(False)

        def _save_settings():
            # Rebuild keybinds: keyboard_key -> gba_name
            new_keybinds = {}
            for gba_name, var in bind_vars.items():
                new_keybinds[var.get()] = gba_name

            self.settings["rom_path"] = rom_entry_var.get()
            self.settings["keybinds"] = new_keybinds
            self.settings["audio"] = {
                "mute": mute_var.get(),
                "volume": vol_var.get(),
                "notif_volume": notif_vol_var.get(),
            }
            self.settings["display"] = {
                "scale": scale_var.get(),
                "fps_cap": fps_cap_var.get(),
                "dark_mode": dark_var.get(),
            }
            self.settings["video_enabled"] = video_var.get()
            save_settings(self.settings)

            # Apply ROM path to sidebar entry
            self._rom_var.set(rom_entry_var.get())
            self._validate_rom_display()

            win.destroy()

        ctk.CTkButton(btn_row, text="Save", width=100, height=34,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=C["accent"], hover_color=C["accent_h"],
                      command=_save_settings).pack(side="right", padx=12, pady=8)
        ctk.CTkButton(btn_row, text="Cancel", width=80, height=34,
                      font=ctk.CTkFont(size=12),
                      fg_color=C["bg_dark"], hover_color=C["bg_input"],
                      border_width=1, border_color=C["border"],
                      command=win.destroy).pack(side="right", padx=(0, 4), pady=8)

        # Start on ROM tab
        _switch_tab("ROM / Paths")

    # ─────────────────────────────────────────────────────────────────────
    #  ACTIONS
    # ─────────────────────────────────────────────────────────────────────

    def _browse_rom(self):
        path = ctk.filedialog.askopenfilename(
            title="Select GBA ROM",
            filetypes=[("GBA ROMs", "*.gba *.bin"), ("All files", "*.*")],
        )
        if not path:
            return
        src = Path(path)
        from modules.config import EMULATOR_DIR
        EMULATOR_DIR.mkdir(parents=True, exist_ok=True)
        # Always copy to canonical name: emulator/firered.gba
        dest = EMULATOR_DIR / "firered.gba"
        if src.resolve() != dest.resolve():
            try:
                shutil.copy2(src, dest)
            except Exception as exc:
                self._rom_status.configure(
                    text=f"Copy failed: {exc}", text_color=C["red"])
                dest = src
        self._rom_var.set(str(dest))
        self.settings["rom_path"] = str(dest)
        save_settings(self.settings)
        self._validate_rom_display()

    def _validate_rom_display(self):
        rom = self._rom_var.get()
        if not rom:
            self._rom_status.configure(text="No ROM selected", text_color=C["text_dim"])
            return False
        p = Path(rom)
        if not p.exists():
            self._rom_status.configure(text="File not found!", text_color=C["red"])
            return False
        size_mb = p.stat().st_size / (1024 * 1024)
        self._rom_status.configure(text=f"{p.name} ({size_mb:.1f} MB)", text_color=C["green"])
        return True

    def _start_all(self):
        if not self._validate_rom_display():
            from tkinter import messagebox
            messagebox.showerror("Error", "Select a valid GBA ROM file first.")
            return

        rom_path = self._rom_var.get()
        area = self._area_var.get()
        speed = self._speed_var.get()
        count = int(self._inst_var.get())
        game_version = self._game_version_var.get()
        _rom_p = Path(rom_path)

        # ── Check save files for all instances-to-be-created ─────────────
        _any_save = any(
            save_exists_for_instance(inst_num, _rom_p)
            for inst_num in range(1, count + 1)
        )

        mode = self._mode_var.get()
        if not mode:
            if _any_save:
                # Has saves but no mode selected – ask user to pick one
                from tkinter import messagebox
                messagebox.showerror(
                    "Bot Mode Required",
                    "A save file was found.\nPlease select a Bot Mode before starting."
                )
                return
            else:
                # No saves at all – auto-start in manual mode, no bot mode needed
                mode = "manual"
                logger.info(
                    "No save files found for %d instance(s) – auto-starting in MANUAL mode. "
                    "Bot will attempt new-game intro sequence, then hand control to you.", count
                )

        # ── Stop and clean up any previous run ───────────────────────────
        for s in self.instances.values():
            s.request_stop()
        for w_dict in self._instance_widgets.values():
            try:
                w_dict["win"].destroy()
            except Exception:
                pass
        self._instance_widgets.clear()
        self.instances.clear()
        self.threads.clear()
        self._next_id = 1  # always start from instance 1
        self._photo_cache.clear()
        for r in getattr(self, "_inst_rows", {}).values():
            try:
                r["frame"].destroy()
            except Exception:
                pass
        self._inst_rows = {}

        self.settings.update({
            "rom_path": rom_path, "target_area": area,
            "speed_multiplier": speed, "max_instances": count,
            "video_enabled": self._video_var.get(), "bot_mode": mode,
            "game_version": game_version,
        })
        save_settings(self.settings)

        if not _any_save:
            self._placeholder.configure(
                text=f"{count} instance(s) starting in MANUAL mode (no save file found).\n\n"
                     "Bot will try to navigate the new-game intro automatically.\n"
                     "If it gets stuck, use the Control button to take over.\n\n"
                     f"Save path expected:  emulator/saves/<1-{count}>/{_rom_p.stem}.sav"
            )
        else:
            self._placeholder.configure(
                text=f"{count} instance window(s) opening…\n\n"
                     "Each instance runs in its own window.\n"
                     "Use the Control button in each window to take manual control."
            )
        self._placeholder.pack(pady=40)
        self._start_time = time.time()

        for i in range(count):
            seed = (0x1234 + i * 0x111) & 0xFFFF
            trainer_id = seed_to_ids(seed)
            inst_mode = mode

            state = InstanceState(
                instance_id=self._next_id,
                seed=seed, tid=trainer_id.tid, sid=trainer_id.sid,
                speed_multiplier=speed, bot_mode=inst_mode,
            )
            iid = self._next_id
            self._next_id += 1

            self.instances[iid] = state
            self._create_card(iid, state)

            t = threading.Thread(
                target=emulator_worker,
                args=(state, rom_path, area, speed, self.hw["cpu_physical"]),
                daemon=True,
            )
            self.threads[iid] = t
            t.start()

        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._pause_btn.configure(state="normal")

    def _stop_all(self):
        for s in self.instances.values():
            s.request_stop()
        self._stop_btn.configure(state="disabled")
        self._pause_btn.configure(state="disabled")
        self.after(2000, self._check_cleanup)

    def _pause_all(self):
        for s in self.instances.values():
            if s.status in ("running", "paused"):
                s.request_pause()

    def _check_cleanup(self):
        if all(not t.is_alive() for t in self.threads.values()):
            self._start_btn.configure(state="normal")
        else:
            self.after(1000, self._check_cleanup)

    # ─────────────────────────────────────────────────────────────────────
    #  REFRESH
    # ─────────────────────────────────────────────────────────────────────

    def _refresh_gui(self):
        total_enc = 0
        total_fps = 0.0
        active = 0

        status_colors = {
            "running": C["green"], "booting": C["yellow"], "paused": C["yellow"],
            "manual": C["accent"], "shiny_found": C["gold"], "stopped": C["red"],
            "error": C["red"], "idle": C["text_dim"], "completed": C["green"],
        }
        status_labels = {
            "running": "RUNNING", "booting": "BOOTING", "paused": "PAUSED",
            "manual": "MANUAL", "shiny_found": "SHINY!", "stopped": "STOPPED",
            "error": "ERROR", "idle": "IDLE", "completed": "DONE",
        }
        for iid, state in list(self.instances.items()):
            self._update_card(iid, state)
            total_enc += state.encounters
            if state.status in ("running", "manual"):
                total_fps += state.fps
                active += 1
            # Update scroll-frame row
            row = self._inst_rows.get(iid)
            if row:
                txt = status_labels.get(state.status, state.status.upper())
                col = status_colors.get(state.status, C["text_dim"])
                row["status"].configure(text=txt, text_color=col)
                if state.status == "error" and state.error:
                    row["metrics"].configure(
                        text=state.error[:50], text_color=C["red"])
                else:
                    row["metrics"].configure(
                        text=f"Enc: {state.encounters:,}  |  FPS: {state.fps:,.0f}",
                        text_color=C["text"])

        self._stat_enc.configure(text=f"Encounters: {total_enc:,}")
        try:
            self._stat_shiny.configure(text=f"Shinies: {total_shinies()}")
        except Exception:
            pass
        self._stat_fps.configure(text=f"Total FPS: {total_fps:,.0f}  ({active} active)")
        self._active_label.configure(text=f"{active} active")

        if self._start_time:
            e = int(time.time() - self._start_time)
            self._stat_time.configure(text=f"Uptime: {e // 3600}:{(e % 3600) // 60:02d}:{e % 60:02d}")

        # Stats tracker data
        try:
            stats = _global_stats.get_summary()
            enc_hr = stats.get("rolling_rate", 0)
            if hasattr(self, "_stat_enc_rate"):
                self._stat_enc_rate.configure(text=f"Enc/hr: {enc_hr:,.0f}")
            if hasattr(self, "_stat_probability") and total_enc > 0:
                prob = shiny_probability(total_enc)
                self._stat_probability.configure(
                    text=f"Shiny chance: {prob['probability']:.1f}%")
        except Exception:
            pass

        # Living Dex progress
        try:
            prog = get_living_dex_progress()
            owned = prog.get("owned", 0)
            total = prog.get("total", NATIONAL_DEX_SIZE)
            pct = (owned / total * 100) if total > 0 else 0
            self._dex_progress_label.configure(text=f"{owned} / {total} ({pct:.1f}%)")
            self._dex_bar.set(owned / total if total > 0 else 0)
            by_stage = prog.get("by_stage", {})
            s1 = by_stage.get(1, {}).get("owned", 0)
            s2 = by_stage.get(2, {}).get("owned", 0)
            s3 = by_stage.get(3, {}).get("owned", 0)
            self._dex_detail.configure(text=f"Base: {s1}  |  Stage 2: {s2}  |  Final: {s3}")
        except Exception:
            pass

        # Legitimacy check
        try:
            if is_save_legitimate():
                self._legit_label.configure(text="Legitimacy: CLEAN", text_color=C["green"])
            else:
                self._legit_label.configure(text="Legitimacy: MODIFIED", text_color=C["yellow"])
        except Exception:
            pass

        # Recent encounters log
        try:
            log_entries = _global_stats.session.encounter_log[-10:]
            if log_entries and hasattr(self, "_encounter_log_text"):
                lines = []
                for rec in reversed(log_entries):
                    shiny_tag = " SHINY!" if rec.is_shiny else ""
                    lines.append(f"#{rec.species_id:03d} [{rec.bot_mode}]{shiny_tag}")
                text = "\n".join(lines)
                self._encounter_log_text.configure(state="normal")
                self._encounter_log_text.delete("1.0", "end")
                self._encounter_log_text.insert("1.0", text)
                self._encounter_log_text.configure(state="disabled")
        except Exception:
            pass

        if self.instances:
            done = all(s.status in ("stopped", "shiny_found", "idle", "completed", "error")
                       for s in self.instances.values())
            if done and not any(t.is_alive() for t in self.threads.values()):
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                self._pause_btn.configure(state="disabled")

        self.after(200, self._refresh_gui)

    def _on_close(self):
        self.settings["window_geometry"] = self.geometry()
        save_settings(self.settings)
        for s in self.instances.values():
            s.request_stop()
        for t in self.threads.values():
            t.join(timeout=2)
        try:
            get_async_worker().stop()
        except Exception:
            pass
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
