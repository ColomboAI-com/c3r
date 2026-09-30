"""Text-only, non-storing Responses subset with an explicit host policy fallback."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import uuid4
from dataclasses import dataclass, replace

from .adapters.providers import ProviderAdapter
from .runtime import RuntimeRequest, StandaloneController
from .state_schema import CompiledState


@dataclass(frozen=True, slots=True)
class TextGenerationResult:
    text: str
    finish: str
    usage: dict[str, float]


class TextDeliberator:
    def __init__(self, provider: ProviderAdapter, maximum: int) -> None:
        self.provider, self.maximum = provider, maximum

    def deliberate(self, state: CompiledState) -> TextGenerationResult:
        return TextGenerationResult(*self.provider.generate(state.goal, self.maximum))


class GenerationRequestFactory(Protocol):
    def build(self, payload: Mapping[str, object]) -> RuntimeRequest: ...


class ResponsesService:
    def __init__(self, runtime: StandaloneController, factory: GenerationRequestFactory,
                 provider: ProviderAdapter) -> None:
        self.runtime, self.factory, self.provider = runtime, factory, provider

    def respond(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) - {"model", "input", "max_output_tokens", "store", "stream"}:
            raise ValueError("unsupported Responses fields")
        if payload.get("model") != "c3r-core":
            raise ValueError("only c3r-core supports text generation")
        if payload.get("store", False) is not False or payload.get("stream", False) is not False:
            raise ValueError("storage and streaming are not supported")
        text = payload.get("input")
        maximum = payload.get("max_output_tokens", 512)
        if (not isinstance(text, str) or not text.strip() or len(text) > 4096
                or len(text.encode()) > 16384
                or isinstance(maximum, bool) or not isinstance(maximum, int)
                or not 1 <= maximum <= 2048):
            raise ValueError("bounded text input and token limit required")
        if not self.runtime.decision_enabled:
            raise RuntimeError("C3R disabled")
        request = replace(self.factory.build({"goal": text, "current_subgoal": text}),
                          requested_text_generation=True)
        decision = self.runtime.run(request, requested_deliberator=TextDeliberator(self.provider, maximum))
        if not isinstance(decision.deliberation, TextGenerationResult):
            raise RuntimeError("controller declined text generation")
        # An explicit caller request for bounded text-only generation is the host
        # fallback when unknown task quality gives no positive CVoC. It is NOT a
        # positive learned utility claim and cannot execute a catalog action.
        output, finish, usage = (decision.deliberation.text, decision.deliberation.finish,
                                decision.deliberation.usage)
        identifier = "resp_" + uuid4().hex
        return {
            "id": identifier, "object": "response", "model": "c3r-core",
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
