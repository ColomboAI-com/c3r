"""A separate authenticated loopback maintenance channel, never an API proxy."""
import hmac
import json
import re
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

ReadinessProbe = Callable[[], Mapping[str, object]]
CHECKS = ("runtime", "clm_qwen", "deepseek", "required_local_artifact_files")


class InternalReadinessServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *, token: str, port: int,
                 probe: ReadinessProbe | None = None) -> None:
        if len(token) < 32:
            raise ValueError("internal readiness token must have at least 32 characters")
        self.token, self.probe = token, probe
        super().__init__(("127.0.0.1", port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    @property
    def readiness_server(self) -> InternalReadinessServer:
        return cast(InternalReadinessServer, self.server)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, value: Mapping[str, object]) -> None:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/internal/ready":
            self._send(404, {"error": "not_found"})
            return
        supplied = self.headers.get_all("Authorization", [])
        if (len(supplied) != 1 or not hmac.compare_digest(
                ("Bearer " + self.readiness_server.token).encode(), supplied[0].encode())):
            self._send(401, {"error": "unauthorized"})
            return
        raw_report: object = None
        if self.readiness_server.probe is not None:
            try:
                raw_report = self.readiness_server.probe()
            except (OSError, RuntimeError, TypeError, ValueError, KeyError):
                pass
        report: Mapping[str, object] = (raw_report
                  if isinstance(raw_report, Mapping) else {})
        checks = {name: report.get(name) is True for name in CHECKS}
        pin = report.get("required_local_artifact_manifest_sha256")
        valid_pin = isinstance(pin, str) and re.fullmatch(r"[a-f0-9]{64}", pin) is not None
        ready = all(checks.values()) and valid_pin
        self._send(200 if ready else 503, {
            "status": "ready" if ready else "not_ready", "checks": checks,
            "artifact_scope": "required_local_files_not_deepseek_weight_attestation",
            "required_local_artifact_manifest_sha256": pin if valid_pin else None,
        })

    def do_POST(self) -> None:
        self._send(405, {"error": "method_not_allowed"})
