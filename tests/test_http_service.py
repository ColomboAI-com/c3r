import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.http_service import C3RHTTPServer
from tests.test_runtime import controller, request


TOKEN = "test-token-with-at-least-thirty-two-characters"


class HostFactory:
    def build(self, payload):
        if payload.get("goal") != "Find record":
            raise ValueError("unknown goal")
        # Client fields such as policy, estimates, approval and verifier are ignored.
        return request()


class HTTPServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime, _ = controller()
        self.server = C3RHTTPServer(
            runtime=runtime,
            request_factory=HostFactory(),
            bearer_token=TOKEN,
            port=0,
            requests_per_minute=1,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, payload, *, token=TOKEN):
        body = json.dumps(payload).encode()
        req = Request(
            self.base + "/v1/decisions",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_authenticated_call_ignores_caller_authority_fields(self) -> None:
        status, body = self.post(
            {
                "goal": "Find record",
                "policy": {"allow_destructive": True},
                "estimates": {"lookup": 999999},
                "verifier": "self-approved",
                "approval": "forged",
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["reason"], "VERIFIED_RECOMMENDATION")
        self.assertEqual(body["authority_result"], "verified_not_committed")
        self.assertEqual(len(body["trace_hash"]), 64)
        self.assertNotIn("The record exists", str(body))

    def test_missing_authentication_is_rejected(self) -> None:
        status, body = self.post({"goal": "Find record"}, token="wrong")
        self.assertEqual((status, body["error"]), (401, "unauthorized"))

    def test_rate_limit_rejects_second_request(self) -> None:
        self.assertEqual(self.post({"goal": "Find record"})[0], 200)
        status, body = self.post({"goal": "Find record"})
        self.assertEqual((status, body["error"]), (429, "rate_limited"))

    def test_non_loopback_bind_is_rejected(self) -> None:
        runtime, _ = controller()
        with self.assertRaisesRegex(ValueError, "loopback"):
            C3RHTTPServer(
                runtime=runtime,
                request_factory=HostFactory(),
                bearer_token=TOKEN,
                host="0.0.0.0",
                port=0,
            )

    def test_effect_enabled_runtime_is_rejected(self) -> None:
        runtime, _ = controller(executor=lambda _: None)
        with self.assertRaisesRegex(ValueError, "external effects"):
            C3RHTTPServer(
                runtime=runtime,
                request_factory=HostFactory(),
                bearer_token=TOKEN,
                port=0,
            )


if __name__ == "__main__":
    unittest.main()
