"""Developer authentication and admission through the real gateway HTTP boundary."""
import json
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.api_access import AccessStore
from c3r.ingress_proxy import C3RIngressServer

BACKEND_TOKEN = "backend-test-token-distinct-and-long-enough"


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        body = b'{"object":"list","data":[{"id":"c3r-system-one"}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if payload.get("input") == "wait_headers":
            server = cast(UpstreamServer, self.server)
            server.pending_headers.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                readable, _, _ = select.select([self.connection], [], [], 0.05)
                if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                    server.cancelled.set()
                    return
            return
        if payload.get("input") == "reject":
            body = b'{"error":"private upstream diagnostic"}'
            self.send_response(400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if payload.get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'event: response.created\ndata: {"type":"response.created"}\n\n')
            self.wfile.flush()
            server = cast(UpstreamServer, self.server)
            deadline = time.monotonic() + 2
            while not server.stream_release.wait(0.05) and time.monotonic() < deadline:
                readable, _, _ = select.select([self.connection], [], [], 0)
                if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                    server.cancelled.set()
                    return
            self.wfile.write(b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"safe"}\n\n')
            self.wfile.write(b'event: response.completed\ndata: {"type":"response.completed","response":{"model":"c3r-core","usage":{"input_tokens":13,"output_tokens":7}}}\n\n')
            self.wfile.flush()
            return
        body = json.dumps({"model": "c3r-core", "output_text": "PRIVATE_RETURN_MARKER",
                           "usage": {"input_tokens": 13, "output_tokens": 7},
                           "c3r": {"system_one_invocations": 1, "system_two_invocations": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UpstreamServer(ThreadingHTTPServer):
    stream_release: threading.Event
    cancelled: threading.Event
    pending_headers: threading.Event


class APIAccessHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.store = AccessStore(Path(self.scratch.name) / "access.sqlite3")
        self.store.create_project("tenant-a", "project-a")
        self.key = self.store.issue_key("tenant-a", "project-a", {"models:read"})
        self.upstream = UpstreamServer(("127.0.0.1", 0), Upstream)
        self.upstream.stream_release = threading.Event()
        self.upstream.cancelled = threading.Event()
        self.upstream.pending_headers = threading.Event()
        self.gateway = C3RIngressServer(
            upstream_port=self.upstream.server_port, upstream_token=BACKEND_TOKEN,
            client_token="unused-staging-token-with-at-least-32-characters",
            host="127.0.0.1", port=0, access_store=self.store,
        )
        self.threads = [threading.Thread(target=server.serve_forever, daemon=True)
                        for server in (self.upstream, self.gateway)]
        for thread in self.threads:
            thread.start()

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.upstream.shutdown()
        self.gateway.server_close()
        self.upstream.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.scratch.cleanup()

    def call(self, path: str, *, key: str | None = None, method: str = "GET",
             payload: dict[str, object] | None = None) -> tuple[int, dict[str, object], str | None]:
        request = Request(f"http://127.0.0.1:{self.gateway.server_port}" + path,
                          headers={"Authorization": "Bearer " + (key or self.key.secret),
                                   "Content-Type": "application/json"},
                          data=json.dumps(payload).encode() if payload is not None else None,
                          method=method)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, cast(dict[str, object], json.load(response)), response.headers.get("x-request-id")
        except HTTPError as error:
            return error.code, cast(dict[str, object], json.load(error)), error.headers.get("x-request-id")

    def test_scoped_developer_key_can_discover_models(self) -> None:
        status, body, request_id = self.call("/v1/models")
        self.assertEqual((status, body["object"]), (200, "list"))
        self.assertIsNotNone(request_id)

    def test_key_scope_blocks_generation_with_standard_error_and_request_id(self) -> None:
        status, body, request_id = self.call("/v1/responses", method="POST", payload={
            "model": "c3r-core", "input": "sensitive text must not be retained"})
        error = cast(dict[str, object], body["error"])
        self.assertEqual((status, error["type"]), (403, "permission_error"))
        self.assertEqual(error["request_id"], request_id)

    def test_authenticated_refusal_has_one_payload_free_outcome(self) -> None:
        status, _, request_id = self.call("/v1/responses", method="POST", payload={
            "model": "c3r-core", "input": "PRIVATE_REFUSAL_MARKER"})
        rows = self.store.project_usage("tenant-a", "project-a")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["request_id"], rows[0]["status"]), (request_id, status))
        self.assertEqual(status, 403)
        self.assertIsNone(rows[0]["system_one_invocations"])
        self.assertNotIn("PRIVATE_REFUSAL_MARKER", json.dumps(rows))

    def test_revoked_and_expired_keys_cannot_infer(self) -> None:
        self.store.revoke_key("tenant-a", "project-a", self.key.key_id)
        self.assertEqual(self.call("/v1/models")[0], 401)
        expired = self.store.issue_key("tenant-a", "project-a", {"models:read"}, expires_at=1)
        self.assertEqual(self.call("/v1/models", key=expired.secret)[0], 401)

    def test_project_rate_limit_is_shared_by_its_keys_not_other_tenants(self) -> None:
        self.store.create_project("tenant-b", "project-a", rpm=1)
        first = self.store.issue_key("tenant-b", "project-a", {"models:read"})
        second = self.store.issue_key("tenant-b", "project-a", {"models:read"})
        self.assertEqual(self.call("/v1/models", key=first.secret)[0], 200)
        status, body, _ = self.call("/v1/models", key=second.secret)
        self.assertEqual((status, cast(dict[str, object], body["error"])["type"]),
                         (429, "rate_limit_error"))
        self.assertEqual(self.call("/v1/models")[0], 200)

    def test_operator_cli_issues_show_once_key_accepted_by_gateway(self) -> None:
        result = subprocess.run([sys.executable, "-m", "c3r.key_management", "--database",
                                 str(self.store.path), "issue", "--tenant", "tenant-a",
                                 "--project", "project-a", "--scope", "models:read"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        issued = cast(dict[str, str], json.loads(result.stdout))
        self.assertEqual(self.call("/v1/models", key=issued["api_key"])[0], 200)
        listed = subprocess.run([sys.executable, "-m", "c3r.key_management", "--database",
                                 str(self.store.path), "keys", "--tenant", "tenant-a",
                                 "--project", "project-a"], capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(listed.returncode, 0)
        self.assertNotIn(issued["api_key"], listed.stdout)

    def test_usage_cli_reports_actual_counts_without_payloads_or_fabricated_gpu_cost(self) -> None:
        key = self.store.issue_key("tenant-a", "project-a", {"responses:write"})
        status, _, request_id = self.call("/v1/responses", key=key.secret, method="POST", payload={
            "model": "c3r-core", "input": "PRIVATE_INPUT_MARKER"})
        self.assertEqual(status, 200)
        result = subprocess.run([sys.executable, "-m", "c3r.key_management", "--database",
                                 str(self.store.path), "usage", "--tenant", "tenant-a",
                                 "--project", "project-a"], capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0)
        rows = cast(list[dict[str, object]], json.loads(result.stdout))
        self.assertEqual((rows[0]["request_id"], rows[0]["input_tokens"], rows[0]["output_tokens"]),
                         (request_id, 13, 7))
        self.assertIsNone(rows[0]["gpu_allocation_ms"])
        self.assertIsNone(rows[0]["allocated_cost_usd"])
        self.assertNotIn("PRIVATE_", result.stdout)
        self.assertNotIn(key.secret, self.store.path.read_bytes().decode("latin1"))

    def test_operator_metadata_purge_removes_only_aged_rows_in_selected_project(self) -> None:
        self.store.clock = lambda: 1.0
        self.assertEqual(self.call("/v1/models")[0], 200)
        self.store.create_project("tenant-b", "project-a")
        other = self.store.issue_key("tenant-b", "project-a", {"models:read"})
        self.assertEqual(self.call("/v1/models", key=other.secret)[0], 200)
        self.store.clock = time.time
        self.assertEqual(self.call("/v1/models")[0], 200)
        result = subprocess.run([sys.executable, "-m", "c3r.key_management", "--database",
                                 str(self.store.path), "purge", "--tenant", "tenant-a",
                                 "--project", "project-a", "--retention-seconds", "86400",
                                 "--limit", "10"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads(result.stdout)
        self.assertEqual((proof["usage_deleted"], proof["audit_deleted"]), (1, 1))
        self.assertFalse(proof["backup_deletion_verified"])
        self.assertEqual(len(self.store.project_usage("tenant-a", "project-a")), 1)
        self.assertEqual(len(self.store.project_usage("tenant-b", "project-a")), 1)
        self.assertEqual(self.call("/v1/models")[0], 200)  # Key was not deleted.

    def test_stream_is_forwarded_before_generation_finishes(self) -> None:
        key = self.store.issue_key("tenant-a", "project-a", {"responses:write"})
        request = Request(f"http://127.0.0.1:{self.gateway.server_port}/v1/responses",
                          headers={"Authorization": "Bearer " + key.secret,
                                   "Content-Type": "application/json"},
                          data=b'{"model":"c3r-core","input":"test","stream":true}')
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            self.assertEqual(response.readline(), b"event: response.created\n")
            status, rejected, _ = self.call("/v1/responses", key=key.secret, method="POST",
                                           payload={"model": "c3r-core", "input": "test"})
            self.assertEqual(status, 429)
            self.assertEqual(cast(dict[str, object], rejected["error"])["type"], "rate_limit_error")
            self.upstream.stream_release.set()
            remaining = response.read()
            self.assertIn(b"event: response.completed", remaining)

    def test_upstream_rejection_has_canonical_redacted_error(self) -> None:
        key = self.store.issue_key("tenant-a", "project-a", {"responses:write"})
        status, body, request_id = self.call("/v1/responses", key=key.secret, method="POST",
                                            payload={"model": "c3r-core", "input": "reject"})
        self.assertEqual(status, 400)
        self.assertEqual(cast(dict[str, object], body["error"])["request_id"], request_id)
        self.assertNotIn("private", json.dumps(body))

    def test_disconnect_cancels_idle_upstream_and_releases_core_capacity(self) -> None:
        key = self.store.issue_key("tenant-a", "project-a", {"responses:write"})
        request = Request(f"http://127.0.0.1:{self.gateway.server_port}/v1/responses",
                          headers={"Authorization": "Bearer " + key.secret,
                                   "Content-Type": "application/json"},
                          data=b'{"model":"c3r-core","input":"test","stream":true}')
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.readline(), b"event: response.created\n")
        self.assertTrue(self.upstream.cancelled.wait(1), "idle generation was not cancelled")
        deadline = time.monotonic() + 1
        status = 429
        while time.monotonic() < deadline:
            status, _, _ = self.call("/v1/responses", key=key.secret, method="POST",
                                     payload={"model": "c3r-core", "input": "test"})
            if status == 200:
                break
            time.sleep(0.05)
        self.assertEqual(status, 200)

    def test_unavailable_access_database_fails_closed_with_sanitized_error(self) -> None:
        self.store.path.unlink()
        status, body, _ = self.call("/v1/models")
        self.assertEqual(status, 503)
        self.assertEqual(cast(dict[str, object], body["error"])["code"], "access_unavailable")

    def test_unsupported_method_returns_json_error_and_request_id(self) -> None:
        status, body, request_id = self.call("/v1/models", method="PUT")
        self.assertEqual(status, 405)
        self.assertEqual(cast(dict[str, object], body["error"])["request_id"], request_id)

    def test_disconnect_before_upstream_headers_cancels_and_releases_capacity(self) -> None:
        key = self.store.issue_key("tenant-a", "project-a", {"responses:write"})
        payload = b'{"model":"c3r-core","input":"wait_headers","stream":true}'
        with socket.create_connection(("127.0.0.1", self.gateway.server_port), timeout=2) as client:
            client.sendall(("POST /v1/responses HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer " +
                            key.secret + "\r\nContent-Type: application/json\r\nContent-Length: " +
                            str(len(payload)) + "\r\n\r\n").encode() + payload)
            self.assertTrue(self.upstream.pending_headers.wait(1))
        self.assertTrue(self.upstream.cancelled.wait(1))
        status = 429
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            status, _, _ = self.call("/v1/responses", key=key.secret, method="POST",
                                     payload={"model": "c3r-core", "input": "test"})
            if status == 200:
                break
            time.sleep(0.05)
        self.assertEqual(status, 200)
        rows = self.store.project_usage("tenant-a", "project-a")
        cancelled = [row for row in rows if row["status"] == 499]
        self.assertEqual(len(cancelled), 1)
        self.assertIsNone(cancelled[0]["system_one_invocations"])
        self.assertIsNone(cancelled[0]["system_two_invocations"])
        self.assertNotIn("wait_headers", json.dumps(rows))
        self.assertEqual(len({row["request_id"] for row in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()
