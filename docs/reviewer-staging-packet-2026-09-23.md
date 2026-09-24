# C3R private-staging review packet — 2026-09-23

This is a **non-sensitive evidence index** for Swapnil Pawar's independent
review. It contains no trace rows, prompts, credentials, or secrets. The
resources remain private; links to Google Cloud resources require separately
approved, least-privilege access. Do not grant project-wide access merely to
make this packet viewable.

The reviewer accepted the role and reviewed the [fixture-only dry run](../evidence/trace-control-dry-run-v1/report.json).
He found the nine local checks clear, but explicitly did **not** approve live
collection or public publication. The dry run uses one synthetic C3R-authored
fixture. This packet responds to his request for available *deployment*
evidence; it does not turn an unavailable control into a pass.

| Review gate | Available evidence | Still missing for sign-off |
| --- | --- | --- |
| Deployed storage and IAM | [Private retention staging record](../evidence/private-retention-staging-v1/report.json): dedicated empty bucket, uniform bucket-level access, public-access prevention, bucket policy, Cloud Run purger identity, and a generation-guarded marker deletion. [Disabled host record](../evidence/staging-deployment-v1/report.json): dedicated runtime identity, private IAM/TLS ingress and distinct Secret Manager token references. | Independent inspection of effective *inherited* IAM and encryption settings; a reviewed trace writer with least-privilege access. The fixed-disabled service has no bucket write grant. |
| Read/export audit | The private bucket was empty at the staging check; no hosted trace read/export probe has run. | An approved, working audit path with a reviewed access scope and a probe. Cloud Storage Data Access logging is not evidenced for this shared project; enabling it may affect other buckets and costs. |
| 30-day deletion and copies | 28-day bucket lifecycle rule; daily UTC purge schedule; direct and scheduler-triggered empty-bucket runs; one 68-byte marker deleted by the purger identity with a generation precondition; bucket then empty. | First natural daily execution, age-based deletion of an expired trace, and inventory/deletion proof for every independent backup or replica. The model-checkpoint backup is a separate asset and is **not** a trace backup. |
| Independent ledger-head anchoring | [Local dry run](../evidence/trace-control-dry-run-v1/report.json) checks a chain checkpoint; [governed store](../c3r/telemetry/governed_store.py) has local tamper checks. | Host-level append-only or independently controlled anchor, deployed write path, replay and tamper drill. |
| Alerting, rollback, kill switch | [Disabled staging record](../evidence/staging-deployment-v1/report.json): service-specific 5xx policy, owner-reported drill receipt/acknowledgement, and disabled-revision traffic rollback. [Retention record](../evidence/private-retention-staging-v1/report.json): failed-purge policy configured. Repository tests cover fail-closed controller behavior. | Failed-purge alert delivery drill, continuous on-call/response proof, live decision-host rollback and kill-switch drill. Disabled-host rollback is not production rollback. |
| Internal-task provenance and outcomes | [Five-case controlled replay](controlled-replay.md) has C3R-authored fixture states and predeclared rubric matches only. | Attested live C3R-controlled source registry, independently adjudicated outcomes, sealed partitions, governed trace runs, training/calibration and paired safety/canary evidence. |

## Access and decision boundaries

- ColomboAI WorkMail to `swapnil.p@colomboai.com` is the approved coordination
  channel. This packet can be sent there as a link. It is **not** a grant of
  Google Cloud, GitHub, or Hugging Face permissions.
- Before sharing raw cloud logs, object listings beyond this empty bucket, or
  effective IAM exports, the owner must approve an access-controlled route and
  minimize unrelated shared-project details. Never email tokens or private
  traces. If direct read-only cloud access is needed, scope it to C3R resources
  and verify the grants before issuance.
- Swapnil should use the [review record template](reviewer-signoff-template.md)
  to state **approve / needs changes / reject / not reviewed** for each gate,
  identify inspected revisions and limitations, and distinguish collection
  approval from public-release approval.
- Collection, training on live traces, publication, and public service
  promotion stay **off** pending the missing controls and explicit review.
  MC-1 remains outside the standalone scope, not complete under the directive.

