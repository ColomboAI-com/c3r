"""Parity tests for the Postgres access store against the SQLite contract.

Gated: runs only when pg8000 is importable and C3R_TEST_PG_DSN points at a
disposable Postgres database. Otherwise skipped, so the default suite is
dependency-free and unchanged.

    C3R_TEST_PG_DSN=postgresql://c3r:pw@127.0.0.1:5432/c3r_access_test \
        python -m unittest tests.test_pg_access -v
"""
import importlib.util
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import json
import subprocess
import sys
from typing import Any
from unittest.mock import patch

from c3r.api_access import IssuedKey

DSN = os.environ.get("C3R_TEST_PG_DSN", "")
_HAVE_DRIVER = importlib.util.find_spec("pg8000") is not None


@unittest.skipUnless(DSN and _HAVE_DRIVER, "requires pg8000 and C3R_TEST_PG_DSN")
class PostgresAccessStoreParityTests(unittest.TestCase):
    def setUp(self) -> None:
        from c3r.pg_access import PostgresAccessStore
        self.now = [1_000_000.0]
        self.store = PostgresAccessStore(DSN, clock=lambda: self.now[0], pool_size=4)
        self.addCleanup(self.store.close)
        self.tenant = "t" + uuid.uuid4().hex
        self.project = "p" + uuid.uuid4().hex
        self.store.create_project(self.tenant, self.project, rpm=600, key_rps=2)

    def _issue(self, scopes: set[str], *, ttl: float = 3600, live: bool = True) -> IssuedKey:
        return self.store.issue_key(self.tenant, self.project, set(scopes), live=live,
                                    expires_at=self.now[0] + ttl)

    def test_issue_authenticate_roundtrip_and_scopes(self) -> None:
        issued = self._issue({"models:read", "responses:write"})
        principal = self.store.authenticate(issued.secret)
        self.assertIsNotNone(principal)
        assert principal is not None
        self.assertEqual((principal.tenant_id, principal.project_id), (self.tenant, self.project))
        self.assertEqual(principal.scopes, frozenset({"models:read", "responses:write"}))

    def test_tampered_and_unknown_keys_rejected(self) -> None:
        issued = self._issue({"models:read"})
        self.assertIsNone(self.store.authenticate(issued.secret[:-1] + ("A" if issued.secret[-1] != "A" else "B")))
        self.assertIsNone(self.store.authenticate("c3r_sk_live_" + "0" * 24 + "_" + "a" * 43))
        self.assertIsNone(self.store.authenticate("not-a-key"))

    def test_revocation_and_expiry(self) -> None:
        issued = self._issue({"models:read"})
        self.store.revoke_key(self.tenant, self.project, issued.key_id)
        self.assertIsNone(self.store.authenticate(issued.secret))
        with self.assertRaises(ValueError):
            self.store.revoke_key(self.tenant, "p" + uuid.uuid4().hex, issued.key_id)
        short = self._issue({"models:read"}, ttl=10)
        self.assertIsNotNone(self.store.authenticate(short.secret))
        self.now[0] += 20
        self.assertIsNone(self.store.authenticate(short.secret))

    def test_admit_enforces_key_rate_limit(self) -> None:
        issued = self._issue({"models:read"})
        principal = self.store.authenticate(issued.secret)
        assert principal is not None
        self.assertTrue(self.store.admit(principal))
        self.assertTrue(self.store.admit(principal))
        self.assertFalse(self.store.admit(principal))  # key_rps=2 exhausted this second
        self.now[0] += 1
        self.assertTrue(self.store.admit(principal))

    def test_concurrent_first_window_never_exceeds_project_quota(self) -> None:
        project = "p" + uuid.uuid4().hex
        self.store.create_project(self.tenant, project, rpm=1, key_rps=1)
        keys = [self.store.issue_key(self.tenant, project, {"models:read"}) for _ in range(8)]
        principals = [self.store.authenticate(key.secret) for key in keys]
        self.assertTrue(all(principal is not None for principal in principals))
        start = threading.Barrier(8)

        def attempt(index: int) -> bool:
            start.wait(timeout=5)
            principal = principals[index]
            assert principal is not None
            return self.store.admit(principal)

        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(attempt, range(8)))
        self.assertEqual(sum(results), 1)

    def test_failed_connections_do_not_permanently_consume_pool_capacity(self) -> None:
        driver: Any = importlib.import_module("pg8000.dbapi")
        unknown_key = "c3r_sk_live_" + "0" * 24 + "_" + "a" * 43
        # Break and discard the initially pooled connection at the DB boundary.
        with patch.object(driver.Connection, "cursor", side_effect=driver.InterfaceError("fixture")):
            with self.assertRaises((driver.Error, sqlite3.Error, OSError)):
                self.store.authenticate(unknown_key)
        with patch.object(driver, "connect", side_effect=driver.InterfaceError("fixture")):
            for _ in range(4):
                with self.assertRaises((driver.Error, sqlite3.Error, OSError)):
                    self.store.authenticate(unknown_key)
        outcome: list[object] = []

        def recover() -> None:
            try:
                outcome.append(self.store.authenticate(unknown_key))
            except Exception as error:
                outcome.append(type(error).__name__)

        thread = threading.Thread(target=recover, daemon=True)
        thread.start()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive(), "failed connection reservations leaked pool capacity")
        self.assertEqual(outcome, [None])

    def test_database_error_is_normalized_without_exporting_driver_diagnostics(self) -> None:
        driver: Any = importlib.import_module("pg8000.dbapi")
        with patch.object(driver.Connection, "cursor", side_effect=driver.InterfaceError("PRIVATE_DB_DETAIL")):
            with self.assertRaisesRegex(OSError, "^access store unavailable$"):
                self.store.project_usage(self.tenant, self.project)

    def test_pool_wait_is_bounded_when_all_connections_are_busy(self) -> None:
        from c3r.pg_access import PostgresAccessStore
        driver: Any = importlib.import_module("pg8000.dbapi")
        store = PostgresAccessStore(DSN, pool_size=1, pool_timeout_seconds=0.05)
        self.addCleanup(store.close)
        entered, release = threading.Event(), threading.Event()
        original: Any = driver.Cursor.execute

        def execute(cursor: Any, operation: str, *args: Any, **kwargs: Any) -> Any:
            entered.set()
            release.wait(timeout=2)
            return original(cursor, operation, *args, **kwargs)

        failures: list[Exception] = []

        def hold() -> None:
            try:
                store.project_usage(self.tenant, self.project)
            except Exception as error:
                failures.append(error)

        with patch.object(driver.Cursor, "execute", execute):
            thread = threading.Thread(target=hold, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                with self.assertRaisesRegex(OSError, "^access store unavailable$"):
                    store.project_usage(self.tenant, self.project)
            finally:
                release.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])

    def test_operator_cli_issues_revokes_and_purges_the_selected_postgres_store(self) -> None:
        tenant, project = "t" + uuid.uuid4().hex, "p" + uuid.uuid4().hex

        def command(*arguments: str):
            run = subprocess.run([sys.executable, "-m", "c3r.key_management", "--backend", "postgres",
                "--dsn-env", "C3R_TEST_PG_DSN", *arguments, "--tenant", tenant, "--project", project],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, "selected-backend operator command refused")
            return json.loads(run.stdout)

        self.assertEqual(command("project")["status"], "created")
        issued = command("issue", "--scope", "models:read")
        principal = self.store.authenticate(issued["api_key"])
        self.assertIsNotNone(principal)
        assert principal is not None
        self.store.record_usage(principal, "req_" + uuid.uuid4().hex, route="/v1/models",
            model=None, status=200, latency_ms=1, input_tokens=None, output_tokens=None,
            system_one_invocations=None, system_two_invocations=None)
        self.assertEqual(command("purge", "--retention-seconds", "60")["usage_deleted"], 1)
        self.assertEqual(command("revoke", "--key-id", issued["api_key_id"])["status"], "revoked")
        self.assertIsNone(self.store.authenticate(issued["api_key"]))

    def test_usage_roundtrip_is_payload_free(self) -> None:
        issued = self._issue({"responses:write"})
        principal = self.store.authenticate(issued.secret)
        assert principal is not None
        self.store.record_usage(principal, "req_" + uuid.uuid4().hex, route="/v1/responses",
                                model="c3r-core", status=200, latency_ms=12.5,
                                input_tokens=10, output_tokens=3,
                                system_one_invocations=1, system_two_invocations=1,
                                invocation_basis="adapter_transport_attempts")
        rows = self.store.project_usage(self.tenant, self.project)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["route"], "/v1/responses")
        self.assertNotIn("input", rows[0])  # no prompt/output text stored
        self.assertEqual(rows[0]["cost_basis"], "unmeasured")

    def test_purge_metadata_removes_aged_rows(self) -> None:
        issued = self._issue({"responses:write"})
        principal = self.store.authenticate(issued.secret)
        assert principal is not None
        self.store.record_usage(principal, "req_" + uuid.uuid4().hex, route="/v1/models",
                                model=None, status=200, latency_ms=1.0, input_tokens=None,
                                output_tokens=None, system_one_invocations=None,
                                system_two_invocations=None)
        self.now[0] += 100000  # advance well past retention
        result = self.store.purge_metadata(self.tenant, self.project, retention_seconds=60)
        deleted = result["usage_deleted"]
        assert isinstance(deleted, int)
        self.assertGreaterEqual(deleted, 1)
        self.assertEqual(self.store.project_usage(self.tenant, self.project), [])


if __name__ == "__main__":
    unittest.main()
