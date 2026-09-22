"""Data-boundary-aware bridge from compiled C3R state to provider adapters."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlparse

from ..adapters.providers import DeliberationRequest, ProviderAdapter
from ..deliberative.envelope import DeliberativeResult
from ..state_schema import CompiledState


class ProviderDeliberator:
    """Return a non-authoritative plan; never execute model-requested actions."""

    def __init__(self, adapter: ProviderAdapter) -> None:
        self._adapter = adapter

    def deliberate(self, state: CompiledState) -> DeliberativeResult:
        hostname = urlparse(self._adapter.config.base_url).hostname
        local = hostname in {"localhost", "127.0.0.1", "::1"}
        if not local and state.data_boundary not in {"approved_remote", "public"}:
            raise ValueError("state is not approved for a remote provider")
        result = self._adapter.deliberate(DeliberationRequest(asdict(state)))
        return result.deliberation
