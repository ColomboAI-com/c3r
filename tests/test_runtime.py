import unittest

from c3r.candidate_compiler import CandidateCompiler
from c3r.commit_gateway import InMemoryApprovalNonceStore, TrustedCommitGateway
from c3r.cvoc import RobustCvocController
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
from c3r.system_one.fast_path import LayaFastPath
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
) -> tuple[StandaloneController, TraceLedger]:
    ledger = TraceLedger()
    verifier = VerifierFirewall(
        {"policy": lambda _: VerifierDecision(accepted, "policy fixture")},
        VerifierPolicy(default_verifier="policy"),
        attestation_key=KEY,
    )
    gateway = TrustedCommitGateway(
        trusted_verifier_ids=frozenset({"policy"}),
        verification_key=KEY,
        approval_key=b"approval-test-key",
        policy_version="policy-v1",
        approval_nonce_store=InMemoryApprovalNonceStore(),
    )
    runtime = StandaloneController(
        flags=FeatureFlags(
            enabled_requested=enabled,
            system_one_requested=system_one,
            deliberative_requested=deliberative,
        ),
        compiler=StateCompiler(),
        candidates=CandidateCompiler(),
        cvoc=RobustCvocController(),
        verifier=verifier,
        gateway=gateway,
        ledger=ledger,
        executor=executor,
        fast_path=fast_path,
        deliberator=deliberator,
    )
    return runtime, ledger


class RuntimeTests(unittest.TestCase):
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
        effects = []
        runtime, _ = controller(enabled=False, executor=effects.append)
        outcome = runtime.run(request())

        self.assertEqual(outcome.reason, "C3R_DISABLED")
        self.assertEqual(effects, [])

    def test_missing_provenance_stops_before_any_effect(self) -> None:
        effects = []
        runtime, _ = controller(executor=effects.append)
        outcome = runtime.run(request(provenance=False))

        self.assertEqual(outcome.reason, "STATE_UNSAFE_TO_COMPRESS")
        self.assertEqual(effects, [])

    def test_verifier_rejection_stops_before_commit(self) -> None:
        effects = []
        runtime, _ = controller(accepted=False, executor=effects.append)
        outcome = runtime.run(request())

        self.assertEqual(outcome.reason, "VERIFICATION_REJECTED")
        self.assertEqual(effects, [])

    def test_external_write_requires_independent_approval(self) -> None:
        effects = []
        runtime, _ = controller(executor=effects.append)
        outcome = runtime.run(request(risk=RiskClass.EXTERNAL_WRITE))

        self.assertEqual(outcome.reason, "approval required")
        self.assertEqual(effects, [])

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

        effects = []
        runtime, _ = controller(
            system_one=True,
            deliberative=True,
            fast_path=fast_path,
            deliberator=Deliberator(),
            executor=effects.append,
        )
        outcome = runtime.run(request())

        self.assertEqual(outcome.route, "deliberative")
        self.assertEqual(outcome.reason, "SYSTEM_ONE_ABSTAINED")
        self.assertIsNone(outcome.selected_action_id)
        self.assertEqual(effects, [])


if __name__ == "__main__":
    unittest.main()
