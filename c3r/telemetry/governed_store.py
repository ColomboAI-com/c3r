"""Fail-closed local admission and retention for C3R-authored internal traces.

The host still owns encryption, backup purge, IAM, daily scheduling, and an
independent hash-head anchor. This store does not enable collection by itself.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Callable

from .ledger_anchor import LedgerHead, capture_head
from .trace import DecisionTrace
from .trace_ledger import LedgerRecord, _record_hash


RETENTION_DAYS = 30
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_GENESIS = "0" * 64


@dataclass(frozen=True, slots=True)
class SourceGrant:
    source_id: str
    owner: str
    task_ids: frozenset[str]
    rights_attested: bool

    def __post_init__(self) -> None:
        if not self.rights_attested or not self.task_ids:
            raise ValueError("source rights and task inventory must be attested")
        for value in (self.source_id, self.owner, *self.task_ids):
            if not _TOKEN.fullmatch(value):
                raise ValueError("source registry identifiers must be bounded tokens")


def _validate_trace(trace: DecisionTrace) -> None:
    identifiers = (
        trace.run_id,
        trace.access_level,
        trace.model_provider,
        trace.authority_result,
        *trace.candidate_ids,
        *trace.artifact_refs,
    )
    if trace.selected_action_id is not None:
        identifiers += (trace.selected_action_id,)
    if not _HASH.fullmatch(trace.state_hash) or any(
        not _TOKEN.fullmatch(value) for value in identifiers
    ):
        raise ValueError("trace failed redaction schema")
    # Artifact references are not yet admitted: the policy requires a separate
    # opaque-reference registry and leakage review before that field is enabled.
    if trace.artifact_refs:
        raise ValueError("trace failed redaction schema")
    for key, values in trace.probabilities.items():
        if not _TOKEN.fullmatch(key) or not values or any(
            not isfinite(value) or not 0 <= value <= 1 for value in values
        ):
            raise ValueError("trace failed redaction schema")
    for mapping in (trace.utility_quantiles, trace.system_cost):
        if any(not _TOKEN.fullmatch(key) or not isfinite(value) for key, value in mapping.items()):
            raise ValueError("trace failed redaction schema")
    if any(value < 0 for value in trace.system_cost.values()):
        raise ValueError("trace failed redaction schema")
    for key, value in trace.task_outcome.items():
        if not _TOKEN.fullmatch(key):
            raise ValueError("trace failed redaction schema")
        if isinstance(value, str):
            if not _TOKEN.fullmatch(value):
                raise ValueError("trace failed redaction schema")
        elif isinstance(value, bool):
            pass
        elif not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError("trace failed redaction schema")


class GovernedTraceStore:
    """SQLite source-gated traces with a prefix checkpoint for 30-day purge.

    `purge_expired` must be run by the deployment's daily scheduler, and its
    result independently audited. Local deletion cannot erase external backups.
    """

    def __init__(
        self,
        path: Path,
        *,
        grants: tuple[SourceGrant, ...],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not path.parent.is_dir() or path.is_symlink():
            raise ValueError("store parent must exist and path must not be a symlink")
        if not grants or len({grant.source_id for grant in grants}) != len(grants):
            raise ValueError("unique approved sources are required")
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("store file must not be accessible to group or other users")
        self._clock = clock
        self._grants = {grant.source_id: grant for grant in grants}
        self._lock = Lock()
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA secure_delete=ON")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS metadata ("
            "id INTEGER PRIMARY KEY CHECK(id=1), checkpoint_hash TEXT NOT NULL, "
            "last_collected_at TEXT NOT NULL)"
        )
        self._db.execute(
            "INSERT OR IGNORE INTO metadata (id, checkpoint_hash, last_collected_at) "
            "VALUES (1, ?, '')", (_GENESIS,)
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, "
            "collected_at TEXT NOT NULL, previous_hash TEXT NOT NULL, "
            "record_hash TEXT NOT NULL, canonical_json TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS purge_audit ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, purged_at TEXT NOT NULL, "
            "record_count INTEGER NOT NULL, checkpoint_hash TEXT NOT NULL)"
        )
        if not self.verify():
            self._db.close()
            raise ValueError("governed trace hash chain is invalid")

    def __enter__(self) -> GovernedTraceStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("trace clock must return UTC")
        return value

    def records(self) -> tuple[LedgerRecord, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT previous_hash, record_hash, canonical_json "
                "FROM records ORDER BY sequence"
            ).fetchall()
        return tuple(LedgerRecord(*row) for row in rows)

    def _verified_head(self) -> tuple[int, str] | None:
        with self._lock:
            checkpoint, last_collected_at = self._db.execute(
                "SELECT checkpoint_hash, last_collected_at FROM metadata WHERE id=1"
            ).fetchone()
            rows = self._db.execute(
                "SELECT sequence, run_id, collected_at, previous_hash, "
                "record_hash, canonical_json FROM records ORDER BY sequence"
            ).fetchall()
            sequence_row = self._db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='records'"
            ).fetchone()
        sequence = int(sequence_row[0]) if sequence_row is not None else 0
        if rows and rows[-1][2] != last_collected_at:
            return None
        if rows and rows[-1][0] != sequence:
            return None
        previous = checkpoint
        for _, run_id, collected_at, prior, digest, payload in rows:
            if prior != previous:
                return None
            try:
                decoded = json.loads(payload)
                canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, allow_nan=False)
                if decoded["trace"]["run_id"] != run_id or decoded["collected_at"] != collected_at:
                    return None
            except (ValueError, TypeError, KeyError):
                return None
            if canonical != payload or _record_hash(prior, payload) != digest:
                return None
            previous = digest
        return sequence, previous

    def verify(self) -> bool:
        return self._verified_head() is not None

    def snapshot_head(self, *, policy_version: str) -> LedgerHead:
        """Capture a verified head for signing outside the trace-writer identity.

        The caller must send this to a separately controlled signer and durable
        destination. Capturing a head locally is not independent anchoring.
        """
        state = self._verified_head()
        if state is None:
            raise ValueError("governed trace hash chain is invalid")
        sequence, record_hash = state
        return capture_head(
            sequence=sequence, record_hash=record_hash,
            policy_version=policy_version, clock=self._clock,
        )

    def append(self, trace: DecisionTrace, *, source_id: str, task_id: str) -> LedgerRecord:
        grant = self._grants.get(source_id)
        if grant is None or task_id not in grant.task_ids:
            raise ValueError("unapproved source or task")
        _validate_trace(trace)
        now = self._now()
        collected_at = now.isoformat(timespec="microseconds")
        retention_cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(
            timespec="microseconds"
        )
        payload = json.dumps(
            {"collected_at": collected_at, "source_id": source_id, "task_id": task_id,
             "trace": asdict(trace)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                checkpoint, last_collected_at = self._db.execute(
                    "SELECT checkpoint_hash, last_collected_at FROM metadata WHERE id=1"
                ).fetchone()
                if collected_at < last_collected_at:
                    raise ValueError("trace clock moved backwards")
                overdue = self._db.execute(
                    "SELECT 1 FROM records WHERE collected_at <= ? LIMIT 1",
                    (retention_cutoff,),
                ).fetchone()
                if overdue is not None:
                    raise ValueError("retention purge overdue; new collection is disabled")
                row = self._db.execute(
                    "SELECT record_hash FROM records ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous = row[0] if row is not None else checkpoint
                record = LedgerRecord(previous, _record_hash(previous, payload), payload)
                self._db.execute(
                    "INSERT INTO records (run_id, collected_at, previous_hash, "
                    "record_hash, canonical_json) VALUES (?, ?, ?, ?, ?)",
                    (trace.run_id, collected_at, previous, record.record_hash, payload),
                )
                self._db.execute(
                    "UPDATE metadata SET last_collected_at=? WHERE id=1", (collected_at,)
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return record

    def purge_expired(self) -> int:
        now = self._now()
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="microseconds")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                expired = self._db.execute(
                    "SELECT sequence, record_hash FROM records "
                    "WHERE collected_at <= ? ORDER BY sequence", (cutoff,)
                ).fetchall()
                if not expired:
                    self._db.execute("COMMIT")
                    return 0
                last_sequence, checkpoint = expired[-1]
                self._db.execute("DELETE FROM records WHERE sequence <= ?", (last_sequence,))
                self._db.execute("UPDATE metadata SET checkpoint_hash=? WHERE id=1", (checkpoint,))
                self._db.execute(
                    "INSERT INTO purge_audit (purged_at, record_count, checkpoint_hash) "
                    "VALUES (?, ?, ?)", (now.isoformat(timespec="microseconds"), len(expired),
                                        checkpoint),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("VACUUM")
        return len(expired)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class BoundGovernedTraceSink:
    """Bind one approved task in trusted host code to the controller's trace API.

    A shared HTTP controller must not reuse this binding across unrelated tasks.
    The host, never the caller payload, chooses the source and task identifiers.
    """

    def __init__(self, store: GovernedTraceStore, *, source_id: str, task_id: str) -> None:
        grant = store._grants.get(source_id)
        if grant is None or task_id not in grant.task_ids:
            raise ValueError("unapproved source or task")
        self._store = store
        self._source_id = source_id
        self._task_id = task_id

    def append(self, trace: DecisionTrace) -> LedgerRecord:
        return self._store.append(trace, source_id=self._source_id, task_id=self._task_id)

