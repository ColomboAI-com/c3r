import json
import unittest
from hashlib import sha256
from typing import cast

from c3r.adapters.providers import (
    DeliberationRequest,
    ProviderAdapter,
    ProviderConfig,
    ProviderController,
    ProviderKind,
    TransportResponse,
)
from c3r.state_schema import ActionFamily


class ProviderAdapterTests(unittest.TestCase):
    def test_all_structured_codecs_use_the_supplied_prompt_and_retain_json_contract(self) -> None:
        content = '{"plan":[],"assumptions":[],"uncertainty":[],"candidate_commitments":[],"requested_actions":[]}'
        payloads: list[dict[str, object]] = []
        def transport(
            _url: str, _headers: dict[str, str], payload: dict[str, object],
        ) -> TransportResponse:
            payloads.append(payload)
            body: dict[str, object]
            if "system" in payload:
                body = {"content": [{"text": content}]}
            elif "systemInstruction" in payload:
                body = {"candidates": [{"content": {"parts": [{"text": content}]}}]}
            else:
                body = {"choices": [{"message": {"content": content}}]}
            return TransportResponse(200, body, 1)
        for kind in (ProviderKind.OPENAI_COMPATIBLE, ProviderKind.ANTHROPIC, ProviderKind.GEMINI):
            with self.subTest(kind=kind):
                payloads.clear()
                adapter = ProviderAdapter(ProviderConfig("fixture", kind,
                    "https://provider.example/v1", "model", None), transport=transport)
                adapter.deliberate(DeliberationRequest(state={"goal": "verify"}))
                encoded = json.dumps(payloads[0], ensure_ascii=False)
                self.assertIn("Created by ColomboAI Lab", encoded)
                self.assertIn("Return only one JSON object", encoded)
                if kind == ProviderKind.ANTHROPIC:
                    system = payloads[0]["system"]
                elif kind == ProviderKind.GEMINI:
                    instruction = cast(dict[str, list[dict[str, str]]], payloads[0]["systemInstruction"])
                    system = instruction["parts"][0]["text"]
                else:
                    messages = cast(list[dict[str, str]], payloads[0]["messages"])
                    system = messages[0]["content"]
                assert isinstance(system, str)
                original = system.split("\n\nC3R v0.1 RUNTIME BOUNDARY", 1)[0]
                self.assertEqual(sha256(original.encode()).hexdigest(),
                    "6cae0e283d911b3166f02eb771c0f90a00df86f29211f82832dee0435320b608")

    def test_openai_compatible_adapter_returns_structured_result_and_usage(self) -> None:
        calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

        def transport(
            url: str, headers: dict[str, str], payload: dict[str, object]
        ) -> TransportResponse:
            calls.append((url, headers, payload))
            return TransportResponse(
                status=200,
                body={
                    "choices": [
                        {
                            "message": {
                                "content": '{"plan":["verify"],"assumptions":[],"uncertainty":["provider"],"candidate_commitments":[],"requested_actions":["VERIFY"]}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
                latency_ms=42.0,
            )

        adapter = ProviderAdapter(
            ProviderConfig(
                provider_id="mc1-qwen",
                kind=ProviderKind.OPENAI_COMPATIBLE,
                base_url="https://mc1.example/v1",
                model="qwen-test",
                api_key="secret",
            ),
            transport=transport,
        )

        result = adapter.deliberate(DeliberationRequest(state={"goal": "test"}))

        self.assertEqual(result.deliberation.plan, ("verify",))
        self.assertEqual(result.deliberation.requested_actions, ("VERIFY",))
        self.assertEqual(result.observed_cost["latency_ms"], 42.0)
        self.assertEqual(result.observed_cost["input_tokens"], 10.0)
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertNotIn("secret", repr(result))

    def test_non_https_remote_endpoint_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            ProviderConfig(
                provider_id="unsafe",
                kind=ProviderKind.OPENAI_COMPATIBLE,
                base_url="http://provider.example/v1",
                model="model",
                api_key="secret",
            )

    def test_malformed_provider_payload_fails_closed(self) -> None:
        adapter = ProviderAdapter(
            ProviderConfig(
                provider_id="local-vllm",
                kind=ProviderKind.OPENAI_COMPATIBLE,
                base_url="http://localhost:8000/v1",
                model="qwen",
                api_key=None,
            ),
            transport=lambda _url, _headers, _payload: TransportResponse(
                status=200, body={"choices": []}, latency_ms=1.0
            ),
        )

        with self.assertRaisesRegex(ValueError, "malformed"):
            adapter.deliberate(DeliberationRequest(state={"goal": "test"}))

    def test_provider_timeout_selects_explicit_deterministic_fallback(self) -> None:
        adapter = ProviderAdapter(
            ProviderConfig(
                "offline",
                ProviderKind.OPENAI_COMPATIBLE,
                "http://localhost:8000/v1",
                "model",
                None,
            ),
            transport=lambda _url, _headers, _payload: (_ for _ in ()).throw(
                TimeoutError()
            ),
        )
        result = ProviderController(
            adapter, fallback_action=ActionFamily.STOP
        ).deliberate(DeliberationRequest(state={"goal": "test"}))
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.selected_action, ActionFamily.STOP)
        self.assertEqual(result.failure_reason, "TimeoutError")

    def test_oversized_structured_output_fails_closed(self) -> None:
        content = {
            "plan": ["x"] * 33,
            "assumptions": [],
            "uncertainty": [],
            "candidate_commitments": [],
            "requested_actions": [],
        }
        adapter = ProviderAdapter(
            ProviderConfig(
                "local",
                ProviderKind.OPENAI_COMPATIBLE,
                "http://localhost:8000/v1",
                "model",
                None,
            ),
            transport=lambda _url, _headers, _payload: TransportResponse(
                200,
                {"choices": [{"message": {"content": json.dumps(content)}}]},
                1.0,
            ),
        )
        with self.assertRaisesRegex(ValueError, "oversized"):
            adapter.deliberate(DeliberationRequest(state={"goal": "test"}))


if __name__ == "__main__":
    unittest.main()
