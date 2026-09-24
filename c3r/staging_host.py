"""Private Cloud Run boundary-smoke host; never enables C3R decisions or collection.

This is deliberately not a production host. It proves packaging and ingress only.
No provider, external effect, or durable trace sink is configured here.
"""

from __future__ import annotations

from secrets import token_bytes

from .candidate_compiler import CandidateCompiler
from .commit_gateway import InMemoryApprovalNonceStore, TrustedCommitGateway
from .cvoc import RobustCvocController
from .feature_flags import FeatureFlags
from .host_factory import ReadOnlyRequestFactory
from .runtime import StandaloneController
from .state_compiler import StateCompiler
from .state_schema import ActionDefinition, ActionFamily, AuthorityPolicy, RiskClass
from .telemetry.trace import DecisionTrace
from .telemetry.trace_ledger import LedgerRecord, _record_hash, canonical_trace_json
from .verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy


class EphemeralStagingSink:
    """Return a per-request integrity hash without retaining any trace rows."""

    def append(self, trace: DecisionTrace) -> LedgerRecord:
        canonical = canonical_trace_json(trace)
        genesis = "0" * 64
        return LedgerRecord(genesis, _record_hash(genesis, canonical), canonical)


def build() -> tuple[StandaloneController, ReadOnlyRequestFactory]:
    """Construct a fixed-disabled, recommendation-only staging boundary."""
    key = token_bytes(32)
    verifier = VerifierFirewall(
        {"deny": lambda _candidate: VerifierDecision(False, "staging disabled")},
        VerifierPolicy(default_verifier="deny"), attestation_key=key,
    )
    gateway = TrustedCommitGateway(
        trusted_verifier_ids=frozenset({"deny"}), verification_key=key,
        approval_key=token_bytes(32), policy_version="staging-disabled-v1",
        approval_nonce_store=InMemoryApprovalNonceStore(),
    )
    controller = StandaloneController(
        flags=FeatureFlags(enabled_requested=False),
        compiler=StateCompiler(), candidates=CandidateCompiler(),
        cvoc=RobustCvocController(), verifier=verifier, gateway=gateway,
        ledger=EphemeralStagingSink(),
    )
    definition = ActionDefinition(
        id="staging_noop", family=ActionFamily.TOOL, subgroup="staging",
        operation="noop", risk_class=RiskClass.READ_ONLY,
        argument_variants=((),), placements=("local",), verifier_ids=("deny",),
        optimistic_utility=0.0, estimated_cost=0.0,
    )
    factory = ReadOnlyRequestFactory(
        definitions=(definition,),
        policy=AuthorityPolicy(
            frozenset({ActionFamily.TOOL}), frozenset({RiskClass.READ_ONLY}),
        ),
        estimate_source=lambda _state: {},
        remaining_usd=0.0,
        data_boundary="local",
    )
    return controller, factory

