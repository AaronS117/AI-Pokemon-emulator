"""
bot_modes – Specialized bot modes for shiny living dex completion.

Each mode implements a specific hunting/evolution strategy using
the GameBot's libmgba-py memory access and input system.

Modes:
  - EncounterFarmMode: Walk in grass for wild encounters
  - StarterResetMode: Soft-reset for shiny starters
  - StaticEncounterMode: Soft-reset for legendaries/static encounters
  - FishingMode: Fish for water Pokémon (ported from pokebot-gen3)
  - BreedingMode: Daycare egg hatching loop
  - LevelEvolutionMode: Level Pokémon to evolution threshold
  - StoneEvolutionMode: Apply evolution stones from bag
  - TradeEvolutionMode: Coordinate trade evolutions between instances
  - SweetScentMode: Use Sweet Scent for guaranteed encounters
"""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot, PokemonData

from modules.game_bot import GBAButton, GameState

logger = logging.getLogger(__name__)


# ── Mode status ─────────────────────────────────────────────────────────────

class ModeStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ModeResult:
    """Result from a single mode iteration."""
    encounter: Optional[PokemonData] = None
    is_shiny: bool = False
    encounters_this_session: int = 0
    status: ModeStatus = ModeStatus.RUNNING
    message: str = ""


# ── Base Mode ───────────────────────────────────────────────────────────────

class BotMode:
    """Base class for all bot modes."""

    name: str = "Base"
    description: str = ""

    def __init__(self, bot: GameBot):
        self.bot = bot
        self.status = ModeStatus.IDLE
        self.encounters = 0
        self.shinies_found = 0
        self.start_time: float = 0.0

    def start(self) -> None:
        self.status = ModeStatus.RUNNING
        self.start_time = time.time()
        logger.info("Started mode: %s", self.name)

    def stop(self) -> None:
        self.status = ModeStatus.IDLE
        logger.info("Stopped mode: %s (encounters=%d, shinies=%d)",
                     self.name, self.encounters, self.shinies_found)

    def step(self) -> ModeResult:
        """Execute one iteration of the mode. Override in subclasses."""
        raise NotImplementedError

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time == 0:
            return 0.0
        return time.time() - self.start_time

    @property
    def encounters_per_hour(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return (self.encounters / elapsed) * 3600


# ── Encounter Farm Mode ─────────────────────────────────────────────────────

class EncounterFarmMode(BotMode):
    """Walk back and forth in grass to trigger wild encounters."""

    name = "Encounter Farm"
    description = "Walk in grass/cave to trigger random wild encounters"

    def __init__(self, bot: GameBot, direction_frames: int = 16,
                 pause_frames: int = 4):
        super().__init__(bot)
        self._step_count = 0
        self._direction_frames = direction_frames
        self._pause_frames = pause_frames

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        # Alternate walking up and down
        direction = GBAButton.UP if self._step_count % 2 == 0 else GBAButton.DOWN
        self.bot.press_button(direction, hold_frames=self._direction_frames)
        self.bot.advance_frames(self._pause_frames)
        self._step_count += 1

        # Check if we entered a battle
        if self.bot.is_in_battle():
            enemy = self.bot._read_enemy_lead()
            self.encounters += 1

            if enemy.is_shiny:
                self.shinies_found += 1
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY found after {self.encounters} encounters!"
                )

            # Run from non-shiny
            self.bot.run_from_battle()
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Encounter #{self.encounters} - not shiny"
            )

        return ModeResult(
            encounters_this_session=self.encounters,
            status=ModeStatus.RUNNING,
            message=f"Walking... (step {self._step_count})"
        )


# ── Starter Reset Mode ──────────────────────────────────────────────────────

class StarterResetMode(BotMode):
    """
    Soft-reset loop for shiny starters (FireRed/LeafGreen new-game flow).

    After a soft reset the game starts a NEW GAME from scratch:
      1. Title screen → mash A through Oak's intro speech
      2. Naming screen → skip (already handled by app.py intro sequence)
      3. Player spawns in bedroom at (17, 12) in Pallet Town
      4. Walk downstairs, exit house, walk north toward Route 1
      5. Oak cutscene triggers → Oak takes you to his lab (scripted)
      6. Oak talks, tells you to pick a starter → mash A
      7. Player gains control in Oak's Lab → walk to pokeball
      8. Face up, press A to interact → confirm selection
      9. Read party slot 0, check shininess
     10. If not shiny → soft reset and repeat

    NOTE: pokebot-gen3 requires a save file already in Oak's Lab.
    We handle the full new-game flow instead, which is slower but
    works without any save file.

    FRLG Oak's Lab pokeball coordinates (pokefirered decompilation):
      Bulbasaur = (8, 5)   Squirtle = (9, 5)   Charmander = (10, 5)
    """

    name = "Starter Reset"
    description = "Soft-reset for shiny starter Pokémon"

    # Pokeball table coordinates in Oak's Lab (FRLG)
    _STARTER_COORDS = {
        0: (8, 5),   # Bulbasaur  (left)
        1: (9, 5),   # Squirtle   (middle)
        2: (10, 5),  # Charmander (right)
    }

    # Map group/number constants (FRLG)
    _MAP_OAKS_LAB = (4, 3)        # Pallet Town - Professor Oak's Lab
    _MAP_PLAYER_HOUSE_1F = (4, 1) # Pallet Town - Player's House 1F
    _MAP_PALLET_TOWN = (3, 0)     # Pallet Town (overworld)

    def __init__(self, bot: GameBot, starter_index: int = 0):
        super().__init__(bot)
        self.starter_index = starter_index  # 0=left, 1=middle, 2=right
        self._phase = "reset"
        self._wait_frames = 0
        self._has_save = False  # set True once we detect a save file exists

    def _log(self, msg, *args):
        logger.info("[StarterReset] " + msg, *args)

    def _mash_a(self, count: int = 1, gap: int = 10):
        """Press A count times with gap frames between."""
        for _ in range(count):
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(gap)

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        # ── Phase: reset ──────────────────────────────────────────────────
        if self._phase == "reset":
            fc = self.bot.frame_count
            self._log("Soft reset #%d at frame %d", self.encounters + 1, fc)
            self.bot.soft_reset()
            self._phase = "skip_intro"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message=f"Soft resetting... (reset #{self.encounters+1})")

        # ── Phase: skip_intro ─────────────────────────────────────────────
        # Mash A through title screen, Oak intro, naming, etc.
        # until we reach the overworld (either bedroom or Oak's Lab if saved there)
        elif self._phase == "skip_intro":
            self._mash_a(1, 10)
            self._wait_frames += 1

            if self._wait_frames > 30:
                state = self.bot.get_game_state()
                if state == GameState.OVERWORLD:
                    try:
                        coords = self.bot.get_player_coords()
                        map_gn = self.bot.get_player_map()
                        self._log("Overworld at frame %d  pos=%s  map=%s",
                                  self.bot.frame_count, coords, map_gn)

                        # If we're already in Oak's Lab (save file was there), skip navigation
                        if map_gn == self._MAP_OAKS_LAB:
                            self._has_save = True
                            self._log("Already in Oak's Lab (from save) – going to pokeball")
                            self._phase = "walk_to_pokeball"
                            self._wait_frames = 0
                        else:
                            # New game: player is in bedroom or house
                            self._phase = "navigate_to_oak"
                            self._wait_frames = 0
                    except Exception as e:
                        self._log("Overworld reached but coords failed: %s", e)
                        self._phase = "navigate_to_oak"
                        self._wait_frames = 0

            if self._wait_frames > 300:
                self._log("Intro skip timed out at frame %d – resetting", self.bot.frame_count)
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING, message="Skipping intro...")

        # ── Phase: navigate_to_oak ────────────────────────────────────────
        # Full new-game navigation: bedroom → downstairs → outside → north → Oak cutscene
        elif self._phase == "navigate_to_oak":
            self._log("Navigating new-game flow at frame %d", self.bot.frame_count)

            # Step 1: Walk down from bedroom to stairs
            # Player starts at roughly (17, 12) facing down in bedroom (2F)
            # The stairs are at the bottom of the room
            self._log("Step 1: Walking down to exit bedroom...")
            self.bot.hold_button(GBAButton.DOWN)
            for i in range(60):
                self.bot._apply_inputs_and_run_frame()
            self.bot.release_all()
            self.bot.advance_frames(30)  # wait for map transition

            # Step 2: Walk down to exit the house (1F)
            self._log("Step 2: Walking down to exit house...")
            self.bot.hold_button(GBAButton.DOWN)
            for i in range(90):
                self.bot._apply_inputs_and_run_frame()
            self.bot.release_all()
            self.bot.advance_frames(30)  # wait for map transition

            # Step 3: Walk north in Pallet Town toward Route 1
            # This triggers Oak's cutscene where he stops you
            self._log("Step 3: Walking north to trigger Oak cutscene...")
            self.bot.hold_button(GBAButton.UP)
            for i in range(120):
                self.bot._apply_inputs_and_run_frame()
            self.bot.release_all()

            self._phase = "oak_cutscene"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Walking to trigger Oak...")

        # ── Phase: oak_cutscene ───────────────────────────────────────────
        # Oak stops you, walks you to his lab, gives a speech.
        # Just mash A through all of it until we're in the overworld in Oak's Lab.
        elif self._phase == "oak_cutscene":
            self._mash_a(1, 5)
            self._wait_frames += 1

            # Check periodically if we're in Oak's Lab overworld
            if self._wait_frames % 20 == 0:
                state = self.bot.get_game_state()
                if state == GameState.OVERWORLD:
                    try:
                        map_gn = self.bot.get_player_map()
                        coords = self.bot.get_player_coords()
                        if map_gn == self._MAP_OAKS_LAB:
                            self._log("In Oak's Lab! pos=%s  frame %d", coords, self.bot.frame_count)
                            # Oak tells you to pick a starter — keep mashing A
                            # until the player can move freely
                            self._phase = "wait_for_control"
                            self._wait_frames = 0
                    except Exception:
                        pass

            if self._wait_frames > 600:
                self._log("Oak cutscene timed out at frame %d – resetting", self.bot.frame_count)
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Oak cutscene...")

        # ── Phase: wait_for_control ───────────────────────────────────────
        # In Oak's Lab, Oak talks and tells you to pick a starter.
        # Mash A until we can actually move (overworld + no script running).
        elif self._phase == "wait_for_control":
            self._mash_a(1, 5)
            self._wait_frames += 1

            # Try to detect when we have free movement by checking if
            # coordinates change when we press a direction
            if self._wait_frames % 10 == 0 and self._wait_frames > 30:
                try:
                    state = self.bot.get_game_state()
                    coords = self.bot.get_player_coords()
                    if state == GameState.OVERWORLD:
                        # Try pressing up briefly and see if we can move
                        old_coords = coords
                        self.bot._pressed_inputs = 1 << GBAButton.UP.value
                        for _ in range(16):
                            self.bot._apply_inputs_and_run_frame()
                        self.bot._pressed_inputs = 0
                        self.bot.advance_frames(8)
                        new_coords = self.bot.get_player_coords()
                        if new_coords != old_coords:
                            self._log("Player can move! pos=%s→%s  frame %d",
                                      old_coords, new_coords, self.bot.frame_count)
                            self._phase = "walk_to_pokeball"
                            self._wait_frames = 0
                except Exception:
                    pass

            if self._wait_frames > 400:
                self._log("Wait for control timed out at frame %d – resetting", self.bot.frame_count)
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Waiting for Oak to finish talking...")

        # ── Phase: walk_to_pokeball ───────────────────────────────────────
        elif self._phase == "walk_to_pokeball":
            target_x, target_y = self._STARTER_COORDS.get(self.starter_index, (8, 5))
            self._log("Walking to pokeball at (%d, %d)  frame %d",
                      target_x, target_y, self.bot.frame_count)
            reached = self.bot.walk_to(target_x, target_y, timeout_frames=600)
            if reached:
                try:
                    coords = self.bot.get_player_coords()
                    self._log("Reached pokeball at %s  frame %d", coords, self.bot.frame_count)
                except Exception:
                    pass
                self._phase = "face_and_interact"
                self._wait_frames = 0
            else:
                self._log("Walk to pokeball timed out at frame %d – resetting",
                          self.bot.frame_count)
                self._phase = "reset"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Walking to pokeball...")

        # ── Phase: face_and_interact ──────────────────────────────────────
        elif self._phase == "face_and_interact":
            self.bot.face_direction("up")
            self.bot.advance_frames(10)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            self._log("Interacted with pokeball at frame %d", self.bot.frame_count)
            self._phase = "confirm_starter"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Interacting with pokeball...")

        # ── Phase: confirm_starter ────────────────────────────────────────
        elif self._phase == "confirm_starter":
            self._mash_a(1, 10)
            self._wait_frames += 1

            party_count = self.bot.get_party_count()
            if party_count > 0:
                self._log("Starter received! party=%d  frame %d",
                          party_count, self.bot.frame_count)
                # Decline nickname with B, then wait for dialog to finish
                self.bot.press_button(GBAButton.B)
                self.bot.advance_frames(30)
                self.bot.press_button(GBAButton.B)
                self.bot.advance_frames(60)
                self._phase = "check_shiny"
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Starter received, checking...")

            if self._wait_frames > 300:
                self._log("Starter confirm timed out at frame %d – resetting",
                          self.bot.frame_count)
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Confirming starter selection...")

        # ── Phase: check_shiny ────────────────────────────────────────────
        elif self._phase == "check_shiny":
            self.encounters += 1
            try:
                raw = self.bot.read_symbol("gPlayerParty", 0, 100)
                pv = struct.unpack("<I", raw[0:4])[0]
                ot = struct.unpack("<I", raw[4:8])[0]
                tid = ot & 0xFFFF
                sid = (ot >> 16) & 0xFFFF
                is_shiny = (tid ^ sid ^ (pv >> 16) ^ (pv & 0xFFFF)) < 8

                self._log("Reset #%d  PV=0x%08X  TID=%d  SID=%d  shiny=%s  frame %d",
                          self.encounters, pv, tid, sid, is_shiny, self.bot.frame_count)

                if is_shiny:
                    self.shinies_found += 1
                    self.status = ModeStatus.COMPLETED
                    return ModeResult(
                        is_shiny=True,
                        encounters_this_session=self.encounters,
                        status=ModeStatus.COMPLETED,
                        message=f"SHINY STARTER after {self.encounters} resets!"
                    )
            except Exception as exc:
                logger.error("[StarterReset] Failed to read starter data: %s", exc)

            # Not shiny – reset
            self._phase = "reset"
            return ModeResult(
                is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Reset #{self.encounters} - not shiny"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Static Encounter Mode ───────────────────────────────────────────────────

class StaticEncounterMode(BotMode):
    """
    Soft-reset for static encounters (legendaries, Snorlax, etc.).

    Ported from pokebot-gen3's static_soft_resets.py.
    Expects the save to be positioned in front of the static Pokémon.
    """

    name = "Static Encounter"
    description = "Soft-reset for shiny legendaries and static encounters"

    def __init__(self, bot: GameBot):
        super().__init__(bot)
        self._phase = "reset"
        self._wait_frames = 0

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "reset":
            self.bot.soft_reset()
            self._phase = "wait_overworld"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Soft resetting...")

        elif self._phase == "wait_overworld":
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(5)
            self._wait_frames += 1

            state = self.bot.get_game_state()
            if state == GameState.OVERWORLD and self._wait_frames > 30:
                self._phase = "interact"
                self._wait_frames = 0

            if self._wait_frames > 300:
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Waiting for overworld...")

        elif self._phase == "interact":
            # Press A to interact with the static Pokémon
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            self._wait_frames += 1

            if self.bot.is_in_battle():
                self._phase = "check_shiny"
                self._wait_frames = 0

            if self._wait_frames > 200:
                self._phase = "reset"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Interacting with Pokémon...")

        elif self._phase == "check_shiny":
            # Wait for battle to fully load
            self.bot.advance_frames(60)
            self.encounters += 1

            enemy = self.bot._read_enemy_lead()
            if enemy.is_shiny:
                self.shinies_found += 1
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY LEGENDARY after {self.encounters} resets!"
                )

            # Not shiny – reset
            self._phase = "reset"
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Reset #{self.encounters} - not shiny"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Fishing Mode ────────────────────────────────────────────────────────────

class FishingMode(BotMode):
    """
    Fish for shiny water Pokémon.

    Ported from pokebot-gen3's fishing.py and modes/fishing.py.
    Uses the registered rod (Select button) to fish, detects bites
    via game state changes, and checks encountered Pokémon for shininess.

    Requires: Player facing water, fishing rod in key items.
    """

    name = "Fishing"
    description = "Fish for shiny water Pokémon using registered rod"

    def __init__(self, bot: GameBot):
        super().__init__(bot)
        self._phase = "cast"
        self._wait_frames = 0
        self._max_bite_wait = 300  # Max frames to wait for a bite

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "cast":
            # Use registered item (Select) to cast rod
            self.bot.press_button(GBAButton.SELECT)
            self.bot.advance_frames(30)
            self._phase = "wait_bite"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Casting rod...")

        elif self._phase == "wait_bite":
            # Wait for "Oh! A bite!" or "Not even a nibble..."
            # The game shows a "!" and requires pressing A at the right time
            self.bot.advance_frames(1)
            self._wait_frames += 1

            # Check if we got a bite by looking at game state
            state = self.bot.get_game_state()

            if state == GameState.BATTLE:
                self._phase = "check_shiny"
                self._wait_frames = 0
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Got a bite! Battle starting...")

            # Press A when we see the exclamation mark
            # The fishing minigame requires pressing A at the right moment
            # We press A every few frames to catch the timing
            if self._wait_frames % 3 == 0:
                self.bot.press_button(GBAButton.A, hold_frames=2)

            if self._wait_frames > self._max_bite_wait:
                # No bite – recast
                self._phase = "recast_wait"
                self._wait_frames = 0

            return ModeResult(status=ModeStatus.RUNNING,
                              message=f"Waiting for bite... ({self._wait_frames})")

        elif self._phase == "recast_wait":
            # Wait for the "Not even a nibble" text to clear
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)
            self._wait_frames += 1

            state = self.bot.get_game_state()
            if state == GameState.OVERWORLD and self._wait_frames > 3:
                self._phase = "cast"

            if self._wait_frames > 30:
                self._phase = "cast"

            return ModeResult(status=ModeStatus.RUNNING,
                              message="No bite, recasting...")

        elif self._phase == "check_shiny":
            # Wait for battle to fully load
            self.bot.advance_frames(60)
            self.encounters += 1

            enemy = self.bot._read_enemy_lead()
            if enemy.is_shiny:
                self.shinies_found += 1
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY FISH after {self.encounters} encounters!"
                )

            # Run from non-shiny
            self.bot.run_from_battle()
            self._phase = "cast"
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Fish #{self.encounters} - not shiny"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Sweet Scent Mode ────────────────────────────────────────────────────────

class SweetScentMode(BotMode):
    """
    Use Sweet Scent to guarantee wild encounters.

    Ported from pokebot-gen3's sweet_scent.py.
    Requires a Pokémon with Sweet Scent in the party.
    More efficient than walking since every use triggers an encounter.
    """

    name = "Sweet Scent"
    description = "Use Sweet Scent for guaranteed encounters (needs party Pokémon with move)"

    def __init__(self, bot: GameBot, sweet_scent_slot: int = 0,
                 move_index: int = 0):
        super().__init__(bot)
        self._pokemon_slot = sweet_scent_slot
        self._move_index = move_index
        self._phase = "open_menu"
        self._wait_frames = 0

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "open_menu":
            # Open Start menu
            self.bot.press_button(GBAButton.START)
            self.bot.advance_frames(20)
            self._phase = "select_pokemon"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Opening menu...")

        elif self._phase == "select_pokemon":
            # Navigate to Pokémon option (first option in menu)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)

            # Select the Pokémon with Sweet Scent
            for _ in range(self._pokemon_slot):
                self.bot.press_button(GBAButton.DOWN)
                self.bot.advance_frames(5)

            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(15)
            self._phase = "use_sweet_scent"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Selecting Pokémon...")

        elif self._phase == "use_sweet_scent":
            # Select Sweet Scent from the field move menu
            # Sweet Scent appears as a field move option
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            # Navigate to Sweet Scent in the submenu
            for _ in range(self._move_index):
                self.bot.press_button(GBAButton.DOWN)
                self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            self._phase = "wait_battle"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Using Sweet Scent...")

        elif self._phase == "wait_battle":
            self.bot.advance_frames(5)
            self._wait_frames += 1

            if self.bot.is_in_battle():
                self._phase = "check_shiny"
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Battle triggered!")

            if self._wait_frames > 120:
                # Sweet Scent failed (maybe indoors or no encounters here)
                self._phase = "open_menu"
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Sweet Scent failed, retrying...")

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Waiting for encounter...")

        elif self._phase == "check_shiny":
            self.bot.advance_frames(60)
            self.encounters += 1

            enemy = self.bot._read_enemy_lead()
            if enemy.is_shiny:
                self.shinies_found += 1
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY via Sweet Scent! ({self.encounters} enc)"
                )

            self.bot.run_from_battle()
            self._phase = "open_menu"
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Sweet Scent #{self.encounters} - not shiny"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Breeding / Egg Hatch Mode ──────────────────────────────────────────────

class BreedingMode(BotMode):
    """
    Automated egg hatching loop for shiny breeding.

    Ported from pokebot-gen3's daycare.py.
    Walks back and forth to hatch eggs, checks shininess on hatch,
    and picks up new eggs from the daycare man.

    Requires: Two compatible Pokémon in the daycare, player on
    the daycare route (Route 117 in RSE, Four Island in FRLG).
    """

    name = "Breeding"
    description = "Hatch eggs from daycare for shiny breeding"

    # Fire Red daycare data offset in save block 1
    DAYCARE_OFFSET_FRLG = 0x2F80
    # Egg pending flag address (event flag)
    PENDING_EGG_FLAG = "PENDING_DAYCARE_EGG"

    def __init__(self, bot: GameBot, use_fast_hatch: bool = False):
        super().__init__(bot)
        self._phase = "walk"
        self._walk_steps = 0
        self._eggs_hatched = 0
        self._use_fast_hatch = use_fast_hatch
        self._direction = True  # True=right, False=left
        self._hatch_check_interval = 50  # Check every N steps

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "walk":
            # Walk back and forth to accumulate steps for egg hatching
            direction = GBAButton.RIGHT if self._direction else GBAButton.LEFT
            self.bot.press_button(direction, hold_frames=16)
            self.bot.advance_frames(2)
            self._walk_steps += 1

            # Reverse direction every 20 steps
            if self._walk_steps % 20 == 0:
                self._direction = not self._direction

            # Check for egg hatch periodically
            if self._walk_steps % self._hatch_check_interval == 0:
                state = self.bot.get_game_state()
                if state == GameState.EGG_HATCH:
                    self._phase = "hatching"
                    return ModeResult(status=ModeStatus.RUNNING,
                                      message="Egg is hatching!")

            # Check for random encounters (dismiss them)
            if self.bot.is_in_battle():
                self.bot.run_from_battle()
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Ran from wild encounter")

            return ModeResult(
                encounters_this_session=self._eggs_hatched,
                status=ModeStatus.RUNNING,
                message=f"Walking to hatch... (steps: {self._walk_steps})"
            )

        elif self._phase == "hatching":
            # Mash A through the hatch animation
            for _ in range(120):
                self.bot.press_button(GBAButton.A, hold_frames=2)
                self.bot.advance_frames(2)

            self._eggs_hatched += 1
            self.encounters += 1
            self._phase = "check_hatch"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Egg hatched! Checking...")

        elif self._phase == "check_hatch":
            # Check the most recently hatched Pokémon in party
            # It will be the last non-egg slot
            try:
                party_count = struct.unpack(
                    "<I", self.bot.read_bytes(0x02024280, 4))[0]
                if party_count > 0:
                    # Read the last party slot (most recently hatched)
                    last_slot = party_count - 1
                    addr = 0x02024284 + (last_slot * 100)
                    raw = self.bot.read_bytes(addr, 100)
                    pv = struct.unpack("<I", raw[0:4])[0]
                    ot = struct.unpack("<I", raw[4:8])[0]
                    tid = ot & 0xFFFF
                    sid = (ot >> 16) & 0xFFFF
                    is_shiny = (tid ^ sid ^ (pv >> 16) ^ (pv & 0xFFFF)) < 8

                    if is_shiny:
                        self.shinies_found += 1
                        return ModeResult(
                            is_shiny=True,
                            encounters_this_session=self._eggs_hatched,
                            status=ModeStatus.RUNNING,
                            message=f"SHINY HATCH after {self._eggs_hatched} eggs!"
                        )
            except Exception as exc:
                logger.error("Failed to check hatched Pokémon: %s", exc)

            # Check if party is full – need to deposit Pokémon
            try:
                party_count = struct.unpack(
                    "<I", self.bot.read_bytes(0x02024280, 4))[0]
                if party_count >= 6:
                    self._phase = "deposit"
                    return ModeResult(status=ModeStatus.RUNNING,
                                      message="Party full, depositing...")
            except Exception:
                pass

            self._phase = "walk"
            return ModeResult(
                encounters_this_session=self._eggs_hatched,
                status=ModeStatus.RUNNING,
                message=f"Egg #{self._eggs_hatched} - not shiny, continuing..."
            )

        elif self._phase == "deposit":
            # TODO: Implement PC deposit automation
            # For now, just continue walking (user should manage PC manually)
            logger.warning("Party full – manual PC management needed")
            self._phase = "walk"
            return ModeResult(
                status=ModeStatus.RUNNING,
                message="Party full – deposit non-shiny Pokémon manually"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Level Evolution Mode ────────────────────────────────────────────────────

class LevelEvolutionMode(BotMode):
    """
    Level a Pokémon to its evolution threshold using Rare Candies
    or by battling wild Pokémon.

    Reads the party Pokémon's level and applies Rare Candies from
    the bag until the target level is reached, then allows evolution.
    """

    name = "Level Evolution"
    description = "Level Pokémon to evolution threshold"

    def __init__(self, bot: GameBot, party_slot: int = 0,
                 target_level: int = 0, use_rare_candy: bool = True):
        super().__init__(bot)
        self._party_slot = party_slot
        self._target_level = target_level
        self._use_rare_candy = use_rare_candy
        self._phase = "check_level"
        self._wait_frames = 0

    def _read_party_level(self) -> int:
        """Read the level of the Pokémon in the target party slot."""
        try:
            # Party Pokémon battle stats start at offset 84 within the
            # 100-byte party structure. Level is at offset 84 (u8).
            addr = 0x02024284 + (self._party_slot * 100) + 84
            raw = self.bot.read_bytes(addr, 2)
            return raw[0]  # Level byte
        except Exception:
            return 0

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "check_level":
            current_level = self._read_party_level()
            if current_level >= self._target_level:
                self._phase = "done"
                return ModeResult(
                    status=ModeStatus.COMPLETED,
                    message=f"Pokémon reached level {current_level}!"
                )

            if self._use_rare_candy:
                self._phase = "use_candy"
            else:
                self._phase = "battle"

            return ModeResult(
                status=ModeStatus.RUNNING,
                message=f"Level {current_level}/{self._target_level}"
            )

        elif self._phase == "use_candy":
            # Open bag, navigate to Rare Candy, use on target Pokémon
            # Open Start menu
            self.bot.press_button(GBAButton.START)
            self.bot.advance_frames(20)
            # Select Bag (second option)
            self.bot.press_button(GBAButton.DOWN)
            self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)

            # Navigate to Rare Candy in items pocket
            # This is simplified – in practice we'd need to scroll to find it
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            # Select "Use"
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)

            # Select target Pokémon
            for _ in range(self._party_slot):
                self.bot.press_button(GBAButton.DOWN)
                self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(60)

            # Mash through level up messages
            for _ in range(20):
                self.bot.press_button(GBAButton.A, hold_frames=2)
                self.bot.advance_frames(5)

            # Check if evolution is happening
            state = self.bot.get_game_state()
            if state == GameState.EVOLUTION:
                self._phase = "evolving"
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Pokémon is evolving!")

            # Close menus and check level again
            self.bot.press_button(GBAButton.B)
            self.bot.advance_frames(10)
            self.bot.press_button(GBAButton.B)
            self.bot.advance_frames(10)
            self.bot.press_button(GBAButton.B)
            self.bot.advance_frames(10)

            self._phase = "check_level"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Used Rare Candy")

        elif self._phase == "evolving":
            # Let evolution happen – mash A
            for _ in range(180):
                self.bot.press_button(GBAButton.A, hold_frames=2)
                self.bot.advance_frames(2)

            self._phase = "check_level"
            self.status = ModeStatus.COMPLETED
            return ModeResult(
                status=ModeStatus.COMPLETED,
                message="Evolution complete!"
            )

        elif self._phase == "battle":
            # Battle wild Pokémon for XP
            # Walk to trigger encounter
            direction = GBAButton.UP if self._wait_frames % 2 == 0 else GBAButton.DOWN
            self.bot.press_button(direction, hold_frames=16)
            self.bot.advance_frames(4)
            self._wait_frames += 1

            if self.bot.is_in_battle():
                # Use first move to KO
                self.bot.execute_battle_command(move_index=0)
                self.bot.advance_frames(120)

                # Wait for battle to end
                for _ in range(60):
                    self.bot.press_button(GBAButton.A, hold_frames=2)
                    self.bot.advance_frames(5)

                # Check for evolution
                state = self.bot.get_game_state()
                if state == GameState.EVOLUTION:
                    self._phase = "evolving"
                    return ModeResult(status=ModeStatus.RUNNING,
                                      message="Pokémon is evolving!")

                self._phase = "check_level"
                self._wait_frames = 0

            return ModeResult(status=ModeStatus.RUNNING,
                              message=f"Battling for XP... (step {self._wait_frames})")

        elif self._phase == "done":
            return ModeResult(status=ModeStatus.COMPLETED,
                              message="Target level reached!")

        return ModeResult(status=ModeStatus.RUNNING)


# ── Stone Evolution Mode ────────────────────────────────────────────────────

class StoneEvolutionMode(BotMode):
    """
    Apply an evolution stone from the bag to a party Pokémon.

    Opens the bag, navigates to the stone, and uses it on the
    target party slot.
    """

    name = "Stone Evolution"
    description = "Apply evolution stone to a Pokémon"

    def __init__(self, bot: GameBot, party_slot: int = 0,
                 stone_name: str = ""):
        super().__init__(bot)
        self._party_slot = party_slot
        self._stone_name = stone_name
        self._phase = "open_bag"

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "open_bag":
            self.bot.press_button(GBAButton.START)
            self.bot.advance_frames(20)
            # Navigate to Bag
            self.bot.press_button(GBAButton.DOWN)
            self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(20)
            self._phase = "find_stone"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Opening bag...")

        elif self._phase == "find_stone":
            # Navigate to the stone in the items pocket
            # Simplified: press A on first item (assumes stone is there
            # via cheat manager pre-population)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            # Select "Use"
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(10)
            self._phase = "select_pokemon"
            return ModeResult(status=ModeStatus.RUNNING,
                              message=f"Found {self._stone_name}...")

        elif self._phase == "select_pokemon":
            for _ in range(self._party_slot):
                self.bot.press_button(GBAButton.DOWN)
                self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            # Confirm
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(60)
            self._phase = "evolving"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Applying stone...")

        elif self._phase == "evolving":
            # Mash A through evolution animation
            for _ in range(180):
                self.bot.press_button(GBAButton.A, hold_frames=2)
                self.bot.advance_frames(2)

            self.status = ModeStatus.COMPLETED
            return ModeResult(
                status=ModeStatus.COMPLETED,
                message=f"Stone evolution complete!"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Trade Evolution Coordinator ─────────────────────────────────────────────

class TradeEvolutionMode(BotMode):
    """
    Coordinate trade evolutions between two emulator instances.

    This mode manages the link cable trade process between two
    GameBot instances to evolve trade-evolution Pokémon.

    NOTE: This requires two running instances and is orchestrated
    by the main app, not run independently.
    """

    name = "Trade Evolution"
    description = "Trade Pokémon between instances for trade evolutions"

    def __init__(self, bot: GameBot, partner_bot: Optional[GameBot] = None):
        super().__init__(bot)
        self.partner_bot = partner_bot
        self._phase = "setup"
        self._trade_item: Optional[str] = None

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self.partner_bot is None:
            return ModeResult(
                status=ModeStatus.ERROR,
                message="Trade evolution requires two instances"
            )

        # Trade evolution is complex and requires coordinating two
        # emulator instances through the link cable trade menu.
        # This is a framework for the trade coordinator.

        if self._phase == "setup":
            return ModeResult(
                status=ModeStatus.RUNNING,
                message="Trade evolution: Setup phase (requires manual positioning)"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Safari Zone Mode ────────────────────────────────────────────────────────

class SafariZoneMode(BotMode):
    """
    Hunt for shinies in the Safari Zone.

    Uses a strategy of throwing Safari Balls at every encounter
    since we can't weaken Pokémon in the Safari Zone.
    """

    name = "Safari Zone"
    description = "Hunt shinies in the Safari Zone"

    def __init__(self, bot: GameBot):
        super().__init__(bot)
        self._phase = "walk"
        self._step_count = 0

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "walk":
            direction = GBAButton.UP if self._step_count % 2 == 0 else GBAButton.DOWN
            self.bot.press_button(direction, hold_frames=16)
            self.bot.advance_frames(4)
            self._step_count += 1

            if self.bot.is_in_battle():
                self._phase = "check_shiny"

            return ModeResult(status=ModeStatus.RUNNING,
                              message=f"Safari walk (step {self._step_count})")

        elif self._phase == "check_shiny":
            self.bot.advance_frames(60)
            self.encounters += 1

            enemy = self.bot._read_enemy_lead()
            if enemy.is_shiny:
                self.shinies_found += 1
                # Throw Safari Ball (first option)
                self.bot.press_button(GBAButton.A)
                self.bot.advance_frames(180)
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY in Safari Zone! Throwing ball..."
                )

            # Run from non-shiny (select Run option)
            self.bot.press_button(GBAButton.DOWN)
            self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.RIGHT)
            self.bot.advance_frames(5)
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(60)

            self._phase = "walk"
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Safari #{self.encounters} - not shiny"
            )

        return ModeResult(status=ModeStatus.RUNNING)


# ── Rock Smash Mode ────────────────────────────────────────────────────────

class RockSmashMode(BotMode):
    """
    Smash rocks for encounters (Geodude, Shuckle, etc.).

    Ported from pokebot-gen3's rock_smash.py concept.
    Player must be facing a smashable rock.
    """

    name = "Rock Smash"
    description = "Smash rocks for encounters"

    def __init__(self, bot: GameBot):
        super().__init__(bot)
        self._phase = "smash"
        self._wait_frames = 0

    def step(self) -> ModeResult:
        if self.status != ModeStatus.RUNNING:
            return ModeResult(status=self.status)

        if self._phase == "smash":
            # Press A to interact with rock
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(30)
            # Confirm Rock Smash use
            self.bot.press_button(GBAButton.A)
            self.bot.advance_frames(60)
            self._phase = "check_result"
            self._wait_frames = 0
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Smashing rock...")

        elif self._phase == "check_result":
            self._wait_frames += 1

            if self.bot.is_in_battle():
                self._phase = "check_shiny"
                return ModeResult(status=ModeStatus.RUNNING,
                                  message="Encounter from rock!")

            # No encounter – walk to next rock or wait for respawn
            if self._wait_frames > 30:
                self._phase = "reposition"
                self._wait_frames = 0

            return ModeResult(status=ModeStatus.RUNNING,
                              message="Checking for encounter...")

        elif self._phase == "check_shiny":
            self.bot.advance_frames(60)
            self.encounters += 1

            enemy = self.bot._read_enemy_lead()
            if enemy.is_shiny:
                self.shinies_found += 1
                return ModeResult(
                    encounter=enemy, is_shiny=True,
                    encounters_this_session=self.encounters,
                    status=ModeStatus.RUNNING,
                    message=f"SHINY from Rock Smash!"
                )

            self.bot.run_from_battle()
            self._phase = "reposition"
            return ModeResult(
                encounter=enemy, is_shiny=False,
                encounters_this_session=self.encounters,
                status=ModeStatus.RUNNING,
                message=f"Rock Smash #{self.encounters} - not shiny"
            )

        elif self._phase == "reposition":
            # Walk away and back to respawn the rock
            self.bot.press_button(GBAButton.DOWN, hold_frames=16)
            self.bot.advance_frames(4)
            self.bot.press_button(GBAButton.UP, hold_frames=16)
            self.bot.advance_frames(4)
            self._phase = "smash"
            return ModeResult(status=ModeStatus.RUNNING,
                              message="Repositioning for next rock...")

        return ModeResult(status=ModeStatus.RUNNING)


# ── Mode Registry ──────────────────────────────────────────────────────────

ALL_MODES = {
    "encounter_farm": EncounterFarmMode,
    "starter_reset": StarterResetMode,
    "static_encounter": StaticEncounterMode,
    "fishing": FishingMode,
    "sweet_scent": SweetScentMode,
    "breeding": BreedingMode,
    "level_evolution": LevelEvolutionMode,
    "stone_evolution": StoneEvolutionMode,
    "trade_evolution": TradeEvolutionMode,
    "safari_zone": SafariZoneMode,
    "rock_smash": RockSmashMode,
}

MODE_DESCRIPTIONS = {
    "encounter_farm": "Walk in grass/cave for wild encounters",
    "starter_reset": "Soft-reset for shiny starters",
    "static_encounter": "Soft-reset for legendaries",
    "fishing": "Fish for shiny water Pokémon",
    "sweet_scent": "Use Sweet Scent for guaranteed encounters",
    "breeding": "Hatch eggs from daycare",
    "level_evolution": "Level Pokémon to evolution threshold",
    "stone_evolution": "Apply evolution stones",
    "trade_evolution": "Trade between instances for evolution",
    "safari_zone": "Hunt shinies in Safari Zone",
    "rock_smash": "Smash rocks for encounters",
}
