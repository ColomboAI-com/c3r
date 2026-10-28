import unittest
from typing import cast

from scripts.run_trace_control_dry_run import run


class TraceControlDryRunTests(unittest.TestCase):
    def test_fixture_only_report_passes_without_claiming_deployed_controls(self):
        report = run()
        self.assertTrue(report["all_local_checks_passed"])
        self.assertFalse(report["live_trace_collection_enabled"])
        checks = report["checks"]
        assert isinstance(checks, dict)
        self.assertEqual(len(cast(dict[object, object], checks)), 9)
        unverified = report["not_verified_by_this_run"]
        assert isinstance(unverified, list)
        self.assertIn("deployed encryption and IAM", cast(list[object], unverified))


if __name__ == "__main__":
    unittest.main()

