"""Uncalibrated ranker which makes no learned control/authority decisions."""
from collections.abc import Sequence
from ..state_schema import CompiledState
from .clm_adapter import ClmAdapter
from .fast_path import FastPathDecision
from .question_registry import TypedQuestion


class AdvisoryFastPath:
    def __init__(self, adapter: ClmAdapter) -> None:
        self.adapter = adapter

    @property
    def provider(self) -> str:
        return self.adapter.provider

    def decide(self, state: CompiledState, questions: Sequence[TypedQuestion], *,
               action_family: str, language: str = "en",
               candidate_options: tuple[str, ...] = ()) -> FastPathDecision:
        scores = self.adapter.rank_actions(state, candidate_options) if candidate_options else ()
        return FastPathDecision({}, {}, False, ("UNCALIBRATED_ADVISORY_ONLY",),
                                self.adapter.model_id, self.adapter.revision, scores)
