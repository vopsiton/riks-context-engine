"""Deterministic concurrency tests for SemanticMemory connection management (#163).

The flaky failure 'Expected 100 entries, got 75' in
TestCrossProcessConcurrency was caused by SemanticMemory._connect()
opening a fresh sqlite3 connection per call and never closing it: under
sustained load the process exhausted its file-descriptor limit, sqlite3
calls started failing ('bad parameter or other API misuse') and writes
were silently lost.

These tests pin the fix deterministically (no wall-clock races):

- test_connect_returns_same_object: _connect() reuses one connection per
  thread (the fix), instead of a new object per call (the bug).
- test_fd_count_stable_under_load: 200 sequential add/get/query calls do
  not grow the process fd count by more than 2 (the old code grew it by
  ~1 per call).
- test_cross_process_100_writes: the original scenario (4 procs x 25
  writes) with a generous join timeout and a hard assert.
"""

from __future__ import annotations

import os
import tempfile
import threading
from multiprocessing import Process

from riks_context_engine.memory.semantic import SemanticMemory


def _proc_writer(db_path: str, prefix: str, count: int) -> None:
    """Worker: write `count` entries to the semantic DB."""
    mem = SemanticMemory(db_path=db_path)
    for _ in range(count):
        mem.add(subject=f"{prefix}_{_}", predicate="test", object="value")


class TestConnectionReuse:
    """_connect() must reuse one connection per thread (#163)."""

    def test_connect_returns_same_object(self, tmp_path):
        mem = SemanticMemory(db_path=str(tmp_path / "sem.db"))
        c1 = mem._connect()
        c2 = mem._connect()
        # The buggy version returned a fresh sqlite3.Connection per call;
        # the fix reuses the thread-local connection.
        assert c1 is c2

    def test_separate_thread_gets_own_connection(self, tmp_path):
        mem = SemanticMemory(db_path=str(tmp_path / "sem.db"))
        main_conn = mem._connect()
        holder: list = []

        def other():
            holder.append(mem._connect())

        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert len(holder) == 1
        # Different thread → different connection object (thread-local).
        assert holder[0] is not main_conn

    def test_fd_count_stable_under_load(self, tmp_path):
        """Sustained writes must not leak file descriptors.

        The buggy version called sqlite3.connect() per operation and
        never closed the results: fd count grew ~1 per call until the
        process hit its limit and writes failed with
        'bad parameter or other API misuse'.
        """
        before = len(os.listdir(f"/proc/{os.getpid()}/fd"))
        mem = SemanticMemory(db_path=str(tmp_path / "sem.db"))
        for i in range(200):
            mem.add(subject=f"s_{i}", predicate="p", object="o")
            mem.get(f"sm_{mem.query()[0].created_at.timestamp()}") if i == 0 else None
            if i % 20 == 0:
                mem.query(predicate="p")
        after = len(os.listdir(f"/proc/{os.getpid()}/fd"))
        # Allow a small slack (sqlite WAL journal files); the buggy code
        # grew by ~1 per operation (hundreds).
        assert after - before <= 2, f"fd leak: {before} -> {after}"

    def test_cross_process_100_writes(self):
        """4 processes x 25 writes → all 100 entries present.

        Original flaky scenario, now with the connection fix in place.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            procs = [Process(target=_proc_writer, args=(db_path, f"proc{i}", 25)) for i in range(4)]
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=30)
                assert p.exitcode == 0, f"writer proc {p.pid} exited {p.exitcode}"
            mem = SemanticMemory(db_path=db_path)
            entries = mem.query()
            assert len(entries) == 100, f"Expected 100 entries, got {len(entries)}"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass
