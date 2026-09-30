"""Public HTTP contract for the stateless recommendation-only release."""

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.http_service import C3RHTTPServer
from tests.test_runtime import controller, request


TOKEN = "stateless-test-token-with-at-least-thirty-two-characters"


class _Factory:
    def build(self, payload):
        if payload.get("goal") != "Find record":
            raise ValueError("unknown goal")
        return request()


class StatelessAPITests(unittest.TestCase):
    def setUp(self):
        runtime, _ = controller()
        self.server = C3RHTTPServer(
            runtime=runtime, request_factory=_Factory(), bearer_token=TOKEN,
            port=0, requests_per_minute=20,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, path, *, method="POST", token=TOKEN, payload=None):
        headers = {"Authorization": f"Bearer {token}"}
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_decide_and_rank_are_recommendation_only(self):
        for path in ("/v1/c3r/decide", "/v1/c3r/rank", "/v1/system-one"):
            status, body = self.call(path, payload={"goal": "Find record"})
            self.assertEqual(status, 200)
            self.assertEqual(body["authority_result"], "verified_not_committed")
            self.assertFalse(body["effect_executed"])
            self.assertNotIn("confidence", body)
            if path.endswith("rank") or path.endswith("system-one"):
                self.assertEqual(body["candidate_ranking"], [])
                self.assertTrue(body["abstained"])

    def test_execute_and_untyped_responses_are_unavailable(self):
        for path in ("/v1/c3r/execute", "/v1/responses"):
            status, body = self.call(path, payload={"goal": "Find record"})
            self.assertEqual(status, 501)
            self.assertEqual(body["error"], "not_implemented")

    def test_new_paths_require_authentication(self):
        for path in ("/v1/c3r/decide", "/v1/c3r/execute", "/v1/responses"):
            status, body = self.call(path, token="wrong", payload={"goal": "Find record"})
            self.assertEqual((status, body["error"]), (401, "unauthorized"))
        for path in ("/ready", "/v1/models"):
            status, body = self.call(path, method="GET", token="wrong")
            self.assertEqual((status, body["error"]), (401, "unauthorized"))

    def test_models_do_not_claim_calibration_or_generation(self):
        status, body = self.call("/v1/models", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(body["models"][0]["id"], "c3r-core")
        self.assertFalse(body["models"][0]["text_generation"])
        self.assertFalse(body["models"][0]["calibrated"])
        self.assertFalse(body["models"][0]["available"])
        status, body = self.call("/ready", method="GET")
        self.assertEqual((status, body["status"]), (503, "disabled"))


if __name__ == "__main__":
    unittest.main()
