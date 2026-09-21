"""Structured contract for Qwen, DeepSeek, and frontier-model deliberation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..state_schema import CompiledState


@dataclass(frozen=True, slots=True)
class DeliberativeResult:
    plan: tuple[str, ...]
    assumptions: tuple[str, ...]
    uncertainty: tuple[str, ...]
    candidate_commitments: tuple[str, ...]
    requested_actions: tuple[str, ...]


class DeliberativeEnvelope(Protocol):
    provider_id: str
    model_id: str

    def deliberate(self, state: CompiledState) -> DeliberativeResult: ...

