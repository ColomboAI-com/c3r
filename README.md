# C3R

**Robust Calibrated Compute Control for Machine-Native Intelligence**

C3R is an open-core control plane for deciding which computation is worth performing next.
It treats typed decisions, tools, retrieval, local and frontier models, verification, runtime
placement, and stopping as candidates under one conservative value-of-computation policy.

This repository is the public reference implementation described in the C3R System-One
Integration paper and execution directive. It is an early implementation, not yet the trained
or production-qualified release described by the complete roadmap.

## Architectural boundary

```text
application / agent
        |
versioned state fabric -> state compiler -> candidate compiler + hard masks
                                           |                     |
                                      System-One             deliberative
                                       fast path               envelope
                                           +----------+----------+
                                                      |
                                                robust CVoC
                                                      |
                                             verifier firewall
                                                      |
                                          trusted commit gateway
                                                      |
                                          outcome, trace, cost twin
```

The controller proposes work. It does not grant itself authority. A conforming host integration
must completely mediate effects so a learned component cannot:

- bypass permissions, approvals, data-boundary policy, or provider allowlists;
- select or rewrite its authoritative verifier;
- turn a failed verification into success;
- directly commit an external side effect;
- change target-model semantics on a declared lossless path.

## Implemented in v0.1

- Versioned, bounded state-schema gate and an explicit `STATE_UNSAFE_TO_COMPRESS` outcome.
- Provenance requirement for facts admitted to the bounded decision state.
- Policy-first candidate filtering with per-family caps and `no_safe_action`.
- Progressive widening utility for statistically close candidates.
- Conservative CVoC lower-bound selection and deterministic `STOP` fallback.
- Verifier Firewall reference with policy-selected, action-bound attestations.
- Trusted Commit Gateway reference for independently verified and approved effects.
- Dual-timescale Adaptive Cost Twin reference estimator with staleness detection.
- Fixed typed-question registry for bounded System-One decisions.
- Revision-pinned, dependency-injected Laya adapter contract.
- Calibration and abstention primitives.
- Deliberative Envelope, provider/runtime adapter, and evidence-grade trace contracts.

The current Candidate Compiler is the safe first stage of the required hierarchy. Subgroup,
operation, argument, placement, verifier attachment, branch-and-bound, and integrated progressive
widening remain roadmap work and are not claimed as implemented.

## Deliberately not claimed yet

The following directive milestones require data, compute, service credentials, or integrations
that are not present in this initial repository commit:

- a trained `ColomboAI/C3R-Decision-Laya-421M-v0.1` checkpoint;
- a published `ColomboAI/C3R-DecisionMix-v1` dataset;
- measured calibration, latency, cost, or task-success results;
- production OpenAI, Anthropic, Gemini, Qwen, DeepSeek, vLLM, SGLang, or Colibri adapters;
- MC-1 API, console, billing, and fleet-wide cost-twin integration;
- any apples-to-apples Jev comparison.

Those remain release gates. See [the roadmap](docs/roadmap.md).

## Quick start

The reference core has no runtime dependencies outside Python 3.11+.

```bash
python -m unittest discover -s tests -v
```

Minimal conservative selection:

```python
from c3r.cvoc import RobustCvocController
from c3r.state_schema import ActionCandidate, ActionFamily, RiskClass, ValueEstimate

candidate = ActionCandidate(
    id="retrieve",
    family=ActionFamily.RETRIEVAL,
    risk_class=RiskClass.READ_ONLY,
    optimistic_utility=0.7,
)
decision = RobustCvocController().select(
    (candidate,),
    {
        "retrieve": ValueEstimate(
            expected_gain=0.8,
            total_cost=0.2,
            risk_penalty=0.0,
            uncertainty=0.1,
        )
    },
)
```

If the conservative lower bound is not positive, `decision.selected` is `None` and the fallback
is `STOP`.

## System-One and deliberative paths

The initial Laya integration is a contract, not a hidden download. A production application must
provide a backend, pin an exact Hugging Face revision, verify the upstream license, and supply
slice-specific calibration metadata. `laya-typed-decisions` is permitted only as a comparison
baseline, not as the primary production base.

System-One receives bounded typed questions and returns probabilities. It never returns prose and
never decides permissions, price, or commitment. Unsafe compilation, high abstention, new schemas,
ambiguous intent, creative work, long-horizon planning, or high consequence route to a structured
Deliberative Envelope.

## Feature flags

Production integrations must preserve these independently controllable flags:

```text
C3R_ENABLED
C3R_SYSTEM_ONE
C3R_DELIBERATIVE
C3R_ROUTING
C3R_SPECULATION
C3R_MOE_CONTROL
C3R_ONLINE_LEARNING=false
```

The learned fast path must be globally disableable without breaking the host system's normal
operation.

## Evaluation discipline

Scenario values are not empirical results. Release claims require raw traces, exact revisions,
manifests, calibration slices, paired baselines, failed-run disclosure, and independent
reproduction. Required metrics include accuracy, Brier score, ECE, maximum calibration error,
negative log likelihood, selective risk versus coverage, abstention, escalation, p50/p95 latency,
throughput, model calls avoided, and cost per completed task.

## Upstream attribution

The planned derived controller is based on [Laya by Convai Innovations](https://huggingface.co/convaiinnovations/laya),
an Apache-2.0 open System-One decision model. C3R is a broader runtime architecture and is not a
fork or rebranding of Laya. See [NOTICE](NOTICE) for the canonical attribution boundary.

C3R does not claim to invent machine-native probabilistic decisions, RLCD, model routing,
speculative decoding, or expert prefetching. It treats these mechanisms as computational
primitives inside a unified risk-bounded value-of-computation controller.

## Security

Do not report vulnerabilities in a public issue. Follow [SECURITY.md](SECURITY.md). The authority
boundary is security-critical: production deployments must ensure every consequential effect is
completely mediated by an independently configured commit gateway.

## License

Licensed under Apache License 2.0. See [LICENSE](LICENSE).
