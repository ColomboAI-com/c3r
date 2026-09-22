# Changelog

## 0.1.0 — 2026-09-21

First reviewed C3R vertical slice.

### Added

- policy-first hierarchical candidate compilation across family, subgroup, operation, argument,
  placement, and verifier levels;
- budget and optimistic-utility pruning, bounded family expansion, and progressive widening;
- exact-revision and Apache-2.0 license verification for the upstream Laya fast path;
- typed calibrated decisions with confidence/margin abstention and held-out temperature fitting;
- DecisionMix v1 validated records, deterministic splits, manifests, and a 144-record synthetic
  schema preview;
- action-bound verifier attestations and expiring, single-use approvals backed by an atomic nonce
  store;
- launch-ready documentation, model/dataset cards, and the C3R architecture hero.

### Release boundary

This release contains no fine-tuned C3R weights and makes no empirical model-quality,
calibration, latency, cost, or production-safety claim. See `docs/roadmap.md` for the remaining
release gates.
