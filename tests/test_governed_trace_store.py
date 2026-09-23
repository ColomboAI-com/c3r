import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from c3r.telemetry.governed_store import BoundGovernedTraceSink, GovernedTraceStore, SourceGrant
from c3r.telemetry.trace import DecisionTrace


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def trace(**changes):
    fields = dict(
        run_id="run_001",
        state_hash="a" * 64,
        access_level="internal",
        model_provider="deepseek_v4_1_flash",
        candidate_ids=("recommend",),
        probabilities={"route": (0.8, 0.2)},
        utility_quantiles={"selected_lower_bound": 0.3},
        selected_action_id="recommend",
        authority_result="verified",
        system_cost={"latency_ms": 18.0},
        task_outcome={"status": "controlled_success"},
        artifact_refs=(),
    )
    fields.update(changes)
    return DecisionTrace(**fields)


class GovernedTraceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "governed.sqlite3"
        self.grant = SourceGrant(
            source_id="c3r_internal_001",
            owner="wilkont",
            task_ids=frozenset({"task_001"}),
            rights_attested=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def store(self, *, now=NOW):
        return GovernedTraceStore(self.path, grants=(self.grant,), clock=lambda: now)

    def test_admits_only_attested_registered_internal_task(self):
        with self.store() as store:
            record = store.append(trace(), source_id="c3r_internal_001", task_id="task_001")
            self.assertEqual(len(store.records()), 1)
            self.assertEqual(store.records()[0].record_hash, record.record_hash)
            with self.assertRaisesRegex(ValueError, "unapproved source or task"):
                store.append(trace(run_id="run_002"), source_id="laya_logs", task_id="task_001")
            with self.assertRaisesRegex(ValueError, "unapproved source or task"):
                store.append(trace(run_id="run_003"), source_id="c3r_internal_001", task_id="other")
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(trace(), source_id="c3r_internal_001", task_id="task_001")

    def test_unattested_source_cannot_be_registered(self):
        with self.assertRaisesRegex(ValueError, "rights"):
            SourceGrant(source_id="imported", owner="wilkont",
                        task_ids=frozenset({"task_001"}), rights_attested=False)

    def test_trusted_host_can_bind_source_and_task_for_runtime_sink(self):
        with self.store() as store:
            sink = BoundGovernedTraceSink(store, source_id="c3r_internal_001", task_id="task_001")
            record = sink.append(trace())
            self.assertEqual(store.records(), (record,))
            with self.assertRaisesRegex(ValueError, "unapproved source or task"):
                BoundGovernedTraceSink(store, source_id="imported", task_id="task_001")

    def test_rejects_free_text_or_private_artifact_reference(self):
        with self.store() as store:
            with self.assertRaisesRegex(ValueError, "redaction"):
                store.append(trace(task_outcome={"status": "email me at a@example.com"}),
                             source_id="c3r_internal_001", task_id="task_001")
            with self.assertRaisesRegex(ValueError, "redaction"):
                store.append(trace(artifact_refs=("gs://private/object",)),
                             source_id="c3r_internal_001", task_id="task_001")
            self.assertEqual(store.records(), ())

    def test_purges_after_30_days_and_preserves_remaining_chain(self):
        with self.store(now=NOW - timedelta(days=31)) as store:
            first = store.append(trace(), source_id="c3r_internal_001", task_id="task_001")
        with self.store(now=NOW - timedelta(days=1)) as store:
            self.assertEqual(store.purge_expired(), 1)
            second = store.append(trace(run_id="run_002"), source_id="c3r_internal_001",
                                  task_id="task_001")
        with self.store(now=NOW) as store:
            self.assertEqual(store.purge_expired(), 0)
            remaining = store.records()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].record_hash, second.record_hash)
            self.assertEqual(remaining[0].previous_hash, first.record_hash)
            self.assertTrue(store.verify())

    def test_rejects_tampered_database_on_reopen(self):
        with self.store() as store:
            store.append(trace(), source_id="c3r_internal_001", task_id="task_001")
        db = sqlite3.connect(self.path)
        try:
            db.execute("UPDATE records SET canonical_json = '{}' WHERE sequence = 1")
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "hash chain"):
            self.store()

    def test_clock_rollback_cannot_relabel_traces_after_purge(self):
        with self.store() as store:
            store.append(trace(), source_id="c3r_internal_001", task_id="task_001")
        with self.store(now=NOW + timedelta(days=31)) as store:
            self.assertEqual(store.purge_expired(), 1)
        with self.store(now=NOW - timedelta(days=1)) as store:
            with self.assertRaisesRegex(ValueError, "clock moved backwards"):
                store.append(trace(run_id="run_002"), source_id="c3r_internal_001",
                             task_id="task_001")

    def test_overdue_purge_blocks_new_collection_until_purged(self):
        with self.store(now=NOW - timedelta(days=31)) as store:
            store.append(trace(), source_id="c3r_internal_001", task_id="task_001")
        with self.store(now=NOW) as store:
            with self.assertRaisesRegex(ValueError, "retention purge overdue"):
                store.append(trace(run_id="run_002"), source_id="c3r_internal_001",
                             task_id="task_001")
            self.assertEqual(len(store.records()), 1)
            self.assertEqual(store.purge_expired(), 1)
            store.append(trace(run_id="run_002"), source_id="c3r_internal_001",
                         task_id="task_001")
            self.assertEqual(len(store.records()), 1)


if __name__ == "__main__":
    unittest.main()

