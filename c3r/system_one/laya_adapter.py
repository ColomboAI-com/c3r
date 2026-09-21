"""Dependency-injected adapter for pinned Laya-compatible inference backends."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re

from ..state_schema import CompiledState
from .question_registry import TypedQuestion

InferenceBackend = Callable[[CompiledState, tuple[TypedQuestion, ...]], Mapping[str, tuple[float, ...]]]
IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")


@dataclass(frozen=True, slots=True)
class LayaAdapter:
    model_id: str
    revision: str
    backend: InferenceBackend

    def __post_init__(self) -> None:
        if self.model_id not in {
            "convaiinnovations/laya",
            "convaiinnovations/laya-multilingual",
            "ColomboAI/C3R-Decision-Laya-421M-v0.1",
        }:
            raise ValueError("unapproved System-One checkpoint")
        if IMMUTABLE_REVISION.fullmatch(self.revision) is None:
            raise ValueError("revision must be an immutable 40-64 character hexadecimal hash")

    def predict(
        self,
        state: CompiledState,
        questions: tuple[TypedQuestion, ...],
    ) -> Mapping[str, tuple[float, ...]]:
        return self.backend(state, questions)
