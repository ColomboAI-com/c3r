"""Policy-first bounded candidate compilation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .state_schema import (
    ActionCandidate,
    ActionFamily,
    AuthorityPolicy,
    CandidateCompilation,
)


class CandidateCompiler:
    def __init__(self, per_family_cap: int = 8) -> None:
        if per_family_cap < 1:
            raise ValueError("per_family_cap must be positive")
        self._per_family_cap = per_family_cap

    def compile(
        self,
        candidates: Iterable[ActionCandidate],
        policy: AuthorityPolicy,
    ) -> CandidateCompilation:
        feasible: dict[ActionFamily, list[ActionCandidate]] = defaultdict(list)
        masked: list[str] = []

        for candidate in candidates:
            if not policy.permits(candidate):
                masked.append(candidate.id)
                continue
            feasible[candidate.family].append(candidate)

        bounded: list[ActionCandidate] = []
        for family in sorted(feasible, key=lambda item: item.value):
            ranked = sorted(
                feasible[family],
                key=lambda candidate: (-candidate.optimistic_utility, candidate.id),
            )
            bounded.extend(ranked[: self._per_family_cap])

        return CandidateCompilation(
            candidates=tuple(bounded),
            masked_ids=tuple(masked),
            no_safe_action=not bounded,
        )

