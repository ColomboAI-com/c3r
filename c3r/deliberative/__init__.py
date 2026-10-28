"""Interfaces for open and frontier deliberative models."""

from importlib import import_module

from .envelope import DeliberativeEnvelope, DeliberativeResult


def __getattr__(name: str):
    if name in {
        "DEFAULT_DEEPSEEK_API_MODEL",
        "DEFAULT_LANGUAGE_MODEL",
        "DEFAULT_OPENROUTER_MODEL",
        "DefaultModelProfile",
        "default_provider_config",
    }:
        defaults = import_module(".defaults", __name__)
        return getattr(defaults, name)
    raise AttributeError(name)

__all__ = [
    "DEFAULT_DEEPSEEK_API_MODEL",
    "DEFAULT_LANGUAGE_MODEL",
    "DEFAULT_OPENROUTER_MODEL",
    "DefaultModelProfile",
    "DeliberativeEnvelope",
    "DeliberativeResult",
    "default_provider_config",
]
