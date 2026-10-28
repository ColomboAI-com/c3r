"""Unmodified official SDKs against the real local C3R HTTP composition.

Fixture inference proves protocol compatibility, not GPU or release qualification.
Install the optional Python SDK and set C3R_JS_SDK_MODULE for the JavaScript run.
"""
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from c3r.adapters.providers import ProviderAdapter, ProviderConfig, ProviderKind
from c3r.api_access import AccessStore
from c3r.candidate_compiler import CandidateCompiler
from c3r.cvoc import RobustCvocController
from c3r.feature_flags import FeatureFlags
from c3r.host_factory import ReadOnlyRequestFactory
from c3r.http_service import C3RHTTPServer
from c3r.ingress_proxy import C3RIngressServer
from c3r.responses import ResponsesService
from c3r.runtime import StandaloneController
from c3r.state_compiler import StateCompiler
from c3r.state_schema import ActionDefinition, ActionFamily, AuthorityPolicy, RiskClass
from c3r.telemetry.ephemeral import EphemeralTraceSink
from c3r.verifier_firewall import VerifierDecision, VerifierFirewall, VerifierPolicy


class GenerationFixture(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if payload.get("stream")
                         else "application/json")
        self.end_headers()
        if payload.get("stream"):
            chunks: tuple[dict[str, object], ...] = (
                {"choices": [{"delta": {"content": "Inspect safely.",
                                          "reasoning_content": "NEVER_PUBLIC"},
                              "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 3}},
            )
            for value in chunks:
                self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({"choices": [{"message": {
                "content": "Inspect safely.", "reasoning_content": "NEVER_PUBLIC"},
                "finish_reason": "stop"}], "usage": {
                    "prompt_tokens": 4, "completion_tokens": 3}}).encode())


class OfficialSDKAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        store = AccessStore(Path(self.scratch.name) / "access.sqlite")
        store.create_project("fixture", "sdk", rpm=100, key_rps=10)
        self.key = store.issue_key("fixture", "sdk", {"responses:write"}).secret
        runtime = StandaloneController(
            flags=FeatureFlags(enabled_requested=True, deliberative_requested=True),
            compiler=StateCompiler(), candidates=CandidateCompiler(), cvoc=RobustCvocController(),
            verifier=VerifierFirewall({"policy": lambda _: VerifierDecision(True, "read-only fixture")},
                VerifierPolicy(default_verifier="policy"), attestation_key=b"sdk-fixture-only-key"),
            ledger=EphemeralTraceSink(),
        )
        factory = ReadOnlyRequestFactory(definitions=(ActionDefinition(
            "DELIBERATE", ActionFamily.DELIBERATE, "compute", "generate",
            RiskClass.READ_ONLY, ((),), ("local",), ("policy",), 0, 0,
        ),), policy=AuthorityPolicy(frozenset({ActionFamily.DELIBERATE}),
                                   frozenset({RiskClass.READ_ONLY})),
            estimate_source=lambda _: {}, remaining_usd=0)
        generation = ThreadingHTTPServer(("127.0.0.1", 0), GenerationFixture)
        provider = ProviderAdapter(ProviderConfig(
            "fixture", ProviderKind.OPENAI_COMPATIBLE,
            f"http://127.0.0.1:{generation.server_port}/v1", "fixture-model", None))
        backend = C3RHTTPServer(runtime=runtime, request_factory=factory, port=0,
            bearer_token="backend-fixture-token-with-over-32-characters",
            responses=ResponsesService(runtime, factory, provider))
        gateway = C3RIngressServer(upstream_port=backend.server_port, host="127.0.0.1", port=0,
            client_token="unused-staging-fixture-token-with-over-32-characters",
            upstream_token=backend.bearer_token, access_store=store)
        self.servers = [generation, backend, gateway]
        for server in self.servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 3)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{gateway.server_port}/v1"

    @unittest.skipUnless(importlib.util.find_spec("openai"), "optional official Python SDK")
    def test_official_python_responses_and_sse(self):
        from openai import OpenAI

        with OpenAI(api_key=self.key, base_url=self.base, max_retries=0, timeout=5) as client:
            response = client.responses.create(model="c3r-core", input="Inspect", store=False)
            self.assertEqual(response.output_text, "Inspect safely.")
            assert response.usage is not None
            self.assertEqual(response.usage.total_tokens, 7)
            self.assertGreater(response.created_at, 0)
            self.assertEqual(response.created_at, int(response.created_at))
            self.assertNotIn("NEVER_PUBLIC", response.model_dump_json())
            events = list(client.responses.create(model="c3r-core", input="Inspect", stream=True))
            self.assertEqual("".join(event.delta for event in events
                                     if event.type == "response.output_text.delta"), "Inspect safely.")
            self.assertEqual(events[-1].type, "response.completed")

    @unittest.skipUnless(os.environ.get("C3R_JS_SDK_MODULE"), "optional official JavaScript SDK")
    def test_official_javascript_responses_and_sse(self):
        env = {**os.environ, "C3R_SDK_TEST_URL": self.base, "C3R_SDK_TEST_KEY": self.key}
        result = subprocess.run(["node", str(Path(__file__).with_name("official_sdk_acceptance.mjs"))],
                                env=env, capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SDK_ACCEPTANCE_PASS")
