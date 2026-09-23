import unittest

from c3r.serve import load_host_builder
from c3r.staging_host import EphemeralStagingSink
from c3r.telemetry.trace import DecisionTrace


class StagingHostTests(unittest.TestCase):
    def test_staging_builder_cannot_enable_decisions_or_effects(self):
        controller, factory = load_host_builder("c3r.staging_host:build")()
        self.assertFalse(controller.effect_execution_enabled)
        request = factory.build({"goal": "fixture", "current_subgoal": "check"})
        self.assertEqual(request.estimates, {})
        outcome = controller.run(request)
        self.assertEqual(outcome.reason, "C3R_DISABLED")
        self.assertIsNone(outcome.selected_action_id)

    def test_staging_sink_has_no_row_store_or_cross_request_chain(self):
        trace = DecisionTrace(
            run_id="fixture_run", state_hash="a" * 64, access_level="internal",
            model_provider="fixture", candidate_ids=(), probabilities={},
            utility_quantiles={}, selected_action_id=None,
            authority_result="not_attempted", system_cost={},
            task_outcome={"status": "C3R_DISABLED"}, artifact_refs=(),
        )
        sink = EphemeralStagingSink()
        first = sink.append(trace)
        second = sink.append(trace)
        self.assertEqual(first.record_hash, second.record_hash)
        self.assertEqual(first.previous_hash, "0" * 64)
        self.assertFalse(hasattr(sink, "records"))


if __name__ == "__main__":
    unittest.main()

