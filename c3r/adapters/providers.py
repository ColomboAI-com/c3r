"""Structured, bounded, fail-closed adapters for deliberative runtimes."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from math import isfinite
from threading import Event, Thread
from typing import Protocol, cast
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from ..deliberative.envelope import DeliberativeResult
from ..http_transport import NoRedirectHandler
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
    api_key: str | None = field(repr=False)
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("remote provider endpoints must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("provider origin must not contain credentials, query, or fragment")
        if not self.provider_id or not self.model:
            raise ValueError("provider_id and model are required")
        if not isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be positive")

    @property
    def is_local(self) -> bool:
        return urlparse(self.base_url).hostname in {"localhost", "127.0.0.1", "::1"}

    @property
    def uses_openrouter(self) -> bool:
        return self.base_url.rstrip("/") == "https://openrouter.ai/api/v1"


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
    with build_opener(ProxyHandler({}), NoRedirectHandler()).open(request, timeout=timeout) as response:
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


class TextGenerationStream(Iterator[tuple[str, str | None, dict[str, int] | None]]):
    """Closeable, bounded reader of an actual OpenAI-compatible generation stream."""

    def __init__(self, response: HTTPResponse, connection: HTTPConnection,
                 backend_socket: socket.socket) -> None:
        self._response = response
        self._connection = connection
        self._backend_socket = backend_socket
        self._finished = False
        self._reading = False
        self._saw_finish = False
        self._bytes = 0

    def __iter__(self) -> TextGenerationStream:
        return self

    def __next__(self) -> tuple[str, str | None, dict[str, int] | None]:
        if self._finished:
            raise StopIteration
        try:
            while True:
                self._reading = True
                try:
                    line = self._response.readline(16_385)
                finally:
                    self._reading = False
                    if self._finished:
                        self._response.close()
                if not line or len(line) > 16_384:
                    raise RuntimeError("generation stream ended without completion")
                self._bytes += len(line)
                if self._bytes > MAX_RESPONSE_BYTES:
                    raise RuntimeError("generation stream exceeds byte limit")
                if not line.startswith(b"data: "):
                    continue
                data = line[6:].strip()
                if data == b"[DONE]":
                    self.close()
                    if not self._saw_finish:
                        raise RuntimeError("generation stream ended without a finish reason")
                    raise StopIteration
                event_raw = json.loads(data)
                if not isinstance(event_raw, dict):
                    raise TypeError("invalid generation stream event")
                event = cast(Mapping[str, object], event_raw)
                choices = event.get("choices")
                usage = event.get("usage")
                if usage is not None:
                    if not isinstance(usage, dict):
                        raise TypeError("invalid generation usage")
                    usage = cast(Mapping[str, object], usage)
                    input_tokens = usage.get("prompt_tokens")
                    output_tokens = usage.get("completion_tokens")
                    if (isinstance(input_tokens, bool) or not isinstance(input_tokens, int)
                            or input_tokens < 0 or isinstance(output_tokens, bool)
                            or not isinstance(output_tokens, int) or output_tokens < 0):
                        raise ValueError("invalid generation token counts")
                    counts = {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    }
                else:
                    counts = None
                if not isinstance(choices, list):
                    raise TypeError("invalid generation choices")
                choices = cast(list[object], choices)
                if len(choices) > 1:
                    raise ValueError("invalid generation choices")
                if not choices:
                    if counts is None:
                        raise ValueError("empty generation stream event")
                    return "", None, counts
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise TypeError("invalid generation choice")
                choice = cast(Mapping[str, object], choice)
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    raise TypeError("invalid generation delta")
                delta = cast(Mapping[str, object], delta)
                if delta.get("tool_calls") or delta.get("function_call"):
                    raise ValueError("invalid generation delta")
                content = delta.get("content", "")
                if not isinstance(content, str):
                    raise TypeError("invalid generation text")
                finish = choice.get("finish_reason")
                if finish is not None and not isinstance(finish, str):
                    raise TypeError("invalid generation finish reason")
                if finish not in {None, "stop", "length"}:
                    raise ValueError("invalid generation finish reason")
                if finish is not None:
                    self._saw_finish = True
                return content, finish, counts
        except StopIteration:
            raise
        except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
            self.close()
            raise

    def abort(self) -> None:
        if not self._finished:
            self._finished = True
            try:
                self._backend_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._connection.close()

    def close(self) -> None:
        self.abort()
        if not self._reading:
            self._response.close()


class ProviderAdapter:
    def __init__(
        self, config: ProviderConfig, *, transport: Transport = _default_transport
    ) -> None:
        self.config = config
        self._transport = transport
        self._codec = _CODECS[config.kind]

    def generate(self, text: str, max_output_tokens: int) -> tuple[str, str, dict[str, float]]:
        """Bounded text-only OpenAI-compatible generation; never returns hidden reasoning."""
        if self.config.kind not in {ProviderKind.OPENAI, ProviderKind.OPENAI_COMPATIBLE}:
            raise ValueError("text generation requires an OpenAI-compatible provider")
        if not text or len(text.encode("utf-8")) > 16384 or not 1 <= max_output_tokens <= 2048:
            raise ValueError("generation request outside bounds")
        headers = {"X-C3R-Timeout": str(self.config.timeout_seconds)}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        payload: dict[str, object] = {
            "model": self.config.model, "max_tokens": max_output_tokens, "temperature": 0,
            "messages": [
                {"role": "system", "content": "Provide a helpful final answer only. Do not expose "
                 "private reasoning or claim to execute tools, commit actions, or grant authority."},
                {"role": "user", "content": text},
            ],
        }
        if self.config.uses_openrouter:
            if not self.config.api_key:
                raise RuntimeError("hosted provider credential unavailable")
            payload["provider"] = {"zdr": True, "data_collection": "deny",
                                   "require_parameters": True, "allow_fallbacks": False}
        try:
            response = self._transport(self.config.base_url.rstrip("/") + "/chat/completions",
                                       headers, payload)
            size = len(json.dumps(response.body, allow_nan=False).encode())
        except (OSError, ValueError, TypeError) as error:
            raise RuntimeError("generative provider transport unavailable") from error
        if not 200 <= response.status < 300:
            raise RuntimeError("generative provider unavailable")
        if size > MAX_RESPONSE_BYTES:
            raise RuntimeError("generative provider response oversized")
        try:
            choices = cast(list[dict[str, object]], response.body["choices"])
            message = cast(dict[str, object], choices[0]["message"])
            if message.get("tool_calls") or message.get("function_call"):
                raise ValueError("tool execution is not supported")
            output = _content(message["content"])
            reason = choices[0].get("finish_reason")
            if not output.strip() or reason not in {"stop", "length"}:
                raise ValueError("invalid generation result")
            usage = cast(Mapping[str, object], response.body.get("usage", {}))
            observed = {
                "input_tokens": _number(usage.get("prompt_tokens")),
                "output_tokens": _number(usage.get("completion_tokens")),
                "latency_ms": response.latency_ms,
            }
            cost = usage.get("cost")
            if (isinstance(cost, (int, float)) and not isinstance(cost, bool)
                    and isfinite(cost) and cost >= 0):
                observed["provider_cost_usd"] = float(cost)
            return output, cast(str, reason), observed
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
            raise RuntimeError("invalid generative provider response") from error

    def stream_generate(self, text: str, max_output_tokens: int, *,
                        cancelled: Event | None = None) -> TextGenerationStream:
        """Open a live backend SSE response; closing it aborts backend generation."""
        if self.config.kind not in {ProviderKind.OPENAI, ProviderKind.OPENAI_COMPATIBLE}:
            raise ValueError("text generation requires an OpenAI-compatible provider")
        if not text or len(text.encode("utf-8")) > 16384 or not 1 <= max_output_tokens <= 2048:
            raise ValueError("generation request outside bounds")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        payload: dict[str, object] = {
            "model": self.config.model, "max_tokens": max_output_tokens, "temperature": 0,
            "stream": True, "stream_options": {"include_usage": True},
            "messages": [
                {"role": "system", "content": "Provide a helpful final answer only. Do not expose "
                 "private reasoning or claim to execute tools, commit actions, or grant authority."},
                {"role": "user", "content": text},
            ],
        }
        if self.config.uses_openrouter:
            if not self.config.api_key:
                raise RuntimeError("hosted provider credential unavailable")
            payload["provider"] = {"zdr": True, "data_collection": "deny",
                                   "require_parameters": True, "allow_fallbacks": False}
        parsed = urlparse(self.config.base_url)
        if parsed.hostname is None:
            raise ValueError("provider origin requires a host")
        connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        connection = connection_type(
            parsed.hostname, parsed.port, timeout=self.config.timeout_seconds,
        )
        finished_opening = Event()

        def interrupt_opening() -> None:
            while not finished_opening.wait(0.05):
                if cancelled is not None and cancelled.is_set():
                    transport = connection.sock
                    if transport is not None:
                        try:
                            transport.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    connection.close()
                    return

        watcher = Thread(target=interrupt_opening, daemon=True) if cancelled is not None else None
        if watcher is not None:
            watcher.start()
        try:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("generation cancelled")
            connection.connect()
            backend_socket = connection.sock
            if backend_socket is None:
                raise OSError("provider connection unavailable")
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("generation cancelled")
            connection.request(
                "POST", parsed.path.rstrip("/") + "/chat/completions",
                body=json.dumps(payload, separators=(",", ":")).encode(), headers=headers,
            )
            response = connection.getresponse()
            if cancelled is not None and cancelled.is_set():
                response.close()
                raise RuntimeError("generation cancelled")
            if not 200 <= response.status < 300 or response.headers.get_content_type() != "text/event-stream":
                response.close()
                raise RuntimeError("provider did not return a successful event stream")
            return TextGenerationStream(response, connection, backend_socket)
        except BaseException:
            connection.close()
            raise
        finally:
            finished_opening.set()
            if watcher is not None:
                watcher.join(timeout=0.2)

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
