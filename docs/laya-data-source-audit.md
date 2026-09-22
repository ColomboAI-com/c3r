# Laya and DeepSeek data-source audit (2026-09-22)

Scope: assess the user's proposed Laya project and DeepSeek V4.1 Flash as sources for
C3R DecisionMix and a C3R-specific Laya checkpoint. This is an artifact/provenance
assessment, not a legal opinion or permission to publish third-party or customer records.

## Finding

**Usable as a model base and a bounded synthetic benchmark; not an existing governed
empirical C3R corpus.** The [pinned Laya model revision](https://huggingface.co/convaiinnovations/laya/tree/1c5edc17a7acd8701df6fc341c0d179f1c62c982)
is `1c5edc17a7acd8701df6fc341c0d179f1c62c982`, and its
[model card](https://huggingface.co/convaiinnovations/laya) labels the weights Apache-2.0.
The [Laya SDK](https://github.com/NandhaKishorM/laya/blob/573e5b62696ba441230cd6be71d593331b5d23af/pyproject.toml)
is also Apache-2.0. This supports an attributed C3R fine-tune, subject to preserving
license/notice obligations and checking every incorporated asset. We found no published
set of C3R decisions with independent real-world outcomes in these assets.

| Asset | What it actually contains | Permissible C3R role; limitation |
| --- | --- | --- |
| [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya) | Apache-2.0 English 421M checkpoint and inference interface; C3R pins the exact Hub revision above. | Attributed base weights/System-One baseline. Weights are not examples, human labels, or production traces. The [model card](https://huggingface.co/convaiinnovations/laya) says its base checkpoint is near chance on the typed-decisions benchmark and overconfident before domain temperature fitting; no C3R calibration may be inferred from it. |
| [Laya source/notebook](https://github.com/NandhaKishorM/laya/blob/573e5b62696ba441230cd6be71d593331b5d23af/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) | Reproducible *method* for fine-tuning on `LocalLLaMA/typed-decisions` train split, plus benchmark scripts and [aggregate results](https://github.com/NandhaKishorM/laya/blob/573e5b62696ba441230cd6be71d593331b5d23af/research/README.md). | Training/evaluation reference, not a C3R-trained artifact or governed live traces. The benchmark results belong to Laya on its tasks and cannot be copied as C3R outcomes. |
| [`convaiinnovations/laya-typed-decisions`](https://huggingface.co/convaiinnovations/laya-typed-decisions) | Apache-2.0 specialist fine-tuned on the same four synthetic workflows. Its card explicitly warns of overconfidence and says to refit on held-out domain data. | Comparison baseline only. It is not C3R-specific and its test performance is not evidence of C3R performance. |
| [`LocalLLaMA/typed-decisions`](https://huggingface.co/datasets/LocalLLaMA/typed-decisions) | Apache-2.0 **synthetic**, model-rendered states and teacher-distribution labels: four workflows, 1,200 train and 400 test cases (6,000 and 2,000 decisions). Even the `agent_trace_observability` rows are generated scenarios, not observed production agent traces. The card says the labels measure agreement with a teacher, not correctness. | An attributed, explicitly synthetic training or benchmark slice. Keep its test split sealed, deduplicate against all C3R train/calibration material, and report specialist vs zero-shot comparisons separately. It cannot substantiate an empirical DecisionMix or a real-world task-success claim. |
| [`deepseek-ai/DeepSeek-V4.1-Flash`](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) | Model repository and weights, [MIT-licensed](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/LICENSE); model card describes inference and evaluation, not a downloadable C3R trace dataset. | Self-hosted deliberative baseline or generator of clearly **model-generated** proposals on approved prompts. Its output does not become independently verified truth or an empirical production outcome. Rights in input prompts and publication of resulting records must be checked separately; the model-weight license does not grant rights over third-party source data. |

## Provenance decision for the requested use

1. **Accept** pinned, attributed Laya weights/code as a base; accept the public typed-decisions *train* split as a separately labeled Apache-2.0 synthetic source after recording dataset revision, file hashes, attribution, and transformations. Keep the public test split out of all training and calibration.
2. **Accept only as synthetic/model-generated** DeepSeek outputs from C3R-authored or otherwise approved prompts. Record the exact checkpoint, serving configuration, prompt/template revision, sampling settings, and output hashes. Independently adjudicate proposed actions/outcomes; an LLM cannot supply its own ground truth.
3. **Do not relabel** either source as governed empirical DecisionMix or held-out C3R calibration. To make that claim, collect actual C3R runs on a documented task population with independent verifier/outcome labels, source ownership and data-use rights, consent/privacy review where applicable, redaction, retention/deletion policy, immutable splits, contamination checks, and human/independent provenance review. Public release may need redacted or aggregate records if raw traces include protected data.
4. **Do not infer** permission to ingest Laya users' prompts, DeepSeek API users' prompts, or Colibri/customer logs from a public repository or model license. No such records were identified in the reviewed assets. C3R-controlled internal tasks can create a new, accurately labeled *controlled evaluation trace* corpus, but that is not equivalent to production field evidence or live Colibri shadow qualification.

Release wording until those gates pass: “Laya-derived integration and synthetic/controlled evaluation preview,” not “empirical DecisionMix,” “calibrated C3R-Laya,” or “production-qualified.”
