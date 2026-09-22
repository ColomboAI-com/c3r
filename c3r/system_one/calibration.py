"""Post-hoc probability calibration metadata and application."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationKey:
    question_type: str
    action_family: str
    option_count_bucket: str
    language: str = "en"
    consequence_class: str = "default"


@dataclass(frozen=True, slots=True)
class TemperatureCalibrator:
    temperatures: dict[CalibrationKey, float]

    def apply(self, logits: tuple[float, ...], key: CalibrationKey) -> tuple[float, ...]:
        temperature = self.temperatures.get(key)
        if temperature is None or temperature <= 0:
            raise ValueError("calibration metadata unavailable for decision slice")
        if not logits or not all(math.isfinite(value) for value in logits):
            raise ValueError("model logits must be finite and non-empty")
        scaled = tuple(value / temperature for value in logits)
        peak = max(scaled)
        exps = tuple(math.exp(value - peak) for value in scaled)
        total = sum(exps)
        return tuple(value / total for value in exps)

    def supports(self, key: CalibrationKey) -> bool:
        temperature = self.temperatures.get(key)
        return temperature is not None and temperature > 0
