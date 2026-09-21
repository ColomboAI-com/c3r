"""Canonical action and risk vocabulary for the initial release."""

from .state_schema import ActionFamily, RiskClass

ACTION_FAMILIES = tuple(ActionFamily)
RISK_CLASSES = tuple(RiskClass)

