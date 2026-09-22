# Execution Directive v2 compliance matrix

This matrix audits the public repository against the directive's Definition of Done. Status is
evidence-bearing:

- **complete** - implemented and backed by repository or published artifact evidence;
- **partial** - a tested slice or contract exists, but the directive's production evidence is
  incomplete;
- **not started** - no implementation evidence is claimed here;
- **blocked externally** - completion requires governed data, compute, credentials, MC-1 code, or
  another repository/runtime not present in this workspace.

The full directive is **not complete**. The current release is the first reviewed vertical slice.

| DoD | Requirement | Status | Evidence / remaining gate |
| --- | --- | --- | --- |
| 22 | C3R runs with Laya as System-One fast path | partial | pinned/license-verified backend, typed calibration and abstention tests; no trained C3R checkpoint or production shadow run |
| 23 | explicit unsafe-to-compress state | complete | versioned State Compiler returns `STATE_UNSAFE_TO_COMPRESS`; omission/provenance tests |
| 24 | hierarchical Candidate Compilation | partial | family/subgroup/operation/argument/placement/verifier slice exists; typed value constraints, per-argument provenance, dominated-branch pruning, mandatory placement policy, and compiler-to-deliberation routing remain |
| 25 | C3R-specific Laya checkpoint exists and is calibrated | blocked externally | no governed empirical corpus, training run, derived weights, or held-out calibration evidence |
| 26 | checkpoint published with attribution | partial | Hugging Face integration-preview repository, license, NOTICE, paper links, and upstream manifest are published; no derived checkpoint exists |
| 27 | empirical DecisionMix v1 published | partial | synthetic 144-record schema preview with deterministic splits and hashes is public; empirical provenance-audited corpus remains |
| 28 | Qwen/DeepSeek/frontier Deliberative Envelope works | partial | structured envelope plus tested OpenAI, Anthropic, Gemini, and OpenAI-compatible Qwen/DeepSeek/vLLM/SGLang/MC-1 request/response contracts exist; live provider qualification and paired end-to-end traces do not |
| 29 | CVoC uses measured runtime cost/risk | partial | conservative reference calculation and fallback tests exist; calibrated production inputs and end-to-end measured traces do not |
| 30 | Verifier Firewall and Commit Gateway independent | partial | independent reference modules, action-bound attestations, atomic expiring approvals, and bypass tests; host-level complete mediation remains |
| 31 | OpenAI-compatible MC-1 API supports System-One | not started | the private `MC-1-platform` repository is identified and accessible, but the request contract, controller service, traces, and production qualification are not implemented |
| 32 | MC-1 Console visualizes both paths | not started | the private `MC-1-platform` console is identified and accessible, but C3R trace ingestion, read models, and UI are not implemented |
| 33 | Colibri adapter runs in shadow mode | partial | non-authoritative recommendations consume the required telemetry shape and retain native fallback in tests; a dedicated `c3r-colibri` repository, compatible build, and live shadow traces remain |
| 34 | calibration metrics reproduce from raw traces | partial | fitter and accuracy/Brier/ECE/MCE/NLL/selective-risk tests plus a tamper-evident trace ledger exist; no empirical raw trace release pack |
| 35 | all controller baselines compared identically | not started | requires immutable empirical test states and pinned serving environments |
| 36 | no non-comparable TypeSafe Jev/RLCD claim | complete | repository and cards make no apples-to-apples Jev claim and preserve the caveat |
| 37 | deterministic fallback survives controller failure | partial | conservative STOP, malformed provider output, Colibri controller failure, and fail-closed prediction behavior are tested; live provider timeout and end-to-end outage qualification remain |
| 38 | global learned-fast-path disable preserves MC-1 | partial | fail-closed reference flags and global-disable tests exist; product-level MC-1 kill-switch integration and rollback evidence remain |
| 39 | README/docs/cards/papers/examples/security/license complete | partial | core documentation, release cards, both papers, security, license, NOTICE, and citation exist; production examples and remaining component cards follow their implementations |

## Directive-wide gaps outside the numbered DoD

- The public `c3r-evals` and `c3r-colibri` repositories are not present.
- Provider protocol contracts are shipped, but credentialed qualification for OpenAI, Anthropic,
  Gemini, Qwen, DeepSeek, vLLM, SGLang, llama.cpp, and MC-1 is not yet evidenced.
- Required empirical tests for multilingual traffic, unseen schemas, provider outages, inventory
  changes, calibration drift, and Colibri fallback are not complete.
- MC-1 website, API, console, admin, docs, pricing, billing, and usage analytics integration is not
  evidenced in this repository.
- No raw trace pack currently supports calibration, latency, cost, task-success, or calls-avoided
  claims.

Directive section 22's required prior-art links and canonical novelty boundary are collected in
[`prior-art.md`](prior-art.md).

## Completion rule

Do not rename a preview artifact to the production identifier or change a row to **complete** until
its evidence is public or independently auditable. The execution sequence and exit gates are in
[`empirical-release-plan.md`](empirical-release-plan.md).
