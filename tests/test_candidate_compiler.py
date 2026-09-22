import unittest

from c3r.candidate_compiler import CandidateCompiler
from c3r.state_schema import (
    ActionCandidate,
    ActionDefinition,
    ActionFamily,
    AuthorityPolicy,
    RiskClass,
)


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

    def test_hard_masks_run_before_hierarchical_expansion(self) -> None:
        definitions = (
            ActionDefinition(
                id="unsafe-deploy",
                family=ActionFamily.TOOL,
                subgroup="deployment",
                operation="deploy",
                risk_class=RiskClass.HIGH_CONSEQUENCE,
                argument_variants=((('environment', 'production'),),) * 100,
                placements=("remote",),
                verifier_ids=("release-policy",),
                optimistic_utility=1.0,
                estimated_cost=0.1,
            ),
            ActionDefinition(
                id="safe-read",
                family=ActionFamily.TOOL,
                subgroup="repository",
                operation="read",
                risk_class=RiskClass.READ_ONLY,
                argument_variants=((('path', 'README.md'),),),
                placements=("local",),
                verifier_ids=("read-policy",),
                optimistic_utility=0.5,
                estimated_cost=0.01,
            ),
        )
        policy = AuthorityPolicy(
            allowed_families=frozenset({ActionFamily.TOOL}),
            allowed_risks=frozenset({RiskClass.READ_ONLY}),
        )

        result = CandidateCompiler(per_family_cap=4).compile_hierarchical(
            definitions,
            policy,
            remaining_budget=1.0,
            allowed_verifiers=frozenset({"read-policy", "release-policy"}),
        )

        self.assertEqual(result.masked_ids, ("unsafe-deploy",))
        self.assertEqual(len(result.candidates), 1)
        self.assertIn(("operation", "read"), result.candidates[0].payload)

    def test_progressive_widening_expands_only_close_leaders(self) -> None:
        definitions = tuple(
            ActionDefinition(
                id=name,
                family=ActionFamily.LOCAL_MODEL,
                subgroup="model",
                operation=name,
                risk_class=RiskClass.READ_ONLY,
                argument_variants=((),),
                placements=("local",),
                verifier_ids=("model-policy",),
                optimistic_utility=utility,
                estimated_cost=0.1,
            )
            for name, utility in (("a", 0.90), ("b", 0.88), ("c", 0.40))
        )
        policy = AuthorityPolicy(
            allowed_families=frozenset({ActionFamily.LOCAL_MODEL}),
            allowed_risks=frozenset({RiskClass.READ_ONLY}),
        )

        result = CandidateCompiler(per_family_cap=8).compile_hierarchical(
            definitions,
            policy,
            remaining_budget=1.0,
            allowed_verifiers=frozenset({"model-policy"}),
            initial_width=1,
            maximum_width=3,
            widening_margin=0.05,
        )

        self.assertEqual([item.id.split(":", 1)[0] for item in result.candidates], ["a", "b"])
        self.assertEqual(result.widened_families, (ActionFamily.LOCAL_MODEL,))

    def test_selects_subgroup_before_operation_and_validates_arguments(self) -> None:
        definitions = (
            ActionDefinition(
                id="local-small",
                family=ActionFamily.LOCAL_MODEL,
                subgroup="small",
                operation="infer",
                risk_class=RiskClass.READ_ONLY,
                argument_variants=((('prompt', 'bounded'),),),
                placements=("local",),
                verifier_ids=("model-policy",),
                optimistic_utility=0.7,
                estimated_cost=0.1,
                required_argument_keys=frozenset({"prompt"}),
                allowed_argument_keys=frozenset({"prompt"}),
            ),
            ActionDefinition(
                id="local-large",
                family=ActionFamily.LOCAL_MODEL,
                subgroup="large",
                operation="infer",
                risk_class=RiskClass.READ_ONLY,
                argument_variants=((('unexpected', 'value'),),),
                placements=("unapproved-gpu",),
                verifier_ids=("model-policy",),
                optimistic_utility=0.95,
                estimated_cost=0.1,
                required_argument_keys=frozenset({"prompt"}),
                allowed_argument_keys=frozenset({"prompt"}),
            ),
        )
        policy = AuthorityPolicy(
            allowed_families=frozenset({ActionFamily.LOCAL_MODEL}),
            allowed_risks=frozenset({RiskClass.READ_ONLY}),
        )

        result = CandidateCompiler().compile_hierarchical(
            definitions,
            policy,
            remaining_budget=1.0,
            allowed_verifiers=frozenset({"model-policy"}),
            allowed_placements=frozenset({"local"}),
        )

        self.assertEqual([item.id.split(":", 1)[0] for item in result.candidates], ["local-small"])
        self.assertEqual(result.masked_ids, ("local-large",))


if __name__ == "__main__":
    unittest.main()
