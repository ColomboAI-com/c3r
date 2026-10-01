# Release policy by scope

## Stateless C3R Core inference

An accountable ColomboAI release owner may authorize a recommendation-only
deployment after the automated and live gates in
[stateless-core-api.md](stateless-core-api.md) pass and the evidence is recorded.
The approval must name the deployed artifact digest, CLM/Qwen revisions,
hostname, rollback revision, on-call contact, and canary result. A green build
alone is insufficient. The release owner may stop or roll back at any time.

This scope does not collect training traces, train C3R-specific weights, publish
DecisionMix rows, or claim empirical calibration. Swapnil Pawar's existing
`CHANGES_REQUESTED` review on PR #2 is preserved; it is not silently converted
to approval. His separate collection/publication review does not automatically
authorize or block this no-collection API. Any legal, security, or organizational
review otherwise required by ColomboAI remains applicable.

## Research collection and empirical publication

The approved C3R-controlled internal-task scope and independent reviewer gates
remain unchanged. Trace collection stays off until that scope's deployed
controls and explicit approval exist. Training, held-out calibration, publication
of rows or weights, and empirical claims each require their own evidence and
review. No production inference deployment implies research approval.
