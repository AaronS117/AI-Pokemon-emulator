"""Unit tests for modules.performance – pools, async worker, monitoring."""
import time
import pytest
from modules.performance import (
    MemoryPool, AsyncWorker, PerformanceMonitor, get_pool,
)


class TestMemoryPool:
    def test_acquire_returns_buffer(self):
        pool = MemoryPool(pool_size=4, buffer_size=64)
        buf = pool.acquire()
        assert isinstance(buf, bytearray)
        assert len(buf) >= 64

    def test_acquire_custom_size(self):
        pool = MemoryPool(pool_size=4, buffer_size=32)
        buf = pool.acquire(128)
        assert len(buf) >= 128

    def test_release_and_reuse(self):
        pool = MemoryPool(pool_size=4, buffer_size=64)
        buf1 = pool.acquire()
        pool.release(buf1)
        buf2 = pool.acquire()
        # Should reuse the same buffer
        assert pool.stats["reused"] >= 1

    def test_pool_exhaustion(self):
        pool = MemoryPool(pool_size=2, buffer_size=32)
        b1 = pool.acquire()
        b2 = pool.acquire()
        b3 = pool.acquire()  # Pool empty, should allocate new
        assert pool.stats["allocated"] >= 1
        assert isinstance(b3, bytearray)

    def test_hit_rate(self):
        pool = MemoryPool(pool_size=8, buffer_size=32)
        for _ in range(10):
            buf = pool.acquire()
            pool.release(buf)
        stats = pool.stats
        assert stats["hit_rate"] > 0.5

    def test_get_pool_sizes(self):
        p4 = get_pool(4)
        p100 = get_pool(100)
        p600 = get_pool(600)
        assert p4 is not p100
        assert p100 is not p600


class TestAsyncWorker:
    def test_start_stop(self):
        w = AsyncWorker()
        w.start()
        assert w.stats["running"] is True
        w.stop()
        assert w.stats["running"] is False

    def test_submit_and_process(self):
        w = AsyncWorker()
        w.start()
        results = []
        w.submit(lambda: results.append(42))
        time.sleep(0.2)
        w.stop()
        assert 42 in results
        assert w.stats["processed"] >= 1

    def test_multiple_tasks(self):
        w = AsyncWorker()
        w.start()
        counter = {"n": 0}
        for _ in range(10):
            w.submit(lambda: counter.__setitem__("n", counter["n"] + 1))
        time.sleep(0.5)
        w.stop()
        assert counter["n"] == 10

    def test_error_handling(self):
        w = AsyncWorker()
        w.start()
        w.submit(lambda: 1 / 0)  # Will raise ZeroDivisionError
        time.sleep(0.2)
        w.stop()
        assert w.stats["errors"] >= 1

    def test_pending_count(self):
        w = AsyncWorker()
        # Don't start — tasks should queue
        for _ in range(5):
            w.submit(lambda: None)
        assert w.pending == 5


class TestPerformanceMonitor:
    def test_timer(self):
        pm = PerformanceMonitor()
        start = pm.time_start("op")
        time.sleep(0.01)
        duration = pm.time_end("op", start)
        assert duration > 0
        assert pm.get_avg("op") > 0

    def test_counter(self):
        pm = PerformanceMonitor()
        pm.increment("reads", 5)
        pm.increment("reads", 3)
        report = pm.report()
        assert report["counters"]["reads"] == 8

    def test_p99(self):
        pm = PerformanceMonitor()
        for i in range(100):
            start = pm.time_start("fast")
            pm.time_end("fast", start)
        assert pm.get_p99("fast") >= 0

    def test_report_structure(self):
        pm = PerformanceMonitor()
        start = pm.time_start("x")
        pm.time_end("x", start)
        pm.increment("y", 1)
        report = pm.report()
        assert "timers" in report
        assert "counters" in report
        assert "x" in report["timers"]
        assert report["timers"]["x"]["count"] == 1

    def test_unknown_timer_avg(self):
        pm = PerformanceMonitor()
        assert pm.get_avg("nonexistent") == 0.0
        assert pm.get_p99("nonexistent") == 0.0
