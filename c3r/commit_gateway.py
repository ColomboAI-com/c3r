"""Complete mediation for externally visible effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
import time

from .authority import action_fingerprint, attestation_matches
from .state_schema import ActionCandidate, RiskClass, VerificationResult


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    candidate_id: str
    action_fingerprint: str
    policy_version: str
    authority_id: str
    nonce: str
    expires_at_epoch_s: int
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
        policy_version: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not trusted_verifier_ids:
            raise ValueError("at least one trusted verifier is required")
        self._trusted_verifier_ids = trusted_verifier_ids
        self._verification_key = verification_key
        self._approval_key = approval_key
        self._policy_version = policy_version
        self._clock = clock
        self._consumed_approval_nonces: set[str] = set()
        self._approval_lock = Lock()

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
        fingerprint = action_fingerprint(candidate)
        if verification.action_fingerprint != fingerprint:
            return CommitResult(False, "verification action mismatch")
        if verification.policy_version != self._policy_version:
            return CommitResult(False, "verification policy mismatch")
        accepted = "1" if verification.accepted else "0"
        if not attestation_matches(
            verification.attestation,
            self._verification_key,
            verification.verifier_id,
            verification.candidate_id,
            verification.action_fingerprint,
            verification.policy_version,
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
            if request.approval.action_fingerprint != fingerprint:
                return CommitResult(False, "approval action mismatch")
            if request.approval.policy_version != self._policy_version:
                return CommitResult(False, "approval policy mismatch")
            if not attestation_matches(
                request.approval.attestation,
                self._approval_key,
                request.approval.authority_id,
                request.approval.candidate_id,
                request.approval.action_fingerprint,
                request.approval.policy_version,
                request.approval.nonce,
                str(request.approval.expires_at_epoch_s),
            ):
                return CommitResult(False, "invalid approval attestation")
            with self._approval_lock:
                if request.approval.nonce in self._consumed_approval_nonces:
                    return CommitResult(False, "approval replayed")
                if self._clock() > request.approval.expires_at_epoch_s:
                    return CommitResult(False, "approval expired")
                self._consumed_approval_nonces.add(request.approval.nonce)

        executor(candidate)
        return CommitResult(True, "committed")
