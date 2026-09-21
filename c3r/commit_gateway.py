"""Complete mediation for externally visible effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
import time
from typing import Protocol

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


class ApprovalNonceStore(Protocol):
    """Atomically claims approval nonces across every gateway replica."""

    def claim(self, nonce: str, *, expires_at_epoch_s: int, now_epoch_s: float) -> bool: ...


class InMemoryApprovalNonceStore:
    """Single-process test store; production must use durable shared storage."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = Lock()

    def claim(self, nonce: str, *, expires_at_epoch_s: int, now_epoch_s: float) -> bool:
        with self._lock:
            if now_epoch_s > expires_at_epoch_s or nonce in self._claimed:
                return False
            self._claimed.add(nonce)
            return True


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
        approval_nonce_store: ApprovalNonceStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not trusted_verifier_ids:
            raise ValueError("at least one trusted verifier is required")
        self._trusted_verifier_ids = trusted_verifier_ids
        self._verification_key = verification_key
        self._approval_key = approval_key
        self._policy_version = policy_version
        self._approval_nonce_store = approval_nonce_store
        self._clock = clock

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
            if not self._approval_nonce_store.claim(
                request.approval.nonce,
                expires_at_epoch_s=request.approval.expires_at_epoch_s,
                now_epoch_s=self._clock(),
            ):
                return CommitResult(False, "approval expired or replayed")

        executor(candidate)
        return CommitResult(True, "committed")
