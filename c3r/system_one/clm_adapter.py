"""Bounded, loopback-only adapter for the pinned upstream CLM rank API.

CLM predictions are never authority or calibrated probabilities. The guarded
fast path consumes these as logits only when a held-out calibration slice exists.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import cast
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, ProxyHandler, Request, build_opener

from ..http_transport import NoRedirectHandler
from ..state_schema import CompiledState
from ..telemetry.invocations import transport_attempt
from .question_registry import TypedQuestion

UPSTREAM_CLM_COMMIT = "bb42c6c5bf914fd449bed2f6ca65be80602cb1f7"
_IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_MAX_CONTEXT_BYTES = 32_768
_MAX_RESPONSE_BYTES = 65_536
_MAX_OPTIONS = 64
RankTransport = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class ClmAdapter:
    """Convert CLM rankings to typed logits in the original option order.

    ``revision`` is the host-declared CLM head/encoder bundle hash, not an
    attestation from the server. The upstream code pin is recorded separately.
    """

    revision: str
    endpoint: str = "http://127.0.0.1:8700"
    api_key: str | None = None
    timeout_seconds: float = 0.5
    transport: RankTransport | None = None
    model_id: str = "Contrastive-LM/CLM"
    served_model: str = "clm-latest"

    @property
    def provider(self) -> str:
        return "clm"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            raise ValueError("CLM endpoint must be a local HTTP origin with an explicit port")
        if _IMMUTABLE_REVISION.fullmatch(self.revision) is None:
            raise ValueError("CLM artifact revision must be an immutable SHA-256/SHA-1 hash")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 10:
            raise ValueError("CLM timeout must be finite and at most ten seconds")
        if not self.served_model or len(self.served_model) > 128:
            raise ValueError("CLM served model name must be bounded")

    def predict(
        self, state: CompiledState, questions: tuple[TypedQuestion, ...],
        *, deadline: float | None = None,
    ) -> Mapping[str, tuple[float, ...]]:
        context = self._context(state)
        output: dict[str, tuple[float, ...]] = {}
        for question in questions:
            probabilities = self._rank(context, question.id, question.options, deadline=deadline)
            output[question.id] = tuple(math.log(max(value, 1e-12)) for value in probabilities)
        return output

    def rank_actions(
        self, state: CompiledState, candidate_ids: tuple[str, ...],
        *, deadline: float | None = None,
    ) -> tuple[float, ...]:
        """Advisory candidate distribution; CVoC and policy still choose actions."""
        return self._rank(self._context(state), "NEXT_ACTION", candidate_ids, deadline=deadline)

    def rank_text(self, context: str, question: str, options: tuple[str, ...],
                  *, deadline: float | None = None) -> tuple[float, ...]:
        """Rank caller text without assigning it policy or execution authority."""
        if not context or len(context.encode("utf-8")) > _MAX_CONTEXT_BYTES:
            raise ValueError("CLM context must be nonempty and bounded")
        if not question or len(question) > 1024:
            raise ValueError("CLM question must be nonempty and bounded")
        return self._rank(context, question, options, deadline=deadline)

    def _context(self, state: CompiledState) -> str:
        context = json.dumps(asdict(state), sort_keys=True, allow_nan=False, ensure_ascii=False)
        if len(context.encode("utf-8")) > _MAX_CONTEXT_BYTES:
            raise ValueError("compiled state exceeds the bounded CLM context")
        return context

    def _rank(
        self, context: str, question: str, options: tuple[str, ...],
        *, deadline: float | None = None,
    ) -> tuple[float, ...]:
        if not options or len(options) > _MAX_OPTIONS or len(set(options)) != len(options):
            raise ValueError("CLM options must be unique and bounded")
        if any(not option or len(option) > 1024 for option in options):
            raise ValueError("CLM option is empty or oversized")
        payload: Mapping[str, object] = {
            "context": context,
            "question": question,
            "answers": list(options),
            "model": self.served_model,
        }
        remaining = self.timeout_seconds
        if deadline is not None:
            remaining = min(remaining, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("CLM decision deadline exceeded")
        transport_attempt("system_one")
        response = self.transport(payload) if self.transport is not None else self._post(payload, remaining)
        if response.get("model") != self.served_model:
            raise ValueError("CLM served model does not match the requested model")
        ranked = response.get("ranked")
        if not isinstance(ranked, list) or len(ranked) != len(options):
            raise ValueError("CLM returned an incomplete ranking")
        probabilities: dict[str, float] = {}
        for item in ranked:
            if not isinstance(item, dict):
                raise ValueError("CLM returned an invalid ranking item")
            candidate = item.get("candidate")
            probability = item.get("prob")
            if (
                not isinstance(candidate, str)
                or candidate not in options
                or candidate in probabilities
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not math.isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ValueError("CLM ranking contains an unknown or invalid probability")
            probabilities[candidate] = float(probability)
        total = sum(probabilities.values())
        if not 0.98 <= total <= 1.02:
            raise ValueError("CLM ranking probabilities do not sum to one")
        return tuple(probabilities[option] / total for option in options)

    def _post(self, payload: Mapping[str, object], timeout: float) -> Mapping[str, object]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.endpoint.rstrip("/") + "/v1/rank",
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        # Ignore proxy environment variables and reject redirects so a local
        # server cannot relay the secret or state to an off-host destination.
        opener = build_opener(ProxyHandler({}), NoRedirectHandler(), HTTPHandler())
        with opener.open(request, timeout=timeout) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("CLM response exceeds the allowed size")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("CLM returned a non-object response")
        return cast(Mapping[str, object], parsed)
