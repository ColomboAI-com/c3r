import json
import unittest
from concurrent.futures import ThreadPoolExecutor

from c3r.telemetry.trace import DecisionTrace
from c3r.telemetry.trace_ledger import TraceLedger


def trace(run_id: str) -> DecisionTrace:
    return DecisionTrace(
        run_id=run_id,
        state_hash="state-hash",
        access_level="shadow",
        model_provider="deterministic",
        candidate_ids=("STOP",),
        probabilities={},
        utility_quantiles={"STOP": 0.0},
        selected_action_id="STOP",
        authority_result="not-requested",
        system_cost={"latency_ms": 1.0},
        task_outcome={"success": True},
        artifact_refs=(),
    )


class TraceLedgerTests(unittest.TestCase):
    def test_hash_chain_replays_and_detects_tampering(self) -> None:
        ledger = TraceLedger()
        first = ledger.append(trace("run-1"))
        second = ledger.append(trace("run-2"))

        self.assertEqual(second.previous_hash, first.record_hash)
        self.assertTrue(TraceLedger.verify(ledger.records))

        tampered = json.loads(second.canonical_json)
        tampered["authority_result"] = "committed"
        corrupted = second.__class__(
            previous_hash=second.previous_hash,
            record_hash=second.record_hash,
            canonical_json=json.dumps(tampered, sort_keys=True, separators=(",", ":")),
        )
        self.assertFalse(TraceLedger.verify((first, corrupted)))

    def test_serialized_ledger_round_trips(self) -> None:
        ledger = TraceLedger()
        ledger.append(trace("run-1"))

        restored = TraceLedger.from_jsonl(ledger.to_jsonl())

        self.assertTrue(TraceLedger.verify(restored.records))
        self.assertEqual(restored.records[0].record_hash, ledger.records[0].record_hash)

    def test_concurrent_appends_keep_one_valid_chain(self) -> None:
        ledger = TraceLedger()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: ledger.append(trace(f"run-{index}")), range(100)))

        self.assertEqual(len(ledger.records), 100)
        self.assertTrue(TraceLedger.verify(ledger.records))


if __name__ == "__main__":
    unittest.main()
