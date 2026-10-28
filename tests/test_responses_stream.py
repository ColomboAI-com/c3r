"""Authenticated HTTP streaming contract backed by a local generation service."""

import json
import select
import socket
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from c3r.adapters.providers import ProviderAdapter, ProviderConfig, ProviderKind
from c3r.host_factory import ReadOnlyRequestFactory
from c3r.http_service import C3RHTTPServer
from c3r.responses import ResponsesService
from c3r.state_schema import ActionDefinition, ActionFamily, AuthorityPolicy, RiskClass
from tests.test_runtime import controller

TOKEN = "stream-test-token-with-at-least-thirty-two-characters"


class _GenerationServer(ThreadingHTTPServer):
    requests: list[dict[str, object]]
    hold_headers: bool
    headers_pending: threading.Event
    hold_after_first: bool
    fail_after_first: bool
    finish_with_text: bool
    release_next: threading.Event
    abort_seen: threading.Event


class _GenerationHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        assert isinstance(self.server, _GenerationServer)
        length_header = self.headers["Content-Length"]
        assert length_header is not None
        body = json.loads(self.rfile.read(int(length_header)))
        self.server.requests.append(body)
        if self.server.hold_headers:
            self.server.headers_pending.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                ready, _, _ = select.select([self.connection], [], [], 0.05)
                if ready and not self.connection.recv(1, socket.MSG_PEEK):
                    self.server.abort_seen.set()
                    return
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        events: list[dict[str, object]] = [
            {"choices": [{"delta": {"content": "Check ", "reasoning_content": "PRIVATE"},
                          "finish_reason": None}]},
            {"choices": [{"delta": {"content": "charges."},
                          "finish_reason": "stop" if self.server.finish_with_text else None}]},
        ]
        if not self.server.finish_with_text:
            events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        events.append(
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        )
        for index, data in enumerate(events):
            if index == 1 and self.server.hold_after_first:
                deadline = time.monotonic() + 3
                while not self.server.release_next.is_set() and time.monotonic() < deadline:
                    ready, _, _ = select.select([self.connection], [], [], 0.05)
                    if ready and not self.connection.recv(1, socket.MSG_PEEK):
                        self.server.abort_seen.set()
                        return
            if index == 1 and self.server.fail_after_first:
                self.wfile.write(b"data: {broken\n\n")
                self.wfile.flush()
                return
            try:
                self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode())
                self.wfile.flush()
            except OSError:
                return
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            return


class ResponsesStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _GenerationServer(("127.0.0.1", 0), _GenerationHandler)
        self.backend.requests = []
        self.backend.hold_headers = False
        self.backend.headers_pending = threading.Event()
        self.backend.hold_after_first = False
        self.backend.fail_after_first = False
        self.backend.finish_with_text = False
        self.backend.release_next = threading.Event()
        self.backend.abort_seen = threading.Event()
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        runtime, _ = controller(deliberative=True)
        factory = ReadOnlyRequestFactory(
            definitions=(ActionDefinition(
                "DELIBERATE", ActionFamily.DELIBERATE, "compute", "generate",
                RiskClass.READ_ONLY, ((),), ("local",), ("policy",), 0, 0,
            ),),
            policy=AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}),
                                   frozenset({RiskClass.READ_ONLY})),
            estimate_source=lambda _: {}, remaining_usd=0,
        )
        provider = ProviderAdapter(ProviderConfig(
            "local", ProviderKind.OPENAI_COMPATIBLE,
            f"http://127.0.0.1:{self.backend.server_port}/v1", "model", None,
        ))
        self.api = C3RHTTPServer(runtime=runtime, request_factory=factory,
                                 bearer_token=TOKEN, port=0,
                                 responses=ResponsesService(runtime, factory, provider))
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()

    def tearDown(self) -> None:
        self.backend.release_next.set()
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(timeout=2)
        self.backend.shutdown()
        self.backend.server_close()
        self.backend_thread.join(timeout=2)

    def test_stream_emits_real_text_deltas_and_terminal_response(self) -> None:
        connection = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        connection.request("POST", "/v1/responses", body=json.dumps({
            "model": "c3r-core", "input": "Find record", "stream": True,
        }), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        response = connection.getresponse()
        wire = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        self.assertEqual([line.removeprefix("event: ") for line in wire.splitlines()
                          if line.startswith("event: ")], [
            "response.created", "response.output_text.delta", "response.output_text.delta",
            "response.output_text.done", "response.completed",
        ])
        self.assertIn("Check charges.", wire)
        self.assertNotIn("PRIVATE", wire)
        self.assertTrue(self.backend.requests[0]["stream"])
        messages = cast(list[dict[str, str]], self.backend.requests[0]["messages"])
        self.assertTrue(messages[0]["content"].startswith("C³-R — SYSTEM PROMPT\n"))
        self.assertIn("C3R v0.1 RUNTIME BOUNDARY", messages[0]["content"])
        self.assertEqual(messages[1], {"role": "user", "content": "Find record"})
        terminal = [json.loads(line[6:]) for line in wire.splitlines()
                    if line.startswith("data: ")][-1]["response"]
        self.assertEqual((terminal["c3r"]["system_one_invocations"],
                          terminal["c3r"]["system_two_invocations"]), (0, 1))

    def test_rejected_stream_does_not_start_backend_generation(self) -> None:
        runtime, _ = controller(deliberative=True, accepted=False)
        self.api.runtime = runtime
        assert self.api.responses is not None
        self.api.responses.runtime = runtime
        connection = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        connection.request("POST", "/v1/responses", body=json.dumps({
            "model": "c3r-core", "input": "Find record", "stream": True,
        }), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 503)
        response.read()
        connection.close()
        self.assertEqual(self.backend.requests, [])

    def test_backend_error_emits_failed_terminal_event_without_private_reasoning(self) -> None:
        self.backend.fail_after_first = True
        connection = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        connection.request("POST", "/v1/responses", body=json.dumps({
            "model": "c3r-core", "input": "Find record", "stream": True,
        }), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        response = connection.getresponse()
        wire = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("event: response.failed", wire)
        self.assertNotIn("event: response.completed", wire)
        self.assertNotIn("PRIVATE", wire)

    def test_final_delta_with_finish_reason_is_not_lost(self) -> None:
        self.backend.finish_with_text = True
        connection = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        connection.request("POST", "/v1/responses", body=json.dumps({
            "model": "c3r-core", "input": "Find record", "stream": True,
        }), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        response = connection.getresponse()
        wire = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn('"text":"Check charges."', wire)
        self.assertIn("event: response.completed", wire)

    def test_disconnect_before_backend_headers_cancels_generation(self) -> None:
        self.api.generation_capacity = threading.BoundedSemaphore(1)
        self.backend.hold_headers = True
        body = json.dumps({"model": "c3r-core", "input": "Find record", "stream": True}).encode()
        first = socket.create_connection(("127.0.0.1", self.api.server_port), timeout=2)
        first.sendall(("POST /v1/responses HTTP/1.1\r\nHost: localhost\r\n"
                       f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
                       f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
        self.assertTrue(self.backend.headers_pending.wait(timeout=1))
        first.shutdown(socket.SHUT_RDWR)
        first.close()
        self.assertTrue(self.backend.abort_seen.wait(timeout=1))
        self.backend.hold_headers = False
        time.sleep(0.1)
        second = HTTPConnection("127.0.0.1", self.api.server_port, timeout=2)
        second.request("POST", "/v1/responses", body=body, headers={
            "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        response = second.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        second.close()

    def test_disconnected_stream_releases_generation_capacity(self) -> None:
        self.api.generation_capacity = threading.BoundedSemaphore(1)
        self.backend.hold_after_first = True
        first = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        first.connect()
        client_socket = first.sock
        assert client_socket is not None
        body = json.dumps({"model": "c3r-core", "input": "Find record", "stream": True})
        headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
        first.request("POST", "/v1/responses", body=body, headers=headers)
        first_response = first.getresponse()
        self.assertEqual(first_response.status, 200)
        while first_response.readline() != b"event: response.output_text.delta\n":
            pass
        second = HTTPConnection("127.0.0.1", self.api.server_port, timeout=3)
        second.request("POST", "/v1/responses", body=body, headers=headers)
        refused = second.getresponse()
        self.assertEqual(refused.status, 429)
        refused.read()
        second.close()
        client_socket.shutdown(socket.SHUT_RDWR)
        first_response.close()
        first.close()
        deadline = time.monotonic() + 1
        capacity_released = False
        while time.monotonic() < deadline:
            if (self.api.metrics.snapshot().get("stream_disconnect")
                    and self.api.generation_capacity.acquire(blocking=False)):
                self.api.generation_capacity.release()
                capacity_released = True
                break
            time.sleep(0.02)
        self.assertEqual(self.api.metrics.snapshot().get("stream_disconnect"), 1)
        self.assertTrue(capacity_released)
        self.assertTrue(self.backend.abort_seen.wait(timeout=1))
        self.backend.release_next.set()


if __name__ == "__main__":
    unittest.main()
