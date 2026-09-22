"""Calibrated, abstaining System-One execution path."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..state_schema import CompiledState
from .abstention import should_abstain
from .calibration import CalibrationKey, TemperatureCalibrator
from .laya_adapter import LayaAdapter
from .question_registry import TypedQuestion


def option_count_bucket(option_count: int) -> str:
    if option_count <= 2:
        return str(option_count)
    if option_count <= 5:
        return "3-5"
    if option_count <= 10:
        return "6-10"
    if option_count <= 20:
        return "11-20"
    return "21+"


@dataclass(frozen=True, slots=True)
class FastPathDecision:
    answers: dict[str, str]
    probabilities: dict[str, tuple[float, ...]]
    abstained: bool
    reasons: tuple[str, ...]
    model_id: str
    model_revision: str


class LayaFastPath:
    def __init__(
        self,
        *,
        adapter: LayaAdapter,
        calibrator: TemperatureCalibrator,
        minimum_top_probability: float = 0.65,
        minimum_margin: float = 0.10,
    ) -> None:
        if not 0.0 <= minimum_top_probability <= 1.0:
            raise ValueError("minimum_top_probability must be between 0 and 1")
        if not 0.0 <= minimum_margin <= 1.0:
            raise ValueError("minimum_margin must be between 0 and 1")
        self._adapter = adapter
        self._calibrator = calibrator
        self._minimum_top_probability = minimum_top_probability
        self._minimum_margin = minimum_margin

    def decide(
        self,
        state: CompiledState,
        questions: tuple[TypedQuestion, ...],
        *,
        action_family: str,
        language: str = "en",
    ) -> FastPathDecision:
        logits_by_question = self._adapter.predict(state, questions)
        consequence = str(state.risk.get("consequence", "default"))
        answers: dict[str, str] = {}
        probabilities: dict[str, tuple[float, ...]] = {}
        reasons: list[str] = []

        for question in questions:
            logits = logits_by_question.get(question.id)
            if (
                logits is None
                or len(logits) != len(question.options)
                or not all(math.isfinite(value) for value in logits)
            ):
                reasons.append(f"invalid prediction for {question.id}")
                continue
            key = CalibrationKey(
                question_type=question.id,
                action_family=action_family,
                option_count_bucket=option_count_bucket(len(question.options)),
                language=language,
                consequence_class=consequence,
            )
            if not self._calibrator.supports(key):
                reasons.append(f"missing calibration for {question.id}")
                continue
            calibrated = self._calibrator.apply(logits, key)
            probabilities[question.id] = calibrated
            if should_abstain(
                calibrated,
                minimum_top_probability=self._minimum_top_probability,
                minimum_margin=self._minimum_margin,
            ):
                reasons.append(f"low decision margin for {question.id}")
                continue
            best_index = max(range(len(calibrated)), key=calibrated.__getitem__)
            answers[question.id] = question.options[best_index]

        return FastPathDecision(
            answers=answers,
            probabilities=probabilities,
            abstained=bool(reasons),
            reasons=tuple(reasons),
            model_id=self._adapter.model_id,
            model_revision=self._adapter.revision,
        )
