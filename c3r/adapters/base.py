"""Invariant adapter contract for closed and open model/runtime surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ..state_schema import ActionCandidate


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output: object
    observed_cost: Mapping[str, float]
    artifact_refs: tuple[str, ...]


class ComputeAdapter(Protocol):
    adapter_id: str
    access_level: str

    def execute(self, candidate: ActionCandidate) -> ExecutionResult: ...

