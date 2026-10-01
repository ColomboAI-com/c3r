import unittest
from dataclasses import replace

from c3r.adapters.providers import ProviderExecutionResult
from c3r.candidate_compiler import CandidateCompiler
from c3r.cvoc import RobustCvocController
from c3r.deliberative.envelope import DeliberativeResult
from c3r.feature_flags import FeatureFlags
from c3r.runtime import RuntimeRequest, StandaloneController
from c3r.state_compiler import StateCompiler
from c3r.state_schema import (
    ActionDefinition,
    ActionFamily,
    AuthorityPolicy,
    Provenance,
    RawState,
    RiskClass,
    ValueEstimate,
)
from c3r.system_one.calibration import TemperatureCalibrator
from c3r.system_one.clm_adapter import ClmAdapter
from c3r.system_one.fast_path import CalibratedFastPath, LayaFastPath
from c3r.system_one.laya_adapter import LayaAdapter
from c3r.telemetry.trace_ledger import TraceLedger
from c3r.verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy


KEY = b"verification-test-key"
ACTION_ID = "lookup:0:local:policy"


def request(*, risk: RiskClass = RiskClass.READ_ONLY, provenance: bool = True) -> RuntimeRequest:
    fact = "The record exists"
    raw = RawState(
        goal="Find record",
        current_subgoal="Lookup",
        verified_facts=(fact,),
        available_action_families=(ActionFamily.TOOL,),
        budget={"remaining_usd": 1.0},
        provenance={fact: Provenance("fixture", "2026-09-22T00:00:00Z")}
        if provenance
        else {},
    )
    definition = ActionDefinition(
        id="lookup",
        family=ActionFamily.TOOL,
        subgroup="records",
        operation="get",
        risk_class=risk,
        argument_variants=((('record_id', 'fixture-1'),),),
        placements=("local",),
        verifier_ids=("policy",),
        optimistic_utility=1.0,
        estimated_cost=0.1,
        data_boundary="local",
    )
    return RuntimeRequest(
        raw_state=raw,
        definitions=(definition,),
        policy=AuthorityPolicy(
            frozenset({ActionFamily.TOOL}), frozenset({risk})
        ),
        estimates={ACTION_ID: ValueEstimate(0.9, 0.1, 0.0, 0.1)},
        run_id="fixture-run",
    )


def controller(
    *,
    enabled: bool = True,
    system_one: bool = False,
    deliberative: bool = False,
    accepted: bool = True,
    executor=None,
    fast_path=None,
    deliberator=None,
    system_one_provider: str = "clm",
) -> tuple[StandaloneController, TraceLedger]:
    ledger = TraceLedger()
    verifier = VerifierFirewall(
        {"policy": lambda _: VerifierDecision(accepted, "policy fixture")},
        VerifierPolicy(default_verifier="policy"),
        attestation_key=KEY,
    )
    runtime = StandaloneController(
        flags=FeatureFlags(
            enabled_requested=enabled,
            system_one_requested=system_one,
            deliberative_requested=deliberative,
            system_one_provider=system_one_provider,
        ),
        compiler=StateCompiler(),
        candidates=CandidateCompiler(),
        cvoc=RobustCvocController(),
        verifier=verifier,
        ledger=ledger,
        executor=executor,
        fast_path=fast_path,
        deliberator=deliberator,
    )
    return runtime, ledger


class RuntimeTests(unittest.TestCase):
    def test_executor_configuration_is_rejected_before_any_effect(self) -> None:
        effects = []
        with self.assertRaisesRegex(ValueError, "external effects"):
            controller(executor=effects.append)

        self.assertEqual(effects, [])

    def test_verified_recommendation_has_no_effect_and_is_traced(self) -> None:
        runtime, ledger = controller()
        outcome = runtime.run(request())

        self.assertEqual(outcome.route, "recommendation")
        self.assertEqual(outcome.selected_action_id, ACTION_ID)
        self.assertEqual(outcome.authority_result, "verified_not_committed")
        self.assertEqual(len(ledger.records), 1)
        self.assertTrue(TraceLedger.verify(ledger.records))
        self.assertNotIn("The record exists", ledger.to_jsonl())

    def test_global_disable_stops_before_candidate_or_provider_execution(self) -> None:
        runtime, _ = controller(enabled=False)
        outcome = runtime.run(request())

        self.assertEqual(outcome.reason, "C3R_DISABLED")
        self.assertFalse(runtime.effect_execution_enabled)

    def test_missing_provenance_stops_before_any_effect(self) -> None:
        runtime, _ = controller()
        outcome = runtime.run(request(provenance=False))

        self.assertEqual(outcome.reason, "STATE_UNSAFE_TO_COMPRESS")
        self.assertFalse(runtime.effect_execution_enabled)

    def test_verifier_rejection_stops_before_commit(self) -> None:
        runtime, _ = controller(accepted=False)
        outcome = runtime.run(request())

        self.assertEqual(outcome.reason, "VERIFICATION_REJECTED")
        self.assertFalse(runtime.effect_execution_enabled)

    def test_unavailable_action_family_is_never_compiled(self) -> None:
        runtime, _ = controller()
        req = request()
        req = replace(req, raw_state=replace(req.raw_state, available_action_families=()))

        outcome = runtime.run(req)

        self.assertEqual(outcome.reason, "NO_SAFE_ACTION")
        self.assertIsNone(outcome.selected_action_id)

    def test_external_write_is_unavailable_to_recommendation_only_controller(self) -> None:
        runtime, ledger = controller()
        outcome = runtime.run(request(risk=RiskClass.EXTERNAL_WRITE))

        self.assertEqual(outcome.reason, "EFFECT_EXECUTION_UNAVAILABLE")
        self.assertEqual(outcome.route, "deterministic")
        self.assertIsNone(outcome.selected_action_id)
        self.assertTrue(TraceLedger.verify(ledger.records))

    def test_uncalibrated_system_one_abstains_into_non_authoritative_deliberation(self) -> None:
        adapter = LayaAdapter(
            "convaiinnovations/laya",
            "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
            backend=lambda _state, _questions: {
                "STOP_NOW": (0.0, 3.0),
                "DELIBERATION_REQUIRED": (3.0, 0.0),
            },
        )
        fast_path = LayaFastPath(adapter=adapter, calibrator=TemperatureCalibrator({}))

        class Deliberator:
            def deliberate(self, _state):
                return {"plan": ["inspect"]}

        runtime, _ = controller(
            system_one=True,
            deliberative=True,
            fast_path=fast_path,
            system_one_provider="laya",
            deliberator=Deliberator(),
        )
        outcome = runtime.run(request())

        self.assertEqual(outcome.route, "deliberative")
        self.assertEqual(outcome.reason, "SYSTEM_ONE_ABSTAINED")
        self.assertIsNone(outcome.selected_action_id)
        self.assertFalse(runtime.effect_execution_enabled)

    def test_default_clm_never_silently_runs_laya(self) -> None:
        adapter = LayaAdapter(
            "convaiinnovations/laya",
            "1c5edc17a7acd8701df6fc341c0d179f1c62c982",
            backend=lambda _state, _questions: {},
        )
        runtime, _ = controller(
            system_one=True,
            fast_path=LayaFastPath(adapter=adapter, calibrator=TemperatureCalibrator({})),
        )
        outcome = runtime.run(request())
        self.assertEqual(outcome.reason, "SYSTEM_ONE_PROVIDER_MISMATCH")

    def test_clm_rank_is_advisory_and_abstains_without_calibration(self) -> None:
        def rank(payload):
            options = payload["answers"]
            probability = 1.0 / len(options)
            return {
                "model": "clm-latest",
                "ranked": [
                    {"candidate": option, "prob": probability}
                    for option in options
                ],
            }

        adapter = ClmAdapter(revision="a" * 64, transport=rank)
        runtime, ledger = controller(
            system_one=True,
            fast_path=CalibratedFastPath(
                adapter=adapter, calibrator=TemperatureCalibrator({})
            ),
        )
        outcome = runtime.run(request())
        self.assertEqual(outcome.reason, "SYSTEM_ONE_ABSTAINED_NO_PROVIDER")
        self.assertEqual(outcome.fast_path.candidate_probabilities, (1.0,))
        self.assertIn('"model_provider":"Contrastive-LM/CLM"', ledger.records[-1].canonical_json)

    def test_clm_outage_escalates_without_granting_authority(self) -> None:
        def unavailable(_payload):
            raise OSError("CLM unavailable")

        class Deliberator:
            def deliberate(self, _state):
                return {"plan": ["inspect"]}

        runtime, ledger = controller(
            system_one=True,
            deliberative=True,
            fast_path=CalibratedFastPath(
                adapter=ClmAdapter(revision="a" * 64, transport=unavailable),
                calibrator=TemperatureCalibrator({}),
            ),
            deliberator=Deliberator(),
        )
        outcome = runtime.run(request())
        self.assertEqual(outcome.route, "deliberative")
        self.assertEqual(outcome.reason, "SYSTEM_ONE_FAILURE")
        self.assertIsNone(outcome.selected_action_id)
        self.assertTrue(TraceLedger.verify(ledger.records))

    def test_provider_usage_is_recorded_without_granting_authority(self) -> None:
        class Deliberator:
            def deliberate(self, _state):
                return ProviderExecutionResult(
                    DeliberativeResult(("inspect",), (), (), (), ()),
                    {"latency_ms": 12.0, "input_tokens": 10.0},
                    "deepseek-local", "deepseek-v4.1-flash",
                )

        runtime, ledger = controller(deliberative=True, deliberator=Deliberator())
        req = request()
        req = RuntimeRequest(
            req.raw_state, req.definitions, req.policy, {}, req.run_id,
        )
        # A deliberative candidate, rather than a tool, is selected by CVoC.
        definition = ActionDefinition(
            "reason", ActionFamily.DELIBERATE, "model", "plan", RiskClass.READ_ONLY,
            ((),), ("local",), ("policy",), 1.0, 0.1,
        )
        req = RuntimeRequest(
            replace(req.raw_state, available_action_families=(ActionFamily.DELIBERATE,)),
            (definition,),
            AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}), frozenset({RiskClass.READ_ONLY})),
            {"reason:0:local:policy": ValueEstimate(0.9, 0.1, 0.0, 0.1)}, req.run_id,
        )
        outcome = runtime.run(req)

        self.assertEqual(outcome.route, "deliberative")
        self.assertIsNone(outcome.selected_action_id)
        self.assertEqual(ledger.records[0].record_hash, outcome.ledger_record.record_hash)
        self.assertIn('"model_provider":"deepseek-local"', ledger.records[0].canonical_json)
        self.assertIn('"latency_ms":12.0', ledger.records[0].canonical_json)

    def test_model_requested_unsafe_action_never_reaches_executor(self) -> None:
        class Deliberator:
            def deliberate(self, _state):
                return ProviderExecutionResult(
                    DeliberativeResult((), (), (), (), ("delete all records",)),
                    {"latency_ms": 1.0}, "untrusted-model", "fixture",
                )

        runtime, _ = controller(deliberative=True, deliberator=Deliberator())
        base = request()
        definition = ActionDefinition(
            "reason", ActionFamily.DELIBERATE, "model", "plan", RiskClass.READ_ONLY,
            ((),), ("local",), ("policy",), 1.0, 0.1,
        )
        req = RuntimeRequest(
            replace(base.raw_state, available_action_families=(ActionFamily.DELIBERATE,)),
            (definition,),
            AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}), frozenset({RiskClass.READ_ONLY})),
            {"reason:0:local:policy": ValueEstimate(0.9, 0.1, 0.0, 0.1)},
            base.run_id,
        )

        outcome = runtime.run(req)

        self.assertEqual(outcome.route, "deliberative")
        self.assertFalse(runtime.effect_execution_enabled)
        self.assertEqual(outcome.deliberation.requested_actions, ("delete all records",))

    def test_provider_outage_falls_back_without_effect(self) -> None:
        class Deliberator:
            def deliberate(self, _state):
                raise OSError("provider unavailable")

        runtime, _ = controller(deliberative=True, deliberator=Deliberator())
        base = request()
        definition = ActionDefinition(
            "reason", ActionFamily.DELIBERATE, "model", "plan", RiskClass.READ_ONLY,
            ((),), ("local",), ("policy",), 1.0, 0.1,
        )
        req = RuntimeRequest(
            replace(base.raw_state, available_action_families=(ActionFamily.DELIBERATE,)),
            (definition,),
            AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}), frozenset({RiskClass.READ_ONLY})),
            {"reason:0:local:policy": ValueEstimate(0.9, 0.1, 0.0, 0.1)},
            base.run_id,
        )

        outcome = runtime.run(req)

        self.assertEqual(outcome.reason, "DELIBERATIVE_FAILURE")
        self.assertEqual(outcome.route, "deterministic")
        self.assertFalse(runtime.effect_execution_enabled)


if __name__ == "__main__":
    unittest.main()
