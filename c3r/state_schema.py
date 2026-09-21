"""Versioned public schemas shared by the C3R control path."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


SCHEMA_VERSION = "c3r.state.v1"


class CompilationStatus(StrEnum):
    COMPILED = "COMPILED"
    STATE_UNSAFE_TO_COMPRESS = "STATE_UNSAFE_TO_COMPRESS"


class ActionFamily(StrEnum):
    DIRECT_TYPED_ACTION = "DIRECT_TYPED_ACTION"
    TOOL = "TOOL"
    RETRIEVAL = "RETRIEVAL"
    LOCAL_MODEL = "LOCAL_MODEL"
    FRONTIER_MODEL = "FRONTIER_MODEL"
    VERIFY = "VERIFY"
    DELIBERATE = "DELIBERATE"
    ASK_USER = "ASK_USER"
    STOP = "STOP"


class RiskClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_REVERSIBLE = "LOW_REVERSIBLE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    HIGH_CONSEQUENCE = "HIGH_CONSEQUENCE"
    DESTRUCTIVE = "DESTRUCTIVE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass(frozen=True, slots=True)
class Provenance:
    source: str
    observed_at: str
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class RawState:
    goal: str
    current_subgoal: str
    verified_facts: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    recent_failures: tuple[str, ...] = ()
    available_action_families: tuple[ActionFamily, ...] = ()
    tool_summary: tuple[str, ...] = ()
    model_inventory: tuple[str, ...] = ()
    budget: Mapping[str, float] = field(default_factory=dict)
    runtime_summary: Mapping[str, str | float | bool] = field(default_factory=dict)
    risk: Mapping[str, str | float | bool] = field(default_factory=dict)
    reversibility: str = "unknown"
    approval_required: bool = False
    data_boundary: str = "unknown"
    rollback_state: str | None = None
    ambiguity: float = 0.0
    consequence: str = "low"
    provenance: Mapping[str, Provenance] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompiledState:
    goal: str
    current_subgoal: str
    verified_facts: tuple[str, ...]
    open_questions: tuple[str, ...]
    recent_failures: tuple[str, ...]
    available_action_families: tuple[ActionFamily, ...]
    tool_summary: tuple[str, ...]
    model_inventory: tuple[str, ...]
    budget: Mapping[str, float]
    runtime_summary: Mapping[str, str | float | bool]
    risk: Mapping[str, str | float | bool]
    reversibility: str
    approval_required: bool
    data_boundary: str
    rollback_state: str | None
    ambiguity: float
    state_compilation_confidence: float
    provenance: Mapping[str, Provenance]
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CompilationResult:
    status: CompilationStatus
    state: CompiledState | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    id: str
    family: ActionFamily
    risk_class: RiskClass
    optimistic_utility: float
    requested_verifier: str | None = None
    payload: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    allowed_families: frozenset[ActionFamily]
    allowed_risks: frozenset[RiskClass]

    def permits(self, candidate: ActionCandidate) -> bool:
        return (
            candidate.family in self.allowed_families
            and candidate.risk_class in self.allowed_risks
        )


@dataclass(frozen=True, slots=True)
class CandidateCompilation:
    candidates: tuple[ActionCandidate, ...]
    masked_ids: tuple[str, ...]
    no_safe_action: bool


@dataclass(frozen=True, slots=True)
class ValueEstimate:
    expected_gain: float
    total_cost: float
    risk_penalty: float
    uncertainty: float


@dataclass(frozen=True, slots=True)
class CvocDecision:
    selected: ActionCandidate | None
    lower_bound: float
    fallback: ActionFamily | None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verifier_id: str
    candidate_id: str
    action_fingerprint: str
    policy_version: str
    accepted: bool
    evidence: str
    attestation: str
