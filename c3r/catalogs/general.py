"""Compute recommendations only, not implemented tool capabilities."""
from .base import Catalog
from ..state_schema import ActionDefinition, ActionFamily, AuthorityPolicy, RiskClass


def general_catalog(name: str = "agent-v1") -> Catalog:
    operations = (
        ("STOP", ActionFamily.STOP), ("WAIT", ActionFamily.STOP),
        ("VERIFY", ActionFamily.VERIFY), ("RETRIEVE", ActionFamily.RETRIEVAL),
        ("SYSTEM_ONE", ActionFamily.LOCAL_MODEL), ("DELIBERATE", ActionFamily.DELIBERATE),
        ("CALL_LOCAL_MODEL", ActionFamily.LOCAL_MODEL),
        ("CALL_FRONTIER_MODEL", ActionFamily.FRONTIER_MODEL), ("ASK_USER", ActionFamily.ASK_USER),
    )
    definitions = tuple(ActionDefinition(
        id=operation, family=family, subgroup="compute", operation=operation,
        risk_class=RiskClass.READ_ONLY, argument_variants=((),), placements=("local",),
        verifier_ids=("recommendation",), optimistic_utility=0, estimated_cost=0,
    ) for operation, family in operations)
    return Catalog(name, definitions, AuthorityPolicy(
        frozenset(family for _, family in operations), frozenset({RiskClass.READ_ONLY}),
        allowed_data_boundaries=frozenset({"local"})))
