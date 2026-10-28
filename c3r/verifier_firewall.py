"""Independent policy selection, execution, and attestation of verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .authority import action_fingerprint, sign_fields
from .state_schema import ActionCandidate, RiskClass, VerificationResult


@dataclass(frozen=True, slots=True)
class VerifierDecision:
    accepted: bool
    evidence: str


Verifier = Callable[[ActionCandidate], VerifierDecision]


@dataclass(frozen=True, slots=True)
class VerifierPolicy:
    default_verifier: str
    by_risk: Mapping[RiskClass, str] = field(default_factory=dict)
    version: str = "policy-v1"

    def select(self, candidate: ActionCandidate) -> str:
        return self.by_risk.get(candidate.risk_class, self.default_verifier)


class VerifierFirewall:
    def __init__(
        self,
        verifiers: Mapping[str, Verifier],
        policy: VerifierPolicy,
        *,
        attestation_key: bytes,
    ) -> None:
        self._verifiers = dict(verifiers)
        self._policy = policy
        self._attestation_key = attestation_key

    @property
    def available_verifier_ids(self) -> frozenset[str]:
        """Identifiers configured by the trusted host, never by a proposal."""
        return frozenset(self._verifiers)

    def verify(self, candidate: ActionCandidate) -> VerificationResult:
        verifier_id = self._policy.select(candidate)
        try:
            verifier = self._verifiers[verifier_id]
        except KeyError as error:
            raise ValueError("policy-selected verifier is unavailable") from error
        decision = verifier(candidate)
        accepted = "1" if decision.accepted else "0"
        fingerprint = action_fingerprint(candidate)
        attestation = sign_fields(
            self._attestation_key,
            verifier_id,
            candidate.id,
            fingerprint,
            self._policy.version,
            accepted,
            decision.evidence,
        )
        return VerificationResult(
            verifier_id=verifier_id,
            candidate_id=candidate.id,
            action_fingerprint=fingerprint,
            policy_version=self._policy.version,
            accepted=decision.accepted,
            evidence=decision.evidence,
            attestation=attestation,
        )
