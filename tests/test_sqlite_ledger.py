import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from c3r.telemetry.sqlite_ledger import SqliteTraceLedger
from c3r.telemetry.trace_ledger import TraceLedger
from tests.test_trace_ledger import trace


class SqliteTraceLedgerTests(unittest.TestCase):
    def test_records_survive_restart_and_concurrent_appends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.sqlite3"
            ledger = SqliteTraceLedger(path)
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: ledger.append(trace(f"run-{i}")), range(100)))
            ledger.close()

            reopened = SqliteTraceLedger(path)
            self.assertEqual(len(reopened.records), 100)
            self.assertTrue(TraceLedger.verify(reopened.records))
            reopened.close()

    def test_tampering_is_detected_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.sqlite3"
            ledger = SqliteTraceLedger(path)
            ledger.append(trace("run-1"))
            ledger.close()
            db = sqlite3.connect(path)
            try:
                db.execute("UPDATE records SET record_hash = ? WHERE sequence = 1", ("0" * 64,))
                db.commit()
            finally:
                db.close()

            with self.assertRaises(ValueError):
                SqliteTraceLedger(path)


if __name__ == "__main__":
    unittest.main()
