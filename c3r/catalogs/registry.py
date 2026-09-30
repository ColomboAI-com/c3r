"""Admission of caller task text to registered, host-owned catalogs."""
from collections.abc import Mapping
import json
from ..host_factory import ReadOnlyRequestFactory
from ..runtime import RuntimeRequest
from .base import Catalog


class CatalogRegistry:
    def __init__(self, catalogs: tuple[Catalog, ...]) -> None:
        self._factories = {catalog.name: ReadOnlyRequestFactory(
            definitions=catalog.definitions, policy=catalog.policy,
            # Unpriced/unknown quality has no positive CVoC estimate. No invented
            # dollar cost or success probability is admitted as measured evidence.
            estimate_source=lambda _state: {}, remaining_usd=0,
            model_inventory=("c3r-system-one", "deepseek"), data_boundary="local",
        ) for catalog in catalogs}

    def build(self, payload: Mapping[str, object]) -> RuntimeRequest:
        if set(payload) - {"goal", "state", "current_subgoal", "open_questions",
                           "catalog", "application_id"}:
            raise ValueError("caller authority or unsupported fields rejected")
        catalog = payload.get("catalog", "agent-v1")
        if not isinstance(catalog, str) or catalog not in self._factories:
            raise ValueError("unregistered catalog")
        application = payload.get("application_id")
        if application is not None and (not isinstance(application, str) or len(application) > 128):
            raise ValueError("invalid application identifier")
        state = payload.get("state", payload.get("current_subgoal", payload.get("goal")))
        if isinstance(state, dict):
            state = json.dumps(state, ensure_ascii=False, allow_nan=False)
        return self._factories[catalog].build({
            "goal": payload.get("goal"), "current_subgoal": state,
            "open_questions": payload.get("open_questions", []),
        })
