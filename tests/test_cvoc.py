import unittest

from c3r.cvoc import RobustCvocController
from c3r.state_schema import ActionCandidate, ActionFamily, RiskClass, ValueEstimate


class CvocControllerTests(unittest.TestCase):
    def test_selects_highest_positive_conservative_lower_bound(self) -> None:
        local = ActionCandidate("local", ActionFamily.LOCAL_MODEL, RiskClass.READ_ONLY, 0.0)
        frontier = ActionCandidate("frontier", ActionFamily.FRONTIER_MODEL, RiskClass.READ_ONLY, 0.0)
        estimates = {
            "local": ValueEstimate(expected_gain=0.7, total_cost=0.2, risk_penalty=0.0, uncertainty=0.1),
            "frontier": ValueEstimate(
                expected_gain=1.1, total_cost=0.4, risk_penalty=0.1, uncertainty=0.05
            ),
        }

        decision = RobustCvocController(uncertainty_multiplier=2.0).select(
            (local, frontier), estimates
        )

        self.assertEqual(decision.selected.id, "frontier")
        self.assertAlmostEqual(decision.lower_bound, 0.5)

    def test_stops_when_all_lower_bounds_are_non_positive(self) -> None:
        candidate = ActionCandidate("frontier", ActionFamily.FRONTIER_MODEL, RiskClass.READ_ONLY, 0.0)
        estimates = {
            "frontier": ValueEstimate(
                expected_gain=0.3, total_cost=0.2, risk_penalty=0.0, uncertainty=0.1
            )
        }

        decision = RobustCvocController(uncertainty_multiplier=2.0).select(
            (candidate,), estimates
        )

        self.assertIsNone(decision.selected)
        self.assertEqual(decision.fallback, "STOP")


if __name__ == "__main__":
    unittest.main()

