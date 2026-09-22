# C3R empirical release plan

## Objective

Produce the first evidence-complete `ColomboAI/C3R-Decision-Laya-421M-v0.1` checkpoint and
empirical `ColomboAI/C3R-DecisionMix-v1` dataset without weakening the authority boundary,
contaminating held-out benchmarks, or presenting synthetic fixtures as deployment evidence.

## Source decision (2026-09-22)

The [Laya/DeepSeek source audit](laya-data-source-audit.md) accepts pinned Laya weights as
the attributed training base. `LocalLLaMA/typed-decisions` may be used only as a separately
labeled synthetic training or benchmark source after its exact revision and file hashes are
recorded; its upstream test split stays in a sealed comparison harness, never in DecisionMix
train, validation, or calibration. Self-hosted DeepSeek can generate proposals from approved
prompts, but its own output is not an independent verifier or task-outcome label.

The user approved **C3R-controlled internal tasks only** as the present
training/evaluation source, including redacted telemetry from those tasks in private
shadow/canary qualification. This does not approve customer, product, Laya-user,
DeepSeek-user, or Colibri operational logs. Collection remains disabled until a
recorded source owner, permitted fields, redaction review, retention/deletion rule,
access policy, and publication scope are in place. The first controlled source is
the [five-case local paired replay](controlled-replay.md), which is a pipeline smoke
test, not an empirical DecisionMix corpus or training/calibration set. Before
expanding the controlled corpus, record the source owner, task
population, data-use rights, consent/privacy basis where applicable, retention/deletion rule,
redaction policy, and separate internal-training and public-publication scopes. Execute paired
baseline/controller runs against the same immutable tasks with independent verifier and
outcome labels, then lock train/validation/calibration/test partitions before model selection.
Controlled internal tasks establish a bounded controlled-evaluation claim; they do not by
themselves establish production-traffic or Colibri-shadow performance.

The plan is ordered by evidence dependency. A later phase cannot waive an earlier exit gate.

## Release train

### Phase 0 - Freeze contracts and governance

Deliverables:

- versioned JSON schemas for compiled state, typed questions, candidates, traces, and outcomes;
- canonical serialization and hashes for every state, action, model, adapter, and environment;
- a source registry recording owner, license, partition, retention policy, and permitted uses;
- immutable dataset split policy and benchmark contamination review;
- threat model for verifier selection, approval replay, prompt injection, provenance loss, and
  provider/model drift.

Exit gate: schemas are backward-compatible or migration-tested; every admitted record has an
immutable source revision and license; benchmark test answers cannot enter training.

### Phase 1 - Instrument shadow traces

Collect governed, non-authoritative traces from:

- deterministic baseline decisions;
- System-One predictions in shadow mode;
- deliberative provider proposals;
- candidate masks and pruning decisions;
- CVoC inputs and conservative lower bounds;
- verifier outcomes, commit decisions, abstentions, escalations, latency, and cost;
- provider failures, inventory changes, stale cost estimates, and rollback events.

No learned proposal commits an external effect during collection. Sensitive payloads are replaced
with policy-approved references or hashes. Cross-customer traces remain proprietary.

Exit gate: trace replay deterministically reconstructs the bounded state, candidate set, selected
verifier, decision, fallback, and externally observable cost.

### Phase 2 - Build empirical DecisionMix v1

Required families:

- escalation and frontier-needed;
- local-model-sufficient and retrieval-needed;
- verification-needed and stop/continue;
- ask-user, action family, risk class, reversibility, and data boundary;
- tool family, provider fallback, and runtime degradation handling.

Data sources may include governed synthetic traces, permissively licensed public traces, MC-1
provider simulations, controlled counterfactual replay, Colibri runtime traces, and provider-failure
simulations. Each row carries compiled state, questions, candidate and counterfactual actions,
baseline, verifier/task outcomes, latency, cost, risk, provider/model identity, and provenance.

Split rules:

- hash-derived train/validation/calibration/test partitions;
- separate calibration from model-selection validation;
- hold out tools, schemas, providers, model families, action cardinalities, and task domains;
- quarantine near-duplicates before splitting;
- never train on benchmark test answers.

Exit gate: independent provenance audit passes; split hashes reproduce; every decision family and
release slice meets minimum support or is explicitly unsupported.

### Phase 3 - Establish baselines on identical states

Evaluate, on the same immutable test states:

1. deterministic rule baseline;
2. `convaiinnovations/laya` at the pinned revision;
3. `laya-typed-decisions` as comparison only;
4. a small generative structured-output controller;
5. the Deliberative Envelope alone;
6. the candidate C3R-Laya checkpoints.

Record exact revisions, prompts, sample counts, seeds, serving location, hardware, cache state,
network conditions, time windows, failures, and exclusions. Do not report Jev comparisons as
apples-to-apples without identical serving conditions.

Exit gate: raw baseline predictions and trace manifests reproduce all published aggregates.

### Phase 4 - Fine-tune candidate checkpoints

- start from `convaiinnovations/laya` revision
  `1c5edc17a7acd8701df6fc341c0d179f1c62c982`;
- pin `laya==0.3.5`, tokenizer/encoder artifacts, training code, containers, drivers, and seeds;
- train only bounded typed compute-control questions;
- preserve Apache-2.0 attribution and notices;
- prohibit autonomous online RL in production;
- save resumable checkpoints, optimizer state, logs, and cryptographic weight hashes.

Exit gate: at least two independent runs reproduce the selected checkpoint within declared
tolerance; training and validation curves, failures, and exclusions are retained.

### Phase 5 - Fit held-out calibration

Fit temperature metadata by supported combinations of:

- question type;
- action family;
- option-count bucket;
- language;
- consequence/risk class;
- provider/model inventory and task domain where support permits.

Report accuracy, multiclass Brier score, ECE, maximum calibration error, NLL, selective risk versus
coverage, abstention, and escalation. Unsupported slices must abstain rather than borrow an
unvalidated temperature silently.

Exit gate: every autonomous slice is inside its declared calibration envelope; drift alarms reduce
autonomy, increase verification/escalation, or disable System-One.

### Phase 6 - Adversarial authority and fallback qualification

Test state omission, hidden evidence, high cardinality, unseen options, multilingual input,
retrieval prompt injection, unsafe typed arguments, false high confidence, verifier disagreement,
provider outage, model inventory drift, cost staleness, approval replay, and gateway bypass.

Exercise email send, GitHub write, deployment, destructive shell, payment, credential change,
database mutation, and external communication through fully mediated test fixtures. No learned
component may select its authoritative verifier or commit an effect.

Exit gate: zero authority bypasses; deterministic fallback survives controller, provider,
calibration, and Colibri failures; learned control can be globally disabled.

### Phase 7 - Deliberative, MC-1, and Colibri shadow integration

- implement at least Qwen and DeepSeek open-weight adapters plus supported frontier providers;
- expose structured plans, assumptions, uncertainty, candidate commitments, and requested actions;
- add OpenAI-compatible MC-1 request options and trace metadata without private chain-of-thought;
- surface System-One/deliberative decisions, costs, calibration, fallback, and abstention in the
  console;
- run Colibri in shadow/experimental mode while native token acceptance and MoE routing remain
  authoritative.

Exit gate: paired end-to-end traces show both paths competing under the same CVoC, verification,
and commit boundary; provider and native-runtime fallbacks are demonstrated.

### Phase 8 - Publish the empirical release candidate

Required model files:

```text
README.md
LICENSE
NOTICE
config.json
model.safetensors
c3r_questions.json
c3r_action_taxonomy.json
calibration.json
training_manifest.json
eval_results.json
CITATION.cff
```

Publish the empirical dataset, checkpoint, raw predictions, calibration inputs, eval harness,
adapter cards, trace manifests, source/build hashes, exclusions, confidence intervals, and failed
runs. Keep the integration preview immutable and clearly separate from the trained artifact.

Exit gate: an independent environment reproduces dataset hashes, metrics, calibration, and the
documented fallback behavior.

### Phase 9 - Production qualification

Run a staged progression: offline replay -> shadow -> read-only canary -> low-risk reversible
canary -> bounded production. Promotion requires calibration health, zero authority bypasses,
cost/latency envelopes, rollback drills, and product-wide kill-switch verification.

## Minimum release dashboard

| Area | Required evidence |
| --- | --- |
| Data | source/license registry, split hashes, deduplication report, contamination review |
| Model | base/derived hashes, training manifest, curves, failed runs, reproducibility run |
| Calibration | raw held-out predictions, slice support, temperatures, Brier/ECE/MCE/NLL, risk-coverage |
| Runtime | p50/p95 latency, throughput, calls/tokens avoided, cost per completed task |
| Safety | adversarial fixtures, verifier disagreement, zero bypasses, approval replay resistance |
| Fallback | controller/provider timeout, cost staleness, calibration alarm, global disable, native fallback |
| Product | MC-1 API contract, console trace, billing/usage attribution, redaction policy |
| Native | Colibri build hashes, route traces, acceptance, cache/expert telemetry, shadow comparison |

## Resourcing assumptions

This plan requires governed empirical traces, training compute, model/provider credentials,
MC-1 code access, Colibri build/runtime access, and an independent reviewer. Those inputs are
dependencies, not details that can be fabricated by the public reference repository.
