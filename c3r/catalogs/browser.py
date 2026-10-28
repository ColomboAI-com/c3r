"""Browser execution is deliberately unavailable in stateless v1."""
from .general import general_catalog


def browser_catalog():
    return general_catalog("browser-v1")
