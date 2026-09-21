"""Explicit System-One abstention policy."""

from __future__ import annotations


def should_abstain(
    probabilities: tuple[float, ...],
    *,
    minimum_top_probability: float,
    minimum_margin: float,
) -> bool:
    if len(probabilities) < 2:
        return True
    first, second = sorted(probabilities, reverse=True)[:2]
    return first < minimum_top_probability or first - second < minimum_margin

