import unittest

from c3r.state_compiler import StateCompiler, StateLimits
from c3r.state_schema import CompilationStatus, RawState


class StateCompilerTests(unittest.TestCase):
    def test_refuses_to_compress_consequential_fact_without_provenance(self) -> None:
        raw = RawState(
            goal="Deploy a verified build",
            current_subgoal="Select the next computation",
            verified_facts=("Production deploy requires approval",),
            consequence="high",
        )

        result = StateCompiler().compile(raw)

        self.assertEqual(result.status, CompilationStatus.STATE_UNSAFE_TO_COMPRESS)
        self.assertIsNone(result.state)
        self.assertIn("verified fact lacks provenance", result.reasons)

    def test_routes_low_confidence_compilation_to_deliberation(self) -> None:
        raw = RawState(
            goal="Resolve an ambiguous request",
            current_subgoal="Determine intent",
            ambiguity=0.8,
        )

        result = StateCompiler(minimum_confidence=0.4).compile(raw)

        self.assertEqual(result.status, CompilationStatus.STATE_UNSAFE_TO_COMPRESS)
        self.assertIn("compilation confidence below threshold", result.reasons)

    def test_refuses_state_that_exceeds_declared_bounds(self) -> None:
        raw = RawState(
            goal="Bound the decision state",
            current_subgoal="Compile facts",
            open_questions=("one", "two"),
        )

        result = StateCompiler(limits=StateLimits(max_items_per_field=1)).compile(raw)

        self.assertEqual(result.status, CompilationStatus.STATE_UNSAFE_TO_COMPRESS)
        self.assertIn("open_questions exceeds item bound", result.reasons)


if __name__ == "__main__":
    unittest.main()
