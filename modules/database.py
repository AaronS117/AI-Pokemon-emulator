"""
database – SQLite persistence layer for shiny encounter logging
and living dex progress tracking.

Creates and manages ``shiny_log.db`` with read / write / query helpers.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional

from modules.config import DATABASE_PATH


# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shiny_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tid          INTEGER NOT NULL,
    sid          INTEGER NOT NULL,
    seed         INTEGER NOT NULL,
    species      TEXT    NOT NULL,
    instance_id  TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    save_path    TEXT    NOT NULL,
    game_version TEXT    NOT NULL DEFAULT 'firered',
    personality  INTEGER,
    ivs          TEXT,
    nature       TEXT,
    ability      TEXT,
    merged       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_species   ON shiny_log(species);
CREATE INDEX IF NOT EXISTS idx_seed      ON shiny_log(seed);
CREATE INDEX IF NOT EXISTS idx_merged    ON shiny_log(merged);
CREATE INDEX IF NOT EXISTS idx_instance  ON shiny_log(instance_id);

CREATE TABLE IF NOT EXISTS living_dex (
    pokemon_id       INTEGER PRIMARY KEY,
    pokemon_name     TEXT    NOT NULL,
    owned            INTEGER NOT NULL DEFAULT 0,
    obtained_date    TEXT,
    evolution_stage  INTEGER NOT NULL DEFAULT 1,
    is_final_form    INTEGER NOT NULL DEFAULT 0,
    location_caught  TEXT,
    method_obtained  TEXT,
    current_level    INTEGER DEFAULT 0,
    target_level     INTEGER DEFAULT 0,
    needs_evolution  INTEGER NOT NULL DEFAULT 0,
    evolution_method TEXT,
    evolution_req    TEXT,
    box_number       INTEGER DEFAULT 0,
    box_position     INTEGER DEFAULT 0,
    personality      INTEGER,
    shiny_log_id     INTEGER REFERENCES shiny_log(id)
);

CREATE TABLE IF NOT EXISTS evolution_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pokemon_id INTEGER NOT NULL,
    target_pokemon_id INTEGER NOT NULL,
    method           TEXT    NOT NULL,
    requirement      TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending',
    priority         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    completed_at     TEXT,
    instance_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_evo_status ON evolution_queue(status);

CREATE TABLE IF NOT EXISTS evolution_materials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name    TEXT    NOT NULL,
    quantity     INTEGER NOT NULL DEFAULT 0,
    reserved_for INTEGER,
    game_version TEXT    NOT NULL DEFAULT 'firered'
);

CREATE TABLE IF NOT EXISTS cheat_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cheat_name   TEXT    NOT NULL,
    cheat_code   TEXT    NOT NULL,
    category     TEXT    NOT NULL DEFAULT 'safe',
    activated_at TEXT    NOT NULL,
    instance_id  TEXT,
    affects_legitimacy INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cheat_cat ON cheat_log(category);
"""


# ── Data class ───────────────────────────────────────────────────────────────

@dataclass
class ShinyRecord:
    id: Optional[int]
    tid: int
    sid: int
    seed: int
    species: str
    instance_id: str
    timestamp: str
    save_path: str
    game_version: str = "firered"
    personality: Optional[int] = None
    ivs: Optional[str] = None
    nature: Optional[str] = None
    ability: Optional[str] = None
    merged: bool = False


# ── Connection helper ────────────────────────────────────────────────────────

@contextmanager
def _connect(db_path: Path = DATABASE_PATH) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DATABASE_PATH) -> None:
    """Create the database and tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


# ── Write ────────────────────────────────────────────────────────────────────

def insert_shiny(record: ShinyRecord, db_path: Path = DATABASE_PATH) -> int:
    """Insert a shiny record and return its row id."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO shiny_log
                (tid, sid, seed, species, instance_id, timestamp, save_path,
                 game_version, personality, ivs, nature, ability, merged)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.tid,
                record.sid,
                record.seed,
                record.species,
                record.instance_id,
                record.timestamp,
                record.save_path,
                record.game_version,
                record.personality,
                record.ivs,
                record.nature,
                record.ability,
                int(record.merged),
            ),
        )
        return cur.lastrowid


def mark_merged(record_id: int, db_path: Path = DATABASE_PATH) -> None:
    """Flag a record as merged into the master save."""
    with _connect(db_path) as conn:
        conn.execute("UPDATE shiny_log SET merged = 1 WHERE id = ?", (record_id,))


# ── Read / Query ─────────────────────────────────────────────────────────────

def _row_to_record(row: sqlite3.Row) -> ShinyRecord:
    return ShinyRecord(
        id=row["id"],
        tid=row["tid"],
        sid=row["sid"],
        seed=row["seed"],
        species=row["species"],
        instance_id=row["instance_id"],
        timestamp=row["timestamp"],
        save_path=row["save_path"],
        game_version=row["game_version"],
        personality=row["personality"],
        ivs=row["ivs"],
        nature=row["nature"],
        ability=row["ability"],
        merged=bool(row["merged"]),
    )


def get_all(db_path: Path = DATABASE_PATH) -> List[ShinyRecord]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM shiny_log ORDER BY id").fetchall()
    return [_row_to_record(r) for r in rows]


def get_by_species(species: str, db_path: Path = DATABASE_PATH) -> List[ShinyRecord]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM shiny_log WHERE species = ? ORDER BY id", (species,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_unmerged(db_path: Path = DATABASE_PATH) -> List[ShinyRecord]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM shiny_log WHERE merged = 0 ORDER BY id"
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_unique_species(db_path: Path = DATABASE_PATH) -> List[str]:
    """Return a sorted list of distinct species that have shiny entries."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT species FROM shiny_log ORDER BY species"
        ).fetchall()
    return [r["species"] for r in rows]


def count_by_species(db_path: Path = DATABASE_PATH) -> dict[str, int]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT species, COUNT(*) as cnt FROM shiny_log GROUP BY species ORDER BY species"
        ).fetchall()
    return {r["species"]: r["cnt"] for r in rows}


def get_by_instance(instance_id: str, db_path: Path = DATABASE_PATH) -> List[ShinyRecord]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM shiny_log WHERE instance_id = ? ORDER BY id", (instance_id,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def total_shinies(db_path: Path = DATABASE_PATH) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM shiny_log").fetchone()
    return row["cnt"]


def log_shiny(
    species_id: int,
    personality_value: int,
    tid: int,
    sid: int,
    seed: int,
    encounter_count: int,
    instance_id: str = "",
    save_path: str = "",
    game_version: str = "firered",
    db_path: Path = DATABASE_PATH,
) -> int:
    """Convenience wrapper to log a shiny encounter from the GUI / worker."""
    record = ShinyRecord(
        id=None,
        tid=tid,
        sid=sid,
        seed=seed,
        species=str(species_id),
        instance_id=instance_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        save_path=save_path,
        game_version=game_version,
        personality=personality_value,
        merged=False,
    )
    return insert_shiny(record, db_path)


def recent_shinies(limit: int = 10, db_path: Path = DATABASE_PATH) -> list:
    """Return the most recent shiny records as raw tuples for quick display."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, species, personality, tid, sid, seed, "
            "       (SELECT COUNT(*) FROM shiny_log) as enc, timestamp "
            "FROM shiny_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [tuple(r) for r in rows]


# ── Living Dex ──────────────────────────────────────────────────────────────

@dataclass
class LivingDexEntry:
    pokemon_id: int
    pokemon_name: str
    owned: bool = False
    obtained_date: Optional[str] = None
    evolution_stage: int = 1
    is_final_form: bool = False
    location_caught: Optional[str] = None
    method_obtained: Optional[str] = None
    current_level: int = 0
    target_level: int = 0
    needs_evolution: bool = False
    evolution_method: Optional[str] = None
    evolution_req: Optional[str] = None
    box_number: int = 0
    box_position: int = 0
    personality: Optional[int] = None
    shiny_log_id: Optional[int] = None


def init_living_dex(db_path: Path = DATABASE_PATH) -> None:
    """Populate the living_dex table with all 386 Pokémon if empty."""
    from modules.evolution_data import POKEDEX, EvoMethod
    with _connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM living_dex").fetchone()["cnt"]
        if count > 0:
            return
        for pid, sp in sorted(POKEDEX.items()):
            has_no_evos = len(sp.evolutions) == 0
            evo_method = None
            evo_req = None
            target_lvl = 0
            needs_evo = False
            if sp.pre_evolution_id is not None:
                parent = POKEDEX.get(sp.pre_evolution_id)
                if parent:
                    for evo in parent.evolutions:
                        if evo.target_id == pid:
                            evo_method = evo.method.value
                            if evo.method == EvoMethod.LEVEL:
                                target_lvl = evo.level
                            elif evo.stone:
                                evo_req = evo.stone.value
                            elif evo.trade_item:
                                evo_req = evo.trade_item.value
                            break
            conn.execute(
                "INSERT OR IGNORE INTO living_dex "
                "(pokemon_id, pokemon_name, evolution_stage, is_final_form, "
                " target_level, evolution_method, evolution_req) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, sp.name, sp.evolution_stage, int(has_no_evos),
                 target_lvl, evo_method, evo_req),
            )


def mark_pokemon_owned(
    pokemon_id: int,
    location: str = "",
    method: str = "",
    personality: Optional[int] = None,
    shiny_log_id: Optional[int] = None,
    db_path: Path = DATABASE_PATH,
) -> None:
    """Mark a Pokémon as owned in the living dex."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE living_dex SET owned=1, obtained_date=?, location_caught=?, "
            "method_obtained=?, personality=?, shiny_log_id=? WHERE pokemon_id=?",
            (datetime.now(timezone.utc).isoformat(), location, method,
             personality, shiny_log_id, pokemon_id),
        )


def get_living_dex_progress(db_path: Path = DATABASE_PATH) -> dict:
    """Return living dex completion stats."""
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM living_dex").fetchone()["c"]
        owned = conn.execute("SELECT COUNT(*) as c FROM living_dex WHERE owned=1").fetchone()["c"]
        by_stage = {}
        for row in conn.execute(
            "SELECT evolution_stage, COUNT(*) as total, "
            "SUM(owned) as got FROM living_dex GROUP BY evolution_stage"
        ).fetchall():
            by_stage[row["evolution_stage"]] = {"total": row["total"], "owned": row["got"] or 0}
    return {"total": total, "owned": owned, "by_stage": by_stage}


def get_missing_pokemon(db_path: Path = DATABASE_PATH) -> List[LivingDexEntry]:
    """Return all Pokémon not yet owned."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM living_dex WHERE owned=0 ORDER BY pokemon_id"
        ).fetchall()
    return [LivingDexEntry(**dict(r)) for r in rows]


def get_owned_pokemon(db_path: Path = DATABASE_PATH) -> List[LivingDexEntry]:
    """Return all owned Pokémon."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM living_dex WHERE owned=1 ORDER BY pokemon_id"
        ).fetchall()
    return [LivingDexEntry(**dict(r)) for r in rows]


def get_evolution_queue(status: str = "pending", db_path: Path = DATABASE_PATH) -> list:
    """Return evolution queue entries by status."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM evolution_queue WHERE status=? ORDER BY priority DESC, id",
            (status,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_to_evolution_queue(
    source_id: int, target_id: int, method: str,
    requirement: str = "", priority: int = 0,
    db_path: Path = DATABASE_PATH,
) -> int:
    """Add an evolution task to the queue."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO evolution_queue "
            "(source_pokemon_id, target_pokemon_id, method, requirement, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, target_id, method, requirement, priority,
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def complete_evolution(queue_id: int, db_path: Path = DATABASE_PATH) -> None:
    """Mark an evolution queue entry as completed."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE evolution_queue SET status='completed', completed_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), queue_id),
        )


def get_material_inventory(db_path: Path = DATABASE_PATH) -> dict:
    """Return evolution materials inventory as {item_name: quantity}."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT item_name, SUM(quantity) as qty FROM evolution_materials "
            "GROUP BY item_name ORDER BY item_name"
        ).fetchall()
    return {r["item_name"]: r["qty"] for r in rows}


def update_material(
    item_name: str, quantity: int, game_version: str = "firered",
    db_path: Path = DATABASE_PATH,
) -> None:
    """Upsert an evolution material count."""
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM evolution_materials WHERE item_name=? AND game_version=?",
            (item_name, game_version),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE evolution_materials SET quantity=? WHERE id=?",
                (quantity, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO evolution_materials (item_name, quantity, game_version) "
                "VALUES (?, ?, ?)",
                (item_name, quantity, game_version),
            )


def log_cheat(
    cheat_name: str, cheat_code: str, category: str = "safe",
    instance_id: str = "", affects_legitimacy: bool = False,
    db_path: Path = DATABASE_PATH,
) -> int:
    """Log a cheat activation for audit trail."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO cheat_log "
            "(cheat_name, cheat_code, category, activated_at, instance_id, affects_legitimacy) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cheat_name, cheat_code, category,
             datetime.now(timezone.utc).isoformat(),
             instance_id, int(affects_legitimacy)),
        )
        return cur.lastrowid


def get_cheat_history(db_path: Path = DATABASE_PATH) -> list:
    """Return all cheat activations."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM cheat_log ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def is_save_legitimate(db_path: Path = DATABASE_PATH) -> bool:
    """Check if any legitimacy-affecting cheats were used."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM cheat_log WHERE affects_legitimacy=1"
        ).fetchone()
    return row["c"] == 0


# ── Initialization on import ─────────────────────────────────────────────────

init_db()
try:
    init_living_dex()
except Exception:
    pass  # evolution_data may not be importable during early init
