"""Read-only host construction of bounded standalone decision requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from math import isfinite
from uuid import uuid4

from .runtime import RuntimeRequest
from .state_schema import ActionDefinition, AuthorityPolicy, RawState, RiskClass, ValueEstimate


EstimateSource = Callable[[RawState], Mapping[str, ValueEstimate]]


class ReadOnlyRequestFactory:
    """Accept task text only; all authority and estimates come from the host.

    The estimate source is mandatory because constant/example estimates must not be
    mistaken for measured production CVoC inputs.
    """

    def __init__(
        self,
        *,
        definitions: tuple[ActionDefinition, ...],
        policy: AuthorityPolicy,
        estimate_source: EstimateSource,
        remaining_usd: float,
        model_inventory: tuple[str, ...] = (),
        data_boundary: str = "local",
    ) -> None:
        if not definitions or any(item.risk_class is not RiskClass.READ_ONLY for item in definitions):
            raise ValueError("HTTP catalog must contain read-only definitions only")
        if policy.allowed_risks != frozenset({RiskClass.READ_ONLY}):
            raise ValueError("HTTP policy must permit read-only risk only")
        if not isfinite(remaining_usd) or remaining_usd < 0:
            raise ValueError("remaining_usd must be finite and non-negative")
        if data_boundary not in {"local", "approved_remote", "public"}:
            raise ValueError("host data boundary must be explicit")
        self._definitions = definitions
        self._policy = policy
        self._estimate_source = estimate_source
        self._remaining_usd = remaining_usd
        self._model_inventory = model_inventory
        self._data_boundary = data_boundary

    def build(self, payload: Mapping[str, object]) -> RuntimeRequest:
        goal = _text(payload.get("goal"), "goal")
        current_subgoal = _text(payload.get("current_subgoal"), "current_subgoal")
        questions = payload.get("open_questions", [])
        if not isinstance(questions, list) or len(questions) > 64:
            raise ValueError("open_questions must be a bounded array")
        open_questions = tuple(_text(item, "open_question") for item in questions)
        raw = RawState(
            goal=goal,
            current_subgoal=current_subgoal,
            open_questions=open_questions,
            available_action_families=tuple(
                sorted(self._policy.allowed_families, key=lambda family: family.value)
            ),
            model_inventory=self._model_inventory,
            budget={"remaining_usd": self._remaining_usd},
            data_boundary=self._data_boundary,
        )
        estimates = self._estimate_source(raw)
        if not isinstance(estimates, Mapping):
            raise ValueError("host estimate source returned an invalid mapping")
        return RuntimeRequest(
            raw_state=raw,
            definitions=self._definitions,
            policy=self._policy,
            estimates=estimates,
            run_id=str(uuid4()),
        )


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{name} must be non-empty bounded text")
    return value
