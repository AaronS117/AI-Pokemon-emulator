"""Unit tests for modules.database – CRUD, living dex, evolution queue, cheat log."""
import sqlite3
import pytest
from modules.database import (
    init_db, log_shiny, total_shinies, recent_shinies,
    get_living_dex_progress, mark_pokemon_owned, is_save_legitimate,
    log_cheat, get_cheat_history,
    add_to_evolution_queue, get_evolution_queue, complete_evolution,
    update_material, get_material_inventory,
    init_living_dex,
)


@pytest.fixture
def db(tmp_path):
    """Create a fresh database in a temp directory and return its path."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_living_dex(db_path)
    return db_path


class TestInitDB:
    def test_creates_file(self, tmp_path):
        db_path = tmp_path / "new.db"
        init_db(db_path)
        assert db_path.exists()

    def test_creates_tables(self, db):
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "shiny_log" in tables
        assert "living_dex" in tables
        assert "evolution_queue" in tables
        assert "evolution_materials" in tables
        assert "cheat_log" in tables

    def test_living_dex_populated(self, db):
        prog = get_living_dex_progress(db)
        assert prog["total"] == 386
        assert prog["owned"] == 0

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "idem.db"
        init_db(db_path)
        init_db(db_path)  # Should not error
        init_living_dex(db_path)
        prog = get_living_dex_progress(db_path)
        assert prog["total"] == 386


class TestShinyLog:
    def test_log_and_count(self, db):
        log_shiny(
            species_id=25, personality_value=0, tid=12345, sid=54321,
            seed=0x1234, encounter_count=1, instance_id="abc123",
            save_path="/tmp/save.sav", db_path=db,
        )
        assert total_shinies(db) == 1

    def test_multiple_logs(self, db):
        for i in range(5):
            log_shiny(
                species_id=i + 1, personality_value=i, tid=i, sid=i,
                seed=i, encounter_count=i, instance_id=f"inst{i}",
                save_path=f"/tmp/save{i}.sav", db_path=db,
            )
        assert total_shinies(db) == 5

    def test_recent_shinies(self, db):
        for i in range(10):
            log_shiny(
                species_id=i + 1, personality_value=i, tid=i, sid=i,
                seed=i, encounter_count=i, instance_id=f"inst{i}",
                save_path=f"/tmp/save{i}.sav", db_path=db,
            )
        recent = recent_shinies(limit=5, db_path=db)
        assert len(recent) == 5


class TestLivingDex:
    def test_initial_progress(self, db):
        prog = get_living_dex_progress(db)
        assert prog["owned"] == 0
        assert prog["total"] == 386

    def test_mark_owned(self, db):
        mark_pokemon_owned(25, method="wild_catch", location="Route 1", db_path=db)
        prog = get_living_dex_progress(db)
        assert prog["owned"] == 1

    def test_mark_owned_idempotent(self, db):
        mark_pokemon_owned(25, db_path=db)
        mark_pokemon_owned(25, db_path=db)  # Should not double-count
        prog = get_living_dex_progress(db)
        assert prog["owned"] == 1

    def test_mark_multiple(self, db):
        for pid in [1, 2, 3, 25, 150]:
            mark_pokemon_owned(pid, db_path=db)
        prog = get_living_dex_progress(db)
        assert prog["owned"] == 5


class TestCheatLog:
    def test_log_cheat(self, db):
        log_cheat("Max Money", "max_money", "SAFE", db_path=db)
        history = get_cheat_history(db)
        assert len(history) >= 1

    def test_legitimacy_clean(self, db):
        log_cheat("Max Money", "max_money", "SAFE",
                   affects_legitimacy=False, db_path=db)
        assert is_save_legitimate(db) is True

    def test_legitimacy_affected(self, db):
        log_cheat("Bad Cheat", "bad", "CAUTION",
                   affects_legitimacy=True, db_path=db)
        assert is_save_legitimate(db) is False


class TestEvolutionQueue:
    def test_add_and_get(self, db):
        add_to_evolution_queue(
            source_id=25, target_id=26,
            method="stone", requirement="Thunder Stone",
            priority=1, db_path=db,
        )
        queue = get_evolution_queue(db_path=db)
        assert len(queue) >= 1
        task = queue[0]
        assert task["source_pokemon_id"] == 25

    def test_complete_task(self, db):
        add_to_evolution_queue(
            source_id=25, target_id=26,
            method="stone", db_path=db,
        )
        queue = get_evolution_queue(db_path=db)
        task_id = queue[0]["id"]
        complete_evolution(task_id, db_path=db)
        queue_after = get_evolution_queue(db_path=db)
        pending_ids = [t["id"] for t in queue_after]
        assert task_id not in pending_ids


class TestMaterials:
    def test_update_and_get(self, db):
        update_material("Thunder Stone", 3, db_path=db)
        inv = get_material_inventory(db)
        assert inv.get("Thunder Stone", 0) == 3

    def test_update_replaces(self, db):
        update_material("Fire Stone", 2, db_path=db)
        update_material("Fire Stone", 3, db_path=db)
        inv = get_material_inventory(db)
        assert inv.get("Fire Stone", 0) == 3
