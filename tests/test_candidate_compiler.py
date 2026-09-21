import unittest

from c3r.candidate_compiler import CandidateCompiler
from c3r.state_schema import ActionCandidate, ActionFamily, AuthorityPolicy, RiskClass


class CandidateCompilerTests(unittest.TestCase):
    def test_hard_masks_prohibited_candidates_before_family_caps(self) -> None:
        candidates = (
            ActionCandidate("safe-tool", ActionFamily.TOOL, RiskClass.LOW_REVERSIBLE, 0.4),
            ActionCandidate("blocked-deploy", ActionFamily.TOOL, RiskClass.HIGH_CONSEQUENCE, 1.0),
        )
        policy = AuthorityPolicy(
            allowed_families=frozenset({ActionFamily.TOOL}),
            allowed_risks=frozenset({RiskClass.LOW_REVERSIBLE}),
        )

        result = CandidateCompiler(per_family_cap=1).compile(candidates, policy)

        self.assertEqual([candidate.id for candidate in result.candidates], ["safe-tool"])
        self.assertFalse(result.no_safe_action)
        self.assertEqual(result.masked_ids, ("blocked-deploy",))

    def test_returns_explicit_no_safe_action_when_every_candidate_is_masked(self) -> None:
        candidates = (
            ActionCandidate("deploy", ActionFamily.TOOL, RiskClass.HIGH_CONSEQUENCE, 1.0),
        )
        policy = AuthorityPolicy(
            allowed_families=frozenset({ActionFamily.TOOL}),
            allowed_risks=frozenset({RiskClass.READ_ONLY}),
        )

        result = CandidateCompiler().compile(candidates, policy)

        self.assertEqual(result.candidates, ())
        self.assertTrue(result.no_safe_action)


if __name__ == "__main__":
    unittest.main()

