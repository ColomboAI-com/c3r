"""Public HTTP contract for the stateless recommendation-only release."""

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.adapters.providers import ProviderAdapter, ProviderConfig, ProviderKind, TransportResponse
from c3r.host_factory import ReadOnlyRequestFactory
from c3r.http_service import C3RHTTPServer
from c3r.readiness import CachedReadiness
from c3r.responses import ResponsesService
from c3r.state_schema import (
    ActionDefinition,
    ActionFamily,
    AuthorityPolicy,
    RiskClass,
    ValueEstimate,
)
from c3r.system_one.advisory import AdvisoryFastPath
from c3r.system_one.clm_adapter import ClmAdapter
from c3r.system_one.inference import SystemOneInference
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

    def configure_ranker(self, transport, *, enabled=True, system_one=True, ready=lambda: True):
        adapter = ClmAdapter("a" * 64, transport=transport)
        self.server.runtime, _ = controller(enabled=enabled, system_one=system_one,
                                            fast_path=AdvisoryFastPath(adapter))
        self.server.system_one = SystemOneInference(adapter, readiness=ready)

    def test_typed_ranker_respects_disable_switches_without_provider_calls(self):
        calls = []
        for enabled, system_one in ((False, True), (True, False)):
            self.configure_ranker(lambda payload: calls.append(payload), enabled=enabled,
                                  system_one=system_one)
            for path in ("/v1/system-one", "/v1/c3r/rank"):
                status, _ = self.call(path, payload={"state": "test", "candidates": ["A", "B"]})
                self.assertEqual(status, 503)
        self.assertEqual(calls, [])

    def test_model_availability_is_independent_of_system_two(self):
        self.configure_ranker(lambda _: {}, ready=lambda: True)
        status, body = self.call("/v1/models", method="GET")
        self.assertEqual(status, 200)
        self.assertFalse(body["data"][0]["available"])
        self.assertTrue(body["data"][1]["available"])
        self.assertTrue(body["data"][2]["available"])

    def test_metadata_coalesces_health_checks_and_expires_cached_status(self):
        now, calls = [0.0], []
        def probe():
            calls.append(1)
            return len(calls) == 1
        readiness = CachedReadiness(probe, clock=lambda: now[0])
        self.configure_ranker(lambda _: {}, ready=readiness)
        for _ in range(4):
            status, body = self.call("/v1/models", method="GET")
            self.assertEqual(status, 200)
            self.assertTrue(body["data"][1]["available"])
        self.assertEqual(len(calls), 1)
        now[0] = 16
        _, body = self.call("/v1/models", method="GET")
        self.assertFalse(body["data"][1]["available"])
        self.assertEqual(len(calls), 2)

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

    def test_typed_system_one_answers_without_a_governed_action_catalog(self):
        def rank(payload):
            return {"model": "clm-latest", "ranked": [
                {"candidate": option, "prob": score}
                for option, score in zip(payload["answers"], (0.8, 0.2))
            ]}
        self.configure_ranker(rank)
        status, body = self.call("/v1/system-one", payload={
            "model": "c3r-system-one", "state": "An invoice was charged twice",
            "questions": {"department": {"type": "choice", "options": {
                "billing": "Invoices and charges", "technical": "Product bugs"}}},
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["answers"]["department"]["choice"], "billing")
        self.assertEqual(body["answers"]["department"]["scores"]["billing"], 0.8)
        self.assertFalse(body["calibrated"])
        self.assertFalse(body["effect_executed"])

    def test_system_one_boolean_ranking_and_authority_rejection(self):
        def rank(payload):
            return {"model": "clm-latest", "ranked": [
                {"candidate": option, "prob": score}
                for option, score in zip(payload["answers"], (0.25, 0.75))
            ]}
        self.configure_ranker(rank)
        status, body = self.call("/v1/system-one", payload={
            "state": "A duplicate charge", "questions": {"urgent": {"type": "boolean"}},
        })
        self.assertEqual((status, body["answers"]["urgent"]["score"]), (200, 0.75))
        status, body = self.call("/v1/c3r/rank", payload={
            "model": "c3r-verifier", "state": "A duplicate charge",
            "candidates": ["technical", "billing"],
        })
        self.assertEqual((status, body["ranked"][0]["candidate"]), (200, "billing"))
        for extra in ({"authority": "admin"}, {"endpoint": "http://169.254.169.254"}):
            status, _ = self.call("/v1/system-one", payload={
                "state": "test", "candidates": ["A", "B"], **extra})
            self.assertEqual(status, 400)

    def test_system_one_rejects_total_option_overflow_and_provider_failure(self):
        self.configure_ranker(lambda _: {})
        status, _ = self.call("/v1/system-one", payload={
            "state": "test", "candidates": [str(index) for index in range(65)]})
        self.assertEqual(status, 400)
        status, body = self.call("/v1/system-one", payload={
            "state": "test", "candidates": ["A", "B"]})
        self.assertEqual((status, body["error"]), (503, "service_unavailable"))

    def test_responses_returns_text_without_private_reasoning_or_external_effects(self):
        adapter = ProviderAdapter(ProviderConfig(
            "local", ProviderKind.OPENAI_COMPATIBLE, "http://127.0.0.1:8000/v1", "model", None,
        ), transport=lambda *_: TransportResponse(200, {
            "choices": [{"message": {"content": "Check pending and settled charges.",
                                      "reasoning_content": "PRIVATE"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }, 25))
        runtime, _ = controller(deliberative=True)
        factory = ReadOnlyRequestFactory(definitions=(ActionDefinition(
            "DELIBERATE", ActionFamily.DELIBERATE, "compute", "generate",
            RiskClass.READ_ONLY, ((),), ("local",), ("policy",), 0, 0,
        ),), policy=AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}),
                                   frozenset({RiskClass.READ_ONLY})),
        estimate_source=lambda _: {}, remaining_usd=0)
        self.server.responses = ResponsesService(runtime, factory, adapter)
        status, body = self.call("/v1/responses", payload={
            "model": "c3r-core", "input": "Find record", "store": False})
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "response")
        self.assertEqual(body["output"][0]["content"][0]["text"],
                         "Check pending and settled charges.")
        self.assertNotIn("PRIVATE", json.dumps(body))
        self.assertFalse(body["c3r"]["effect_executed"])
        self.assertFalse(body["store"])

    def test_positive_cvoc_generation_still_requires_independent_verification(self):
        calls = []
        adapter = ProviderAdapter(ProviderConfig(
            "local", ProviderKind.OPENAI_COMPATIBLE, "http://127.0.0.1:8000/v1", "model", None,
        ), transport=lambda *_: calls.append(1))
        runtime, _ = controller(deliberative=True, accepted=False)
        factory = ReadOnlyRequestFactory(definitions=(ActionDefinition(
            "DELIBERATE", ActionFamily.DELIBERATE, "compute", "generate",
            RiskClass.READ_ONLY, ((),), ("local",), ("policy",), 0, 0,
        ),), policy=AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}),
                                   frozenset({RiskClass.READ_ONLY})),
        estimate_source=lambda _: {"DELIBERATE:0:local:policy": ValueEstimate(1, 0, 0, 0)},
        remaining_usd=0)
        self.server.responses = ResponsesService(runtime, factory, adapter)
        status, body = self.call("/v1/responses", payload={
            "model": "c3r-core", "input": "Find record"})
        self.assertEqual((status, body["error"]), (503, "service_unavailable"))
        self.assertEqual(calls, [])

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
