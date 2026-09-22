"""Non-authoritative Colibri shadow recommendations with native fallback."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class ColibriAction(StrEnum):
    TARGET_ONLY = "TARGET_ONLY"
    DRAFT_2 = "DRAFT_2"
    DRAFT_4 = "DRAFT_4"
    DRAFT_8 = "DRAFT_8"
    DRAFT_K = "DRAFT_K"
    PAUSE_SPECULATION = "PAUSE_SPECULATION"
    RESUME_SPECULATION = "RESUME_SPECULATION"
    PREFETCH = "PREFETCH"
    RETAIN_RESOURCE = "RETAIN_RESOURCE"
    NATIVE_FALLBACK = "NATIVE_FALLBACK"


@dataclass(frozen=True, slots=True)
class ColibriSnapshot:
    route_trace: str
    coli_usage: float
    dspark_acceptance: float
    verification_width: int
    expert_union: int
    cache_residency: float
    expert_hit_rate: float
    bytes_read: int
    io_rate: float
    cpu_utilization: float
    gpu_utilization: float
    context_length: int

    def __post_init__(self) -> None:
        proportions = (
            self.coli_usage,
            self.dspark_acceptance,
            self.cache_residency,
            self.expert_hit_rate,
            self.cpu_utilization,
            self.gpu_utilization,
        )
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in proportions):
            raise ValueError("Colibri proportions must be finite values from zero to one")
        if min(self.verification_width, self.expert_union, self.bytes_read, self.context_length) < 0:
            raise ValueError("Colibri counters cannot be negative")
        if not math.isfinite(self.io_rate) or self.io_rate < 0:
            raise ValueError("Colibri I/O rate must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ColibriRecommendation:
    action: ColibriAction
    reason: str
    route_trace: str
    authoritative: bool = False


class ColibriShadowController:
    """Produces advisory actions while Colibri's native router stays authoritative."""

    def __init__(
        self,
        *,
        minimum_acceptance: float = 0.60,
        high_cache_residency: float = 0.80,
    ) -> None:
        if not 0.0 <= minimum_acceptance <= 1.0:
            raise ValueError("minimum_acceptance must be between zero and one")
        if not 0.0 <= high_cache_residency <= 1.0:
            raise ValueError("high_cache_residency must be between zero and one")
        self._minimum_acceptance = minimum_acceptance
        self._high_cache_residency = high_cache_residency

    def recommend(self, snapshot: ColibriSnapshot) -> ColibriRecommendation:
        if snapshot.dspark_acceptance < self._minimum_acceptance:
            action = ColibriAction.TARGET_ONLY
            reason = "native draft acceptance is below the shadow release threshold"
        elif snapshot.cache_residency >= self._high_cache_residency:
            action = ColibriAction.DRAFT_4
            reason = "native acceptance and cache residency support bounded speculation"
        elif snapshot.expert_hit_rate < 0.50:
            action = ColibriAction.PREFETCH
            reason = "expert hit rate is low; recommend advisory prefetch"
        else:
            action = ColibriAction.DRAFT_2
            reason = "use conservative bounded speculation in shadow mode"
        return ColibriRecommendation(action, reason, snapshot.route_trace)

    def fallback(self, reason: str) -> ColibriRecommendation:
        return ColibriRecommendation(
            ColibriAction.NATIVE_FALLBACK,
            f"native Colibri behavior retained: {reason}",
            "unavailable",
        )
