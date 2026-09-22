# Standalone C3R production launch gate

MC-1 product integration is explicitly out of scope for the **standalone** launch. It
remains in Execution Directive v2 and must not be marked complete there. This document
distinguishes tested code, private operational evidence, and public release evidence.

| Gate | Current evidence | Exit condition |
| --- | --- | --- |
| Hosted decision path | `StandaloneController` composes state compilation, inventory-masked hierarchical candidates, optional calibrated Laya, conservative CVoC, independent verification, commit control, fallback, and redacted hash-chain traces. Provider latency/token usage is recorded without granting authority. A host-owned read-only request factory ignores caller policy, budgets, estimates, and approvals. The loopback HTTP boundary has bearer authentication, a global rate limit, aggregate metrics, a body limit, and recommendation-only enforcement. A transactional SQLite trace sink survives restart and verifies its hash chain. Local integration tests pass. | Calibrated *pre-decision* value/cost estimate source, durable storage placement, independent ledger-head anchoring, TLS gateway, approved hostname, secret rotation, deployment and rollback rehearsal, monitoring/alerts, and live end-to-end traces. No public endpoint exists yet. |
| DeepSeek | Official DeepSeek-V4.1-Flash shards are verified on the GCP GPU host and in a private GCS backup; localhost inference passed a smoke test. A provider bridge passes compiled state to a local OpenAI-compatible adapter and rejects remote transfer of local-only data in tests. | Secure service-to-service route and paired live C3R decision traces. The localhost model is not a public API. |
| Empirical DecisionMix | Published preview has 144 synthetic records, deterministic splits, and hashes. | Approved trace source, consent/license/data-boundary review, deduplication, immutable split, provenance audit, and empirical dataset publication. Never relabel synthetic data empirical. |
| C3R Laya | Pinned upstream integration and calibration-aware abstention are tested. The Hugging Face C3R model page is an integration preview without trained weights. | Train a C3R-derived checkpoint on governed training data, fit calibration on held-out data, preserve sealed test set, and publish weights, raw predictions, manifests, hashes, and reproducible metrics. |
| Behavioral/safety qualification | Unit and small integration fixtures cover several failure boundaries; one published OpenRouter DeepSeek probe and a GPU smoke test exist. | Same-state baselines, task outcomes, latency/cost, calibration, abstention, outages, injection, unsafe actions, bypass, kill switch, confidence intervals, and independent reproduction. |
| Providers and Colibri | Provider protocol contracts and a non-authoritative Colibri shadow adapter exist. Dedicated `c3r-evals` and `c3r-colibri` repositories exist. Single fixed-prompt credentialed OpenRouter smoke probes now cover Qwen3.8 Flash and Claude Sonnet 4.6 in [c3r-evals PR #1](https://github.com/ColomboAI-com/c3r-evals/pull/1). | Multi-case credentialed provider qualification, paired C3R traces, compatible Colibri instrumentation, actual shadow route traces, offline replay, shadow traffic, read-only and reversible canaries. |
| Public release | v0.1 alpha repository, papers, collection, model/dataset previews. | Update all cards and launch copy only after the corresponding evidence passes; perform security and dependency review; publish an evidence-matched standalone release. |

The current code path is a **tested reference boundary**, not a production service.
The SQLite ledger is optional and does not by itself provide independent audit anchoring;
the estimates are not yet empirically calibrated, and the HTTP server requires a
separate TLS/authentication gateway. Keep
effect execution disabled in this service until host-level complete mediation and
canary evidence are independently reviewed.

## Required operator inputs

1. Approved public hostname and DNS/TLS administration path.
2. A governed trace source with explicit data-use, retention, redaction, and publication
   permissions. Controlled internal tasks can seed an evaluation set, but cannot be
   passed off as representative customer traffic.
3. Qwen and frontier provider accounts/model IDs/quotas, supplied through the secrets
   manager rather than committed files.
4. Colibri deployment owner and an instrumented compatible build that emits native
   route, acceptance, latency, and cost traces without exporting private content.
5. A release owner to approve read-only and reversible canary thresholds and aborts.

No public production claim should be made while any exit condition above is unmet.
