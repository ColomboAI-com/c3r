"""Bounded ingress for an IAM/TLS-terminated host with a loopback C3R backend.

The outer host still owns TLS, IAM, secrets, and abuse controls. This proxy never
trusts caller authorization as backend authorization and never logs request data.
"""

from __future__ import annotations

import hmac
import json
import select
import socket
import sqlite3
import time
from collections.abc import Mapping
from http.client import HTTPConnection, HTTPException, HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore, Event, Thread
from typing import cast
from uuid import uuid4

from .api_access import AccessStore, Principal
from .http_service import MAX_REQUEST_BYTES, TokenBucket

MAX_RESPONSE_BYTES = 65_536


class C3RIngressServer(ThreadingHTTPServer):
    """Expose only the read-only API, with separate client and loopback secrets."""

    daemon_threads = True

    def __init__(
        self,
        *,
        upstream_port: int,
        client_token: str,
        upstream_token: str,
        upstream_host: str = "127.0.0.1",
        host: str = "0.0.0.0",
        port: int = 8080,
        requests_per_minute: int = 60,
        max_in_flight: int = 16,
        upstream_timeout_seconds: float = 5.0,
        access_store: AccessStore | None = None,
    ) -> None:
        if upstream_host not in {"127.0.0.1", "::1"}:
            raise ValueError("upstream must be loopback")
        if not 1 <= upstream_port <= 65535:
            raise ValueError("invalid upstream port")
        if min(len(client_token), len(upstream_token)) < 32:
            raise ValueError("tokens must have at least 32 characters")
        if hmac.compare_digest(client_token, upstream_token):
            raise ValueError("client and upstream tokens must be different")
        if max_in_flight < 1 or upstream_timeout_seconds <= 0:
            raise ValueError("concurrency and timeout must be positive")
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.client_token = client_token
        self.access_store = access_store
        self.upstream_token = upstream_token
        self.upstream_timeout_seconds = upstream_timeout_seconds
        self.limiter = TokenBucket(
            capacity=requests_per_minute,
            refill_per_second=requests_per_minute / 60,
        )
        self.in_flight = BoundedSemaphore(max_in_flight)
        self.route_slots = {"/v1/responses": BoundedSemaphore(1),
                            "/v1/system-one": BoundedSemaphore(4),
                            "/v1/c3r/rank": BoundedSemaphore(4)}
        decisions = BoundedSemaphore(2)
        for path in ("/v1/decisions", "/v1/c3r/decide", "/v1/c3r/execute"):
            self.route_slots[path] = decisions
        super().__init__((host, port), _IngressHandler)

    def get_request(self) -> tuple[socket.socket, object]:
        connection, address = super().get_request()
        connection.settimeout(5.0)
        return connection, address


class _IngressHandler(BaseHTTPRequestHandler):
    @property
    def gateway(self) -> C3RIngressServer:
        return cast(C3RIngressServer, self.server)
    principal: Principal | None = None
    request_id: str = ""
    started: float = 0

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._begin_request()
        self.close_connection = True
        self._send_error(405 if code == 501 else code,
                         "method_not_allowed" if code == 501 else "invalid_request")

    def _send_error(self, status: int, code: str) -> None:
        value: dict[str, object] = {"error": code}
        if self.gateway.access_store is not None:
            category = {400: "invalid_request_error", 401: "authentication_error",
                        403: "permission_error", 404: "not_found_error", 409: "conflict_error",
                        413: "invalid_request_error", 415: "invalid_request_error",
                        429: "rate_limit_error", 503: "service_unavailable"}.get(status, "api_error")
            value = {"error": {"message": "C3R request could not be completed.",
                               "type": category, "code": code, "param": None,
                               "request_id": self.request_id}}
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("x-request-id", self.request_id)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if getattr(self, "command", "") != "HEAD":
            self.wfile.write(body)

    def _begin_request(self) -> None:
        self.request_id = "req_" + uuid4().hex
        self.principal = None
        self.started = time.monotonic()

    def _scope_allowed(self) -> bool:
        if self.gateway.access_store is None:
            return True
        scope = {"/v1/models": "models:read", "/v1/responses": "responses:write",
                 "/v1/system-one": "system_one:write", "/v1/c3r/rank": "rank:write",
                 "/v1/c3r/decide": "decide:write", "/v1/decisions": "decide:write",
                 "/v1/c3r/execute": "decide:write", "/ready": "models:read"}.get(self.path)
        return self.principal is not None and scope in self.principal.scopes

    def _admitted(self) -> bool:
        if self.gateway.access_store is None:
            return self.gateway.limiter.take()
        return self.principal is not None and self.gateway.access_store.admit(self.principal)

    def _record_usage(self, status: int, decoded: Mapping[str, object]) -> None:
        if self.gateway.access_store is None or self.principal is None:
            return
        raw_usage = decoded.get("usage")
        raw_c3r = decoded.get("c3r")
        usage: Mapping[str, object] = cast(Mapping[str, object], raw_usage) if isinstance(raw_usage, dict) else {}
        c3r: Mapping[str, object] = cast(Mapping[str, object], raw_c3r) if isinstance(raw_c3r, dict) else {}

        def count(value: object) -> int | None:
            return value if type(value) is int and value >= 0 else None

        model = decoded.get("model")
        self.gateway.access_store.record_usage(
            self.principal, self.request_id, route=self.path,
            model=model if isinstance(model, str) and model in {"c3r-core", "c3r-system-one", "c3r-verifier"} else None,
            status=status, latency_ms=(time.monotonic() - self.started) * 1000,
            input_tokens=count(usage.get("input_tokens")), output_tokens=count(usage.get("output_tokens")),
            system_one_invocations=count(c3r.get("system_one_invocations")),
            system_two_invocations=count(c3r.get("system_two_invocations")),
        )

    def _authorized(self) -> bool:
        # Tenant and project identity come only from the authenticated key.
        # Reject caller context overrides rather than silently ignoring them.
        if any(name in self.headers for name in (
            "X-Tenant-ID", "X-Project-ID", "OpenAI-Organization", "OpenAI-Project",
            "X-C3R-Organization", "X-C3R-Project",
        )):
            return False
        supplied = self.headers.get_all("X-C3R-Token", [])
        authorization = self.headers.get_all("Authorization", [])
        if len(authorization) > 1 or len(supplied) > 1:
            return False
        if self.gateway.access_store is not None:
            if supplied or len(authorization) != 1 or not authorization[0].startswith("Bearer "):
                return False
            principal = self.gateway.access_store.authenticate(authorization[0][7:])
            if principal is None:
                return False
            self.principal = principal
            return True
        # Preserve IAM staging's separate client header. Without that header,
        # SDK clients use standard Bearer auth; it is never relayed upstream.
        if supplied:
            return hmac.compare_digest(self.gateway.client_token.encode(), supplied[0].encode())
        return (len(authorization) == 1 and
                hmac.compare_digest(("Bearer " + self.gateway.client_token).encode(),
                                    authorization[0].encode()))

    def _forward(self, method: str, body: bytes | None = None) -> None:
        route_slot = self.gateway.route_slots.get(self.path)
        if route_slot is not None and not route_slot.acquire(blocking=False):
            self._send_error(429 if self.gateway.access_store else 503, "over_capacity")
            return
        if not self.gateway.in_flight.acquire(blocking=False):
            if route_slot is not None:
                route_slot.release()
            self._send_error(429 if self.gateway.access_store else 503, "over_capacity")
            return
        connection = HTTPConnection(
            self.gateway.upstream_host,
            self.gateway.upstream_port,
            timeout=self.gateway.upstream_timeout_seconds,
        )
        stopped = Event()
        disconnected = Event()
        watcher: Thread | None = None
        try:
            if self.gateway.access_store is not None and self.principal is not None:
                self.gateway.access_store.dispatch_event(self.principal, self.request_id)
            headers = {"Authorization": "Bearer " + self.gateway.upstream_token}
            headers["x-request-id"] = self.request_id
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.connect()
            transport = connection.sock
            if transport is None:
                raise OSError("upstream transport missing")

            def watch_disconnect() -> None:
                while not stopped.wait(0.05):
                    try:
                        readable, _, _ = select.select([self.connection], [], [], 0)
                        if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                            disconnected.set()
                            transport.shutdown(socket.SHUT_RDWR)
                            return
                    except (OSError, ValueError):
                        return

            watcher = Thread(target=watch_disconnect, daemon=True)
            watcher.start()
            connection.request(method, self.path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status == 200 and response.getheader("Content-Type", "").split(";", 1)[0] == "text/event-stream":
                if method != "POST" or self.path != "/v1/responses" or transport is None:
                    raise ValueError("unexpected stream")
                self._forward_stream(response, disconnected)
                return
            forwarded = response.read(MAX_RESPONSE_BYTES + 1)
            if len(forwarded) > MAX_RESPONSE_BYTES:
                self._send_error(502, "invalid_upstream_response")
                return
            decoded = json.loads(forwarded)
            if not isinstance(decoded, dict) or not 200 <= response.status <= 599:
                raise ValueError("invalid upstream response")
            self._record_usage(response.status, cast(Mapping[str, object], decoded))
            if response.status >= 400 and self.gateway.access_store is not None:
                self._send_error(response.status, "upstream_rejected")
                return
        except (OSError, HTTPException, ValueError, sqlite3.Error):
            if not disconnected.is_set():
                self._send_error(503, "upstream_unavailable")
            return
        finally:
            stopped.set()
            if watcher is not None:
                watcher.join(timeout=1)
            connection.close()
            self.gateway.in_flight.release()
            if route_slot is not None:
                route_slot.release()
        self.send_response(response.status)
        self.send_header("x-request-id", self.request_id)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(forwarded)))
        self.end_headers()
        self.wfile.write(forwarded)

    def _forward_stream(self, response: HTTPResponse, disconnected: Event) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("x-request-id", self.request_id)
        self.end_headers()
        terminal = False
        total = 0
        deadline = time.monotonic() + 300
        try:
            frame = bytearray()
            while time.monotonic() < deadline:
                line = response.readline(MAX_RESPONSE_BYTES + 1)
                if not line:
                    break
                frame.extend(line)
                total += len(line)
                if len(frame) > MAX_RESPONSE_BYTES or total > 2_097_152:
                    raise ValueError("stream bound exceeded")
                if line not in (b"\n", b"\r\n"):
                    continue
                data = b"\n".join(part[5:].strip() for part in bytes(frame).splitlines()
                                   if part.startswith(b"data:"))
                raw_event = json.loads(data)
                if not isinstance(raw_event, dict):
                    raise TypeError("invalid stream event")
                event = cast(dict[str, object], raw_event)
                event_type = event.get("type")
                if not isinstance(event_type, str):
                    raise TypeError("invalid stream event type")
                if event_type in {"response.completed", "response.failed"}:
                    payload = event.get("response")
                    self._record_usage(200 if event_type == "response.completed" else 503,
                                       cast(Mapping[str, object], payload) if isinstance(payload, dict) else {})
                    terminal = True
                self.wfile.write(frame)
                self.wfile.flush()
                frame.clear()
                if terminal:
                    return
            raise ValueError("incomplete stream")
        except (OSError, HTTPException, TypeError, ValueError, sqlite3.Error):
            if not terminal:
                try:
                    self._record_usage(499 if disconnected.is_set() else 503, {})
                    failure = {"type": "response.failed", "response": {"status": "failed",
                               "error": {"code": "stream_interrupted", "message": "C3R stream interrupted."}}}
                    self.wfile.write(b"event: response.failed\ndata: " + json.dumps(failure).encode() + b"\n\n")
                    self.wfile.flush()
                except (OSError, sqlite3.Error):
                    pass

    def do_GET(self) -> None:
        try:
            self._get()
        except (sqlite3.Error, OSError):
            self._send_error(503, "access_unavailable")

    def _get(self) -> None:
        self._begin_request()
        if self.path not in {"/health", "/metrics", "/ready", "/v1/models"}:
            self._send_error(404, "not_found")
            return
        if self.path != "/health" and not self._authorized():
            self._send_error(401, "unauthorized")
            return
        if self.path != "/health" and not self._scope_allowed():
            self._send_error(403, "insufficient_scope")
            return
        if self.path != "/health" and self.gateway.access_store is not None and not self._admitted():
            self._send_error(429, "rate_limited")
            return
        self._forward("GET")

    def do_POST(self) -> None:
        try:
            self._post()
        except (sqlite3.Error, OSError):
            self._send_error(503, "access_unavailable")

    def _post(self) -> None:
        self._begin_request()
        if self.path not in {
            "/v1/decisions", "/v1/c3r/decide", "/v1/c3r/rank",
            "/v1/system-one", "/v1/c3r/execute", "/v1/responses",
        }:
            self._send_error(404, "not_found")
            return
        if not self._authorized():
            self._send_error(401, "unauthorized")
            return
        if not self._scope_allowed():
            self._send_error(403, "insufficient_scope")
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._send_error(400, "unsupported_transfer_encoding")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send_error(415, "unsupported_media_type")
            return
        if not self._admitted():
            self._send_error(429, "rate_limited")
            return
        lengths = self.headers.get_all("Content-Length", [])
        try:
            length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            length = -1
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._send_error(413, "request_size_out_of_bounds")
            return
        self._forward("POST", self.rfile.read(length))

