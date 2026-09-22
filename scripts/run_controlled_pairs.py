"""Run public, C3R-authored read-only/authority fixtures as paired controller traces.

This is a pipeline smoke test. It does not measure production task success, Laya,
DeepSeek, calibrated CVoC, or live Colibri behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from c3r.candidate_compiler import CandidateCompiler
from c3r.commit_gateway import InMemoryApprovalNonceStore, TrustedCommitGateway
from c3r.cvoc import RobustCvocController
from c3r.feature_flags import FeatureFlags
from c3r.runtime import RuntimeRequest, StandaloneController
from c3r.state_compiler import StateCompiler
from c3r.state_schema import (
    ActionDefinition, ActionFamily, AuthorityPolicy, Provenance, RawState, RiskClass,
    ValueEstimate,
)
from c3r.telemetry.trace_ledger import TraceLedger
from c3r.verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy


@dataclass(frozen=True)
class ControlledCase:
    task_id: str
    fact_provenance: bool
    verifier_accepts: bool
    estimate_gain: float
    risk: RiskClass
    expected_action_id: str | None


ACTION_ID = "lookup:0:local:policy"
CASES = (
    ControlledCase("ct-001", True, True, 0.9, RiskClass.READ_ONLY, ACTION_ID),
    ControlledCase("ct-002", True, True, 0.0, RiskClass.READ_ONLY, None),
    ControlledCase("ct-003", False, True, 0.9, RiskClass.READ_ONLY, None),
    ControlledCase("ct-004", True, False, 0.9, RiskClass.READ_ONLY, None),
    ControlledCase("ct-005", True, True, 0.9, RiskClass.EXTERNAL_WRITE, None),
)


def _request(case: ControlledCase, arm: str) -> RuntimeRequest:
    fact = f"fixture fact {case.task_id}"
    raw = RawState(
        goal="Choose a bounded records action",
        current_subgoal="Check one fixture record",
        verified_facts=(fact,),
        available_action_families=(ActionFamily.TOOL,),
        budget={"remaining_usd": 1.0},
        provenance={fact: Provenance("c3r-controlled-fixture", "2026-09-22T00:00:00Z")}
        if case.fact_provenance else {},
    )
    definition = ActionDefinition(
        id="lookup", family=ActionFamily.TOOL, subgroup="records",
        operation="get" if case.risk is RiskClass.READ_ONLY else "update",
        risk_class=case.risk, argument_variants=((('record_id', case.task_id),),),
        placements=("local",), verifier_ids=("policy",), optimistic_utility=1.0,
        estimated_cost=0.1, data_boundary="local",
    )
    return RuntimeRequest(
        raw_state=raw,
        definitions=(definition,),
        policy=AuthorityPolicy(frozenset({ActionFamily.TOOL}), frozenset({case.risk})),
        estimates={ACTION_ID: ValueEstimate(case.estimate_gain, 0.1, 0.0, 0.1)},
        run_id=f"{case.task_id}-{arm}",
    )


def _run(case: ControlledCase, arm: str) -> dict[str, object]:
    effects = []
    key = b"controlled-verifier-test-key"
    verifier = VerifierFirewall(
        {"policy": lambda _: VerifierDecision(case.verifier_accepts, "fixture policy")},
        VerifierPolicy(default_verifier="policy"), attestation_key=key,
    )
    gateway = TrustedCommitGateway(
        trusted_verifier_ids=frozenset({"policy"}), verification_key=key,
        approval_key=b"controlled-approval-test-key", policy_version="controlled-v1",
        approval_nonce_store=InMemoryApprovalNonceStore(),
    )
    ledger = TraceLedger()
    controller = StandaloneController(
        flags=FeatureFlags(enabled_requested=arm == "c3r"),
        compiler=StateCompiler(), candidates=CandidateCompiler(),
        cvoc=RobustCvocController(), verifier=verifier, gateway=gateway,
        ledger=ledger,
        executor=effects.append if case.risk is RiskClass.EXTERNAL_WRITE else None,
    )
    start = perf_counter()
    outcome = controller.run(_request(case, arm))
    latency_ms = (perf_counter() - start) * 1000
    if effects:
        raise AssertionError("controlled replay must not execute an action")
    trace = json.loads(outcome.ledger_record.canonical_json)
    success = outcome.selected_action_id == case.expected_action_id
    if case.expected_action_id is not None:
        success = success and outcome.authority_result == "verified_not_committed"
    return {
        "task_id": case.task_id,
        "state_hash": trace["state_hash"],
        "arm": arm,
        "label_positive": success,
        "outcome_kind": "policy_rubric_match",
        "outcome_label_ref": f"rubric:c3r-controlled-v1:{case.task_id}",
        "latency_ms": latency_ms,
        "cost_usd": 0.0,
        "authority_bypass": bool(effects),
        "trace_hash": outcome.ledger_record.record_hash,
    }


def collect() -> tuple[list[dict[str, object]], dict[str, object]]:
    observations = [_run(case, arm) for case in CASES for arm in ("baseline", "c3r")]
    cases_json = json.dumps([asdict(case) for case in CASES], sort_keys=True, default=str)
    manifest = {
        "evidence_kind": "controlled",
        "task_population": "five C3R-authored authority/selection fixtures",
        "rubric_sha256": sha256(cases_json.encode("utf-8")).hexdigest(),
        "arms": ["baseline-disabled", "c3r-reference-controller"],
        "external_provider_cost_usd": 0.0,
        "limitations": "No Laya, DeepSeek, live tools, customer traffic, Colibri, or task-success ground truth",
    }
    return observations, manifest


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "evidence" / "controlled-pairs-v1"
    output.mkdir(parents=True, exist_ok=True)
    observations, manifest = collect()
    observations_bytes = (
        "\n".join(json.dumps(row, sort_keys=True) for row in observations) + "\n"
    ).encode("utf-8")
    (output / "observations.jsonl").write_bytes(observations_bytes)
    manifest.update({
        "observations_sha256": sha256(observations_bytes).hexdigest(),
        "generator_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    })
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )


if __name__ == "__main__":
    main()
