"""Minimum reproducible decision trace from the C3R paper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    run_id: str
    state_hash: str
    access_level: str
    model_provider: str
    candidate_ids: tuple[str, ...]
    probabilities: Mapping[str, tuple[float, ...]]
    utility_quantiles: Mapping[str, float]
    selected_action_id: str | None
    authority_result: str
    system_cost: Mapping[str, float]
    task_outcome: Mapping[str, str | float | bool]
    artifact_refs: tuple[str, ...]

