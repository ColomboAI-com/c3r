# Directive implementation roadmap

Status labels are evidence-bearing: `implemented` means present and tested in this repository;
`contract` means the stable interface exists but no production backend is shipped; `planned`
means no completion claim is made.

| Workstream | Status | Release evidence required |
| --- | --- | --- |
| State schema gate and unsafe compression | reference | real compression, omission, injection, and rollback evaluations |
| Candidate Compiler and hard masks | partial | typed value constraints, per-argument provenance, dominated-branch pruning, and mandatory placement policy |
| Runtime CVoC | implemented | calibrated value/cost inputs and conservative fallback tests |
| Verifier Firewall | reference | disagreement, bypass, hidden-canary, and failed-check fixtures |
| Trusted Commit Gateway | reference | host-level complete mediation and zero bypasses across consequential suite |
| Adaptive Cost Twin | reference | drift recovery across provider, queue, cache, and thermal shifts |
| Laya System-One adapter | implemented | empirical slice calibration and production shadow evaluation |
| C3R DecisionMix v1 | preview | governed empirical traces and independent provenance audit |
| C3R Decision Laya 421M v0.1 | planned | weights, model card, NOTICE, hashes, calibration, evals |
| Qwen/DeepSeek/frontier envelope | contract | provider cards, time windows, failures, paired baselines |
| OpenAI-compatible MC-1 API | planned | integration tests, trace metadata, no private chain-of-thought |
| MC-1 console and analytics | planned | trace view, calibration health, fallback and abstention metrics |
| Colibri shadow control | planned | build hashes, route traces, native-semantic fallback |
| Evidence-grade benchmark pack | planned | raw traces, scripts, exclusions, confidence intervals |

## Ordered delivery

1. Harden the five authority and selection seams with adversarial and property-based tests.
2. Implement schema-versioned JSON serialization and canonical state hashing.
3. ~~Add a local Laya backend behind the pinned adapter and a license/revision manifest check.~~
4. ~~Build DecisionMix ingestion, provenance validation, and immutable data splits.~~
5. Train and calibrate the C3R-specific checkpoint; publish only after slice gates pass.
6. Add two unrelated deliberative providers and one open-weight runtime.
7. Run shadow-mode end-to-end evaluation with deterministic fallback always available.
8. Add the MC-1 hosted API and console only after authority and calibration release gates pass.
9. Add experimental Colibri control without weakening native token acceptance or MoE routing.
10. Commission independent reproduction and security review before production qualification.
