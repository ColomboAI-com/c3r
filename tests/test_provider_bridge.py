import json
import unittest

from c3r.adapters.providers import (
    ProviderAdapter,
    ProviderConfig,
    ProviderKind,
    TransportResponse,
)
from c3r.deliberative.provider_bridge import ProviderDeliberator
from c3r.state_compiler import StateCompiler
from c3r.state_schema import RawState


def state(data_boundary: str):
    result = StateCompiler().compile(
        RawState(goal="Plan a read-only check", current_subgoal="Inspect", data_boundary=data_boundary)
    )
    assert result.state is not None
    return result.state


class ProviderBridgeTests(unittest.TestCase):
    def test_local_deepseek_receives_compiled_state_and_returns_plan(self) -> None:
        captured = []

        def transport(_url, _headers, payload):
            captured.append(payload)
            return TransportResponse(
                200,
                {
                    "choices": [{"message": {"content": json.dumps({
                        "plan": ["inspect"],
                        "assumptions": [],
                        "uncertainty": [],
                        "candidate_commitments": [],
                        "requested_actions": [],
                    })}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                },
                12.0,
            )

        adapter = ProviderAdapter(
            ProviderConfig(
                "deepseek-local", ProviderKind.OPENAI_COMPATIBLE,
                "http://127.0.0.1:8000/v1", "deepseek-v4.1-flash", None,
            ),
            transport=transport,
        )
        result = ProviderDeliberator(adapter).deliberate(state("local"))

        self.assertEqual(result.plan, ("inspect",))
        self.assertIn("Plan a read-only check", captured[0]["messages"][1]["content"])

    def test_remote_provider_is_not_called_for_local_data(self) -> None:
        calls = []
        adapter = ProviderAdapter(
            ProviderConfig(
                "frontier", ProviderKind.OPENAI_COMPATIBLE,
                "https://example.invalid/v1", "frontier-model", "test-key",
            ),
            transport=lambda *_: calls.append(True),
        )

        with self.assertRaises(ValueError):
            ProviderDeliberator(adapter).deliberate(state("local"))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
