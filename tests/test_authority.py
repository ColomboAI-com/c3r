import unittest

from c3r.authority import action_fingerprint, sign_fields
from c3r.commit_gateway import ApprovalGrant, CommitRequest, TrustedCommitGateway
from c3r.state_schema import (
    ActionCandidate,
    ActionFamily,
    RiskClass,
    VerificationResult,
)
from c3r.verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy


class AuthorityBoundaryTests(unittest.TestCase):
    def test_proposal_cannot_replace_the_authoritative_verifier(self) -> None:
        key = b"test-verification-key"
        firewall = VerifierFirewall(
            {"policy": lambda _: VerifierDecision(accepted=False, evidence="denied")},
            VerifierPolicy(default_verifier="policy"),
            attestation_key=key,
        )
        candidate = ActionCandidate(
            "send-email",
            ActionFamily.TOOL,
            RiskClass.EXTERNAL_WRITE,
            1.0,
            requested_verifier="self-approved",
        )

        result = firewall.verify(candidate)

        self.assertFalse(result.accepted)
        self.assertEqual(result.verifier_id, "policy")

    def test_gateway_blocks_external_write_without_independent_authorization(self) -> None:
        key = b"test-verification-key"
        candidate = ActionCandidate(
            "send-email", ActionFamily.TOOL, RiskClass.EXTERNAL_WRITE, 1.0
        )
        verification = VerifierFirewall(
            {"policy": lambda _: VerifierDecision(accepted=True, evidence="schema valid")},
            VerifierPolicy(default_verifier="policy"),
            attestation_key=key,
        ).verify(candidate)
        request = CommitRequest(
            candidate=candidate,
            verification=verification,
        )
        effects: list[str] = []

        result = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=key,
            approval_key=b"test-approval-key",
            policy_version="policy-v1",
        ).commit(request, lambda action: effects.append(action.id))

        self.assertFalse(result.committed)
        self.assertEqual(result.reason, "approval required")
        self.assertEqual(effects, [])

    def test_gateway_rejects_verification_from_an_untrusted_identity(self) -> None:
        candidate = ActionCandidate(
            "read-record", ActionFamily.TOOL, RiskClass.READ_ONLY, 1.0
        )
        request = CommitRequest(
            candidate=candidate,
            verification=VerificationResult(
                verifier_id="self-approved",
                candidate_id=candidate.id,
                action_fingerprint=action_fingerprint(candidate),
                policy_version="policy-v1",
                accepted=True,
                evidence="claimed",
                attestation="forged",
            ),
        )
        effects: list[str] = []

        result = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=b"test-verification-key",
            approval_key=b"test-approval-key",
            policy_version="policy-v1",
        ).commit(request, lambda action: effects.append(action.id))

        self.assertFalse(result.committed)
        self.assertEqual(result.reason, "untrusted verifier")
        self.assertEqual(effects, [])

    def test_gateway_rejects_forged_verification_with_trusted_name(self) -> None:
        candidate = ActionCandidate(
            "read-record", ActionFamily.TOOL, RiskClass.READ_ONLY, 1.0
        )
        request = CommitRequest(
            candidate=candidate,
            verification=VerificationResult(
                verifier_id="policy",
                candidate_id=candidate.id,
                action_fingerprint=action_fingerprint(candidate),
                policy_version="policy-v1",
                accepted=True,
                evidence="claimed",
                attestation="forged",
            ),
        )
        effects: list[str] = []

        result = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=b"test-verification-key",
            approval_key=b"test-approval-key",
            policy_version="policy-v1",
        ).commit(request, lambda action: effects.append(action.id))

        self.assertFalse(result.committed)
        self.assertEqual(result.reason, "invalid verification attestation")
        self.assertEqual(effects, [])

    def test_gateway_commits_read_only_action_with_bound_verification(self) -> None:
        key = b"test-verification-key"
        candidate = ActionCandidate(
            "read-record", ActionFamily.TOOL, RiskClass.READ_ONLY, 1.0
        )
        verification = VerifierFirewall(
            {"policy": lambda _: VerifierDecision(accepted=True, evidence="allowed")},
            VerifierPolicy(default_verifier="policy"),
            attestation_key=key,
        ).verify(candidate)
        effects: list[str] = []

        result = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=key,
            approval_key=b"test-approval-key",
            policy_version="policy-v1",
        ).commit(
            CommitRequest(candidate=candidate, verification=verification),
            lambda action: effects.append(action.id),
        )

        self.assertTrue(result.committed)
        self.assertEqual(effects, [candidate.id])

    def test_gateway_rejects_attestation_reused_for_changed_action(self) -> None:
        key = b"test-verification-key"
        original = ActionCandidate(
            "same-id", ActionFamily.TOOL, RiskClass.EXTERNAL_WRITE, 1.0
        )
        changed = ActionCandidate(
            "same-id", ActionFamily.TOOL, RiskClass.READ_ONLY, 1.0
        )
        verification = VerifierFirewall(
            {"policy": lambda _: VerifierDecision(accepted=True, evidence="allowed")},
            VerifierPolicy(default_verifier="policy", version="policy-v1"),
            attestation_key=key,
        ).verify(original)
        effects: list[str] = []

        result = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=key,
            approval_key=b"test-approval-key",
            policy_version="policy-v1",
        ).commit(
            CommitRequest(candidate=changed, verification=verification),
            lambda action: effects.append(action.id),
        )

        self.assertFalse(result.committed)
        self.assertEqual(result.reason, "verification action mismatch")
        self.assertEqual(effects, [])

    def test_gateway_consumes_approval_nonce_before_external_effect(self) -> None:
        verification_key = b"test-verification-key"
        approval_key = b"test-approval-key"
        candidate = ActionCandidate(
            "send-once", ActionFamily.TOOL, RiskClass.EXTERNAL_WRITE, 1.0
        )
        fingerprint = action_fingerprint(candidate)
        verification = VerifierFirewall(
            {"policy": lambda _: VerifierDecision(accepted=True, evidence="allowed")},
            VerifierPolicy(default_verifier="policy", version="policy-v1"),
            attestation_key=verification_key,
        ).verify(candidate)
        approval = ApprovalGrant(
            candidate_id=candidate.id,
            action_fingerprint=fingerprint,
            policy_version="policy-v1",
            authority_id="human-review",
            nonce="single-use-nonce",
            expires_at_epoch_s=2_000,
            attestation=sign_fields(
                approval_key,
                "human-review",
                candidate.id,
                fingerprint,
                "policy-v1",
                "single-use-nonce",
                "2000",
            ),
        )
        gateway = TrustedCommitGateway(
            trusted_verifier_ids=frozenset({"policy"}),
            verification_key=verification_key,
            approval_key=approval_key,
            policy_version="policy-v1",
            clock=lambda: 1_000,
        )
        request = CommitRequest(candidate, verification, approval)
        effects: list[str] = []

        first = gateway.commit(request, lambda action: effects.append(action.id))
        second = gateway.commit(request, lambda action: effects.append(action.id))

        self.assertTrue(first.committed)
        self.assertFalse(second.committed)
        self.assertEqual(second.reason, "approval replayed")
        self.assertEqual(effects, [candidate.id])


if __name__ == "__main__":
    unittest.main()
