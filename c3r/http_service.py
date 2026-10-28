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
from threading import Lock
from typing import Protocol, cast

from .deliberative.envelope import DeliberativeResult
from .runtime import RuntimeRequest, StandaloneController


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
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("C3R must bind to loopback behind a TLS gateway")
        if len(bearer_token) < 32:
            raise ValueError("bearer token must have at least 32 characters")
        if runtime.effect_execution_enabled:
            raise ValueError("the HTTP service cannot execute external effects")
        self.runtime = runtime
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
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(expected, supplied)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if self.path == "/metrics":
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"counts": self.server.metrics.snapshot()})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/decisions":
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
            request = self.server.request_factory.build(cast(dict[str, object], payload))
            outcome = self.server.runtime.run(request)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
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
        }
        if isinstance(outcome.deliberation, DeliberativeResult) and is_dataclass(
            outcome.deliberation
        ):
            result["deliberation"] = asdict(outcome.deliberation)
        self._send(200, result)
