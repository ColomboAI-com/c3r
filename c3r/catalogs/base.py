"""Immutable host-owned action definitions."""
from dataclasses import dataclass
from ..state_schema import ActionDefinition, AuthorityPolicy


@dataclass(frozen=True, slots=True)
class Catalog:
    name: str
    definitions: tuple[ActionDefinition, ...]
    policy: AuthorityPolicy
