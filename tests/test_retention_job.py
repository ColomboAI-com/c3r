import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from c3r.retention_job import (
    DELETE_AFTER_DAYS, GcsJsonClient, StoredObject, _created_at,
    _verify_runtime_project, bucket_from_environment, purge,
)


NOW = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
BUCKET = "colomboai-c3r-staging-traces-123456789012"


class FakeClient:
    def __init__(self, objects):
        self.bucket = BUCKET
        self.objects = list(objects)
        self.deleted = []

    def list_all(self):
        return tuple(self.objects)

    def delete_generation(self, obj):
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
            def delete_generation(self, obj):
                self.deleted.append((obj.name, obj.generation))

        with self.assertRaisesRegex(RuntimeError, "expired objects remain"):
            purge(NonDeletingClient([old]), now=NOW)

    def test_duplicate_inventory_and_non_utc_clock_rejected(self):
        old = StoredObject("traces/old", 3, NOW - timedelta(days=29))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            purge(FakeClient([old, old]), now=NOW)
        with self.assertRaisesRegex(ValueError, "UTC"):
            purge(FakeClient([]), now=NOW.replace(tzinfo=None))

    def test_distinct_generations_are_purged_without_treating_them_as_duplicates(self):
        old = StoredObject("traces/replaced", 3, NOW - timedelta(days=29))
        fresh = StoredObject("traces/replaced", 4, NOW - timedelta(days=1))
        client = FakeClient([old, fresh])

        report = purge(client, now=NOW)

        self.assertEqual(client.deleted, [(old.name, old.generation)])
        self.assertEqual(client.objects, [fresh])
        self.assertEqual(report["expired_remaining"], 0)

    def test_gcs_transport_lists_versions_and_deletes_exact_generation(self):
        client = object.__new__(GcsJsonClient)
        client.bucket = BUCKET
        client._storage_api = "https://storage.googleapis.com/storage/v1/b/" + BUCKET + "/o"
        requests = []

        def fake_request(method, url):
            requests.append((method, url))
            if method == "GET":
                return {"items": [
                    {"name": "traces/replaced", "generation": "3", "timeCreated": "2026-08-01T00:00:00Z"},
                    {"name": "traces/replaced", "generation": "4", "timeCreated": "2026-09-23T00:00:00Z"},
                ]}
            return None

        client._request = fake_request
        objects = client.list_all()
        client.delete_generation(objects[0])

        self.assertEqual([obj.generation for obj in objects], [3, 4])
        self.assertIn("versions=true", requests[0][1])
        self.assertIn("generation=3", requests[1][1])
        self.assertNotIn("ifGenerationMatch", requests[1][1])

    def test_creation_timestamp_must_be_timezone_aware(self):
        self.assertEqual(_created_at("2026-09-23T16:00:00Z"), NOW)
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            _created_at("2026-09-23T16:00:00")

    def test_dedicated_bucket_must_be_explicit_and_narrow(self):
        self.assertEqual(bucket_from_environment({"C3R_TRACE_BUCKET": BUCKET}), BUCKET)
        for value in ("", "colomboai-c3r-private-traces-123456789012",
                      "unrelated-bucket", "colomboai-c3r-staging-traces-123456789012/other"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "C3R_TRACE_BUCKET"):
                bucket_from_environment({"C3R_TRACE_BUCKET": value})
        client = FakeClient([])
        client.bucket = "unrelated-bucket"
        with self.assertRaisesRegex(ValueError, "C3R_TRACE_BUCKET"):
            purge(client, now=NOW)

    def test_runtime_project_must_match_bucket_suffix(self):
        _verify_runtime_project(BUCKET, "123456789012")
        with self.assertRaisesRegex(ValueError, "project number"):
            _verify_runtime_project(BUCKET, "999999999999")

    def test_gcs_client_rejects_wrong_project_before_credential_request(self):
        with patch("c3r.retention_job.urlopen", return_value=io.BytesIO(b"999999999999")) as open_url:
            with self.assertRaisesRegex(ValueError, "project number"):
                GcsJsonClient(BUCKET)
        self.assertEqual(open_url.call_count, 1)

    def test_gcs_client_accepts_metadata_bound_bucket(self):
        token = b'{"access_token":"' + b"x" * 24 + b'"}'
        with patch("c3r.retention_job.urlopen", side_effect=[
            io.BytesIO(b"123456789012"), io.BytesIO(token),
        ]) as open_url:
            client = GcsJsonClient(BUCKET)
        self.assertEqual(client.bucket, BUCKET)
        self.assertEqual(open_url.call_count, 2)


if __name__ == "__main__":
    unittest.main()

