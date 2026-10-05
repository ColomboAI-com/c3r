"""Request-local trace hashing without retained rows or a persistent ledger."""

from __future__ import annotations

from .trace import DecisionTrace
from .trace_ledger import LedgerRecord, canonical_trace_json, record_hash


class EphemeralTraceSink:
    """Hash each response independently; the returned record is not stored."""

    def append(self, trace: DecisionTrace) -> LedgerRecord:
        canonical = canonical_trace_json(trace)
        genesis = "0" * 64
        return LedgerRecord(genesis, record_hash(genesis, canonical), canonical)
