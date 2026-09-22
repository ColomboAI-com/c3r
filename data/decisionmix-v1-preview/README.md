---
pretty_name: C3R DecisionMix v1 Preview
license: apache-2.0
task_categories:
  - multiple-choice
language:
  - en
tags:
  - decision-making
  - calibration
  - system-one
  - synthetic
---

# C3R DecisionMix v1 Preview

This is a deterministic **synthetic schema preview**, not the empirical DecisionMix v1 training
corpus and not a benchmark result. It exists so researchers can inspect, load, and validate the
record contract before governed traces are collected and released.

Each record includes the compiled state, typed questions, candidate and counterfactual actions,
baseline action, verifier and task outcomes, latency, cost, risk class, provider identity, and
source provenance. Splits are immutable functions of record ID and the seed in `manifest.json`.

## Intended use

- validate ingestion and training pipelines;
- prototype typed-decision and calibration tooling;
- review the data contract and contribute fixtures.

Do not use these synthetic labels to claim real-world task accuracy, calibration, latency, cost,
or safety performance. The empirical release remains gated on source licensing, held-out split
integrity, sufficient calibration support, and publication of raw evaluation evidence.

## Rebuild

```bash
python scripts/build_decisionmix_preview.py
```

All preview content is licensed under Apache-2.0. See the repository `LICENSE` and `NOTICE`.
