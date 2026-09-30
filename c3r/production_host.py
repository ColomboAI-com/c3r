"""Production composition for stateless, non-authoritative inference only."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from secrets import token_bytes
from typing import cast
from urllib.request import ProxyHandler, build_opener

from .adapters.providers import ProviderAdapter, ProviderConfig, ProviderKind
from .candidate_compiler import CandidateCompiler
from .catalogs.browser import browser_catalog
from .catalogs.general import general_catalog
from .catalogs.registry import CatalogRegistry
from .catalogs.tools import tool_catalog
from .cvoc import RobustCvocController
from .feature_flags import FeatureFlags
from .host_components import HostComponents
from .http_transport import NoRedirectHandler
from .readiness import CachedReadiness
from .responses import ResponsesService
from .runtime import StandaloneController
from .state_compiler import StateCompiler
from .state_schema import RiskClass
from .system_one.advisory import AdvisoryFastPath
from .system_one.clm_adapter import UPSTREAM_CLM_COMMIT, ClmAdapter
from .system_one.inference import SystemOneInference
from .telemetry.ephemeral import EphemeralTraceSink
from .verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy

ENCODER_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
HEAD_REVISION = "e939398d4556fcd9400c76fa8c5a513202f42b0a"
HEAD_SHA256 = "b2b4a8c9c2d39263eff78a351eb909a342ce9b3bf21a3f07c1d1bf15f1c4eda5"


class ProviderReadiness:
    def __init__(self, adapter: ClmAdapter, container_digest: str) -> None:
        self.adapter, self.container_digest = adapter, container_digest
        self.system_one = CachedReadiness(self._system_one)
        self.deliberative = CachedReadiness(self._deliberative)

    def _get(self, url: str) -> Mapping[str, object]:
        with build_opener(ProxyHandler({}), NoRedirectHandler()).open(url, timeout=2) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("oversized provider readback")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("invalid provider readback")
        return cast(Mapping[str, object], value)

    def _system_one(self) -> bool:
        try:
            models = self._get("http://127.0.0.1:8090/v1/models")
            rows = models.get("data")
            if not isinstance(rows, list) or not any(
                isinstance(row, dict) and cast(Mapping[str, object], row).get("id") == "qwen3-8b"
                and cast(Mapping[str, object], row).get("root") == "/encoder"
                for row in cast(list[object], rows)
            ):
                return False
            health = self._get(self.adapter.endpoint + "/health")
            if health.get("embedder") is not True or health.get("mock", False) is not False:
                return False
            artifact = self._get(self.adapter.endpoint + "/internal/clm/artifact")
            expected = {
                "clm_source_revision": UPSTREAM_CLM_COMMIT, "encoder": "Qwen/Qwen3-8B",
                "encoder_revision": ENCODER_REVISION, "head_revision": HEAD_REVISION,
                "head_sha256": HEAD_SHA256, "container_digest": self.container_digest,
                "embedding_cache_size": 0, "action_cache_enabled": False,
                "encoder_content_verified": True,
                "encoder_identity_basis": "immutable_upstream_git_blobs_and_lfs_sha256",
            }
            if any(artifact.get(key) != value for key, value in expected.items()):
                return False
            scores = self.adapter.rank_text("An invoice was charged twice.",
                                            "Which department handles billing?",
                                            ("Billing", "Technical"))
            return len(scores) == 2
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _deliberative(self) -> bool:
        try:
            rows = self._get("http://127.0.0.1:8000/v1/models").get("data")
            listed = isinstance(rows, list) and any(
                isinstance(row, dict) and cast(Mapping[str, object], row).get("id") == "/model"
                for row in cast(list[object], rows))
            if not listed:
                return False
            probe = ProviderAdapter(ProviderConfig(
                "deepseek-readiness", ProviderKind.OPENAI_COMPATIBLE,
                "http://127.0.0.1:8000/v1", "/model", None, timeout_seconds=5,
            ))
            text, _, _ = probe.generate("Reply with the word ready only.", 256)
            return bool(text.strip())
        except (OSError, RuntimeError, ValueError, TypeError):
            return False

    def all(self) -> bool:
        return self.system_one() and self.deliberative()


def build() -> HostComponents:
    flags = FeatureFlags.from_mapping(os.environ)
    if (not flags.enabled_requested or not flags.system_one_enabled
            or not flags.deliberative_enabled or flags.system_one_provider != "clm"):
        raise ValueError("production host requires enabled CLM and deliberative inference")
    if os.environ.get("C3R_MODE") != "production_inference":
        raise ValueError("production host requires production_inference mode")
    for field in ("C3R_TRACE_COLLECTION", "C3R_ONLINE_LEARNING"):
        if os.environ.get(field, "false").lower() not in {"false", "off", "0"}:
            raise ValueError("production host cannot collect or learn online")
    container = os.environ.get("C3R_CLM_CONTAINER_DIGEST", "")
    if len(container) != 71 or not container.startswith("sha256:"):
        raise ValueError("measured immutable CLM container identity required")
    adapter = ClmAdapter(HEAD_SHA256, timeout_seconds=3)
    readiness = ProviderReadiness(adapter, container)
    registry = CatalogRegistry((general_catalog(), browser_catalog(), tool_catalog(),
                                general_catalog("research-v1")))
    verifier = VerifierFirewall({"recommendation": lambda candidate: VerifierDecision(
        candidate.risk_class is RiskClass.READ_ONLY,
        "read-only recommendation; no tool execution or truth claim",
    )}, VerifierPolicy("recommendation"), attestation_key=token_bytes(32))
    runtime = StandaloneController(
        flags=flags, compiler=StateCompiler(), candidates=CandidateCompiler(),
        cvoc=RobustCvocController(), verifier=verifier, ledger=EphemeralTraceSink(),
        fast_path=AdvisoryFastPath(adapter), readiness_probe=readiness.all,
    )
    provider = ProviderAdapter(ProviderConfig(
        "deepseek-local", ProviderKind.OPENAI_COMPATIBLE,
        "http://127.0.0.1:8000/v1", "/model", None, timeout_seconds=60,
    ))
    return HostComponents(runtime, registry, SystemOneInference(adapter, readiness=readiness.system_one),
                          ResponsesService(runtime, registry, provider))
