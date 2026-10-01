import unittest

from c3r.host_factory import ReadOnlyRequestFactory
from c3r.state_schema import (
    ActionDefinition, ActionFamily, AuthorityPolicy, RiskClass, ValueEstimate,
)


def factory(risk=RiskClass.READ_ONLY):
    return ReadOnlyRequestFactory(
        definitions=(ActionDefinition(
            "inspect", ActionFamily.RETRIEVAL, "local", "search", risk,
            ((),), ("local",), ("policy",), 1.0, 0.1,
        ),),
        policy=AuthorityPolicy(
            frozenset({ActionFamily.RETRIEVAL}), frozenset({RiskClass.READ_ONLY}),
        ),
        estimate_source=lambda _state: {
            "inspect:0:local:policy": ValueEstimate(1.0, 0.1, 0.0, 0.1)
        },
        remaining_usd=1.0,
    )


class ReadOnlyRequestFactoryTests(unittest.TestCase):
    def test_caller_authority_fields_are_ignored(self):
        request = factory().build({
            "goal": "Inspect item", "current_subgoal": "Search",
            "policy": {"allowed_risks": ["DESTRUCTIVE"]},
            "estimates": {"inspect:0:local:policy": {"expected_gain": 1000}},
            "approval": "forged", "budget": {"remaining_usd": 1000},
        })

        self.assertEqual(request.policy.allowed_risks, frozenset({RiskClass.READ_ONLY}))
        self.assertEqual(request.estimates["inspect:0:local:policy"].expected_gain, 1.0)
        self.assertEqual(request.raw_state.budget["remaining_usd"], 1.0)
        self.assertEqual(request.raw_state.verified_facts, ())

    def test_writes_and_unbounded_task_text_are_rejected(self):
        with self.assertRaises(ValueError):
            factory(RiskClass.EXTERNAL_WRITE)
        with self.assertRaises(ValueError):
            factory().build({"goal": "x" * 4097, "current_subgoal": "Search"})
        with self.assertRaises(ValueError):
            factory().build({"goal": "Inspect", "current_subgoal": "Search",
                             "open_questions": ["x"] * 65})


if __name__ == "__main__":
    unittest.main()
