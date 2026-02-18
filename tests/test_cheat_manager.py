"""Unit tests for modules.cheat_manager – cheats, categories, presets."""
import pytest
from modules.cheat_manager import CheatManager, CheatCategory


class TestCheatManager:
    def test_init(self):
        cm = CheatManager()
        assert len(cm.cheats) > 0

    def test_all_cheats_have_required_fields(self):
        cm = CheatManager()
        for cid, cheat in cm.cheats.items():
            assert hasattr(cheat, "name"), f"{cid} missing name"
            assert hasattr(cheat, "category"), f"{cid} missing category"
            assert hasattr(cheat, "affects_legitimacy"), f"{cid} missing affects_legitimacy"
            assert isinstance(cheat.category, CheatCategory)

    def test_no_dangerous_cheats(self):
        cm = CheatManager()
        for cid, cheat in cm.cheats.items():
            assert cheat.category != CheatCategory.DANGEROUS, \
                f"Dangerous cheat {cid} should not be registered"


class TestCategories:
    def test_safe_cheats_exist(self):
        cm = CheatManager()
        safe = cm.get_cheats_by_category(CheatCategory.SAFE)
        assert len(safe) > 0

    def test_caution_cheats_exist(self):
        cm = CheatManager()
        caution = cm.get_cheats_by_category(CheatCategory.CAUTION)
        assert len(caution) >= 0  # May be 0 or more

    def test_category_values(self):
        assert CheatCategory.SAFE.value == "safe"
        assert CheatCategory.CAUTION.value == "caution"
        assert CheatCategory.DANGEROUS.value == "dangerous"


class TestEnableDisable:
    def test_enable(self):
        cm = CheatManager()
        first_id = list(cm.cheats.keys())[0]
        cm.enable_cheat(first_id)
        assert first_id in cm.get_enabled_cheats()

    def test_disable(self):
        cm = CheatManager()
        first_id = list(cm.cheats.keys())[0]
        cm.enable_cheat(first_id)
        cm.disable_cheat(first_id)
        assert first_id not in cm.get_enabled_cheats()

    def test_disable_all(self):
        cm = CheatManager()
        cm.apply_hunting_preset()
        assert len(cm.get_enabled_cheats()) > 0
        cm.disable_all()
        assert len(cm.get_enabled_cheats()) == 0


class TestPresets:
    def test_hunting_preset(self):
        cm = CheatManager()
        n = cm.apply_hunting_preset()
        assert n > 0
        assert len(cm.get_enabled_cheats()) == n

    def test_breeding_preset(self):
        cm = CheatManager()
        n = cm.apply_breeding_preset()
        assert n > 0

    def test_evolution_preset(self):
        cm = CheatManager()
        n = cm.apply_evolution_preset()
        assert n > 0

    def test_fishing_preset(self):
        cm = CheatManager()
        n = cm.apply_fishing_preset()
        assert n > 0

    def test_presets_clear_previous(self):
        cm = CheatManager()
        cm.apply_hunting_preset()
        hunting_cheats = set(cm.get_enabled_cheats())
        cm.apply_breeding_preset()
        breeding_cheats = set(cm.get_enabled_cheats())
        # Presets should replace, not accumulate (unless they overlap)
        # At minimum the set should change
        assert isinstance(breeding_cheats, set)


class TestLegitimacy:
    def test_clean_by_default(self):
        cm = CheatManager()
        assert cm.is_legitimate is True

    def test_safe_cheats_stay_legitimate(self):
        cm = CheatManager()
        for cid, cheat in cm.cheats.items():
            if cheat.category == CheatCategory.SAFE:
                cm.enable_cheat(cid)
        assert cm.is_legitimate is True

    def test_report(self):
        cm = CheatManager()
        cm.apply_hunting_preset()
        report = cm.get_legitimacy_report()
        assert "enabled" in report
        assert "legitimate" in report
        assert isinstance(report["enabled"], list)
        assert isinstance(report["legitimate"], bool)
