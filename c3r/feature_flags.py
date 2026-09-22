"""Fail-closed feature flags for every learned or native C3R control surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be an explicit boolean")


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    enabled_requested: bool = False
    system_one_requested: bool = False
    deliberative_requested: bool = False
    routing_requested: bool = False
    speculation_requested: bool = False
    moe_control_requested: bool = False
    online_learning_requested: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> FeatureFlags:
        flags = cls(
            enabled_requested=_boolean(values, "C3R_ENABLED", False),
            system_one_requested=_boolean(values, "C3R_SYSTEM_ONE", False),
            deliberative_requested=_boolean(values, "C3R_DELIBERATIVE", False),
            routing_requested=_boolean(values, "C3R_ROUTING", False),
            speculation_requested=_boolean(values, "C3R_SPECULATION", False),
            moe_control_requested=_boolean(values, "C3R_MOE_CONTROL", False),
            online_learning_requested=_boolean(values, "C3R_ONLINE_LEARNING", False),
        )
        if flags.online_learning_requested:
            raise ValueError("autonomous online learning is prohibited")
        return flags

    @property
    def system_one_enabled(self) -> bool:
        return self.enabled_requested and self.system_one_requested

    @property
    def deliberative_enabled(self) -> bool:
        return self.enabled_requested and self.deliberative_requested

    @property
    def routing_enabled(self) -> bool:
        return self.enabled_requested and self.routing_requested

    @property
    def speculation_enabled(self) -> bool:
        return self.enabled_requested and self.speculation_requested

    @property
    def moe_control_enabled(self) -> bool:
        return self.enabled_requested and self.moe_control_requested
