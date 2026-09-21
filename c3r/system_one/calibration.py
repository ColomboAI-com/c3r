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
        scaled = tuple(value / temperature for value in logits)
        peak = max(scaled)
        exps = tuple(math.exp(value - peak) for value in scaled)
        total = sum(exps)
        return tuple(value / total for value in exps)

