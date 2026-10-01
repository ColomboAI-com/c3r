import unittest

from scripts.run_trace_control_dry_run import run


class TraceControlDryRunTests(unittest.TestCase):
    def test_fixture_only_report_passes_without_claiming_deployed_controls(self):
        report = run()
        self.assertTrue(report["all_local_checks_passed"])
        self.assertFalse(report["live_trace_collection_enabled"])
        self.assertEqual(len(report["checks"]), 9)
        self.assertIn("deployed encryption and IAM", report["not_verified_by_this_run"])


if __name__ == "__main__":
    unittest.main()

