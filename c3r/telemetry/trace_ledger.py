"""Canonical hash-chain integrity checks for C3R decision traces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from threading import Lock

from .trace import DecisionTrace

_GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    previous_hash: str
    record_hash: str
    canonical_json: str


def _record_hash(previous_hash: str, canonical_json: str) -> str:
    return hashlib.sha256(
        (previous_hash + "\n" + canonical_json).encode("utf-8")
    ).hexdigest()


class TraceLedger:
    def __init__(self, records: tuple[LedgerRecord, ...] = ()) -> None:
        if records and not self.verify(records):
            raise ValueError("trace ledger hash chain is invalid")
        self._records = list(records)
        self._lock = Lock()

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def append(self, trace: DecisionTrace) -> LedgerRecord:
        canonical = json.dumps(
            asdict(trace),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        with self._lock:
            previous = self._records[-1].record_hash if self._records else _GENESIS_HASH
            record = LedgerRecord(previous, _record_hash(previous, canonical), canonical)
            self._records.append(record)
            return record

    def to_jsonl(self) -> str:
        return "\n".join(
            json.dumps(asdict(record), sort_keys=True, separators=(",", ":"))
            for record in self.records
        )

    @classmethod
    def from_jsonl(cls, payload: str) -> TraceLedger:
        records: list[LedgerRecord] = []
        for line_number, line in enumerate(payload.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                record = LedgerRecord(
                    previous_hash=str(value["previous_hash"]),
                    record_hash=str(value["record_hash"]),
                    canonical_json=str(value["canonical_json"]),
                )
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(f"invalid trace ledger record on line {line_number}") from error
            records.append(record)
        return cls(tuple(records))

    @staticmethod
    def verify(records: tuple[LedgerRecord, ...]) -> bool:
        previous = _GENESIS_HASH
        for record in records:
            if record.previous_hash != previous:
                return False
            try:
                decoded = json.loads(record.canonical_json)
                canonical = json.dumps(
                    decoded,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                return False
            if canonical != record.canonical_json:
                return False
            if _record_hash(previous, canonical) != record.record_hash:
                return False
            previous = record.record_hash
        return True
