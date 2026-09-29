"""Structured, bounded, fail-closed adapters for deliberative runtimes."""

from __future__ import annotations

import json
from math import isfinite
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..deliberative.envelope import DeliberativeResult
from ..state_schema import ActionFamily

MAX_RESPONSE_BYTES = 65_536
MAX_ARRAY_ITEMS = 32
MAX_ITEM_CHARS = 2_048
MAX_STRUCTURED_CHARS = 32_768


class ProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai-compatible"


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_id: str
    kind: ProviderKind
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("remote provider endpoints must use HTTPS")
        if not self.provider_id or not self.model:
            raise ValueError("provider_id and model are required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class DeliberationRequest:
    state: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    body: Mapping[str, object]
    latency_ms: float


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    deliberation: DeliberativeResult
    observed_cost: Mapping[str, float]
    provider_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class ControlledDeliberation:
    result: ProviderExecutionResult | None
    selected_action: ActionFamily
    fallback_used: bool
    failure_reason: str | None


Transport = Callable[[str, dict[str, str], dict[str, object]], TransportResponse]

_SYSTEM = (
    "Return only one JSON object with string-array fields plan, assumptions, uncertainty, "
    "candidate_commitments, and requested_actions. Propose computation; never claim commit authority."
)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    return number if isfinite(number) and number >= 0 else 0.0


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError("provider returned malformed or oversized structured deliberation")
    items = cast(list[object], value)
    if len(items) > MAX_ARRAY_ITEMS:
        raise TypeError("provider returned malformed or oversized structured deliberation")
    if not all(isinstance(item, str) and len(item) <= MAX_ITEM_CHARS for item in items):
        raise TypeError("provider returned malformed or oversized structured deliberation")
    return tuple(cast(str, item) for item in items)


def _content(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_STRUCTURED_CHARS:
        raise TypeError("provider returned malformed or oversized structured deliberation")
    return value


def _default_transport(
    url: str, headers: dict[str, str], payload: dict[str, object]
) -> TransportResponse:
    import time

    request_headers = dict(headers)
    timeout = float(request_headers.pop("X-C3R-Timeout", "60"))
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={**request_headers, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        status = int(response.status)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds byte limit")
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise TypeError("provider returned a non-object response")
    return TransportResponse(
        status, cast(dict[str, object], parsed), (time.monotonic() - started) * 1000
    )


class _ProviderCodec(Protocol):
    def build(
        self, config: ProviderConfig, state: str
    ) -> tuple[str, dict[str, str], dict[str, object]]: ...

    def extract(self, body: Mapping[str, object]) -> tuple[str, dict[str, float]]: ...


class _OpenAICodec:
    def build(
        self, config: ProviderConfig, state: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        headers = {"X-C3R-Timeout": str(config.timeout_seconds)}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        payload: dict[str, object] = {
            "model": config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": state},
            ],
        }
        return f"{config.base_url.rstrip('/')}/chat/completions", headers, payload

    def extract(self, body: Mapping[str, object]) -> tuple[str, dict[str, float]]:
        choices = cast(list[dict[str, object]], body["choices"])
        content = cast(dict[str, object], choices[0]["message"])["content"]
        usage = cast(Mapping[str, object], body.get("usage", {}))
        return _content(content), {
            "input_tokens": _number(usage.get("prompt_tokens", 0)),
            "output_tokens": _number(usage.get("completion_tokens", 0)),
        }


class _AnthropicCodec:
    def build(
        self, config: ProviderConfig, state: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        headers = {
            "X-C3R-Timeout": str(config.timeout_seconds),
            "anthropic-version": "2023-06-01",
        }
        if config.api_key:
            headers["x-api-key"] = config.api_key
        payload: dict[str, object] = {
            "model": config.model,
            "max_tokens": 2048,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": state}],
        }
        return f"{config.base_url.rstrip('/')}/messages", headers, payload

    def extract(self, body: Mapping[str, object]) -> tuple[str, dict[str, float]]:
        blocks = cast(list[dict[str, object]], body["content"])
        usage = cast(Mapping[str, object], body.get("usage", {}))
        return _content(blocks[0]["text"]), {
            "input_tokens": _number(usage.get("input_tokens", 0)),
            "output_tokens": _number(usage.get("output_tokens", 0)),
        }


class _GeminiCodec:
    def build(
        self, config: ProviderConfig, state: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        headers = {"X-C3R-Timeout": str(config.timeout_seconds)}
        if config.api_key:
            headers["x-goog-api-key"] = config.api_key
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": state}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
            },
        }
        return (
            f"{config.base_url.rstrip('/')}/models/{config.model}:generateContent",
            headers,
            payload,
        )

    def extract(self, body: Mapping[str, object]) -> tuple[str, dict[str, float]]:
        candidates = cast(list[dict[str, object]], body["candidates"])
        candidate = cast(dict[str, object], candidates[0]["content"])
        parts = cast(list[dict[str, object]], candidate["parts"])
        usage = cast(Mapping[str, object], body.get("usageMetadata", {}))
        return _content(parts[0]["text"]), {
            "input_tokens": _number(usage.get("promptTokenCount", 0)),
            "output_tokens": _number(usage.get("candidatesTokenCount", 0)),
        }


_CODECS: Mapping[ProviderKind, _ProviderCodec] = {
    ProviderKind.OPENAI: _OpenAICodec(),
    ProviderKind.OPENAI_COMPATIBLE: _OpenAICodec(),
    ProviderKind.ANTHROPIC: _AnthropicCodec(),
    ProviderKind.GEMINI: _GeminiCodec(),
}


class ProviderAdapter:
    def __init__(
        self, config: ProviderConfig, *, transport: Transport = _default_transport
    ) -> None:
        self.config = config
        self._transport = transport
        self._codec = _CODECS[config.kind]

    def deliberate(self, request: DeliberationRequest) -> ProviderExecutionResult:
        state = json.dumps(dict(request.state), sort_keys=True, separators=(",", ":"))
        url, headers, payload = self._codec.build(self.config, state)
        response = self._transport(url, headers, payload)
        if len(json.dumps(response.body, separators=(",", ":")).encode()) > MAX_RESPONSE_BYTES:
            raise ValueError("provider response exceeds byte limit")
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"provider request failed with status {response.status}")
        try:
            content, usage = self._codec.extract(response.body)
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise TypeError
            value = cast(dict[str, object], decoded)
            deliberation = DeliberativeResult(
                plan=_string_tuple(value.get("plan")),
                assumptions=_string_tuple(value.get("assumptions")),
                uncertainty=_string_tuple(value.get("uncertainty")),
                candidate_commitments=_string_tuple(value.get("candidate_commitments")),
                requested_actions=_string_tuple(value.get("requested_actions")),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(
                "provider returned malformed or oversized structured deliberation"
            ) from error
        return ProviderExecutionResult(
            deliberation=deliberation,
            observed_cost={"latency_ms": response.latency_ms, **usage},
            provider_id=self.config.provider_id,
            model_id=self.config.model,
        )


class ProviderController:
    """Convert provider failures into an explicit policy-selected fallback action."""

    def __init__(
        self, adapter: ProviderAdapter, *, fallback_action: ActionFamily
    ) -> None:
        self._adapter = adapter
        self._fallback_action = fallback_action

    def deliberate(self, request: DeliberationRequest) -> ControlledDeliberation:
        try:
            result = self._adapter.deliberate(request)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return ControlledDeliberation(
                None, self._fallback_action, True, type(error).__name__
            )
        return ControlledDeliberation(result, ActionFamily.DELIBERATE, False, None)
