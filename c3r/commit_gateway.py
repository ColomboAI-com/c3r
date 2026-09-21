"""Complete mediation for externally visible effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .authority import attestation_matches
from .state_schema import ActionCandidate, RiskClass, VerificationResult


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    candidate_id: str
    authority_id: str
    attestation: str


@dataclass(frozen=True, slots=True)
class CommitRequest:
    candidate: ActionCandidate
    verification: VerificationResult
    approval: ApprovalGrant | None = None


@dataclass(frozen=True, slots=True)
class CommitResult:
    committed: bool
    reason: str


class TrustedCommitGateway:
    _approval_classes = frozenset(
        {
            RiskClass.EXTERNAL_WRITE,
            RiskClass.HIGH_CONSEQUENCE,
            RiskClass.DESTRUCTIVE,
            RiskClass.APPROVAL_REQUIRED,
        }
    )

    def __init__(
        self,
        *,
        trusted_verifier_ids: frozenset[str],
        verification_key: bytes,
        approval_key: bytes,
    ) -> None:
        if not trusted_verifier_ids:
            raise ValueError("at least one trusted verifier is required")
        self._trusted_verifier_ids = trusted_verifier_ids
        self._verification_key = verification_key
        self._approval_key = approval_key

    def commit(
        self,
        request: CommitRequest,
        executor: Callable[[ActionCandidate], None],
    ) -> CommitResult:
        verification = request.verification
        candidate = request.candidate
        if verification.verifier_id not in self._trusted_verifier_ids:
            return CommitResult(False, "untrusted verifier")
        if verification.candidate_id != candidate.id:
            return CommitResult(False, "verification candidate mismatch")
        accepted = "1" if verification.accepted else "0"
        if not attestation_matches(
            verification.attestation,
            self._verification_key,
            verification.verifier_id,
            verification.candidate_id,
            accepted,
            verification.evidence,
        ):
            return CommitResult(False, "invalid verification attestation")
        if not verification.accepted:
            return CommitResult(False, "verification failed")
        if candidate.risk_class in self._approval_classes:
            if request.approval is None:
                return CommitResult(False, "approval required")
            if request.approval.candidate_id != candidate.id:
                return CommitResult(False, "approval candidate mismatch")
            if not attestation_matches(
                request.approval.attestation,
                self._approval_key,
                request.approval.authority_id,
                request.approval.candidate_id,
            ):
                return CommitResult(False, "invalid approval attestation")

        executor(candidate)
        return CommitResult(True, "committed")
