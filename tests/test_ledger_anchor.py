import hmac
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from c3r.telemetry.ledger_anchor import capture_head, sign_head, verify_anchor
from c3r.telemetry.trace import DecisionTrace
from c3r.telemetry.trace_ledger import TraceLedger


def trace(run_id: str) -> DecisionTrace:
    return DecisionTrace(
        run_id=run_id,
        state_hash="a" * 64,
        access_level="internal",
        model_provider="fixture",
        candidate_ids=("STOP",),
        probabilities={},
        utility_quantiles={"STOP": 0.0},
        selected_action_id="STOP",
        authority_result="not-requested",
        system_cost={"latency_ms": 1.0},
        task_outcome={"success": True},
        artifact_refs=(),
    )


class LedgerAnchorTests(unittest.TestCase):
    def test_signed_head_matches_chain_and_detects_removal_or_alteration(self) -> None:
        # Test-only signer. Deployment must use a key unavailable to the writer.
        test_key = b"fixture-only-key"
        sign = lambda payload: hmac.digest(test_key, payload, "sha256")
        verify = lambda _key_id, payload, signature: hmac.compare_digest(
            sign(payload), signature
        )
        ledger = TraceLedger()
        ledger.append(trace("one"))
        ledger.append(trace("two"))
        head = capture_head(
            sequence=2,
            record_hash=ledger.records[-1].record_hash,
            policy_version="fixture-v1",
            clock=lambda: datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        anchor = sign_head(head, key_id="test-only", signer=sign)

        self.assertTrue(TraceLedger.verify(ledger.records))
        self.assertTrue(verify_anchor(anchor, sequence=2,
                                      record_hash=ledger.records[-1].record_hash,
                                      verifier=verify))
        self.assertFalse(verify_anchor(anchor, sequence=1,
                                       record_hash=ledger.records[0].record_hash,
                                       verifier=verify))
        self.assertFalse(verify_anchor(anchor, sequence=2,
                                       record_hash="f" * 64, verifier=verify))
        self.assertFalse(verify_anchor(replace(anchor, signature_hex="00"), sequence=2,
                                       record_hash=head.record_hash, verifier=verify))

    def test_rejects_invalid_head_and_empty_signature(self) -> None:
        with self.assertRaises(ValueError):
            capture_head(sequence=-1, record_hash="0" * 64, policy_version="v1")
        with self.assertRaises(ValueError):
            capture_head(sequence=0, record_hash="not-a-hash", policy_version="v1")
        head = capture_head(sequence=0, record_hash="0" * 64, policy_version="v1")
        with self.assertRaises(ValueError):
            sign_head(head, key_id="test-only", signer=lambda _payload: b"")


if __name__ == "__main__":
    unittest.main()

