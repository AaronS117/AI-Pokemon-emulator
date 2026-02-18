"""
stats_dashboard – Statistics, analytics, and data export.

Provides:
  - Real-time encounter rate tracking
  - Shiny probability calculations
  - Per-area encounter heatmaps
  - Session history and trends
  - CSV / JSON data export
  - Matplotlib chart generation for the UI
"""

from __future__ import annotations

import csv
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.config import ROOT_DIR

logger = logging.getLogger(__name__)

EXPORT_DIR = ROOT_DIR / "exports"


# ── Session tracking ────────────────────────────────────────────────────────

@dataclass
class EncounterRecord:
    """A single encounter event."""
    timestamp: float
    species_id: int
    is_shiny: bool
    area: str = ""
    instance_id: str = ""
    bot_mode: str = ""
    personality_value: int = 0


@dataclass
class SessionStats:
    """Aggregated statistics for a hunting session."""
    start_time: float = 0.0
    encounters: int = 0
    shinies: int = 0
    encounters_per_hour: float = 0.0
    species_seen: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    area_encounters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    mode_encounters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    hourly_encounters: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    encounter_log: List[EncounterRecord] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time == 0:
            return 0.0
        return time.time() - self.start_time

    @property
    def elapsed_hours(self) -> float:
        return self.elapsed_seconds / 3600

    @property
    def shiny_rate(self) -> float:
        """Observed shiny rate (0.0 to 1.0)."""
        return self.shinies / self.encounters if self.encounters > 0 else 0.0

    @property
    def shiny_rate_display(self) -> str:
        """Human-readable shiny rate."""
        if self.encounters == 0:
            return "N/A"
        if self.shinies == 0:
            return f"0/{self.encounters:,}"
        ratio = self.encounters / self.shinies
        return f"1/{ratio:,.0f} ({self.shinies}/{self.encounters:,})"

    @property
    def expected_shiny_rate(self) -> str:
        """Expected Gen 3 shiny rate: 1/8192."""
        return "1/8,192"

    @property
    def luck_factor(self) -> float:
        """How lucky the session is (1.0 = average, >1 = lucky, <1 = unlucky)."""
        expected = self.encounters / 8192
        if expected == 0:
            return 0.0
        return self.shinies / expected

    @property
    def most_common_species(self) -> List[Tuple[int, int]]:
        """Top 10 most encountered species."""
        sorted_species = sorted(self.species_seen.items(), key=lambda x: x[1], reverse=True)
        return sorted_species[:10]


class StatsTracker:
    """
    Real-time statistics tracker for shiny hunting sessions.

    Records every encounter and computes running statistics.
    """

    def __init__(self):
        self.session = SessionStats(start_time=time.time())
        self._rate_window: List[float] = []  # Timestamps for rolling rate calc
        self._rate_window_size = 300  # 5-minute window

    def record_encounter(
        self,
        species_id: int,
        is_shiny: bool,
        area: str = "",
        instance_id: str = "",
        bot_mode: str = "",
        personality_value: int = 0,
    ) -> None:
        """Record a single encounter."""
        now = time.time()
        record = EncounterRecord(
            timestamp=now,
            species_id=species_id,
            is_shiny=is_shiny,
            area=area,
            instance_id=instance_id,
            bot_mode=bot_mode,
            personality_value=personality_value,
        )
        self.session.encounters += 1
        if is_shiny:
            self.session.shinies += 1
        self.session.species_seen[species_id] += 1
        self.session.area_encounters[area] += 1
        self.session.mode_encounters[bot_mode] += 1
        self.session.encounter_log.append(record)

        # Hourly bucket
        hour = int((now - self.session.start_time) / 3600)
        self.session.hourly_encounters[hour] += 1

        # Rolling rate
        self._rate_window.append(now)
        cutoff = now - self._rate_window_size
        self._rate_window = [t for t in self._rate_window if t > cutoff]

        # Update encounters per hour
        elapsed = self.session.elapsed_hours
        if elapsed > 0:
            self.session.encounters_per_hour = self.session.encounters / elapsed

    @property
    def rolling_encounters_per_hour(self) -> float:
        """Encounters per hour based on the last 5 minutes."""
        if len(self._rate_window) < 2:
            return 0.0
        window_duration = self._rate_window[-1] - self._rate_window[0]
        if window_duration < 1:
            return 0.0
        return (len(self._rate_window) / window_duration) * 3600

    def get_summary(self) -> dict:
        """Get a summary dict for display."""
        return {
            "total_encounters": self.session.encounters,
            "total_shinies": self.session.shinies,
            "shiny_rate": self.session.shiny_rate_display,
            "encounters_per_hour": round(self.session.encounters_per_hour, 1),
            "rolling_rate": round(self.rolling_encounters_per_hour, 1),
            "elapsed": self.session.elapsed_seconds,
            "luck_factor": round(self.session.luck_factor, 2),
            "top_species": self.session.most_common_species,
            "areas": dict(self.session.area_encounters),
            "modes": dict(self.session.mode_encounters),
        }

    def reset(self) -> None:
        """Reset all statistics."""
        self.session = SessionStats(start_time=time.time())
        self._rate_window.clear()


# ── Probability Calculator ──────────────────────────────────────────────────

def shiny_probability(encounters: int, rate: float = 1 / 8192) -> dict:
    """
    Calculate shiny probability statistics.

    Args:
        encounters: Number of encounters completed.
        rate: Per-encounter shiny rate (default 1/8192 for Gen 3).

    Returns:
        Dict with probability metrics.
    """
    # P(at least one shiny) = 1 - (1 - rate)^encounters
    p_at_least_one = 1 - (1 - rate) ** encounters
    # Expected number of shinies
    expected = encounters * rate
    # Encounters needed for 50% / 90% / 99% chance
    import math
    enc_50 = math.ceil(math.log(0.5) / math.log(1 - rate)) if rate > 0 else 0
    enc_90 = math.ceil(math.log(0.1) / math.log(1 - rate)) if rate > 0 else 0
    enc_99 = math.ceil(math.log(0.01) / math.log(1 - rate)) if rate > 0 else 0

    return {
        "encounters": encounters,
        "rate": rate,
        "rate_display": f"1/{int(1/rate):,}" if rate > 0 else "N/A",
        "probability": round(p_at_least_one * 100, 2),
        "expected_shinies": round(expected, 2),
        "encounters_for_50pct": enc_50,
        "encounters_for_90pct": enc_90,
        "encounters_for_99pct": enc_99,
        "progress_to_50pct": round(encounters / enc_50 * 100, 1) if enc_50 > 0 else 0,
    }


# ── Data Export ─────────────────────────────────────────────────────────────

def export_csv(tracker: StatsTracker, filepath: Optional[Path] = None) -> Path:
    """Export encounter log to CSV."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if filepath is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = EXPORT_DIR / f"encounters_{ts}.csv"

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "species_id", "is_shiny", "area",
            "instance_id", "bot_mode", "personality_value",
        ])
        for rec in tracker.session.encounter_log:
            writer.writerow([
                datetime.fromtimestamp(rec.timestamp, tz=timezone.utc).isoformat(),
                rec.species_id,
                int(rec.is_shiny),
                rec.area,
                rec.instance_id,
                rec.bot_mode,
                f"0x{rec.personality_value:08X}",
            ])

    logger.info("Exported %d encounters to %s",
                len(tracker.session.encounter_log), filepath)
    return filepath


def export_json(tracker: StatsTracker, filepath: Optional[Path] = None) -> Path:
    """Export full session data to JSON."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if filepath is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = EXPORT_DIR / f"session_{ts}.json"

    data = {
        "session": {
            "start_time": datetime.fromtimestamp(
                tracker.session.start_time, tz=timezone.utc).isoformat(),
            "duration_seconds": tracker.session.elapsed_seconds,
            "total_encounters": tracker.session.encounters,
            "total_shinies": tracker.session.shinies,
            "encounters_per_hour": tracker.session.encounters_per_hour,
            "shiny_rate": tracker.session.shiny_rate_display,
            "luck_factor": tracker.session.luck_factor,
        },
        "species_breakdown": {
            str(k): v for k, v in tracker.session.species_seen.items()
        },
        "area_breakdown": dict(tracker.session.area_encounters),
        "mode_breakdown": dict(tracker.session.mode_encounters),
        "hourly_encounters": {
            str(k): v for k, v in tracker.session.hourly_encounters.items()
        },
        "encounters": [
            {
                "timestamp": datetime.fromtimestamp(
                    r.timestamp, tz=timezone.utc).isoformat(),
                "species_id": r.species_id,
                "is_shiny": r.is_shiny,
                "area": r.area,
                "instance_id": r.instance_id,
                "bot_mode": r.bot_mode,
                "personality_value": f"0x{r.personality_value:08X}",
            }
            for r in tracker.session.encounter_log
        ],
    }

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Exported session to %s", filepath)
    return filepath


# ── Chart Generation (matplotlib) ───────────────────────────────────────────

def generate_encounter_rate_chart(
    tracker: StatsTracker,
    filepath: Optional[Path] = None,
) -> Optional[Path]:
    """Generate an encounter rate over time chart."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        if filepath is None:
            filepath = EXPORT_DIR / "encounter_rate.png"

        if not tracker.session.encounter_log:
            return None

        # Bucket encounters into 5-minute intervals
        start = tracker.session.start_time
        buckets: Dict[int, int] = defaultdict(int)
        for rec in tracker.session.encounter_log:
            bucket = int((rec.timestamp - start) / 300)  # 5-min buckets
            buckets[bucket] += 1

        if not buckets:
            return None

        max_bucket = max(buckets.keys())
        x = list(range(max_bucket + 1))
        y = [buckets.get(i, 0) * 12 for i in x]  # ×12 to get per-hour rate

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(x, y, color="#7c3aed", linewidth=2)
        ax.fill_between(x, y, alpha=0.2, color="#7c3aed")
        ax.set_xlabel("Time (5-min intervals)")
        ax.set_ylabel("Encounters / Hour")
        ax.set_title("Encounter Rate Over Time")
        ax.set_facecolor("#0f0f0f")
        fig.patch.set_facecolor("#0f0f0f")
        ax.tick_params(colors="#94a3b8")
        ax.xaxis.label.set_color("#94a3b8")
        ax.yaxis.label.set_color("#94a3b8")
        ax.title.set_color("#e2e8f0")
        for spine in ax.spines.values():
            spine.set_color("#334155")

        fig.tight_layout()
        fig.savefig(filepath, dpi=100, facecolor="#0f0f0f")
        plt.close(fig)
        return filepath

    except ImportError:
        logger.warning("matplotlib not installed; chart generation skipped")
        return None


def generate_species_chart(
    tracker: StatsTracker,
    filepath: Optional[Path] = None,
) -> Optional[Path]:
    """Generate a species distribution bar chart."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        if filepath is None:
            filepath = EXPORT_DIR / "species_distribution.png"

        top = tracker.session.most_common_species
        if not top:
            return None

        species_ids = [str(s[0]) for s in top]
        counts = [s[1] for s in top]

        fig, ax = plt.subplots(figsize=(10, 4))
        bars = ax.barh(species_ids, counts, color="#7c3aed")
        ax.set_xlabel("Encounters")
        ax.set_title("Top Species Encountered")
        ax.set_facecolor("#0f0f0f")
        fig.patch.set_facecolor("#0f0f0f")
        ax.tick_params(colors="#94a3b8")
        ax.xaxis.label.set_color("#94a3b8")
        ax.title.set_color("#e2e8f0")
        for spine in ax.spines.values():
            spine.set_color("#334155")
        ax.invert_yaxis()

        fig.tight_layout()
        fig.savefig(filepath, dpi=100, facecolor="#0f0f0f")
        plt.close(fig)
        return filepath

    except ImportError:
        logger.warning("matplotlib not installed; chart generation skipped")
        return None


def generate_shiny_probability_chart(
    max_encounters: int = 25000,
    filepath: Optional[Path] = None,
) -> Optional[Path]:
    """Generate a cumulative shiny probability chart."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        if filepath is None:
            filepath = EXPORT_DIR / "shiny_probability.png"

        rate = 1 / 8192
        x = list(range(0, max_encounters + 1, 100))
        y = [100 * (1 - (1 - rate) ** n) for n in x]

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(x, y, color="#fbbf24", linewidth=2)
        ax.axhline(y=50, color="#ef4444", linestyle="--", alpha=0.5, label="50%")
        ax.axhline(y=90, color="#22c55e", linestyle="--", alpha=0.5, label="90%")
        ax.set_xlabel("Encounters")
        ax.set_ylabel("Probability (%)")
        ax.set_title("Cumulative Shiny Probability (1/8192)")
        ax.legend(facecolor="#1a1a2e", edgecolor="#334155", labelcolor="#e2e8f0")
        ax.set_facecolor("#0f0f0f")
        fig.patch.set_facecolor("#0f0f0f")
        ax.tick_params(colors="#94a3b8")
        ax.xaxis.label.set_color("#94a3b8")
        ax.yaxis.label.set_color("#94a3b8")
        ax.title.set_color("#e2e8f0")
        for spine in ax.spines.values():
            spine.set_color("#334155")

        fig.tight_layout()
        fig.savefig(filepath, dpi=100, facecolor="#0f0f0f")
        plt.close(fig)
        return filepath

    except ImportError:
        logger.warning("matplotlib not installed; chart generation skipped")
        return None
