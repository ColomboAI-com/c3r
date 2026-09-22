"""Held-out temperature fitting and release-gate calibration metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .calibration import CalibrationKey, TemperatureCalibrator


@dataclass(frozen=True, slots=True)
class CalibrationExample:
    key: CalibrationKey
    logits: tuple[float, ...]
    label_index: int


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    coverage: float
    selective_risk: float
    accepted: int


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    accuracy: float
    brier: float
    ece: float
    maximum_calibration_error: float
    nll: float
    risk_coverage: tuple[RiskCoveragePoint, ...]


@dataclass(frozen=True, slots=True)
class CalibrationSliceReport:
    sample_size: int
    temperature: float
    before: CalibrationMetrics
    after: CalibrationMetrics


@dataclass(frozen=True, slots=True)
class CalibrationFitResult:
    calibrator: TemperatureCalibrator
    reports: dict[CalibrationKey, CalibrationSliceReport]
    skipped_slices: dict[CalibrationKey, str]


def _softmax(logits: tuple[float, ...], temperature: float) -> tuple[float, ...]:
    scaled = tuple(value / temperature for value in logits)
    peak = max(scaled)
    values = tuple(math.exp(value - peak) for value in scaled)
    total = sum(values)
    return tuple(value / total for value in values)


def calibration_metrics(
    examples: list[CalibrationExample],
    *,
    temperature: float,
    bins: int = 10,
) -> CalibrationMetrics:
    if not examples:
        raise ValueError("at least one calibration example is required")
    correct = 0
    brier = 0.0
    nll = 0.0
    bucket_values: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    confidence_outcomes: list[tuple[float, float]] = []
    for example in examples:
        probabilities = _softmax(example.logits, temperature)
        if not 0 <= example.label_index < len(probabilities):
            raise ValueError("label index is outside the probability vector")
        predicted = max(range(len(probabilities)), key=probabilities.__getitem__)
        is_correct = float(predicted == example.label_index)
        correct += int(is_correct)
        brier += sum(
            (probability - float(index == example.label_index)) ** 2
            for index, probability in enumerate(probabilities)
        )
        nll -= math.log(max(probabilities[example.label_index], 1e-12))
        confidence = max(probabilities)
        confidence_outcomes.append((confidence, is_correct))
        bucket = min(int(confidence * bins), bins - 1)
        bucket_values[bucket].append((confidence, is_correct))

    count = len(examples)
    calibration_errors: list[tuple[int, float]] = []
    for values in bucket_values:
        if not values:
            continue
        average_confidence = sum(item[0] for item in values) / len(values)
        average_accuracy = sum(item[1] for item in values) / len(values)
        calibration_errors.append((len(values), abs(average_confidence - average_accuracy)))
    ece = sum(size * error for size, error in calibration_errors) / count
    mce = max((error for _, error in calibration_errors), default=0.0)
    confidence_outcomes.sort(key=lambda item: item[0], reverse=True)
    accepted_counts = sorted(
        {
            max(1, math.ceil(count * requested_coverage))
            for requested_coverage in (0.25, 0.50, 0.75, 1.0)
        }
    )
    risk_coverage = tuple(
        RiskCoveragePoint(
            coverage=accepted / count,
            selective_risk=(
                1.0
                - sum(outcome for _, outcome in confidence_outcomes[:accepted]) / accepted
            ),
            accepted=accepted,
        )
        for accepted in accepted_counts
    )
    return CalibrationMetrics(
        accuracy=correct / count,
        brier=brier / count,
        ece=ece,
        maximum_calibration_error=mce,
        nll=nll / count,
        risk_coverage=risk_coverage,
    )


def fit_calibration(
    examples: list[CalibrationExample],
    *,
    minimum_slice_size: int = 25,
    lower_temperature: float = 0.25,
    upper_temperature: float = 8.0,
    search_steps: int = 160,
) -> CalibrationFitResult:
    if (
        minimum_slice_size < 1
        or search_steps < 2
        or lower_temperature <= 0
        or upper_temperature <= lower_temperature
    ):
        raise ValueError("invalid calibration fit configuration")
    grouped: dict[CalibrationKey, list[CalibrationExample]] = defaultdict(list)
    for example in examples:
        grouped[example.key].append(example)

    temperatures: dict[CalibrationKey, float] = {}
    reports: dict[CalibrationKey, CalibrationSliceReport] = {}
    skipped: dict[CalibrationKey, str] = {}
    log_lower = math.log(lower_temperature)
    log_upper = math.log(upper_temperature)
    candidates = tuple(
        math.exp(log_lower + (log_upper - log_lower) * step / (search_steps - 1))
        for step in range(search_steps)
    )
    for key, slice_examples in grouped.items():
        if len(slice_examples) < minimum_slice_size:
            skipped[key] = (
                f"insufficient support: {len(slice_examples)} < {minimum_slice_size}"
            )
            continue
        best_temperature = min(
            candidates,
            key=lambda value: calibration_metrics(
                slice_examples, temperature=value
            ).nll,
        )
        before = calibration_metrics(slice_examples, temperature=1.0)
        after = calibration_metrics(slice_examples, temperature=best_temperature)
        temperatures[key] = best_temperature
        reports[key] = CalibrationSliceReport(
            sample_size=len(slice_examples),
            temperature=best_temperature,
            before=before,
            after=after,
        )
    return CalibrationFitResult(
        calibrator=TemperatureCalibrator(temperatures),
        reports=reports,
        skipped_slices=skipped,
    )
