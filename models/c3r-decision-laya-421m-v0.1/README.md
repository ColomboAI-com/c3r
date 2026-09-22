---
license: apache-2.0
base_model: convaiinnovations/laya
library_name: laya
pipeline_tag: text-classification
tags:
  - system-one
  - decision-making
  - calibration
  - c3r
---

# C3R Decision Laya 421M v0.1 — integration preview

This directory is the release scaffold for the C3R System-One fast path. **It does not contain
fine-tuned weights and is not an empirical model release.** The runnable implementation loads the
Apache-2.0 upstream Laya checkpoint only after verifying its exact revision and license, then
requires held-out, slice-specific calibration before making a decision. Missing calibration,
low confidence, or a small top-two margin produces an abstention.

## Pinned base

- Repository: `convaiinnovations/laya`
- Revision: `1c5edc17a7acd8701df6fc341c0d179f1c62c982`
- License: Apache-2.0
- Integration dependency: `laya==0.3.5`

## Research papers

- [System-One Integration Edition v5](https://huggingface.co/ColomboAI/C3R-Decision-Laya-421M-v0.1/blob/main/C3R_System_One_Integration_v5.pdf) - the complete 38-page
  architecture, prior-art boundary, algorithms, falsification protocol, and implementation roadmap.
- [arXiv Preprint v5](https://huggingface.co/ColomboAI/C3R-Decision-Laya-421M-v0.1/blob/main/C3R_ArXiv_Preprint_v5.pdf) - the concise 10-page academic preprint.

The papers describe the target C3R architecture. Their full Definition of Done is broader than
this reviewed implementation slice; the release status below is authoritative for this repository.

## Safety boundary

The model answers fixed typed questions. It does not grant permissions, choose its authoritative
verifier, bypass the Verifier Firewall, or commit external effects. The Trusted Commit Gateway
remains the sole authority boundary.

## Release status

| Artifact | Status |
| --- | --- |
| Revision- and license-verified loader | implemented and tested |
| Typed probability adapter | implemented and tested |
| Slice calibration and abstention | implemented and tested |
| DecisionMix schema preview | published artifact candidate |
| Fine-tuned C3R weights | not trained or published |
| Empirical calibration/evaluation | not yet claimed |

The future checkpoint may be published under this release line only after training manifests,
weight hashes, held-out calibration, selective-risk curves, latency/cost evidence, and failed-run
disclosure pass the documented gates.
