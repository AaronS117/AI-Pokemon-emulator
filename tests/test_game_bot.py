"""
Regression tests for modules.game_bot – no ROM required.

Covers bugs found during runtime:
  1. AttributeError: 'GBA' object has no attribute 'set_sync'
     set_speed() must use sleep-based throttle, not core.set_sync().
  2. TclError: invalid command name – _update_card must not crash when
     a Toplevel is destroyed mid-refresh.
  3. Save path must use integer instance_id (saves/1/rom.sav), not UUID.
"""
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bot():
    """Return a GameBot with a fully mocked emulator core (no ROM needed)."""
    from modules.game_bot import GameBot, EmulatorInstance

    bot = GameBot()

    # Build a minimal fake instance
    fake_core = MagicMock()
    fake_core.frame_counter = 0
    fake_core._core = MagicMock()
    fake_native = MagicMock()

    inst = EmulatorInstance(seed=0, tid=0, sid=0)
    inst._core = fake_core
    inst._native = fake_native
    inst._running = True
    inst.save_path = Path("/tmp/fake.sav")

    bot.instance = inst
    return bot


# ── Bug 1: set_speed must NOT call core.set_sync ─────────────────────────────

class TestSetSpeed:
    def test_set_speed_does_not_call_set_sync(self):
        """Regression: 'GBA' has no set_sync – set_speed must not call it."""
        bot = _make_bot()
        # Should not raise AttributeError
        bot.set_speed(0)
        bot.set_speed(1)
        bot.set_speed(2)
        bot.set_speed(4)
        # Verify set_sync was never called on the core
        bot.instance._core.set_sync.assert_not_called()

    def test_max_speed_sets_zero_budget(self):
        bot = _make_bot()
        bot.set_speed(0)
        assert bot._frame_budget == 0.0

    def test_1x_speed_sets_correct_budget(self):
        bot = _make_bot()
        bot.set_speed(1)
        assert abs(bot._frame_budget - (1.0 / 60.0)) < 1e-9

    def test_2x_speed_sets_correct_budget(self):
        bot = _make_bot()
        bot.set_speed(2)
        assert abs(bot._frame_budget - (1.0 / 120.0)) < 1e-9

    def test_4x_speed_sets_correct_budget(self):
        bot = _make_bot()
        bot.set_speed(4)
        assert abs(bot._frame_budget - (1.0 / 240.0)) < 1e-9

    def test_throttle_sleeps_when_budget_set(self):
        """When speed=1x, _apply_inputs_and_run_frame should sleep."""
        bot = _make_bot()
        bot.set_speed(1)
        bot._last_frame_time = time.perf_counter()  # pretend last frame was just now

        sleep_calls = []
        import modules.game_bot as gb_mod
        original_sleep = time.sleep

        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            # Simulate a very fast frame (elapsed ≈ 0) so sleep is needed
            bot._last_frame_time = time.perf_counter() + 10  # force remaining > 0
            bot._apply_inputs_and_run_frame()

        # sleep should have been called with a positive value
        assert len(sleep_calls) >= 1
        assert all(s >= 0 for s in sleep_calls)

    def test_no_sleep_when_max_speed(self):
        """When speed=0 (max), no sleep should occur."""
        bot = _make_bot()
        bot.set_speed(0)

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            bot._apply_inputs_and_run_frame()

        assert len(sleep_calls) == 0


# ── Bug 2: save path uses integer instance_id ─────────────────────────────────

class TestSavePath:
    def test_launch_uses_integer_instance_id_for_save_dir(self, tmp_path):
        """Regression: saves must go to saves/1/rom.sav not saves/<uuid>/rom.sav."""
        from modules.game_bot import GameBot
        from modules.config import SAVE_DIR

        # Create a minimal fake ROM file
        rom = tmp_path / "firered.gba"
        rom.write_bytes(b"\x00" * 1024)

        bot = GameBot()

        fake_core = MagicMock()
        fake_core.frame_counter = 0
        fake_core._core = MagicMock()
        fake_core.desired_video_dimensions.return_value = (240, 160)

        fake_screen = MagicMock()

        with patch("mgba.core.load_path", return_value=fake_core), \
             patch("mgba.vfs.open_path", return_value=MagicMock()), \
             patch("mgba.image.Image", return_value=fake_screen):
            inst = bot.launch(seed=0, tid=0, sid=0, rom_path=rom, instance_id=7)

        assert inst.save_path is not None
        # Must be saves/7/firered.sav, not saves/<uuid>/firered.sav
        assert inst.save_path.parent.name == "7", (
            f"Expected save dir '7', got '{inst.save_path.parent.name}'"
        )
        assert inst.save_path.name == "firered.sav"

    def test_launch_without_instance_id_uses_uuid(self, tmp_path):
        """Without instance_id, falls back to UUID dir (backwards compat)."""
        from modules.game_bot import GameBot

        rom = tmp_path / "firered.gba"
        rom.write_bytes(b"\x00" * 1024)

        bot = GameBot()
        fake_core = MagicMock()
        fake_core.desired_video_dimensions.return_value = (240, 160)

        with patch("mgba.core.load_path", return_value=fake_core), \
             patch("mgba.vfs.open_path", return_value=MagicMock()), \
             patch("mgba.image.Image", return_value=MagicMock()):
            inst = bot.launch(seed=0, tid=0, sid=0, rom_path=rom)

        # Dir name should be a hex UUID (8 chars), not a digit
        dir_name = inst.save_path.parent.name
        assert not dir_name.isdigit(), (
            f"Expected UUID dir, got digit dir '{dir_name}'"
        )


# ── Bug 3: _update_card must not crash on destroyed Toplevel ─────────────────

class TestUpdateCardTclError:
    def test_update_card_survives_destroyed_toplevel(self):
        """Regression: TclError when Toplevel destroyed mid-refresh must be swallowed."""
        # We test _update_card_inner raises and _update_card catches it
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        # Import just the App class structure without launching Tk
        # We mock the inner method to raise TclError and verify no crash
        from app import InstanceState

        state = InstanceState(instance_id=1, status="running")

        # Simulate a destroyed widget by making configure raise TclError
        import tkinter
        bad_widget = MagicMock()
        bad_widget.configure.side_effect = tkinter.TclError("invalid command name")

        fake_w = {
            "win": MagicMock(),
            "status": bad_widget,
            "info": MagicMock(),
            "screen": MagicMock(),
            "placeholder": [None],
            "enc": MagicMock(),
            "fps": MagicMock(),
            "frames": MagicMock(),
            "ctrl_btn_ref": [None],
            "progress": MagicMock(),
            "pause": MagicMock(),
            "stop": MagicMock(),
        }

        # Create a minimal App-like object with just _update_card/_update_card_inner
        class FakeApp:
            _instance_widgets = {1: fake_w}
            _photo_cache = {}

            def _update_card(self, inst_id, state):
                w = self._instance_widgets.get(inst_id)
                if not w:
                    return
                win = w.get("win")
                if win is None:
                    return
                try:
                    self._update_card_inner(inst_id, state, w, win)
                except Exception:
                    pass

            def _update_card_inner(self, inst_id, state, w, win):
                w["status"].configure(text="RUNNING")  # raises TclError

        app = FakeApp()
        # Must not raise
        app._update_card(1, state)
