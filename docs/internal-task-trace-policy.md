# C3R internal-task trace policy (interim approval)

**Effective:** 2026-09-22. **Approval authority:** the user acting for ColomboAI in
this task. **Accountable interim deployment, release, and data owner:** Wilfried
Kouadio (`@wilkont`), as identified by the active ColomboAI GCP account. On
2026-09-23, Wilfried confirmed that he will serve as the interim human on-call
and rollback operator via his ColomboAI work identity
(`wilfried.k@colomboai.com`). A fixed-disabled private staging drill subsequently
opened a Monitoring incident; Wilfried reported receiving and acknowledging
its email, and revision rollback was exercised. That one drill does not prove
continuous operational coverage or production incident response timing.
Those controls must be verified before governed internal-task traffic.

**Named independent reviewer:** Swapnil Pawar, designated by Wilfried on
2026-09-23 for internal-task labels and any proposed public de-identified rows.
He accepted by work email on 2026-09-23 and reported no conflict of interest.
The non-sensitive fixture-only dry-run link was sent to him from ColomboAI's
work mailbox on 2026-09-23. Independent control review and actual sign-off
remain outstanding. Acceptance does not activate collection or authorize publication.

This policy resolves the owner and data-use choices for the *controlled internal
task population only*. It does **not** authorize production traffic or certify
the service, checkpoint, or dataset. MC-1 remains excluded from the standalone
launch scope, not complete under the original directive.

## Source and permitted uses

- Admit only tasks authored and controlled by ColomboAI expressly for C3R
  qualification, with task ID, authoring owner, creation time, and rights attestation.
  The operator must reject imported customer, employee-personal, product, MC-1,
  Colibri operational, Laya-user, and provider-user records.
- Permit private offline replay, shadow and read-only canary qualification,
  training, held-out calibration, paired evaluation, and independent safety review
  on this controlled source. Do not infer representative field performance from it.
- DeepSeek, Laya, Qwen, or frontier model outputs may be recorded as *model outputs*,
  never as independently verified task truth. Record model/version and generation
  provenance. Independently label outcomes and preserve sealed partitions.

## Data minimization and access

- Persist only pseudonymous run/task IDs, state hashes, controlled candidate IDs,
  route/provider/version, numeric predictions and resource use, authority/verifier
  results, independently adjudicated outcome labels, and approved opaque artifact
  references. Keep prompts, completions, free-text reasoning, personal identifiers,
  credentials, URLs containing tokens, and source documents out of the trace store.
- Redaction and an allowlist schema must reject unexpected fields before a trace is
  written. Review a sample and run leakage tests before enabling each new task source.
- Keep private traces encrypted in ColomboAI-controlled storage with least-privilege
  access limited to the owner and named C3R operators. Audit reads and exports. Do
  not put trace data or access credentials in Git, a public Hugging Face repository,
  or chat.

## Retention, deletion, and publication

- Private row-level redacted traces: **30 days maximum** from collection. The
  operator must run and verify deletion at least daily, including replicas and
  backups. No persistent raw prompt/response capture is authorized. A legal hold
  or longer retention requires a new explicit approval before collection.
- Public release may contain reviewed aggregates, metric definitions, source and
  split manifests, code, hashes, and independently reviewed *de-identified rows*
  derived solely from the approved internal tasks. Remove task-specific private
  content and opaque private artifact references. The owner must approve a
  publication manifest and a second reviewer must sign off on leakage and rights
  checks before publication. Public releases may persist indefinitely and cannot
  reliably be recalled; publishing is a separate, irreversible gate.
- Training and calibration data must have frozen, contamination-checked partitions.
  Keep sealed test rows private until evaluation is finalized; publication afterward
  still requires the preceding row-level review. Report the controlled population
  and limitations in every model/dataset card and launch claim.
- On revocation or policy breach, stop collection immediately, quarantine exports,
  preserve a minimal incident audit record, and delete affected private data under
  the approved retention/deletion procedure.

## Activation gates

This written approval **does not turn collection on**. Before the first live trace,
the owner must record the exact task-source registry, permitted-field schema,
redaction/leakage test results, IAM grants, encrypted storage location, daily
30-day deletion job and backup purge proof, access audit, independent ledger-head
anchor, on-call/rollback contact, and a private staging deployment. A
fixed-disabled private Cloud Run staging host now exists, but it has no durable
trace storage or decision authority. Swapnil Pawar or another subsequently
approved independent reviewer must verify the complete controls against an
intentionally non-sensitive dry run.

On 2026-09-23 a separate empty C3R-only staging bucket and 28-day deletion
backstops were provisioned. The bucket has uniform access, public-access
prevention, no versioning or soft-delete retention, and a 28-day lifecycle rule.
A least-privilege Cloud Run purge job completed both a direct and a scheduler-
triggered empty-bucket run; a daily UTC schedule is configured. See the
[staging retention evidence](../evidence/private-retention-staging-v1/report.json).
A subsequent 68-byte, non-sensitive marker was deleted by the purge identity
with a generation precondition; the live and all-version listings were empty
afterward. The one-off probe job was removed. This does **not** demonstrate
age-based deletion of expired data, independently configured backup deletion,
read/export auditing, independent anchoring, or approved live-source operation.
The disabled C3R service has no access to the bucket. Collection stays off.

The reference [`GovernedTraceStore`](../c3r/telemetry/governed_store.py) enforces an
attested source/task allowlist, a bounded token/numeric trace schema, a local 30-day
purge operation, tamper checks, and a post-purge chain checkpoint in tests. It
deliberately admits no artifact references. The deployment must still schedule and
audit that purge daily, remove expired backup copies, encrypt and restrict the
storage, anchor the ledger head independently, and prove redaction on the exact
internal-task source. Token-shape checks cannot detect private names encoded in
identifier-like strings; source-specific allowlists and human leakage review remain
mandatory. A library method is not evidence these operations ran.
The trusted host may use `BoundGovernedTraceSink` to bind a single approved
source/task to the controller's one-argument trace interface. It must not reuse
one binding for unrelated requests or accept those identifiers from callers.

No public endpoint, public dataset promotion, model-weight release, or broad access
is approved by this policy alone. Each requires its own evidence-matched release
decision. This document is a project governance record, not a legal opinion.
