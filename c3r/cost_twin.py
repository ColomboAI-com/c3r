"""A bounded dual-timescale cost estimator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CostForecast:
    expected: float
    p95: float
    stale: bool


@dataclass(slots=True)
class AdaptiveCostTwin:
    priors: dict[str, CostForecast]
    residual_alpha: float = 0.2
    stale_error_threshold: float = 0.5
    _residuals: dict[str, float] = field(default_factory=dict, init=False)
    _stale: set[str] = field(default_factory=set, init=False)

    def forecast(self, action_id: str) -> CostForecast:
        prior = self.priors[action_id]
        residual = self._residuals.get(action_id, 0.0)
        return CostForecast(
            expected=max(0.0, prior.expected + residual),
            p95=max(0.0, prior.p95 + abs(residual)),
            stale=action_id in self._stale or prior.stale,
        )

    def observe(self, action_id: str, observed_cost: float) -> None:
        forecast = self.forecast(action_id)
        error = observed_cost - forecast.expected
        previous = self._residuals.get(action_id, 0.0)
        self._residuals[action_id] = previous + self.residual_alpha * error
        relative_error = abs(error) / max(forecast.expected, 1e-9)
        if relative_error > self.stale_error_threshold:
            self._stale.add(action_id)

