"""Host-owned composition of the C3R decision and authority paths.

The controller accepts bounded inputs from a trusted host. It does not expose an
HTTP endpoint or grant a remote caller permission to execute an action.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Protocol

from .adapters.providers import ProviderExecutionResult
from .candidate_compiler import CandidateCompiler
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
    RiskClass,
    ValueEstimate,
)
from .system_one.advisory import AdvisoryFastPath
from .system_one.fast_path import CalibratedFastPath, FastPathDecision
from .system_one.question_registry import TypedQuestion
from .telemetry.ephemeral import EphemeralTraceSink
from .telemetry.trace import DecisionTrace
from .telemetry.trace_ledger import LedgerRecord
from .verifier_firewall import VerifierFirewall


class Deliberator(Protocol):
    def deliberate(self, state: CompiledState) -> object: ...


class TraceSink(Protocol):
    def append(self, trace: DecisionTrace) -> LedgerRecord: ...


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    raw_state: RawState
    definitions: tuple[ActionDefinition, ...]
    policy: AuthorityPolicy
    estimates: Mapping[str, ValueEstimate]
    run_id: str
    access_level: str = "internal"
    language: str = "en"
    requested_text_generation: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeOutcome:
    route: str
    selected_action_id: str | None
    authority_result: str
    reason: str
    ledger_record: LedgerRecord
    candidate_ids: tuple[str, ...] = ()
    fast_path: FastPathDecision | None = None
    deliberation: object | None = None


class StandaloneController:
    """Run C3R with independent verification and recommendation-only outcomes.

    Estimates, the policy, and verifier must be supplied by the trusted host.
    Supplying an executor is rejected: arbitrary external effects cannot be
    atomically committed with the trace ledger. A learned proposal cannot grant
    authority.
    """

    def __init__(
        self,
        *,
        flags: FeatureFlags,
        compiler: StateCompiler,
        candidates: CandidateCompiler,
        cvoc: RobustCvocController,
        verifier: VerifierFirewall,
        ledger: TraceSink,
        fast_path: CalibratedFastPath | AdvisoryFastPath | None = None,
        deliberator: Deliberator | None = None,
        executor: Callable[[ActionCandidate], None] | None = None,
        readiness_probe: Callable[[], bool] | None = None,
    ) -> None:
        if executor is not None:
            raise ValueError("external effects are unsupported by StandaloneController")
        self._flags = flags
        self._compiler = compiler
        self._candidates = candidates
        self._cvoc = cvoc
        self._verifier = verifier
        self._ledger = ledger
        self._fast_path = fast_path
        self._deliberator = deliberator
        self._readiness_probe = readiness_probe

    @property
    def effect_execution_enabled(self) -> bool:
        """Capability flag retained for fail-closed hosting checks."""
        return False

    @property
    def decision_enabled(self) -> bool:
        """Whether the host requested C3R decisions; not a provider health probe."""
        return self._flags.enabled_requested

    @property
    def system_one_enabled(self) -> bool:
        return self._flags.system_one_enabled and self._fast_path is not None

    @property
    def trace_persistence_enabled(self) -> bool:
        """Unknown host sinks are treated as persistent for production gating."""
        return type(self._ledger) is not EphemeralTraceSink

    @property
    def provider_ready(self) -> bool:
        """No provider-health assertion is made without a host probe."""
        if self._readiness_probe is None:
            return False
        try:
            return bool(self._readiness_probe())
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def run(self, request: RuntimeRequest, *,
            requested_deliberator: Deliberator | None = None) -> RuntimeOutcome:
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
            system_cost: Mapping[str, float] | None = None,
            provider_id: str | None = None,
        ) -> RuntimeOutcome:
            probabilities = {} if fast is None else dict(fast.probabilities)
            if fast is not None and fast.candidate_probabilities:
                probabilities["CANDIDATE_RANK"] = fast.candidate_probabilities
            trace = DecisionTrace(
                run_id=request.run_id,
                state_hash=state_hash,
                access_level=request.access_level,
                model_provider=provider_id or (fast.model_id if fast is not None else route),
                candidate_ids=candidate_ids,
                probabilities=probabilities,
                utility_quantiles=(
                    {} if lower_bound is None else {"selected_lower_bound": lower_bound}
                ),
                selected_action_id=None if selected is None else selected.id,
                authority_result=authority_result,
                system_cost={} if system_cost is None else system_cost,
                task_outcome={"status": reason},
                artifact_refs=(),
            )
            return RuntimeOutcome(
                route=route,
                selected_action_id=None if selected is None else selected.id,
                authority_result=authority_result,
                reason=reason,
                ledger_record=self._ledger.append(trace),
                candidate_ids=candidate_ids,
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
            (
                definition for definition in request.definitions
                if definition.family in state.available_action_families
            ),
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
            if self._fast_path.provider != self._flags.system_one_provider:
                return finish("deterministic", "SYSTEM_ONE_PROVIDER_MISMATCH", candidate_ids=candidate_ids)
            questions = (
                TypedQuestion("STOP_NOW", ("NO", "YES")),
                TypedQuestion("DELIBERATION_REQUIRED", ("NO", "YES")),
            )
            # Only stable identifiers and public operation metadata cross the CLM
            # boundary. Argument values and provenance never enter action labels.
            candidate_options = tuple(
                f"{item.id} | {item.family.value} | {item.risk_class.value}"
                for item in compiled.candidates
            )
            try:
                fast = self._fast_path.decide(
                    state, questions, action_family="CONTROL", language=request.language,
                    candidate_options=candidate_options,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                if not request.requested_text_generation:
                    return self._deliberate_or_stop(
                        state, finish, candidate_ids, "SYSTEM_ONE_FAILURE", None
                    )
            if fast is not None and fast.abstained:
                return self._deliberate_or_stop(
                    state, finish, candidate_ids, "SYSTEM_ONE_ABSTAINED", fast
                )
            if fast is not None and fast.answers.get("STOP_NOW") == "YES":
                return finish("system_one", "STOP_NOW", candidate_ids=candidate_ids, fast=fast)
            if fast is not None and fast.answers.get("DELIBERATION_REQUIRED") == "YES":
                return self._deliberate_or_stop(
                    state, finish, candidate_ids, "DELIBERATION_REQUIRED", fast
                )

        decision = self._cvoc.select(compiled.candidates, request.estimates)
        if decision.selected is None:
            if request.requested_text_generation and requested_deliberator is not None:
                # Trusted host opt-in for caller-requested bounded text only.
                # Unknown quality still has no positive CVoC. This fallback must
                # be admitted by the catalog AND independently verified.
                fallback = next((candidate for candidate in compiled.candidates
                                 if candidate.family is ActionFamily.DELIBERATE
                                 and candidate.risk_class is RiskClass.READ_ONLY), None)
                if fallback is not None:
                    try:
                        verification = self._verifier.verify(fallback)
                    except (OSError, RuntimeError, TypeError, ValueError):
                        return finish("deterministic", "VERIFIER_FAILURE", candidate_ids=candidate_ids)
                    if verification.accepted:
                        return self._deliberate_or_stop(
                            state, finish, candidate_ids, "REQUESTED_TEXT_POLICY_FALLBACK", fast,
                            deliberator=requested_deliberator,
                        )
                    return finish("deterministic", "VERIFICATION_REJECTED", candidate_ids=candidate_ids)
            return finish(
                "deterministic", "NON_POSITIVE_CVOC", candidate_ids=candidate_ids, fast=fast
            )
        selected = decision.selected
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
        if selected.family is ActionFamily.DELIBERATE:
            return self._deliberate_or_stop(
                state, finish, candidate_ids, "CVOC_SELECTED_DELIBERATION", fast,
                deliberator=requested_deliberator if request.requested_text_generation else None,
            )
        if selected.risk_class is not RiskClass.READ_ONLY:
            return finish(
                "deterministic",
                "EFFECT_EXECUTION_UNAVAILABLE",
                candidate_ids=candidate_ids,
                lower_bound=decision.lower_bound,
                fast=fast,
            )
        return finish(
            "recommendation",
            "VERIFIED_RECOMMENDATION",
            selected=selected,
            candidate_ids=candidate_ids,
            lower_bound=decision.lower_bound,
            authority_result="verified_not_committed",
            fast=fast,
        )

    def _deliberate_or_stop(
        self,
        state: CompiledState,
        finish: Callable[..., RuntimeOutcome],
        candidate_ids: tuple[str, ...],
        reason: str,
        fast: FastPathDecision | None,
        *, deliberator: Deliberator | None = None,
    ) -> RuntimeOutcome:
        deliberator = deliberator or self._deliberator
        if not self._flags.deliberative_enabled or deliberator is None:
            return finish(
                "deterministic", reason + "_NO_PROVIDER", candidate_ids=candidate_ids, fast=fast
            )
        try:
            deliberation = deliberator.deliberate(state)
        except (OSError, RuntimeError, TypeError, ValueError):
            return finish(
                "deterministic", "DELIBERATIVE_FAILURE", candidate_ids=candidate_ids, fast=fast
            )
        if isinstance(deliberation, ProviderExecutionResult):
            cost = deliberation.observed_cost
            if any(not isfinite(value) or value < 0 for value in cost.values()):
                return finish(
                    "deterministic", "DELIBERATIVE_INVALID_COST", candidate_ids=candidate_ids,
                    fast=fast,
                )
            return finish(
                "deliberative", reason, candidate_ids=candidate_ids, fast=fast,
                deliberation=deliberation.deliberation, system_cost=cost,
                provider_id=deliberation.provider_id,
            )
        return finish(
            "deliberative",
            reason,
            candidate_ids=candidate_ids,
            fast=fast,
            deliberation=deliberation,
        )
