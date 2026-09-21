"""Bounded, inspectable state compilation for System-One decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .state_schema import (
    CompilationResult,
    CompilationStatus,
    CompiledState,
    RawState,
)


@dataclass(frozen=True, slots=True)
class StateLimits:
    max_items_per_field: int = 64
    max_mapping_entries: int = 64
    max_text_chars: int = 4096
    max_total_chars: int = 16_384

    def __post_init__(self) -> None:
        if min(
            self.max_items_per_field,
            self.max_mapping_entries,
            self.max_text_chars,
            self.max_total_chars,
        ) < 1:
            raise ValueError("all state limits must be positive")


class StateCompiler:
    """Compile runtime history without inventing or dropping consequential evidence."""

    def __init__(
        self,
        minimum_confidence: float = 0.5,
        limits: StateLimits = StateLimits(),
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between zero and one")
        self._minimum_confidence = minimum_confidence
        self._limits = limits

    def compile(self, raw: RawState) -> CompilationResult:
        missing_provenance = tuple(
            fact for fact in raw.verified_facts if fact not in raw.provenance
        )
        if missing_provenance:
            return CompilationResult(
                status=CompilationStatus.STATE_UNSAFE_TO_COMPRESS,
                state=None,
                reasons=("verified fact lacks provenance",),
            )
        bounds_error = self._check_bounds(raw)
        if bounds_error is not None:
            return CompilationResult(
                status=CompilationStatus.STATE_UNSAFE_TO_COMPRESS,
                state=None,
                reasons=(bounds_error,),
            )
        if not 0.0 <= raw.ambiguity <= 1.0:
            return CompilationResult(
                status=CompilationStatus.STATE_UNSAFE_TO_COMPRESS,
                state=None,
                reasons=("ambiguity must be between zero and one",),
            )

        confidence = max(0.0, 1.0 - raw.ambiguity)
        if confidence < self._minimum_confidence:
            return CompilationResult(
                status=CompilationStatus.STATE_UNSAFE_TO_COMPRESS,
                state=None,
                reasons=("compilation confidence below threshold",),
            )
        state = CompiledState(
            goal=raw.goal,
            current_subgoal=raw.current_subgoal,
            verified_facts=raw.verified_facts,
            open_questions=raw.open_questions,
            recent_failures=raw.recent_failures,
            available_action_families=raw.available_action_families,
            tool_summary=raw.tool_summary,
            model_inventory=raw.model_inventory,
            budget=dict(raw.budget),
            runtime_summary=dict(raw.runtime_summary),
            risk={**raw.risk, "consequence": raw.consequence},
            reversibility=raw.reversibility,
            approval_required=raw.approval_required,
            data_boundary=raw.data_boundary,
            rollback_state=raw.rollback_state,
            ambiguity=raw.ambiguity,
            state_compilation_confidence=confidence,
            provenance=dict(raw.provenance),
        )
        return CompilationResult(CompilationStatus.COMPILED, state)

    def _check_bounds(self, raw: RawState) -> str | None:
        sequences = {
            "verified_facts": raw.verified_facts,
            "open_questions": raw.open_questions,
            "recent_failures": raw.recent_failures,
            "available_action_families": raw.available_action_families,
            "tool_summary": raw.tool_summary,
            "model_inventory": raw.model_inventory,
        }
        for field_name, values in sequences.items():
            if len(values) > self._limits.max_items_per_field:
                return f"{field_name} exceeds item bound"
        mappings = {
            "budget": raw.budget,
            "runtime_summary": raw.runtime_summary,
            "risk": raw.risk,
            "provenance": raw.provenance,
        }
        for field_name, values in mappings.items():
            if len(values) > self._limits.max_mapping_entries:
                return f"{field_name} exceeds entry bound"
        text_values = (
            raw.goal,
            raw.current_subgoal,
            raw.reversibility,
            raw.data_boundary,
            raw.rollback_state or "",
            *raw.verified_facts,
            *raw.open_questions,
            *raw.recent_failures,
            *raw.tool_summary,
            *raw.model_inventory,
        )
        if any(len(value) > self._limits.max_text_chars for value in text_values):
            return "state field exceeds text bound"
        if sum(len(value) for value in text_values) > self._limits.max_total_chars:
            return "state exceeds total text bound"
        return None
