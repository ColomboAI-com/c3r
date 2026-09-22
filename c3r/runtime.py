"""Host-owned composition of the C3R decision and authority paths.

The controller accepts bounded inputs from a trusted host. It does not expose an
HTTP endpoint or grant a remote caller permission to execute an action.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Protocol

from .candidate_compiler import CandidateCompiler
from .commit_gateway import ApprovalGrant, CommitRequest, TrustedCommitGateway
from .cvoc import RobustCvocController
from .feature_flags import FeatureFlags
from .state_compiler import StateCompiler
from .state_schema import (
    ActionCandidate,
    ActionDefinition,
    ActionFamily,
    AuthorityPolicy,
    CompiledState,
    RawState,
    ValueEstimate,
)
from .system_one.fast_path import FastPathDecision, LayaFastPath
from .system_one.question_registry import TypedQuestion
from .telemetry.trace import DecisionTrace
from .telemetry.trace_ledger import LedgerRecord, TraceLedger
from .verifier_firewall import VerifierFirewall


class Deliberator(Protocol):
    def deliberate(self, state: CompiledState) -> object: ...


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    raw_state: RawState
    definitions: tuple[ActionDefinition, ...]
    policy: AuthorityPolicy
    estimates: Mapping[str, ValueEstimate]
    run_id: str
    access_level: str = "internal"
    language: str = "en"


@dataclass(frozen=True, slots=True)
class RuntimeOutcome:
    route: str
    selected_action_id: str | None
    authority_result: str
    reason: str
    ledger_record: LedgerRecord
    fast_path: FastPathDecision | None = None
    deliberation: object | None = None


class StandaloneController:
    """Run C3R with independent verification and an optional trusted executor.

    Estimates, the policy, verifier, gateway, and executor must be supplied by the
    trusted host. The default is recommendation only. A learned proposal can never
    supply an executor or a verification attestation through this interface.
    """

    def __init__(
        self,
        *,
        flags: FeatureFlags,
        compiler: StateCompiler,
        candidates: CandidateCompiler,
        cvoc: RobustCvocController,
        verifier: VerifierFirewall,
        gateway: TrustedCommitGateway,
        ledger: TraceLedger,
        fast_path: LayaFastPath | None = None,
        deliberator: Deliberator | None = None,
        executor: Callable[[ActionCandidate], None] | None = None,
    ) -> None:
        self._flags = flags
        self._compiler = compiler
        self._candidates = candidates
        self._cvoc = cvoc
        self._verifier = verifier
        self._gateway = gateway
        self._ledger = ledger
        self._fast_path = fast_path
        self._deliberator = deliberator
        self._executor = executor

    @property
    def effect_execution_enabled(self) -> bool:
        return self._executor is not None

    def run(
        self, request: RuntimeRequest, *, approval: ApprovalGrant | None = None
    ) -> RuntimeOutcome:
        if not request.run_id:
            raise ValueError("run_id is required")
        state_hash = hashlib.sha256(
            json.dumps(
                asdict(request.raw_state),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

        def finish(
            route: str,
            reason: str,
            *,
            selected: ActionCandidate | None = None,
            candidate_ids: tuple[str, ...] = (),
            lower_bound: float | None = None,
            authority_result: str = "not_attempted",
            fast: FastPathDecision | None = None,
            deliberation: object | None = None,
        ) -> RuntimeOutcome:
            probabilities = {} if fast is None else fast.probabilities
            trace = DecisionTrace(
                run_id=request.run_id,
                state_hash=state_hash,
                access_level=request.access_level,
                model_provider=route,
                candidate_ids=candidate_ids,
                probabilities=probabilities,
                utility_quantiles=(
                    {} if lower_bound is None else {"selected_lower_bound": lower_bound}
                ),
                selected_action_id=None if selected is None else selected.id,
                authority_result=authority_result,
                system_cost={},
                task_outcome={"status": reason},
                artifact_refs=(),
            )
            return RuntimeOutcome(
                route=route,
                selected_action_id=None if selected is None else selected.id,
                authority_result=authority_result,
                reason=reason,
                ledger_record=self._ledger.append(trace),
                fast_path=fast,
                deliberation=deliberation,
            )

        if not self._flags.enabled_requested:
            return finish("deterministic", "C3R_DISABLED")

        compilation = self._compiler.compile(request.raw_state)
        if compilation.state is None:
            return finish("deterministic", compilation.status.value)
        state = compilation.state

        remaining_budget = state.budget.get("remaining_usd", 0.0)
        if remaining_budget < 0:
            return finish("deterministic", "INVALID_BUDGET")
        compiled = self._candidates.compile_hierarchical(
            request.definitions,
            request.policy,
            remaining_budget=remaining_budget,
            allowed_verifiers=self._verifier.available_verifier_ids,
        )
        candidate_ids = tuple(item.id for item in compiled.candidates)
        if compiled.no_safe_action:
            return finish("deterministic", "NO_SAFE_ACTION", candidate_ids=candidate_ids)

        fast: FastPathDecision | None = None
        if self._flags.system_one_enabled:
            if self._fast_path is None:
                return finish("deterministic", "SYSTEM_ONE_UNAVAILABLE", candidate_ids=candidate_ids)
            questions = (
                TypedQuestion("STOP_NOW", ("NO", "YES")),
                TypedQuestion("DELIBERATION_REQUIRED", ("NO", "YES")),
            )
            try:
                fast = self._fast_path.decide(
                    state, questions, action_family="CONTROL", language=request.language
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                return finish("deterministic", "SYSTEM_ONE_FAILURE", candidate_ids=candidate_ids)
            if fast.abstained:
                return self._deliberate_or_stop(
                    state, finish, candidate_ids, "SYSTEM_ONE_ABSTAINED", fast
                )
            if fast.answers.get("STOP_NOW") == "YES":
                return finish("system_one", "STOP_NOW", candidate_ids=candidate_ids, fast=fast)
            if fast.answers.get("DELIBERATION_REQUIRED") == "YES":
                return self._deliberate_or_stop(
                    state, finish, candidate_ids, "DELIBERATION_REQUIRED", fast
                )

        decision = self._cvoc.select(compiled.candidates, request.estimates)
        if decision.selected is None:
            return finish(
                "deterministic", "NON_POSITIVE_CVOC", candidate_ids=candidate_ids, fast=fast
            )
        selected = decision.selected
        if selected.family is ActionFamily.DELIBERATE:
            return self._deliberate_or_stop(
                state, finish, candidate_ids, "CVOC_SELECTED_DELIBERATION", fast
            )
        try:
            verification = self._verifier.verify(selected)
        except (OSError, RuntimeError, TypeError, ValueError):
            return finish(
                "deterministic", "VERIFIER_FAILURE", candidate_ids=candidate_ids, fast=fast
            )
        if not verification.accepted:
            return finish(
                "deterministic", "VERIFICATION_REJECTED", candidate_ids=candidate_ids, fast=fast
            )
        if self._executor is None:
            return finish(
                "recommendation",
                "VERIFIED_RECOMMENDATION",
                selected=selected,
                candidate_ids=candidate_ids,
                lower_bound=decision.lower_bound,
                authority_result="verified_not_committed",
                fast=fast,
            )
        try:
            commit = self._gateway.commit(
                CommitRequest(selected, verification, approval), self._executor
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return finish(
                "deterministic", "COMMIT_FAILURE", candidate_ids=candidate_ids, fast=fast
            )
        return finish(
            "commit" if commit.committed else "deterministic",
            commit.reason,
            selected=selected if commit.committed else None,
            candidate_ids=candidate_ids,
            lower_bound=decision.lower_bound,
            authority_result=commit.reason,
            fast=fast,
        )

    def _deliberate_or_stop(
        self,
        state: CompiledState,
        finish: Callable[..., RuntimeOutcome],
        candidate_ids: tuple[str, ...],
        reason: str,
        fast: FastPathDecision | None,
    ) -> RuntimeOutcome:
        if not self._flags.deliberative_enabled or self._deliberator is None:
            return finish(
                "deterministic", reason + "_NO_PROVIDER", candidate_ids=candidate_ids, fast=fast
            )
        try:
            deliberation = self._deliberator.deliberate(state)
        except (OSError, RuntimeError, TypeError, ValueError):
            return finish(
                "deterministic", "DELIBERATIVE_FAILURE", candidate_ids=candidate_ids, fast=fast
            )
        return finish(
            "deliberative",
            reason,
            candidate_ids=candidate_ids,
            fast=fast,
            deliberation=deliberation,
        )
