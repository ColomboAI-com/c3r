# Independent C3R release review handoff

**Status:** accepted, not reviewed or signed off. Wilfried Kouadio named Swapnil
Pawar as the independent reviewer on 2026-09-23. Swapnil replied from his
ColomboAI work mailbox on 2026-09-23 accepting the role, reporting no conflict
of interest, and requesting access to a non-sensitive dry run. His reply also
acknowledged that collection and publication remain off. Acceptance does not
verify independence in practice, complete the review, or authorize launch.

## What the reviewer should decide

1. Record the accepted scope and revisit conflicts if the task or reporting
   relationship changes. The release owner cannot sign on the reviewer's behalf.
2. Before collection, verify the [internal-task trace policy](internal-task-trace-policy.md)
   against an intentionally non-sensitive dry run: C3R-authored task provenance,
   the exact source/task allowlist, permitted fields, redaction/leakage checks,
   storage encryption and IAM, read/export audit, daily 30-day deletion including
   backups, independent ledger-head anchoring, and tested kill switch. Inspect
   deployed settings and execution evidence, not only source code or a plan.
3. For empirical release, review frozen train/calibration/test manifests,
   independent outcome labels, leakage and contamination checks, raw predictions,
   calibration fit, confidence intervals, paired baselines, safety failures,
   and the proposed model/dataset card claims. Provider generations alone are
   not ground truth. The five-case controlled replay and synthetic DecisionMix
   preview are not substitutes for these artifacts.
4. Before any public row release, inspect an explicit publication manifest and
   sample of every proposed row class for rights, re-identification, private
   artifact references, and accidental personal or credential content. Approve
   aggregates separately from row-level publication.

## Current evidence, not yet sufficient for sign-off

- [C3R PR #2](https://github.com/ColomboAI-com/c3r/pull/2) is a draft with the
  tested standalone controller and fail-closed service boundary.
- [CI run 64](https://github.com/ColomboAI-com/c3r/actions/runs/35876574369)
  built and smoke-imported the digest-pinned image and produced a Trivy report
  with zero HIGH/CRITICAL findings. This does not cover lower severities or
  deployment controls.
- The [non-sensitive local trace-control dry run](../evidence/trace-control-dry-run-v1/report.json)
  uses one C3R-authored synthetic fixture. Nine local admission, redaction,
  retention-lockout, purge, and chain checks pass. It creates no live trace and
  cannot verify encrypted deployment storage, backup deletion, access auditing,
  independent anchoring, alerting, or task outcomes. Reproduce with
  `python scripts/run_trace_control_dry_run.py`.
- [Launch issue #3](https://github.com/ColomboAI-com/c3r/issues/3) lists the
  unclosed production gates. No C3R Cloud Run service or governed live trace
  collection exists at this writing.

The reviewer should record findings, evidence links and hashes, date, scope,
and a clear **approve / reject / needs changes** decision for each gate. A
qualified public launch additionally requires owner release approval and live
operational evidence. MC-1 is excluded from this standalone scope; it is not
complete under the original directive.

