# Architecture contract

## Invariants

1. Hard feasibility masks run before learned ranking.
2. Missing or stale evidence widens uncertainty, reduces autonomy, or triggers fallback.
3. State compilation never fabricates facts to fit a context budget.
4. Candidate generation bounds the action space without deciding the winner.
5. CVoC combines calibrated outcome estimates with measured cost, risk, and uncertainty.
6. System-One and deliberative paths share the same authority boundary.
7. The verifier is selected by policy, never by the proposal being judged.
8. All consequential effects pass through the Trusted Commit Gateway.
9. Every optional optimization has a deterministic fallback.
10. Every release claim is reproducible from traces, manifests, hashes, and declared exclusions.

## Decision lifecycle

1. Normalize semantic, provider, runtime, budget, and risk observations.
2. Compile a bounded typed state or emit `STATE_UNSAFE_TO_COMPRESS`.
3. Apply deterministic policy masks.
4. Build and bound candidates by family, subgroup, operation, arguments, placement, and verifier.
5. Obtain calibrated event probabilities from System-One or a structured plan from deliberation.
6. Combine predictions with observed cost distributions in the runtime CVoC calculation.
7. Select only a positive conservative lower bound; otherwise stop, ask, or fall back.
8. Execute the proposal in an adapter.
9. Verify under an independently selected authority.
10. Commit or reject, then append the evidence-grade trace and update the cost twin.

## Non-interference boundary

The learned controller may rank proposals but cannot mutate policy or authenticated policy inputs.
The Verifier Firewall will not honor a proposal's requested verifier as authority. The commit
gateway separately checks verification and consequence-dependent approval before invoking an
effect executor.

