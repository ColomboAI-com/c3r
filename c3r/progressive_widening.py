"""Deterministic progressive widening for statistically close candidates."""

from __future__ import annotations

from collections.abc import Sequence

from .state_schema import ActionCandidate


def widen_when_margin_is_small(
    ranked: Sequence[ActionCandidate],
    *,
    initial_width: int,
    maximum_width: int,
    margin: float,
) -> tuple[ActionCandidate, ...]:
    if initial_width < 1 or maximum_width < initial_width:
        raise ValueError("invalid widening bounds")
    if not ranked:
        return ()
    ordered = sorted(ranked, key=lambda item: (-item.optimistic_utility, item.id))
    width = min(initial_width, len(ordered))
    while width < min(maximum_width, len(ordered)):
        boundary = ordered[width - 1].optimistic_utility - ordered[width].optimistic_utility
        if boundary > margin:
            break
        width += 1
    return tuple(ordered[:width])

