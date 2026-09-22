# Prior art and attribution

C3R is a systems synthesis with a distinct controlled object: the next computation across typed
action, retrieval, model invocation, deliberation, verification, placement, and stopping. It does
not claim to invent the primitives below.

## Machine-native decisions and routing

- [SalesRLAgent](https://arxiv.org/abs/2503.23303) - domain-specific reinforcement learning for
  sequential sales-conversion probability prediction; see also its
  [public implementation](https://huggingface.co/DeepMostInnovations/sales-conversion-model-reinf-learning).
- [Confidence-Aware Routing](https://arxiv.org/abs/2510.01237) - pre-generation reliability
  estimation and routing among local generation, retrieval, larger models, and human review.
- [TypeSafe Jev / RLCD](https://typesafe.ai/blog/introducing-system-one-models-and-jev) - typed
  probabilistic System-One decisions, parallel sampling, and Reinforcement Learning for Calibrated
  Decisions. Jev is referenced as a hosted decision system, not an open checkpoint evaluated here.
- [Laya model family](https://huggingface.co/convaiinnovations/laya) and
  [source/SDK](https://github.com/NandhaKishorM/laya) - Apache-2.0 open non-autoregressive
  System-One decision models used as C3R's first open integration substrate.

## Speculative decoding

- [Fast Inference from Transformers via Speculative Decoding](https://arxiv.org/abs/2211.17192).
- [Accelerating Large Language Model Decoding with Speculative Sampling](https://arxiv.org/abs/2302.01318).
- [Calibrated Speculative Decoding](https://arxiv.org/abs/2604.13634).
- [Learning To Draft](https://arxiv.org/abs/2603.01639).

These works optimize draft/verification work while preserving an authoritative target distribution.
C3R treats speculative policies as candidate computations whose end-to-end value must include
verification, memory, latency, and risk.

## Expert prefetch and heterogeneous inference

- [SpecPrefetch](https://arxiv.org/abs/2607.24787) - parameter-efficient expert prefetch for
  sparse MoE models.
- [APEX](https://arxiv.org/abs/2608.11688) - adaptive expert prefetch in constrained edge settings.
- [Colibri](https://github.com/JustVugg/colibri) - heterogeneous inference substrate spanning
  routing history, prefetch, resource retention, and memory hierarchy.

Native token acceptance and MoE routing remain authoritative on lossless C3R paths.

## Canonical novelty boundary

C3R does not claim to invent machine-native probabilistic decisions, RLCD, model routing,
speculative decoding, or expert prefetching. C3R treats these mechanisms as computational
primitives inside a unified risk-bounded value-of-computation controller that decides what
intelligence computation should happen next, how much should be spent, where it should execute,
when it must be verified, and when computation should stop.

No Laya-versus-Jev result is an apples-to-apples comparison unless prompts, sample counts, network
location, serving conditions, and time windows are identical and raw evidence is published.
