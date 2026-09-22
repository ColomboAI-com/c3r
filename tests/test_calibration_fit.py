import unittest

from c3r.system_one.calibration import CalibrationKey
from c3r.system_one.calibration_fit import CalibrationExample, fit_calibration


class CalibrationFitTests(unittest.TestCase):
    def test_temperature_fit_improves_or_preserves_nll(self) -> None:
        key = CalibrationKey("STOP_NOW", "GLOBAL", "2", "en", "low")
        examples = [
            CalibrationExample(key, (4.0, 0.0), 0),
            CalibrationExample(key, (4.0, 0.0), 0),
            CalibrationExample(key, (0.0, 4.0), 1),
            CalibrationExample(key, (4.0, 0.0), 1),
        ]

        result = fit_calibration(examples, minimum_slice_size=4)

        report = result.reports[key]
        self.assertLessEqual(report.after.nll, report.before.nll)
        self.assertGreater(result.calibrator.temperatures[key], 0.0)
        self.assertEqual(report.sample_size, 4)

    def test_skips_unsupported_small_slices(self) -> None:
        key = CalibrationKey("STOP_NOW", "GLOBAL", "2", "en", "high")

        result = fit_calibration(
            [CalibrationExample(key, (1.0, 0.0), 0)],
            minimum_slice_size=2,
        )

        self.assertEqual(result.calibrator.temperatures, {})
        self.assertEqual(result.skipped_slices[key], "insufficient support: 1 < 2")


if __name__ == "__main__":
    unittest.main()
