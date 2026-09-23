import unittest
from datetime import datetime, timedelta, timezone

from c3r.retention_job import DELETE_AFTER_DAYS, StoredObject, _created_at, purge


NOW = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, objects):
        self.objects = list(objects)
        self.deleted = []

    def list_all(self):
        return tuple(self.objects)

    def delete_if_generation(self, obj):
        self.deleted.append((obj.name, obj.generation))
        self.objects = [item for item in self.objects if item != obj]


class RetentionJobTests(unittest.TestCase):
    def test_deletes_only_expired_generation_and_verifies_empty_overdue_set(self):
        old = StoredObject("traces/old", 3, NOW - timedelta(days=DELETE_AFTER_DAYS))
        fresh = StoredObject("traces/new", 4, NOW - timedelta(days=1))
        client = FakeClient([old, fresh])

        report = purge(client, now=NOW)

        self.assertEqual(client.deleted, [(old.name, old.generation)])
        self.assertEqual(client.objects, [fresh])
        self.assertEqual(report["expired_remaining"], 0)
        self.assertFalse(report["trace_collection_enabled"])

    def test_surviving_expired_object_fails_closed(self):
        old = StoredObject("traces/old", 3, NOW - timedelta(days=29))

        class NonDeletingClient(FakeClient):
            def delete_if_generation(self, obj):
                self.deleted.append((obj.name, obj.generation))

        with self.assertRaisesRegex(RuntimeError, "expired objects remain"):
            purge(NonDeletingClient([old]), now=NOW)

    def test_duplicate_inventory_and_non_utc_clock_rejected(self):
        old = StoredObject("traces/old", 3, NOW - timedelta(days=29))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            purge(FakeClient([old, old]), now=NOW)
        with self.assertRaisesRegex(ValueError, "UTC"):
            purge(FakeClient([]), now=NOW.replace(tzinfo=None))

    def test_creation_timestamp_must_be_timezone_aware(self):
        self.assertEqual(_created_at("2026-09-23T16:00:00Z"), NOW)
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            _created_at("2026-09-23T16:00:00")


if __name__ == "__main__":
    unittest.main()
