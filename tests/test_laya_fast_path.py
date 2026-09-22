import unittest
from dataclasses import dataclass

from c3r.state_schema import CompiledState
from c3r.system_one.calibration import CalibrationKey, TemperatureCalibrator
from c3r.system_one.fast_path import LayaFastPath
from c3r.system_one.laya_adapter import LayaAdapter
from c3r.system_one.laya_backend import HubModelMetadata, PinnedLayaBackend
from c3r.system_one.question_registry import TypedQuestion


def compiled_state() -> CompiledState:
    return CompiledState(
        goal="Select compute",
        current_subgoal="Choose next action",
        verified_facts=(),
        open_questions=(),
        recent_failures=(),
        available_action_families=(),
        tool_summary=(),
        model_inventory=(),
        budget={},
        runtime_summary={},
        risk={"consequence": "low"},
        reversibility="reversible",
        approval_required=False,
        data_boundary="local",
        rollback_state=None,
        ambiguity=0.0,
        state_compilation_confidence=1.0,
        provenance={},
    )


class LayaFastPathTests(unittest.TestCase):
    def test_calibrates_typed_probabilities_and_selects_answer(self) -> None:
        question = TypedQuestion("STOP_NOW", ("NO", "YES"))
        adapter = LayaAdapter(
            model_id="convaiinnovations/laya",
            revision="1c5edc17a7acd8701df6fc341c0d179f1c62c982",
            backend=lambda _state, _questions: {"STOP_NOW": (0.0, 2.0)},
        )
        key = CalibrationKey("STOP_NOW", "LOCAL_MODEL", "2", "en", "low")
        fast_path = LayaFastPath(
            adapter=adapter,
            calibrator=TemperatureCalibrator({key: 1.0}),
            minimum_top_probability=0.7,
            minimum_margin=0.2,
        )

        result = fast_path.decide(
            compiled_state(), (question,), action_family="LOCAL_MODEL", language="en"
        )

        self.assertFalse(result.abstained)
        self.assertEqual(result.answers["STOP_NOW"], "YES")
        self.assertGreater(result.probabilities["STOP_NOW"][1], 0.8)
        self.assertEqual(result.model_revision, adapter.revision)

    def test_abstains_when_calibration_slice_is_missing(self) -> None:
        question = TypedQuestion("STOP_NOW", ("NO", "YES"))
        adapter = LayaAdapter(
            model_id="convaiinnovations/laya",
            revision="1c5edc17a7acd8701df6fc341c0d179f1c62c982",
            backend=lambda _state, _questions: {"STOP_NOW": (0.0, 2.0)},
        )
        fast_path = LayaFastPath(
            adapter=adapter,
            calibrator=TemperatureCalibrator({}),
        )

        result = fast_path.decide(
            compiled_state(), (question,), action_family="LOCAL_MODEL", language="en"
        )

        self.assertTrue(result.abstained)
        self.assertIn("missing calibration", result.reasons[0])

    def test_non_finite_logits_fail_closed(self) -> None:
        question = TypedQuestion("STOP_NOW", ("NO", "YES"))
        key = CalibrationKey("STOP_NOW", "LOCAL_MODEL", "2", "en", "low")
        adapter = LayaAdapter(
            model_id="convaiinnovations/laya",
            revision="1c5edc17a7acd8701df6fc341c0d179f1c62c982",
            backend=lambda _state, _questions: {"STOP_NOW": (float("nan"), 0.0)},
        )
        fast_path = LayaFastPath(
            adapter=adapter,
            calibrator=TemperatureCalibrator({key: 1.0}),
        )

        result = fast_path.decide(
            compiled_state(), (question,), action_family="LOCAL_MODEL"
        )

        self.assertTrue(result.abstained)
        self.assertEqual(result.answers, {})
        self.assertIn("invalid prediction", result.reasons[0])

    def test_pinned_backend_verifies_revision_and_license_before_loading(self) -> None:
        revision = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
        calls: list[tuple[str, str]] = []

        @dataclass
        class FakeAgent:
            def predict(self, _state: object, _questions: object) -> dict[str, object]:
                return {
                    "answers": {
                        "STOP_NOW": {
                            "probabilities": {"NO": 0.75, "YES": 0.25}
                        }
                    }
                }

        backend = PinnedLayaBackend(
            model_id="convaiinnovations/laya",
            revision=revision,
            metadata_resolver=lambda _model, _revision: HubModelMetadata(
                sha=revision, license="apache-2.0"
            ),
            snapshot_fetcher=lambda model, rev: calls.append((model, rev)) or "C:/model",
            agent_loader=lambda _path, _device: FakeAgent(),
        )

        output = backend(compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),))

        self.assertEqual(calls, [("convaiinnovations/laya", revision)])
        self.assertAlmostEqual(output["STOP_NOW"][0], -0.287682, places=5)

    def test_pinned_backend_rejects_upstream_license_mismatch(self) -> None:
        revision = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
        backend = PinnedLayaBackend(
            model_id="convaiinnovations/laya",
            revision=revision,
            metadata_resolver=lambda _model, _revision: HubModelMetadata(
                sha=revision, license="unknown"
            ),
            snapshot_fetcher=lambda _model, _revision: "C:/model",
            agent_loader=lambda _path, _device: object(),
        )

        with self.assertRaisesRegex(ValueError, "license"):
            backend.prepare()

    def test_pinned_backend_drops_non_finite_probabilities(self) -> None:
        revision = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"

        @dataclass
        class FakeAgent:
            def predict(self, _state: object, _questions: object) -> dict[str, object]:
                return {
                    "answers": {
                        "STOP_NOW": {
                            "probabilities": {"NO": float("nan"), "YES": 0.25}
                        }
                    }
                }

        backend = PinnedLayaBackend(
            model_id="convaiinnovations/laya",
            revision=revision,
            metadata_resolver=lambda _model, _revision: HubModelMetadata(
                sha=revision, license="apache-2.0"
            ),
            snapshot_fetcher=lambda _model, _revision: "C:/model",
            agent_loader=lambda _path, _device: FakeAgent(),
        )

        output = backend(compiled_state(), (TypedQuestion("STOP_NOW", ("NO", "YES")),))

        self.assertEqual(output, {})


if __name__ == "__main__":
    unittest.main()
