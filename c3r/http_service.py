"""Authenticated loopback HTTP boundary for recommendation-only C3R hosting.

TLS termination and the request factory belong to the deployment host. This API
never accepts caller-supplied verification, approval, policy, or cost estimates.
"""

from __future__ import annotations

import hmac
import json
import select
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Protocol, cast

from .deliberative.envelope import DeliberativeResult
from .internal_readiness import ReadinessProbe
from .responses import ResponseEventStream, ResponsesService
from .runtime import RuntimeRequest, StandaloneController
from .system_one.inference import SystemOneInference
from .telemetry.invocations import capture_invocations, with_invocations

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


class ClientDisconnected(Exception):
    """A cancelled stream needs cleanup, not an attempted error response."""


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
        max_concurrent_generations: int = 4,
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("C3R must bind to loopback behind a TLS gateway")
        if len(bearer_token) < 32:
            raise ValueError("bearer token must have at least 32 characters")
        if runtime.effect_execution_enabled:
            raise ValueError("the HTTP service cannot execute external effects")
        if max_concurrent_generations < 1:
            raise ValueError("generation capacity must be positive")
        self.runtime = runtime
        self.system_one = system_one
        self.responses = responses
        self.generation_capacity = BoundedSemaphore(max_concurrent_generations)
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
    server: C3RHTTPServer  # pyright: ignore[reportIncompatibleVariableOverride]

    def log_message(self, format: str, *_args: object) -> None:
        # The host exports aggregate metrics; request bodies and tokens are never logged.
        return

    def _send(self, status: int, value: Mapping[str, object]) -> None:
        value = with_invocations(value)
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

    def _open_stream(self, payload: Mapping[str, object]) -> ResponseEventStream:
        """Cancel even while the generation backend has not sent headers yet."""
        assert self.server.responses is not None
        cancelled, finished = Event(), Event()

        def watch_opening() -> None:
            while not finished.wait(0.05):
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0)
                    if readable:
                        cancelled.set()
                        self.server.metrics.increment("stream_disconnect")
                        return
                except (OSError, ValueError):
                    cancelled.set()
                    return

        watcher = Thread(target=watch_opening, daemon=True)
        watcher.start()
        try:
            events = self.server.responses.stream(payload, cancelled=cancelled)
            if cancelled.is_set():
                events.close()
                raise ClientDisconnected
            return events
        except RuntimeError:
            if cancelled.is_set():
                self.close_connection = True
                raise ClientDisconnected from None
            raise
        finally:
            finished.set()
            watcher.join(timeout=0.2)

    def _send_stream(self, events: ResponseEventStream) -> None:
        stop_watch = Event()
        client_gone = Event()
        released = False
        release_lock = Lock()
        watcher: Thread | None = None

        def record_disconnect() -> None:
            with release_lock:
                if not client_gone.is_set():
                    client_gone.set()
                    self.server.metrics.increment("stream_disconnect")

        def release_capacity() -> None:
            nonlocal released
            with release_lock:
                if not released:
                    released = True
                    self.server.generation_capacity.release()

        def watch_disconnect() -> None:
            while not stop_watch.is_set():
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0.1)
                    if readable:
                        # A stream is one request per connection; any further
                        # client bytes or a closed socket aborts that stream.
                        self.connection.recv(1, socket.MSG_PEEK)
                        record_disconnect()
                        events.abort()
                        release_capacity()
                        return
                except OSError:
                    record_disconnect()
                    events.abort()
                    release_capacity()
                    return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            watcher = Thread(target=watch_disconnect, daemon=True)
            watcher.start()
            for name, data in events:
                if client_gone.is_set():
                    break
                response = data.get("response")
                if isinstance(response, dict):
                    data = {**data, "response": with_invocations(cast(Mapping[str, object], response))}
                frame = ("event: " + name + "\n" + "data: "
                         + json.dumps(data, separators=(",", ":"), ensure_ascii=False)
                         + "\n\n").encode("utf-8")
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            record_disconnect()
        finally:
            stop_watch.set()
            events.close()
            if watcher is not None:
                watcher.join(timeout=0.5)
            release_capacity()

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
        with capture_invocations():
            self._post()

    def _post(self) -> None:
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
                raise TypeError("JSON object required")
            payload = cast(dict[str, object], payload)
            if self.path == "/v1/responses" and self.server.responses:
                if not self.server.generation_capacity.acquire(blocking=False):
                    self._send(429, {"error": "capacity_exceeded"})
                    return
                if payload.get("stream") is True:
                    try:
                        events = self._open_stream(payload)
                    except BaseException:
                        self.server.generation_capacity.release()
                        raise
                    self.server.metrics.increment("text_responses")
                    self._send_stream(events)
                    return
                try:
                    response = self.server.responses.respond(payload)
                finally:
                    self.server.generation_capacity.release()
                self.server.metrics.increment("text_responses")
                self._send(200, response)
                return
            if self.path in {"/v1/c3r/rank", "/v1/system-one"} and self.server.system_one:
                if not (self.server.runtime.decision_enabled
                        and self.server.runtime.system_one_enabled):
                    raise RuntimeError("System-One disabled")
                result = self.server.system_one.infer(payload)
                self.server.metrics.increment("system_one_inferences")
                self._send(200, result)
                return
            request = self.server.request_factory.build(payload)
            outcome = self.server.runtime.run(request)
        except ClientDisconnected:
            self.close_connection = True
            return
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
            "cvoc": {"selected_lower_bound": outcome.cvoc_lower_bound,
                     "basis": "host_supplied_estimates"},
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
