import io
import json
import unittest
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.request import Request

from c3r.retention_job import (
    DELETE_AFTER_DAYS,
    GcsJsonClient,
    StoredObject,
    bucket_from_environment,
    purge,
)

NOW = datetime(2026, 9, 23, 16, 0, tzinfo=UTC)
BUCKET = "colomboai-c3r-staging-traces-123456789012"


class FakeClient:
    def __init__(self, objects: Iterable[StoredObject]) -> None:
        self.bucket = BUCKET
        self.objects = list(objects)
        self.deleted: list[tuple[str, int]] = []

    def list_all(self) -> tuple[StoredObject, ...]:
        return tuple(self.objects)

    def delete_generation(self, obj: StoredObject) -> None:
        self.deleted.append((obj.name, obj.generation))
        self.objects = [item for item in self.objects if item != obj]


class RetentionJobTests(unittest.TestCase):
    def test_deletes_only_expired_generation_and_verifies_empty_overdue_set(self) -> None:
        old = StoredObject("traces/old", 3, NOW - timedelta(days=DELETE_AFTER_DAYS))
        fresh = StoredObject("traces/new", 4, NOW - timedelta(days=1))
        client = FakeClient([old, fresh])

        report = purge(client, now=NOW)

        self.assertEqual(client.deleted, [(old.name, old.generation)])
        self.assertEqual(client.objects, [fresh])
        self.assertEqual(report["expired_remaining"], 0)
        self.assertFalse(report["trace_collection_enabled"])

    def test_surviving_expired_object_fails_closed(self) -> None:
        old = StoredObject("traces/old", 3, NOW - timedelta(days=29))

        class NonDeletingClient(FakeClient):
            def delete_generation(self, obj: StoredObject) -> None:
                self.deleted.append((obj.name, obj.generation))

        with self.assertRaisesRegex(RuntimeError, "expired objects remain"):
            purge(NonDeletingClient([old]), now=NOW)

    def test_duplicate_inventory_and_non_utc_clock_rejected(self) -> None:
        old = StoredObject("traces/old", 3, NOW - timedelta(days=29))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            purge(FakeClient([old, old]), now=NOW)
        with self.assertRaisesRegex(ValueError, "UTC"):
            purge(FakeClient([]), now=NOW.replace(tzinfo=None))

    def test_distinct_generations_are_purged_without_treating_them_as_duplicates(self) -> None:
        old = StoredObject("traces/replaced", 3, NOW - timedelta(days=29))
        fresh = StoredObject("traces/replaced", 4, NOW - timedelta(days=1))
        client = FakeClient([old, fresh])

        report = purge(client, now=NOW)

        self.assertEqual(client.deleted, [(old.name, old.generation)])
        self.assertEqual(client.objects, [fresh])
        self.assertEqual(report["expired_remaining"], 0)

    def test_gcs_transport_lists_versions_and_deletes_exact_generation(self) -> None:
        requests: list[tuple[str, str]] = []

        def fake_open(request: Request, *, timeout: int) -> io.BytesIO:
            requests.append((request.get_method(), request.full_url))
            if "numeric-project-id" in request.full_url:
                return io.BytesIO(b"123456789012")
            if "/token" in request.full_url:
                return io.BytesIO(b'{"access_token":"' + b"x" * 24 + b'"}')
            if request.get_method() == "GET":
                return io.BytesIO(json.dumps({"items": [
                    {"name": "traces/replaced", "generation": "3", "timeCreated": "2026-08-01T00:00:00Z"},
                    {"name": "traces/replaced", "generation": "4", "timeCreated": "2026-09-23T00:00:00Z"},
                ]}).encode())
            return io.BytesIO(b"")

        with patch("c3r.retention_job.urlopen", side_effect=fake_open):
            client = GcsJsonClient(BUCKET)
            objects = client.list_all()
            client.delete_generation(objects[0])
        requests = requests[2:]

        self.assertEqual([obj.generation for obj in objects], [3, 4])
        self.assertIn("versions=true", requests[0][1])
        self.assertIn("generation=3", requests[1][1])
        self.assertNotIn("ifGenerationMatch", requests[1][1])

    def test_creation_timestamp_must_be_timezone_aware(self) -> None:
        for timestamp in ("2026-09-23T16:00:00Z", "2026-09-23T16:00:00"):
            inventory = json.dumps({"items": [{"name": "traces/time", "generation": "1",
                                               "timeCreated": timestamp}]}).encode()
            with patch("c3r.retention_job.urlopen", side_effect=[
                io.BytesIO(b"123456789012"),
                io.BytesIO(b'{"access_token":"' + b"x" * 24 + b'"}'),
                io.BytesIO(inventory),
            ]):
                client = GcsJsonClient(BUCKET)
                if timestamp.endswith("Z"):
                    self.assertEqual(client.list_all()[0].created_at, NOW)
                else:
                    with self.assertRaisesRegex(ValueError, "UTC offset"):
                        client.list_all()

    def test_dedicated_bucket_must_be_explicit_and_narrow(self) -> None:
        self.assertEqual(bucket_from_environment({"C3R_TRACE_BUCKET": BUCKET}), BUCKET)
        for value in ("", "colomboai-c3r-private-traces-123456789012",
                      "unrelated-bucket", "colomboai-c3r-staging-traces-123456789012/other"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "C3R_TRACE_BUCKET"):
                bucket_from_environment({"C3R_TRACE_BUCKET": value})
        client = FakeClient([])
        client.bucket = "unrelated-bucket"
        with self.assertRaisesRegex(ValueError, "C3R_TRACE_BUCKET"):
            purge(client, now=NOW)

    def test_runtime_project_must_match_bucket_suffix(self) -> None:
        with patch("c3r.retention_job.urlopen", side_effect=[
            io.BytesIO(b"123456789012"),
            io.BytesIO(b'{"access_token":"' + b"x" * 24 + b'"}'),
        ]):
            self.assertEqual(GcsJsonClient(BUCKET).bucket, BUCKET)
        with (patch("c3r.retention_job.urlopen", return_value=io.BytesIO(b"999999999999")),
              self.assertRaisesRegex(ValueError, "project number")):
            GcsJsonClient(BUCKET)

    def test_gcs_client_rejects_wrong_project_before_credential_request(self) -> None:
        with (patch("c3r.retention_job.urlopen", return_value=io.BytesIO(b"999999999999")) as open_url,
              self.assertRaisesRegex(ValueError, "project number")):
            GcsJsonClient(BUCKET)
        self.assertEqual(open_url.call_count, 1)

    def test_gcs_client_accepts_metadata_bound_bucket(self) -> None:
        token = b'{"access_token":"' + b"x" * 24 + b'"}'
        with patch("c3r.retention_job.urlopen", side_effect=[
            io.BytesIO(b"123456789012"), io.BytesIO(token),
        ]) as open_url:
            client = GcsJsonClient(BUCKET)
        self.assertEqual(client.bucket, BUCKET)
        self.assertEqual(open_url.call_count, 2)


if __name__ == "__main__":
    unittest.main()
