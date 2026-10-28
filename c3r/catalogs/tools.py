"""Routing recommendations only; no arbitrary tool or URL invocation."""
from .general import general_catalog


def tool_catalog():
    return general_catalog("tool-routing-v1")
