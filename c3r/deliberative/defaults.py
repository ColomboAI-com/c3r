"""Auditable defaults for C3R's deliberative language-model path.

The CLM System-One decision model remains separate from this language-model
default. Defaults select a provider profile; they never bypass candidate,
verification, budget, or commit controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..adapters.providers import ProviderConfig, ProviderKind

DEFAULT_LANGUAGE_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
DEFAULT_DEEPSEEK_API_MODEL = "deepseek-flash"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash"


@dataclass(frozen=True, slots=True)
class DefaultModelProfile:
    display_name: str = "DeepSeek V4.1 Flash"
    checkpoint: str = DEFAULT_LANGUAGE_MODEL
    license_id: str = "MIT"
    role: str = "deliberative-language-model"


def default_provider_config(
    *, api_key: str | None = None,
    gateway: Literal["self_hosted", "openrouter", "deepseek"] = "self_hosted"
) -> ProviderConfig:
    """Default to local DeepSeek. Explicit remote profiles are legacy compatibility only."""
    if gateway == "self_hosted":
        return ProviderConfig("deepseek-local", ProviderKind.OPENAI_COMPATIBLE,
                              "http://127.0.0.1:8000/v1", "/model", None)
    if gateway not in {"openrouter", "deepseek"}:
        raise ValueError("unknown gateway")
    if not api_key:
        raise ValueError("api_key is required")
    if gateway == "deepseek":
        return ProviderConfig(
            provider_id="deepseek",
            kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://api.deepseek.com",
            model=DEFAULT_DEEPSEEK_API_MODEL,
            api_key=api_key,
        )
    return ProviderConfig(
        provider_id="openrouter-deepseek",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://openrouter.ai/api/v1",
        model=DEFAULT_OPENROUTER_MODEL,
        api_key=api_key,
    )
