"""
performance – Memory pooling, save state reuse, and async I/O optimizations.

Provides:
  - MemoryPool: Pre-allocated byte buffers to reduce GC pressure
  - StatePool: Cached save states for fast reset cycles
  - BatchProcessor: Batch multiple memory reads into single operations
  - AsyncWorker: Non-blocking I/O for database writes and file ops
  - FrameSkipper: Intelligent frame skipping for non-critical phases
"""

from __future__ import annotations

import logging
import queue
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.game_bot import GameBot

logger = logging.getLogger(__name__)


# ── Memory Pool ─────────────────────────────────────────────────────────────

class MemoryPool:
    """
    Pre-allocated byte buffer pool to reduce garbage collection pressure.

    Instead of creating new bytearray objects for every memory read,
    we reuse buffers from a pool. This is critical for high-speed
    emulation where we read memory thousands of times per second.
    """

    def __init__(self, pool_size: int = 64, buffer_size: int = 256):
        self._pool: deque[bytearray] = deque(maxlen=pool_size)
        self._default_size = buffer_size
        self._allocated = 0
        self._reused = 0
        # Pre-allocate
        for _ in range(pool_size):
            self._pool.append(bytearray(buffer_size))

    def acquire(self, size: int = 0) -> bytearray:
        """Get a buffer from the pool (or allocate a new one)."""
        target_size = size or self._default_size
        try:
            buf = self._pool.popleft()
            if len(buf) < target_size:
                buf = bytearray(target_size)
                self._allocated += 1
            else:
                self._reused += 1
            return buf
        except IndexError:
            self._allocated += 1
            return bytearray(target_size)

    def release(self, buf: bytearray) -> None:
        """Return a buffer to the pool."""
        if len(self._pool) < self._pool.maxlen:
            self._pool.append(buf)

    @property
    def stats(self) -> dict:
        return {
            "pool_size": len(self._pool),
            "allocated": self._allocated,
            "reused": self._reused,
            "hit_rate": self._reused / max(1, self._reused + self._allocated),
        }


# Common buffer pools for different read sizes
_pool_4 = MemoryPool(pool_size=128, buffer_size=4)
_pool_100 = MemoryPool(pool_size=32, buffer_size=100)
_pool_600 = MemoryPool(pool_size=8, buffer_size=600)


def get_pool(size: int) -> MemoryPool:
    """Get the appropriate pool for a given buffer size."""
    if size <= 4:
        return _pool_4
    elif size <= 100:
        return _pool_100
    else:
        return _pool_600


# ── Save State Pool ─────────────────────────────────────────────────────────

@dataclass
class CachedState:
    """A cached save state with metadata."""
    data: bytes
    frame: int
    label: str
    created_at: float = field(default_factory=time.time)
    use_count: int = 0


class StatePool:
    """
    Pool of cached save states for fast reset cycles.

    Instead of saving/loading from disk, keeps states in memory.
    Uses raw state snapshots (core.save_raw_state) which are much
    faster than file-based save states.

    Typical usage:
      - Save a "pre-encounter" state before entering grass
      - On non-shiny encounter, restore to pre-encounter state
      - Skip the entire battle/run animation
    """

    def __init__(self, max_states: int = 10):
        self._states: Dict[str, CachedState] = {}
        self._max_states = max_states
        self._total_saves = 0
        self._total_loads = 0

    def save(self, bot: GameBot, label: str) -> bool:
        """Save current state to the pool."""
        try:
            core = bot.instance._core
            raw = core.save_raw_state()
            if raw is None:
                return False

            # Evict oldest if at capacity
            if len(self._states) >= self._max_states and label not in self._states:
                oldest_key = min(self._states, key=lambda k: self._states[k].created_at)
                del self._states[oldest_key]

            self._states[label] = CachedState(
                data=bytes(raw),
                frame=core.frame_counter,
                label=label,
            )
            self._total_saves += 1
            return True
        except Exception as exc:
            logger.error("StatePool save failed: %s", exc)
            return False

    def load(self, bot: GameBot, label: str) -> bool:
        """Load a state from the pool."""
        state = self._states.get(label)
        if state is None:
            return False
        try:
            result = bot.instance._core.load_raw_state(state.data)
            if result:
                state.use_count += 1
                self._total_loads += 1
            return bool(result)
        except Exception as exc:
            logger.error("StatePool load failed: %s", exc)
            return False

    def has(self, label: str) -> bool:
        return label in self._states

    def clear(self) -> None:
        self._states.clear()

    @property
    def stats(self) -> dict:
        return {
            "cached_states": len(self._states),
            "total_saves": self._total_saves,
            "total_loads": self._total_loads,
            "labels": list(self._states.keys()),
        }


# ── Batch Memory Reader ────────────────────────────────────────────────────

@dataclass
class ReadRequest:
    """A batched memory read request."""
    address: int
    size: int
    result: Optional[bytes] = None


class BatchReader:
    """
    Batch multiple memory reads for efficiency.

    When reading many small values (e.g., checking party data),
    it's faster to read one large block and slice it than to
    make many small ffi.memmove calls.

    Usage:
        reader = BatchReader(bot)
        reader.add(0x02024284, 100)  # Party slot 0
        reader.add(0x02024284 + 100, 100)  # Party slot 1
        results = reader.execute()
    """

    def __init__(self, bot: GameBot):
        self.bot = bot
        self._requests: List[ReadRequest] = []

    def add(self, address: int, size: int) -> int:
        """Add a read request. Returns the request index."""
        idx = len(self._requests)
        self._requests.append(ReadRequest(address, size))
        return idx

    def execute(self) -> List[bytes]:
        """Execute all reads, coalescing adjacent reads where possible."""
        if not self._requests:
            return []

        # Sort by address for coalescing
        sorted_reqs = sorted(enumerate(self._requests), key=lambda x: x[1].address)

        # Coalesce adjacent/overlapping reads
        groups: List[Tuple[int, int, List[Tuple[int, ReadRequest]]]] = []
        current_start = sorted_reqs[0][1].address
        current_end = current_start + sorted_reqs[0][1].size
        current_group = [sorted_reqs[0]]

        for idx, req in sorted_reqs[1:]:
            if req.address <= current_end + 64:  # Allow 64-byte gap for coalescing
                current_end = max(current_end, req.address + req.size)
                current_group.append((idx, req))
            else:
                groups.append((current_start, current_end - current_start, current_group))
                current_start = req.address
                current_end = req.address + req.size
                current_group = [(idx, req)]

        groups.append((current_start, current_end - current_start, current_group))

        # Execute coalesced reads
        results = [b""] * len(self._requests)
        for group_addr, group_size, group_reqs in groups:
            try:
                block = self.bot.read_bytes(group_addr, group_size)
                for orig_idx, req in group_reqs:
                    offset = req.address - group_addr
                    results[orig_idx] = block[offset:offset + req.size]
            except Exception as exc:
                logger.error("Batch read failed at 0x%08X: %s", group_addr, exc)

        self._requests.clear()
        return results

    def read_party_batch(self) -> List[bytes]:
        """Convenience: batch-read all 6 party slots in one operation."""
        # Read the entire party block at once (600 bytes)
        try:
            raw = self.bot.read_bytes(0x02024284, 600)
            return [raw[i * 100:(i + 1) * 100] for i in range(6)]
        except Exception:
            return [b""] * 6


# ── Async Worker ────────────────────────────────────────────────────────────

class AsyncWorker:
    """
    Background worker for non-blocking I/O operations.

    Database writes, file exports, and other I/O should not block
    the emulation loop. This worker processes them in a background thread.
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._processed = 0
        self._errors = 0

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker and drain remaining tasks."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def submit(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """Submit a task to the background worker."""
        try:
            self._queue.put_nowait((func, args, kwargs))
        except queue.Full:
            logger.warning("Async worker queue full, dropping task")
            self._errors += 1

    def _worker_loop(self) -> None:
        while self._running or not self._queue.empty():
            try:
                func, args, kwargs = self._queue.get(timeout=0.1)
                func(*args, **kwargs)
                self._processed += 1
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error("Async worker error: %s", exc)
                self._errors += 1

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> dict:
        return {
            "running": self._running,
            "pending": self.pending,
            "processed": self._processed,
            "errors": self._errors,
        }


# Global async worker instance
_async_worker = AsyncWorker()


def get_async_worker() -> AsyncWorker:
    """Get the global async worker (starts it if needed)."""
    if not _async_worker._running:
        _async_worker.start()
    return _async_worker


# ── Frame Skipper ───────────────────────────────────────────────────────────

class FrameSkipper:
    """
    Intelligent frame skipping for non-critical phases.

    During phases where we don't need to check game state every frame
    (e.g., walking, waiting for text), we can skip frames to increase
    throughput. During critical phases (battle start, encounter check),
    we run every frame.
    """

    def __init__(self, bot: GameBot):
        self.bot = bot
        self._skip_rate = 0  # 0 = no skip, N = skip N frames between checks
        self._phase = "normal"

    def set_phase(self, phase: str) -> None:
        """Set the current phase to adjust skip rate."""
        self._phase = phase
        skip_rates = {
            "walking": 4,       # Check every 4th frame
            "waiting_text": 8,  # Check every 8th frame
            "battle_anim": 16,  # Check every 16th frame
            "normal": 0,        # Every frame
            "critical": 0,      # Every frame (encounter check, shiny check)
            "menu_nav": 2,      # Check every 2nd frame
        }
        self._skip_rate = skip_rates.get(phase, 0)

    def advance(self, frames: int = 1) -> None:
        """Advance frames with intelligent skipping."""
        if self._skip_rate == 0:
            self.bot.advance_frames(frames)
        else:
            # Run frames in bulk without checking state
            total = frames * (1 + self._skip_rate)
            self.bot.advance_frames(total)

    def advance_until(
        self,
        condition: Callable[[], bool],
        max_frames: int = 600,
        check_interval: int = 0,
    ) -> int:
        """
        Advance frames until a condition is met.

        Args:
            condition: Callable that returns True when done.
            max_frames: Maximum frames before timeout.
            check_interval: Override check interval (0 = use phase default).

        Returns:
            Number of frames advanced.
        """
        interval = check_interval or max(1, self._skip_rate + 1)
        frames = 0
        while frames < max_frames:
            self.bot.advance_frames(interval)
            frames += interval
            if condition():
                return frames
        return frames


# ── Performance Monitor ─────────────────────────────────────────────────────

class PerformanceMonitor:
    """
    Track performance metrics across the system.

    Monitors FPS, memory read latency, state save/load times,
    and other performance-critical operations.
    """

    def __init__(self):
        self._timers: Dict[str, List[float]] = {}
        self._counters: Dict[str, int] = {}
        self._window_size = 100  # Keep last N measurements

    def time_start(self, label: str) -> float:
        """Start a timer. Returns the start time."""
        return time.perf_counter()

    def time_end(self, label: str, start: float) -> float:
        """End a timer and record the duration."""
        duration = time.perf_counter() - start
        if label not in self._timers:
            self._timers[label] = []
        self._timers[label].append(duration)
        if len(self._timers[label]) > self._window_size:
            self._timers[label] = self._timers[label][-self._window_size:]
        return duration

    def increment(self, label: str, amount: int = 1) -> None:
        """Increment a counter."""
        self._counters[label] = self._counters.get(label, 0) + amount

    def get_avg(self, label: str) -> float:
        """Get average duration for a timer."""
        times = self._timers.get(label, [])
        return sum(times) / len(times) if times else 0.0

    def get_p99(self, label: str) -> float:
        """Get 99th percentile duration for a timer."""
        times = self._timers.get(label, [])
        if not times:
            return 0.0
        sorted_times = sorted(times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    def report(self) -> dict:
        """Generate a performance report."""
        report = {"timers": {}, "counters": dict(self._counters)}
        for label, times in self._timers.items():
            if times:
                report["timers"][label] = {
                    "avg_ms": round(self.get_avg(label) * 1000, 3),
                    "p99_ms": round(self.get_p99(label) * 1000, 3),
                    "count": len(times),
                    "min_ms": round(min(times) * 1000, 3),
                    "max_ms": round(max(times) * 1000, 3),
                }
        return report


# Global performance monitor
perf_monitor = PerformanceMonitor()
