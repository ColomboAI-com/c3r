"""Conservative calibrated value-of-computation selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .state_schema import ActionCandidate, ActionFamily, CvocDecision, ValueEstimate


class RobustCvocController:
    def __init__(self, uncertainty_multiplier: float = 1.96) -> None:
        if uncertainty_multiplier < 0:
            raise ValueError("uncertainty_multiplier cannot be negative")
        self._uncertainty_multiplier = uncertainty_multiplier

    def lower_bound(self, estimate: ValueEstimate) -> float:
        return (
            estimate.expected_gain
            - estimate.total_cost
            - estimate.risk_penalty
            - self._uncertainty_multiplier * estimate.uncertainty
        )

    def select(
        self,
        candidates: Iterable[ActionCandidate],
        estimates: Mapping[str, ValueEstimate],
    ) -> CvocDecision:
        scored = tuple(
            (self.lower_bound(estimates[candidate.id]), candidate)
            for candidate in candidates
            if candidate.id in estimates
        )
        if not scored:
            return CvocDecision(None, float("-inf"), ActionFamily.STOP)

        lower_bound, selected = max(scored, key=lambda item: (item[0], item[1].id))
        if lower_bound <= 0:
            return CvocDecision(None, lower_bound, ActionFamily.STOP)
        return CvocDecision(selected, lower_bound, None)
