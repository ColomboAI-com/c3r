"""Credential recovery through the operator-local CLI; no live cloud state."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from c3r.api_access import AccessStore


class KeyRecoveryCLITests(unittest.TestCase):
    def run_cli(self, database: Path, command: str, destination: Path,
                *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "c3r.key_management", "--database", str(database),
             command, "--destination", str(destination), *extra],
            capture_output=True, text=True, timeout=5, check=False)

    def test_backup_and_restore_preserve_projects_but_do_not_reactivate_old_keys(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = AccessStore(root / "source.sqlite3")
            source.create_project("avori", "staging")
            key = source.issue_key("avori", "staging", {"models:read"})
            backup = root / "backup.sqlite3"
            restored = root / "restored.sqlite3"
            backup_hash = ""
            for command, database, destination in (
                    ("backup", source.path, backup), ("restore", backup, restored)):
                arguments = [sys.executable, "-m", "c3r.key_management", "--database", str(database),
                             command, "--destination", str(destination)]
                if command == "restore":
                    arguments += ["--expected-sha256", backup_hash]
                result = subprocess.run(arguments,
                    capture_output=True, text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["keys_copied"], 1)
                self.assertFalse(receipt["encryption_verified"])
                self.assertNotIn(key.secret, result.stdout + result.stderr)
                if command == "backup":
                    backup_hash = receipt["sha256"]
            recovered = AccessStore(restored)
            self.assertIsNone(recovered.authenticate(key.secret))
            self.assertIsNotNone(source.authenticate(key.secret))
            self.assertEqual(recovered.list_keys("avori", "staging")[0]["revoked"], 1)
            replacement = recovered.issue_key("avori", "staging", {"models:read"})
            self.assertIsNotNone(recovered.authenticate(replacement.secret))

    def test_backup_excludes_usage_history_and_plaintext_keys(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = AccessStore(root / "source.sqlite3")
            source.create_project("avori", "staging", rpm=1, key_rps=1)
            key = source.issue_key("avori", "staging", {"models:read"})
            principal = source.authenticate(key.secret)
            assert principal is not None
            source.dispatch_event(principal, "unique-request-history-marker")
            source.record_usage(principal, "unique-request-history-marker", route="/v1/models",
                                model=None, status=200, latency_ms=5, input_tokens=None,
                                output_tokens=None, system_one_invocations=0, system_two_invocations=0)
            backup = root / "backup.sqlite3"
            result = self.run_cli(source.path, "backup", backup)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            snapshot = AccessStore(backup)
            self.assertEqual(snapshot.project_usage("avori", "staging"), [])
            self.assertEqual(len(source.project_usage("avori", "staging")), 1)
            content = backup.read_bytes()
            self.assertNotIn(b"unique-request-history-marker", content)
            self.assertNotIn(key.secret.encode(), content)
            snapshot_principal = snapshot.authenticate(key.secret)
            assert snapshot_principal is not None
            self.assertTrue(snapshot.admit(snapshot_principal))
            self.assertFalse(snapshot.admit(snapshot_principal))

    def test_backup_cannot_overwrite_source_or_an_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = AccessStore(root / "source.sqlite3")
            source.create_project("avori", "staging")
            key = source.issue_key("avori", "staging", {"models:read"})
            backup = root / "backup.sqlite3"
            self.assertEqual(self.run_cli(source.path, "backup", backup).returncode, 0)
            prior = backup.read_bytes()
            for destination in (backup, source.path):
                with self.subTest(destination=destination.name):
                    result = self.run_cli(source.path, "backup", destination)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn(key.secret, result.stdout + result.stderr)
            self.assertEqual(backup.read_bytes(), prior)
            self.assertIsNotNone(source.authenticate(key.secret))

    def test_restore_hash_mismatch_and_missing_source_create_no_database(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = AccessStore(root / "source.sqlite3")
            backup = root / "backup.sqlite3"
            self.assertEqual(self.run_cli(source.path, "backup", backup).returncode, 0)
            destination = root / "restored.sqlite3"
            mismatch = self.run_cli(backup, "restore", destination, "--expected-sha256", "0" * 64)
            self.assertEqual(mismatch.returncode, 1)
            self.assertFalse(destination.exists())
            missing = root / "missing.sqlite3"
            self.assertEqual(self.run_cli(missing, "backup", destination).returncode, 1)
            self.assertFalse(missing.exists())
            self.assertFalse(destination.exists())

    def test_restore_rejects_ordinary_database_even_with_matching_hash(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = AccessStore(root / "source.sqlite3")
            digest = hashlib.sha256(source.path.read_bytes()).hexdigest()
            result = self.run_cli(source.path, "restore", root / "restored.sqlite3",
                                  "--expected-sha256", digest)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
