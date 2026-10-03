"""Transactional single-host trace ledger with restart verification."""

from __future__ import annotations

import sqlite3
import os
import stat
from pathlib import Path
from threading import Lock

from .trace import DecisionTrace
from .trace_ledger import LedgerRecord, TraceLedger, _record_hash, canonical_trace_json


class SqliteTraceLedger:
    """Persist redacted traces atomically in a host-owned SQLite database.

    The operator must place the database on durable, access-controlled storage and
    back it up. This is a single-host ledger, not an independently anchored audit log.
    """

    def __init__(self, path: Path) -> None:
        if not path.parent.is_dir() or path.is_symlink():
            raise ValueError("ledger parent must exist and path must not be a symlink")
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("ledger file must not be accessible to group or other users")
        self._lock = Lock()
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL, "
            "canonical_json TEXT NOT NULL)"
        )
        if not TraceLedger.verify(self.records):
            self._db.close()
            raise ValueError("persisted trace ledger hash chain is invalid")

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT previous_hash, record_hash, canonical_json "
                "FROM records ORDER BY sequence"
            ).fetchall()
        return tuple(LedgerRecord(*row) for row in rows)

    def append(self, trace: DecisionTrace) -> LedgerRecord:
        canonical = canonical_trace_json(trace)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT record_hash FROM records ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous = row[0] if row is not None else "0" * 64
                record = LedgerRecord(previous, _record_hash(previous, canonical), canonical)
                self._db.execute(
                    "INSERT INTO records (previous_hash, record_hash, canonical_json) "
                    "VALUES (?, ?, ?)",
                    (record.previous_hash, record.record_hash, record.canonical_json),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return record

    def close(self) -> None:
        with self._lock:
            self._db.close()
