# C3R v0.1 launch announcement

## Canonical announcement

**C3R v0.1 is live: a control plane for deciding what computation is worth performing next.**

Modern agent systems can invoke tools, retrieval, local models, frontier APIs, and verifiers—but
they still need a disciplined way to decide which computation should happen next, how much it is
worth, and when to stop. C3R treats those choices as typed candidates under one conservative,
risk-bounded value-of-computation policy.

The first reviewed vertical slice includes:

- a bounded hierarchical Candidate Compiler with policy-first masks, budget pruning, candidate
  caps, and progressive widening;
- an exact-revision, license-verified Laya System-One integration that emits typed probabilities,
  requires slice-specific calibration, and abstains on uncertainty or malformed output;
- an independent Verifier Firewall and Trusted Commit Gateway designed to prevent learned
  controllers from granting themselves authority or directly committing consequential effects
  when a conforming host makes the gateway the sole effect path;
- a deterministic DecisionMix v1 schema pipeline with immutable splits, provenance validation,
  SHA-256 manifests, and a 144-record synthetic preview;
- evidence-bearing release manifests that say exactly what is—and is not—trained, calibrated, or
  production-qualified.

Explore the release:

- Code and documentation: https://github.com/ColomboAI-com/c3r
- GitHub v0.1.0 pre-release: https://github.com/ColomboAI-com/c3r/releases/tag/v0.1.0
- C3R Decision Laya integration preview: https://huggingface.co/ColomboAI/C3R-Decision-Laya-421M-v0.1
- DecisionMix v1 synthetic preview: https://huggingface.co/datasets/ColomboAI/C3R-DecisionMix-v1-preview

This is deliberately an alpha. It does **not** contain fine-tuned C3R weights or empirical
calibration results. Production provider adapters, the empirical DecisionMix corpus, MC-1
integration, Colibri shadow control, and full directive qualification remain measured release
gates. We are publishing the interfaces, safety boundaries, data contract, and evidence gaps now
so the next milestone can be reproduced—not merely announced.

C3R builds on Laya by Convai Innovations as the first open System-One decision primitive while
keeping the broader architecture model-agnostic. C3R does not claim to invent probabilistic
decisions, RLCD, routing, speculative decoding, or expert prefetch. It places these primitives
inside a unified controller for value, cost, risk, verification, placement, and stopping.

We welcome review of the architecture, adversarial tests, dataset contract, calibration protocol,
and empirical release plan. The explicit prior-art and novelty boundary is documented at
https://github.com/ColomboAI-com/c3r/blob/main/docs/prior-art.md.

## LinkedIn version

Today ColomboAI is releasing **C3R v0.1**, the first reviewed vertical slice of Robust Calibrated
Compute Control.

C3R asks a different systems question: *What computation is worth performing next?* Tools,
retrieval, local and frontier models, verification, placement, and stopping become typed candidates
under a conservative value-of-computation controller.

The release includes hierarchical candidate compilation, a revision-verified Laya fast path with
calibration-gated abstention, independent verification and commit controls, and a reproducible
DecisionMix schema preview.

We are also publishing the release boundary. These are runnable reference components—not trained
C3R weights or production calibration claims. The empirical corpus, model specialization,
provider envelope, MC-1 integration, Colibri shadow control, and paired benchmarks remain explicit
gates.

Code: https://github.com/ColomboAI-com/c3r

Model preview: https://huggingface.co/ColomboAI/C3R-Decision-Laya-421M-v0.1

Dataset preview: https://huggingface.co/datasets/ColomboAI/C3R-DecisionMix-v1-preview

#AI #MachineLearning #AIInfrastructure #Agents #OpenSource #Calibration #AISafety

## X thread

**1/6** C3R v0.1 is live. It is a control plane for deciding what computation is worth performing
next—not another wrapper that calls an LLM before every transition.

**2/6** C3R treats tools, retrieval, local/frontier models, verification, placement, and stopping
as typed candidates under conservative value-of-computation, risk, and uncertainty.

**3/6** The first reviewed slice ships bounded hierarchical candidate compilation plus a pinned,
license-verified Laya fast path with calibration-gated, fail-closed abstention.

**4/6** In a conforming host, learned controllers receive no commit authority: the independent
Verifier Firewall and Trusted Commit Gateway are the sole path for consequential effects.

**5/6** We also published a deterministic DecisionMix schema preview: 144 explicitly synthetic
records, immutable splits, source licensing, and SHA-256 manifests. No empirical model claim is
hidden inside it.

**6/6** Code: https://github.com/ColomboAI-com/c3r

Model: https://huggingface.co/ColomboAI/C3R-Decision-Laya-421M-v0.1

Data: https://huggingface.co/datasets/ColomboAI/C3R-DecisionMix-v1-preview

## Hacker News title and submission text

**Title:** C3R: Open control plane for calibrated compute selection in AI agents

**Text:** We are releasing the first reviewed C3R vertical slice. It compiles bounded candidate
computations, uses a pinned Laya System-One path for typed decisions, combines predictions with
runtime cost/risk through conservative CVoC, and keeps verification and external commit authority
independent. The repository also includes a deterministic synthetic DecisionMix schema preview.
The model page is intentionally an integration preview: there are no C3R-derived weights or
empirical calibration claims yet. We would especially value review of the authority boundary,
hierarchical candidate interface, calibration gates, and empirical-release plan.

## Publication checklist

- Use the canonical links above and the `v0.1.0` release label.
- Call the model artifact an **integration preview**, not a trained checkpoint.
- Call DecisionMix an **explicitly synthetic schema preview**, not empirical training data.
- Do not quote latency, cost, calibration, or task-success numbers until raw traces are public.
- Preserve Laya/Convai Innovations attribution and Apache-2.0 licensing.
- Link the directive compliance matrix when discussing roadmap completeness.

The platform variants repeat the canonical URLs intentionally so each block remains independently
copyable; update all variants together if an artifact is renamed.
