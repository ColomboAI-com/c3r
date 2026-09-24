"""Bounded ingress for an IAM/TLS-terminated host with a loopback C3R backend.

The outer host still owns TLS, IAM, secrets, and abuse controls. This proxy never
trusts caller authorization as backend authorization and never logs request data.
"""

from __future__ import annotations

import hmac
import json
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore

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
        self.upstream_token = upstream_token
        self.upstream_timeout_seconds = upstream_timeout_seconds
        self.limiter = TokenBucket(
            capacity=requests_per_minute,
            refill_per_second=requests_per_minute / 60,
        )
        self.in_flight = BoundedSemaphore(max_in_flight)
        super().__init__((host, port), _IngressHandler)


class _IngressHandler(BaseHTTPRequestHandler):
    server: C3RIngressServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_error(self, status: int, code: str) -> None:
        body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get_all("X-C3R-Token", [])
        return len(supplied) == 1 and hmac.compare_digest(self.server.client_token, supplied[0])

    def _forward(self, method: str, body: bytes | None = None) -> None:
        if not self.server.in_flight.acquire(blocking=False):
            self._send_error(503, "over_capacity")
            return
        connection = HTTPConnection(
            self.server.upstream_host,
            self.server.upstream_port,
            timeout=self.server.upstream_timeout_seconds,
        )
        try:
            headers = {"Authorization": "Bearer " + self.server.upstream_token}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, self.path, body=body, headers=headers)
            response = connection.getresponse()
            forwarded = response.read(MAX_RESPONSE_BYTES + 1)
            if len(forwarded) > MAX_RESPONSE_BYTES:
                self._send_error(502, "invalid_upstream_response")
                return
            decoded = json.loads(forwarded)
            if not isinstance(decoded, dict) or not 200 <= response.status <= 599:
                raise ValueError("invalid upstream response")
        except (OSError, HTTPException, ValueError):
            self._send_error(503, "upstream_unavailable")
            return
        finally:
            connection.close()
            self.server.in_flight.release()
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(forwarded)))
        self.end_headers()
        self.wfile.write(forwarded)

    def do_GET(self) -> None:
        if self.path not in {"/health", "/metrics"}:
            self._send_error(404, "not_found")
            return
        if self.path == "/metrics" and not self._authorized():
            self._send_error(401, "unauthorized")
            return
        self._forward("GET")

    def do_POST(self) -> None:
        if self.path != "/v1/decisions":
            self._send_error(404, "not_found")
            return
        if not self._authorized():
            self._send_error(401, "unauthorized")
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._send_error(400, "unsupported_transfer_encoding")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send_error(415, "unsupported_media_type")
            return
        if not self.server.limiter.take():
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

