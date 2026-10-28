"""Text-only, non-storing Responses subset with an explicit host policy fallback."""
from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from threading import Event
from typing import Protocol
from uuid import uuid4

from .adapters.providers import ProviderAdapter, TextGenerationStream
from .runtime import RuntimeRequest, StandaloneController
from .state_schema import CompiledState


@dataclass(frozen=True, slots=True)
class TextGenerationResult:
    text: str
    finish: str
    usage: dict[str, float]


class TextDeliberator:
    def __init__(self, provider: ProviderAdapter, maximum: int, *, stream: bool = False,
                 cancelled: Event | None = None) -> None:
        self.provider, self.maximum, self.stream = provider, maximum, stream
        self.cancelled = cancelled

    def deliberate(self, state: CompiledState) -> TextGenerationResult | TextGenerationStream:
        if not self.provider.config.is_local and state.data_boundary not in {"approved_remote", "public"}:
            raise ValueError("state is not approved for hosted generation")
        if self.stream:
            return self.provider.stream_generate(state.goal, self.maximum, cancelled=self.cancelled)
        return TextGenerationResult(*self.provider.generate(state.goal, self.maximum))


class GenerationRequestFactory(Protocol):
    def build(self, payload: Mapping[str, object]) -> RuntimeRequest: ...


class ResponseEventStream(Iterator[tuple[str, dict[str, object]]]):
    """Responses events drawn incrementally from the closeable backend stream."""

    def __init__(self, backend: TextGenerationStream, *, identifier: str,
                 message_id: str, reason: str, provider: str) -> None:
        self.backend = backend
        self.identifier = identifier
        self.message_id = message_id
        self.reason = reason
        self.provider = provider
        self.created_at = int(time.time())
        self._started = False
        self._done = False
        self._pending: list[tuple[str, dict[str, object]]] = []
        self._text = ""
        self._finish: str | None = None
        self._usage: dict[str, int] | None = None

    def __iter__(self) -> ResponseEventStream:
        return self

    def __next__(self) -> tuple[str, dict[str, object]]:
        if self._pending:
            return self._pending.pop(0)
        if self._done:
            raise StopIteration
        if not self._started:
            self._started = True
            return "response.created", {"type": "response.created", "response": self._response("in_progress")}
        try:
            while True:
                try:
                    delta, finish, usage = next(self.backend)
                except StopIteration:
                    if self._finish is None:
                        raise RuntimeError("provider stream omitted finish reason")
                    self._done = True
                    status = "completed" if self._finish == "stop" else "incomplete"
                    self._pending.append(("response.completed", {
                        "type": "response.completed", "response": self._response(status),
                    }))
                    return "response.output_text.done", {
                        "type": "response.output_text.done", "response_id": self.identifier,
                        "output_index": 0, "content_index": 0, "text": self._text,
                    }
                if usage is not None:
                    self._usage = usage
                if delta:
                    if self._finish is not None:
                        raise RuntimeError("provider emitted text after finish")
                    self._text += delta
                    if len(self._text.encode("utf-8")) > 65_536:
                        raise RuntimeError("provider output exceeds byte limit")
                    if finish is not None:
                        self._finish = finish
                    return "response.output_text.delta", {
                        "type": "response.output_text.delta", "response_id": self.identifier,
                        "output_index": 0, "content_index": 0, "delta": delta,
                    }
                if finish is not None:
                    self._finish = finish
        except (OSError, RuntimeError, TypeError, ValueError):
            self.close()
            self._done = True
            return "response.failed", {
                "type": "response.failed", "response": self._response("failed"),
                "error": {"type": "server_error", "message": "Generation failed."},
            }

    def _response(self, status: str) -> dict[str, object]:
        usage: dict[str, int] | None = None
        if self._usage is not None:
            input_tokens = int(self._usage["input_tokens"])
            output_tokens = int(self._usage["output_tokens"])
            usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                     "total_tokens": input_tokens + output_tokens}
        return {
            "id": self.identifier, "object": "response", "created_at": self.created_at,
            "model": "c3r-core", "status": status, "store": False,
            "output": [] if status == "in_progress" else [{
                "id": self.message_id, "type": "message", "role": "assistant",
                "status": status, "content": [{"type": "output_text", "text": self._text,
                                      "annotations": []}],
            }],
            "usage": usage,
            "c3r": {"route": "deliberative", "system_one_provider": "clm",
                    "controller_reason": self.reason, "effect_executed": False,
                    "selection_basis": "explicit_text_only_request_policy_fallback",
                    "calibrated": False, "provider": self.provider},
        }

    def close(self) -> None:
        self.backend.close()

    def abort(self) -> None:
        self.backend.abort()


class ResponsesService:
    def __init__(self, runtime: StandaloneController, factory: GenerationRequestFactory,
                 provider: ProviderAdapter) -> None:
        self.runtime, self.factory, self.provider = runtime, factory, provider

    def respond(self, payload: Mapping[str, object]) -> dict[str, object]:
        text, maximum = self._validate(payload, stream=False)
        decision = self._decide(text, maximum, stream=False)
        if not isinstance(decision.deliberation, TextGenerationResult):
            raise RuntimeError("controller declined text generation")  # noqa: TRY004
        # An explicit caller request for bounded text-only generation is the host
        # fallback when unknown task quality gives no positive CVoC. It is NOT a
        # positive learned utility claim and cannot execute a catalog action.
        output, finish, usage = (decision.deliberation.text, decision.deliberation.finish,
                                decision.deliberation.usage)
        identifier = "resp_" + uuid4().hex
        response: dict[str, object] = {
            "id": identifier, "object": "response", "created_at": int(time.time()),
            "model": "c3r-core",
            "status": "completed" if finish == "stop" else "incomplete", "store": False,
            "output": [{"id": "msg_" + uuid4().hex, "type": "message", "role": "assistant",
                        "status": "completed" if finish == "stop" else "incomplete",
                        "content": [{"type": "output_text", "text": output, "annotations": []}]}],
            "usage": {"input_tokens": int(usage["input_tokens"]),
                      "output_tokens": int(usage["output_tokens"]),
                      "total_tokens": int(usage["input_tokens"] + usage["output_tokens"])},
            "c3r": {"route": "deliberative", "system_one_provider": "clm",
                    "controller_reason": decision.reason, "effect_executed": False,
                    "selection_basis": "explicit_text_only_request_policy_fallback",
                    "calibrated": False, "provider": self.provider.config.provider_id},
        }
        if "provider_cost_usd" in usage:
            metadata = response["c3r"]
            assert isinstance(metadata, dict)
            metadata["observed_provider_cost_usd"] = usage["provider_cost_usd"]
        return response

    def stream(self, payload: Mapping[str, object], *, cancelled: Event | None = None) -> ResponseEventStream:
        text, maximum = self._validate(payload, stream=True)
        decision = self._decide(text, maximum, stream=True, cancelled=cancelled)
        if not isinstance(decision.deliberation, TextGenerationStream):
            raise RuntimeError("controller declined text generation")  # noqa: TRY004
        return ResponseEventStream(
            decision.deliberation, identifier="resp_" + uuid4().hex,
            message_id="msg_" + uuid4().hex, reason=decision.reason,
            provider=self.provider.config.provider_id,
        )

    def _validate(self, payload: Mapping[str, object], *, stream: bool) -> tuple[str, int]:
        if set(payload) - {"model", "input", "max_output_tokens", "store", "stream"}:
            raise ValueError("unsupported Responses fields")
        if payload.get("model") != "c3r-core":
            raise ValueError("only c3r-core supports text generation")
        if payload.get("store", False) is not False or payload.get("stream", False) is not stream:
            raise ValueError("storage is unsupported and stream must be an explicit boolean")
        text = payload.get("input")
        maximum = payload.get("max_output_tokens", 512)
        if (not isinstance(text, str) or not text.strip() or len(text) > 4096
                or len(text.encode()) > 16384
                or isinstance(maximum, bool) or not isinstance(maximum, int)
                or not 1 <= maximum <= 2048):
            raise ValueError("bounded text input and token limit required")
        if not self.runtime.decision_enabled:
            raise RuntimeError("C3R disabled")
        return text, maximum

    def _decide(self, text: str, maximum: int, *, stream: bool, cancelled: Event | None = None):
        request = replace(self.factory.build({"goal": text, "current_subgoal": text}),
                          requested_text_generation=True)
        return self.runtime.run(request, requested_deliberator=TextDeliberator(
            self.provider, maximum, stream=stream, cancelled=cancelled,
        ))
