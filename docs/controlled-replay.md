# C3R-controlled paired replay v1

The user authorized **C3R-controlled internal tasks only** for the current
training/evaluation source. This five-case pack exercises the local standalone
controller against an identical disabled-controller baseline. It uses C3R-authored
fixture facts, no customer records, no remote model, and no external effect.

Run `python scripts/run_controlled_pairs.py` to produce a redacted observation
JSONL file and manifest under `evidence/controlled-pairs-v1/`. Each case has a
predeclared policy-choice rubric (action ID or stop), so the positive label means
**rubric match**, not real task success. The observations include state and trace
hashes, measured single-run local latency, and zero external-provider spend.
Latency is diagnostic only: this tiny, un-warmed fixture run is not a throughput
or production cost benchmark. Re-running changes timing and therefore the
observation-file hash; the checked-in file is an immutable snapshot.

The paired report and source admission manifest are in the
[`c3r-evals` draft branch](https://github.com/ColomboAI-com/c3r-evals/tree/feat/redacted-serving-probe-pr/sources).
That report checks one baseline and one C3R result per identical state and keeps
the outcome kind explicit. It does **not** exercise Laya, DeepSeek, production
providers, actual tool/task outcomes, Colibri, calibration, canaries, or field
traffic. It cannot qualify the production release or empirical DecisionMix.

Next, extend the C3R-owned task population beyond these regression fixtures,
freeze task/rubric hashes and splits before selecting a checkpoint, collect
independently reviewed outcomes for both arms, and reserve a separate held-out
calibration set. Any production-traffic claim requires a separately authorized
field source and live deployment evidence.
