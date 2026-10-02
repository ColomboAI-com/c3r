"""Authenticated loopback HTTP boundary for recommendation-only C3R hosting.

TLS termination and the request factory belong to the deployment host. This API
never accepts caller-supplied verification, approval, policy, or cost estimates.
"""

from __future__ import annotations

import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from threading import Lock
from typing import Protocol, cast

from .deliberative.envelope import DeliberativeResult
from .internal_readiness import ReadinessProbe
from .responses import ResponsesService
from .runtime import RuntimeRequest, StandaloneController
from .system_one.inference import SystemOneInference

MAX_REQUEST_BYTES = 65_536


class RequestFactory(Protocol):
    """Construct trusted policies, catalogs, and measured estimates server-side."""

    def build(self, payload: Mapping[str, object]) -> RuntimeRequest: ...


class TokenBucket:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0:
            raise ValueError("rate limit must be positive")
        self._capacity = capacity
        self._refill = refill_per_second
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = Lock()

    def take(self) -> bool:
        with self._lock:
            now = self._clock()
            self._tokens = min(
                self._capacity, self._tokens + max(0.0, now - self._last) * self._refill
            )
            self._last = now
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


class ServiceMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[str, int] = {}

    def increment(self, name: str) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


class C3RHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        *,
        runtime: StandaloneController,
        request_factory: RequestFactory,
        bearer_token: str,
        host: str = "127.0.0.1",
        port: int = 8081,
        requests_per_minute: int = 60,
        system_one: SystemOneInference | None = None,
        responses: ResponsesService | None = None,
        internal_readiness: ReadinessProbe | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("C3R must bind to loopback behind a TLS gateway")
        if len(bearer_token) < 32:
            raise ValueError("bearer token must have at least 32 characters")
        if runtime.effect_execution_enabled:
            raise ValueError("the HTTP service cannot execute external effects")
        self.runtime = runtime
        self.system_one = system_one
        self.responses = responses
        self.internal_readiness = internal_readiness
        self.request_factory = request_factory
        self.bearer_token = bearer_token
        self.limiter = TokenBucket(
            capacity=requests_per_minute,
            refill_per_second=requests_per_minute / 60,
        )
        self.metrics = ServiceMetrics()
        super().__init__((host, port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: C3RHTTPServer

    def log_message(self, _format: str, *_args: object) -> None:
        # The host exports aggregate metrics; request bodies and tokens are never logged.
        return

    def _send(self, status: int, value: Mapping[str, object]) -> None:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = "Bearer " + self.server.bearer_token
        supplied = self.headers.get_all("Authorization", [])
        return len(supplied) == 1 and hmac.compare_digest(expected.encode(), supplied[0].encode())

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if self.path in {"/ready", "/v1/models"}:
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            if self.path == "/ready":
                ready = (self.server.runtime.decision_enabled
                         and self.server.runtime.system_one_enabled
                         and self.server.runtime.provider_ready)
                self._send(200 if ready else 503, {
                    "status": "ready" if ready else "disabled",
                    "scope": "configured_provider_probe_and_decision_policy",
                })
            else:
                available = (self.server.runtime.decision_enabled
                             and self.server.runtime.system_one_enabled
                             and self.server.runtime.provider_ready)
                ranking_available = (self.server.runtime.decision_enabled
                                     and self.server.runtime.system_one_enabled
                                     and self.server.system_one is not None
                                     and self.server.system_one.ready)
                models = [
                    {"id": "c3r-core", "capability": "verified_recommendation",
                     "text_generation": self.server.responses is not None, "calibrated": False,
                     "effect_execution": False, "available": available},
                    {"id": "c3r-system-one", "capability": "advisory_ranking",
                     "text_generation": False, "calibrated": False,
                     "effect_execution": False,
                     "available": ranking_available},
                    {"id": "c3r-verifier", "capability": "advisory_output_ranking",
                     "text_generation": False, "calibrated": False, "effect_execution": False,
                     "available": ranking_available},
                ]
                self._send(200, {"object": "list", "data": models, "models": models})
            return
        if self.path == "/metrics":
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"counts": self.server.metrics.snapshot()})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path not in {
            "/v1/decisions", "/v1/c3r/decide", "/v1/c3r/rank",
            "/v1/system-one", "/v1/c3r/execute", "/v1/responses",
        }:
            self._send(404, {"error": "not_found"})
            return
        if not self._authorized():
            self.server.metrics.increment("unauthorized")
            self._send(401, {"error": "unauthorized"})
            return
        if not self.server.limiter.take():
            self.server.metrics.increment("rate_limited")
            self._send(429, {"error": "rate_limited"})
            return
        if self.path == "/v1/c3r/execute" or (self.path == "/v1/responses" and
                                             self.server.responses is None):
            self._send(501, {"error": "not_implemented", "reason": "recommendation_only"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._send(413, {"error": "request_size_out_of_bounds"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            if self.path == "/v1/responses" and self.server.responses:
                response = self.server.responses.respond(cast(dict[str, object], payload))
                self.server.metrics.increment("text_responses")
                self._send(200, response)
                return
            if self.path in {"/v1/c3r/rank", "/v1/system-one"} and self.server.system_one:
                if not (self.server.runtime.decision_enabled
                        and self.server.runtime.system_one_enabled):
                    raise RuntimeError("System-One disabled")
                result = self.server.system_one.infer(cast(dict[str, object], payload))
                self.server.metrics.increment("system_one_inferences")
                self._send(200, result)
                return
            request = self.server.request_factory.build(cast(dict[str, object], payload))
            outcome = self.server.runtime.run(request)
        except (KeyError, TypeError, ValueError, RecursionError, json.JSONDecodeError):
            self.server.metrics.increment("invalid_request")
            self._send(400, {"error": "invalid_request"})
            return
        except (OSError, RuntimeError):
            self.server.metrics.increment("internal_failure")
            self._send(503, {"error": "service_unavailable"})
            return
        self.server.metrics.increment("decisions")
        result: dict[str, object] = {
            "route": outcome.route,
            "selected_action_id": outcome.selected_action_id,
            "authority_result": outcome.authority_result,
            "reason": outcome.reason,
            "trace_hash": outcome.ledger_record.record_hash,
            "effect_executed": False,
        }
        if self.path in {"/v1/c3r/rank", "/v1/system-one"}:
            result["abstained"] = outcome.fast_path is None or outcome.fast_path.abstained
            result["model_id"] = (
                None if outcome.fast_path is None else outcome.fast_path.model_id
            )
            result["scope"] = "controller_decision_with_system_one_fallback"
            scores = (() if outcome.fast_path is None
                      else outcome.fast_path.candidate_probabilities)
            if (len(scores) != len(outcome.candidate_ids)
                    or any(not isfinite(score) or score < 0 or score > 1 for score in scores)):
                scores = ()
            result["candidate_ranking"] = [
                {"candidate_id": candidate_id, "system_one_score": score,
                 "calibrated": False}
                for candidate_id, score in sorted(
                    zip(outcome.candidate_ids, scores),
                    key=lambda item: item[1], reverse=True,
                )
            ]
        if isinstance(outcome.deliberation, DeliberativeResult) and is_dataclass(
            outcome.deliberation
        ):
            result["deliberation"] = asdict(outcome.deliberation)
        self._send(200, result)
