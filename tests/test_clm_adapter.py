import math
import time
import unittest

from c3r.feature_flags import FeatureFlags
from c3r.system_one.calibration import CalibrationKey, TemperatureCalibrator
from c3r.system_one.clm_adapter import ClmAdapter, UPSTREAM_CLM_COMMIT
from c3r.system_one.fast_path import CalibratedFastPath
from c3r.system_one.question_registry import TypedQuestion
from tests.test_laya_fast_path import compiled_state


REVISION = "a" * 64


def ranked(payload: dict[str, object]) -> dict[str, object]:
    options = payload["answers"]
    assert isinstance(options, list)
    return {
        "model": "clm-latest",
        "ranked": [
            {"rank": index + 1, "candidate": option, "prob": probability}
            for index, (option, probability) in enumerate(
                zip(reversed(options), (0.9, 0.1), strict=True)
            )
        ]
    }


class ClmAdapterTests(unittest.TestCase):
    def test_default_is_clm_but_global_enable_is_off(self) -> None:
        flags = FeatureFlags.from_mapping({})
        self.assertEqual(flags.system_one_provider, "clm")
        self.assertFalse(flags.system_one_enabled)

    def test_rejects_remote_endpoint_and_mutable_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "local HTTP"):
            ClmAdapter(revision=REVISION, endpoint="https://example.com:8700")
        with self.assertRaisesRegex(ValueError, "immutable"):
            ClmAdapter(revision="latest")
        self.assertEqual(len(UPSTREAM_CLM_COMMIT), 40)

    def test_expired_decision_budget_never_calls_clm(self) -> None:
        def unreachable(_payload: object) -> dict[str, object]:
            self.fail("expired request reached CLM")

        adapter = ClmAdapter(revision=REVISION, transport=unreachable)
        with self.assertRaises(TimeoutError):
            adapter.rank_actions(
                compiled_state(), ("a", "b"), deadline=time.monotonic() - 1
            )

    def test_maps_ranked_probabilities_back_to_fixed_option_order(self) -> None:
        calls: list[object] = []

        def transport(payload: object) -> dict[str, object]:
            calls.append(payload)
            assert isinstance(payload, dict)
            return ranked(payload)

        adapter = ClmAdapter(revision=REVISION, transport=transport)
        prediction = adapter.predict(
            compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),)
        )
        self.assertAlmostEqual(math.exp(prediction["STOP_NOW"][0]), 0.1)
        self.assertAlmostEqual(math.exp(prediction["STOP_NOW"][1]), 0.9)
        self.assertEqual(len(calls), 1)
        self.assertEqual(adapter.rank_actions(compiled_state(), ("a", "b")), (0.1, 0.9))

    def test_fails_closed_on_unknown_duplicate_and_nonfinite_candidates(self) -> None:
        invalid_rows = (
            (("NO", 0.5), ("EXTRA", 0.5)),
            (("NO", 0.5), ("NO", 0.5)),
            (("NO", float("nan")), ("YES", 0.5)),
            (("NO", 0.1), ("YES", 0.1)),
        )
        for rows in invalid_rows:
            response = {
                "model": "clm-latest",
                "ranked": [{"candidate": candidate, "prob": prob} for candidate, prob in rows],
            }
            with self.subTest(response=response), self.assertRaises(ValueError):
                ClmAdapter(revision=REVISION, transport=lambda _payload: response).predict(
                    compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),)
                )

    def test_no_calibration_means_abstention_even_with_high_raw_rank(self) -> None:
        adapter = ClmAdapter(revision=REVISION, transport=lambda payload: ranked(dict(payload)))
        fast = CalibratedFastPath(adapter=adapter, calibrator=TemperatureCalibrator({}))
        outcome = fast.decide(
            compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),),
            action_family="CONTROL", candidate_options=("stop", "continue"),
        )
        self.assertTrue(outcome.abstained)
        self.assertEqual(outcome.answers, {})
        self.assertEqual(outcome.candidate_probabilities, (0.1, 0.9))

    def test_held_out_calibration_enables_typed_answer(self) -> None:
        adapter = ClmAdapter(revision=REVISION, transport=lambda payload: ranked(dict(payload)))
        key = CalibrationKey("STOP_NOW", "CONTROL", "2", "en", "low")
        fast = CalibratedFastPath(
            adapter=adapter, calibrator=TemperatureCalibrator({key: 1.0})
        )
        outcome = fast.decide(
            compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),),
            action_family="CONTROL",
        )
        self.assertFalse(outcome.abstained)
        self.assertEqual(outcome.answers["STOP_NOW"], "YES")


if __name__ == "__main__":
    unittest.main()
