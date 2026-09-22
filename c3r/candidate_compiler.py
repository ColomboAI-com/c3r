"""Policy-first bounded candidate compilation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace

from .state_schema import (
    ActionCandidate,
    ActionDefinition,
    ActionFamily,
    AuthorityPolicy,
    CandidateCompilation,
)
from .progressive_widening import widen_when_margin_is_small


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

    def compile_hierarchical(
        self,
        definitions: Iterable[ActionDefinition],
        policy: AuthorityPolicy,
        *,
        remaining_budget: float,
        allowed_verifiers: frozenset[str],
        allowed_placements: frozenset[str] | None = None,
        initial_width: int = 1,
        maximum_width: int | None = None,
        widening_margin: float = 0.05,
        minimum_optimistic_utility: float = 0.0,
    ) -> CandidateCompilation:
        """Compile family -> subgroup -> operation -> arguments -> placement/verifier.

        Policy masks are applied to definitions before any argument or placement expansion.
        Budget and optimistic utility bounds then prune branches. Progressive widening only
        expands statistically close operations inside each surviving family.
        """
        if remaining_budget < 0:
            raise ValueError("remaining_budget cannot be negative")
        if initial_width < 1:
            raise ValueError("initial_width must be positive")
        maximum_width = maximum_width or self._per_family_cap

        feasible: dict[ActionFamily, list[ActionDefinition]] = defaultdict(list)
        masked: list[str] = []
        pruned: list[str] = []
        for definition in definitions:
            skeleton = ActionCandidate(
                definition.id,
                definition.family,
                definition.risk_class,
                definition.optimistic_utility,
            )
            variants = definition.argument_variants or ((),)
            argument_keys_are_valid = all(
                len(keys := tuple(key for key, _ in variant)) == len(set(keys))
                and definition.required_argument_keys.issubset(keys)
                and (
                    not definition.allowed_argument_keys
                    or set(keys).issubset(definition.allowed_argument_keys)
                )
                and all(key and value for key, value in variant)
                for variant in variants
            )
            placement_is_valid = (
                allowed_placements is None
                or set(definition.placements or ("default",)).issubset(allowed_placements)
            )
            if (
                not policy.permits(skeleton)
                or definition.data_boundary not in policy.allowed_data_boundaries
                or not definition.provenance_complete
                or not argument_keys_are_valid
                or not placement_is_valid
                or not allowed_verifiers.intersection(definition.verifier_ids)
            ):
                masked.append(definition.id)
                continue
            if (
                definition.estimated_cost > remaining_budget
                or definition.optimistic_utility < minimum_optimistic_utility
            ):
                pruned.append(definition.id)
                continue
            feasible[definition.family].append(definition)

        compiled: list[ActionCandidate] = []
        widened: list[ActionFamily] = []
        for family in sorted(feasible, key=lambda item: item.value):
            by_subgroup: dict[str, list[ActionDefinition]] = defaultdict(list)
            for definition in feasible[family]:
                by_subgroup[definition.subgroup].append(definition)
            subgroup_skeletons = tuple(
                ActionCandidate(
                    subgroup,
                    family,
                    min(items, key=lambda item: item.risk_class.value).risk_class,
                    max(item.optimistic_utility - item.estimated_cost for item in items),
                )
                for subgroup, items in by_subgroup.items()
            )
            selected_subgroups = widen_when_margin_is_small(
                subgroup_skeletons,
                initial_width=initial_width,
                maximum_width=min(maximum_width, self._per_family_cap),
                margin=widening_margin,
            )
            if len(selected_subgroups) > min(initial_width, len(subgroup_skeletons)):
                widened.append(family)

            family_candidates: list[ActionCandidate] = []
            for subgroup_skeleton in selected_subgroups:
                subgroup_definitions = by_subgroup[subgroup_skeleton.id]
                operation_skeletons = tuple(
                    ActionCandidate(
                        item.id,
                        item.family,
                        item.risk_class,
                        item.optimistic_utility - item.estimated_cost,
                    )
                    for item in subgroup_definitions
                )
                selected_operations = widen_when_margin_is_small(
                    operation_skeletons,
                    initial_width=initial_width,
                    maximum_width=min(maximum_width, self._per_family_cap),
                    margin=widening_margin,
                )
                if len(selected_operations) > min(initial_width, len(operation_skeletons)):
                    if family not in widened:
                        widened.append(family)
                definitions_by_id = {item.id: item for item in subgroup_definitions}
                for selected_skeleton in selected_operations:
                    definition = definitions_by_id[selected_skeleton.id]
                    verifiers = tuple(
                        verifier
                        for verifier in definition.verifier_ids
                        if verifier in allowed_verifiers
                    )
                    variants = definition.argument_variants or ((),)
                    placements = definition.placements or ("default",)
                    for variant_index, arguments in enumerate(variants):
                        for placement in placements:
                            for verifier in verifiers:
                                payload = (
                                    ("subgroup", definition.subgroup),
                                    ("operation", definition.operation),
                                    ("placement", placement),
                                    *arguments,
                                )
                                family_candidates.append(
                                    replace(
                                        selected_skeleton,
                                        id=(
                                            f"{definition.id}:{variant_index}:"
                                            f"{placement}:{verifier}"
                                        ),
                                        requested_verifier=verifier,
                                        payload=payload,
                                    )
                                )
                                if len(family_candidates) >= self._per_family_cap:
                                    break
                            if len(family_candidates) >= self._per_family_cap:
                                break
                        if len(family_candidates) >= self._per_family_cap:
                            break
                    if len(family_candidates) >= self._per_family_cap:
                        break
                if len(family_candidates) >= self._per_family_cap:
                    break
            compiled.extend(family_candidates)

        return CandidateCompilation(
            candidates=tuple(compiled),
            masked_ids=tuple(masked),
            no_safe_action=not compiled,
            pruned_ids=tuple(pruned),
            widened_families=tuple(widened),
        )
