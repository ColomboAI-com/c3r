# Standalone C3R production launch gate

MC-1 product integration is explicitly out of scope for the **standalone** launch. It
remains in Execution Directive v2 and must not be marked complete there. This document
distinguishes tested code, private operational evidence, and public release evidence.

| Gate | Current evidence | Exit condition |
| --- | --- | --- |
| Hosted decision path | `StandaloneController` composes state compilation, inventory-masked hierarchical candidates, optional calibrated Laya, conservative CVoC, independent verification, commit control, fallback, and redacted hash-chain traces. Provider latency/token usage is recorded without granting authority. A host-owned read-only request factory ignores caller policy, budgets, estimates, and approvals. The loopback HTTP boundary has bearer authentication, a global rate limit, aggregate metrics, a body limit, and recommendation-only enforcement. A separate tested ingress allowlists read-only routes, uses distinct client/backend tokens, and fails closed on backend outage. A fail-closed container entrypoint composes both servers only when a trusted host builder and distinct secrets are supplied; the Docker image has not yet been built. A transactional SQLite trace sink survives restart and verifies its hash chain. Local integration tests pass. | Calibrated *pre-decision* value/cost estimate source, trusted host composition, image build/scan, durable storage placement, independent ledger-head anchoring, TLS/IAM gateway, Google-managed HTTPS service URL, secret rotation, deployment and rollback rehearsal, monitoring/alerts, and live end-to-end traces. No C3R cloud service exists yet. |
| DeepSeek | Official DeepSeek-V4.1-Flash shards are verified on the GCP GPU host and in a private GCS backup; localhost inference passed a smoke test. A provider bridge passes compiled state to a local OpenAI-compatible adapter and rejects remote transfer of local-only data in tests. | Secure service-to-service route and paired live C3R decision traces. The localhost model is not a public API. |
| Empirical DecisionMix | Published preview has 144 synthetic records, deterministic splits, and hashes. A [source audit](laya-data-source-audit.md) confirms that Laya-associated typed-decisions examples are also synthetic, not observed C3R outcomes. | Approved trace source, consent/license/data-boundary review, deduplication, immutable split, provenance audit, and empirical dataset publication. Never relabel synthetic data empirical. |
| C3R Laya | Pinned upstream integration and calibration-aware abstention are tested. The Hugging Face C3R model page is an integration preview without trained weights. | Train a C3R-derived checkpoint on governed training data, fit calibration on held-out data, preserve sealed test set, and publish weights, raw predictions, manifests, hashes, and reproducible metrics. |
| Behavioral/safety qualification | Unit and small integration fixtures cover several failure boundaries; one published OpenRouter DeepSeek probe and a GPU smoke test exist. A [five-case controlled paired replay](controlled-replay.md) checks policy-rubric match on identical local states, not task success. | Representative same-state baselines, independently labeled task outcomes, latency/cost, calibration, abstention, outages, injection, unsafe actions, bypass, kill switch, confidence intervals, and independent reproduction. |
| Providers and Colibri | Provider protocol contracts and a non-authoritative Colibri shadow adapter exist. Dedicated `c3r-evals` and `c3r-colibri` repositories exist. Single fixed-prompt credentialed OpenRouter smoke probes now cover Qwen3.8 Flash and Claude Sonnet 4.6 in [c3r-evals PR #1](https://github.com/ColomboAI-com/c3r-evals/pull/1). | Multi-case credentialed provider qualification, paired C3R traces, compatible Colibri instrumentation, actual shadow route traces, offline replay, shadow traffic, read-only and reversible canaries. |
| Public release | v0.1 alpha repository, papers, collection, model/dataset previews. | Update all cards and launch copy only after the corresponding evidence passes; perform security and dependency review; publish an evidence-matched standalone release. |

The current code path is a **tested reference boundary**, not a production service.
An opt-in governed SQLite trace store now validates internal-task source grants,
rejects unbounded text and private artifact references, and has a tested 30-day local
purge/checkpoint operation. It does not run a daily scheduler, delete backups, or
provide independent audit anchoring. The ordinary SQLite ledger is likewise
optional and does not by itself provide independent audit anchoring;
the estimates are not yet empirically calibrated, and the HTTP server requires a
separate TLS/authentication gateway. Keep
effect execution disabled in this service until host-level complete mediation and
canary evidence are independently reviewed.

## Required operator inputs

1. The selected hostname strategy is a Google-managed Cloud Run HTTPS `run.app` URL.
   It is available only after deployment; private staging must require Cloud Run IAM,
   and public access is a separate, explicitly approved promotion. A custom domain is
   optional, not a launch prerequisite.
2. A governed trace source with explicit data-use, retention, redaction, and publication
   permissions. The [interim internal-task policy](internal-task-trace-policy.md)
   records these choices, but its technical activation controls are not yet verified.
   Controlled internal tasks can seed an evaluation set, but cannot be
   passed off as representative customer traffic. The public Laya checkpoint and
   typed-decisions benchmark, and self-hosted DeepSeek generations, do not satisfy
   this requirement; see the [source audit](laya-data-source-audit.md).
3. Qwen and frontier provider accounts/model IDs/quotas, supplied through the secrets
   manager rather than committed files.
4. Colibri deployment owner and an instrumented compatible build that emits native
   route, acceptance, latency, and cost traces without exporting private content.
5. The user designated ColomboAI's `@wilkont` account as interim accountable
   deployment, release, and data owner in the
   [internal-task policy](internal-task-trace-policy.md). The owner still needs a
   reachable on-call/rollback contact, monitoring, read-only and reversible canary
   thresholds and aborts. An account designation is not proof of operational coverage.

## Internal-task telemetry authorization

The current authorization includes **redacted telemetry from C3R-controlled internal
tasks during private shadow/canary tests**. It does not authorize customer or product
traffic, or Colibri operational logs, for training or evaluation. The
[interim policy](internal-task-trace-policy.md) records the owner, 30-day private
retention, data minimization, and reviewed publication scope. Keep collection
disabled until the policy's source registry, redaction tests, storage, access,
deletion, anchoring, and operator controls are verified. A later public service
must not silently widen the data source. Internal-task evidence can qualify the
controlled task population only; it cannot establish field performance.

No public production claim should be made while any exit condition above is unmet.
The [Cloud Run staging decision](cloud-run-staging.md) records the selected
launch-capable URL strategy and the prerequisites that still block deployment.
