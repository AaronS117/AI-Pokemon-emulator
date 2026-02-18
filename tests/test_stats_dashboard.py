"""Unit tests for modules.stats_dashboard – tracking, probability, export."""
import json
import time
import pytest
from modules.stats_dashboard import (
    StatsTracker, SessionStats, EncounterRecord,
    shiny_probability, export_csv, export_json,
)


class TestStatsTracker:
    def test_initial_state(self):
        t = StatsTracker()
        assert t.session.encounters == 0
        assert t.session.shinies == 0
        assert t.session.start_time > 0

    def test_record_encounter(self):
        t = StatsTracker()
        t.record_encounter(species_id=25, is_shiny=False, area="route1")
        assert t.session.encounters == 1
        assert t.session.shinies == 0
        assert t.session.species_seen[25] == 1
        assert t.session.area_encounters["route1"] == 1

    def test_record_shiny(self):
        t = StatsTracker()
        t.record_encounter(species_id=25, is_shiny=True)
        assert t.session.shinies == 1

    def test_multiple_encounters(self):
        t = StatsTracker()
        for i in range(50):
            t.record_encounter(species_id=25, is_shiny=False)
        t.record_encounter(species_id=25, is_shiny=True)
        assert t.session.encounters == 51
        assert t.session.shinies == 1
        assert t.session.species_seen[25] == 51

    def test_species_tracking(self):
        t = StatsTracker()
        t.record_encounter(species_id=25, is_shiny=False)
        t.record_encounter(species_id=25, is_shiny=False)
        t.record_encounter(species_id=1, is_shiny=False)
        assert t.session.species_seen[25] == 2
        assert t.session.species_seen[1] == 1

    def test_area_tracking(self):
        t = StatsTracker()
        t.record_encounter(species_id=1, is_shiny=False, area="route1")
        t.record_encounter(species_id=1, is_shiny=False, area="route2")
        t.record_encounter(species_id=1, is_shiny=False, area="route1")
        assert t.session.area_encounters["route1"] == 2
        assert t.session.area_encounters["route2"] == 1

    def test_mode_tracking(self):
        t = StatsTracker()
        t.record_encounter(species_id=1, is_shiny=False, bot_mode="fishing")
        t.record_encounter(species_id=1, is_shiny=False, bot_mode="fishing")
        t.record_encounter(species_id=1, is_shiny=False, bot_mode="encounter_farm")
        assert t.session.mode_encounters["fishing"] == 2
        assert t.session.mode_encounters["encounter_farm"] == 1

    def test_encounter_log(self):
        t = StatsTracker()
        t.record_encounter(species_id=25, is_shiny=False, area="r1")
        assert len(t.session.encounter_log) == 1
        rec = t.session.encounter_log[0]
        assert rec.species_id == 25
        assert rec.is_shiny is False
        assert rec.area == "r1"

    def test_get_summary(self):
        t = StatsTracker()
        for i in range(10):
            t.record_encounter(species_id=25, is_shiny=(i == 5))
        s = t.get_summary()
        assert s["total_encounters"] == 10
        assert s["total_shinies"] == 1
        assert "1/10" in s["shiny_rate"]

    def test_reset(self):
        t = StatsTracker()
        t.record_encounter(species_id=25, is_shiny=False)
        t.reset()
        assert t.session.encounters == 0
        assert t.session.shinies == 0
        assert len(t.session.encounter_log) == 0


class TestSessionStats:
    def test_shiny_rate_no_encounters(self):
        s = SessionStats()
        assert s.shiny_rate == 0.0
        assert s.shiny_rate_display == "N/A"

    def test_shiny_rate_no_shinies(self):
        s = SessionStats(encounters=100, shinies=0)
        assert s.shiny_rate == 0.0
        assert s.shiny_rate_display == "0/100"

    def test_shiny_rate_with_shinies(self):
        s = SessionStats(encounters=8192, shinies=1)
        assert s.shiny_rate == pytest.approx(1 / 8192)
        assert "1/8,192" in s.shiny_rate_display

    def test_luck_factor(self):
        s = SessionStats(encounters=8192, shinies=2)
        assert s.luck_factor == pytest.approx(2.0)

    def test_most_common_species(self):
        s = SessionStats()
        s.species_seen[25] = 50
        s.species_seen[1] = 30
        s.species_seen[4] = 20
        top = s.most_common_species
        assert top[0] == (25, 50)
        assert top[1] == (1, 30)
        assert top[2] == (4, 20)


class TestShinyProbability:
    def test_zero_encounters(self):
        p = shiny_probability(0)
        assert p["probability"] == 0.0
        assert p["expected_shinies"] == 0.0

    def test_one_encounter(self):
        p = shiny_probability(1)
        assert p["probability"] == pytest.approx(100 / 8192, abs=0.01)

    def test_8192_encounters(self):
        p = shiny_probability(8192)
        # ~63.2% chance of at least one shiny
        assert 63.0 < p["probability"] < 64.0

    def test_milestones(self):
        p = shiny_probability(5000)
        assert p["encounters_for_50pct"] > 0
        assert p["encounters_for_90pct"] > p["encounters_for_50pct"]
        assert p["encounters_for_99pct"] > p["encounters_for_90pct"]

    def test_50pct_is_about_5678(self):
        p = shiny_probability(0)
        # ln(0.5) / ln(1 - 1/8192) ≈ 5678
        assert 5670 < p["encounters_for_50pct"] < 5690

    def test_custom_rate(self):
        p = shiny_probability(100, rate=0.5)
        assert p["probability"] > 99.9


class TestExport:
    def test_csv_export(self, tmp_path):
        t = StatsTracker()
        for i in range(5):
            t.record_encounter(species_id=25, is_shiny=(i == 2), area="r1")
        path = export_csv(t, tmp_path / "test.csv")
        assert path.exists()
        content = path.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 6  # header + 5 rows
        assert "species_id" in lines[0]

    def test_json_export(self, tmp_path):
        t = StatsTracker()
        for i in range(3):
            t.record_encounter(species_id=1, is_shiny=False)
        path = export_json(t, tmp_path / "test.json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["session"]["total_encounters"] == 3
        assert len(data["encounters"]) == 3
