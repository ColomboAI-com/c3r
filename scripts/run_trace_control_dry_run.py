"""Reproducible local fixture check for independent trace-control review.

This never enables live collection and never claims deployed storage controls.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from c3r.telemetry.governed_store import GovernedTraceStore, SourceGrant
from c3r.telemetry.trace import DecisionTrace


START = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
SOURCE_ID = "c3r_fixture_review"
TASK_ID = "fixture_task_001"


def _trace(run_id: str, **changes: object) -> DecisionTrace:
    fields: dict[str, object] = {
        "run_id": run_id,
        "state_hash": "a" * 64,
        "access_level": "internal",
        "model_provider": "fixture_only",
        "candidate_ids": ("recommend",),
        "probabilities": {"route": (0.8, 0.2)},
        "utility_quantiles": {"selected_lower_bound": 0.3},
        "selected_action_id": "recommend",
        "authority_result": "verified",
        "system_cost": {"latency_ms": 1.0},
        "task_outcome": {"status": "fixture_only"},
        "artifact_refs": (),
    }
    fields.update(changes)
    return DecisionTrace(**fields)


def _rejects(callback: Callable[[], object], expected_reason: str) -> bool:
    try:
        callback()
    except ValueError as error:
        return expected_reason in str(error)
    return False


def run() -> dict[str, object]:
    grant = SourceGrant(
        source_id=SOURCE_ID, owner="c3r_review_fixture",
        task_ids=frozenset({TASK_ID}), rights_attested=True,
    )
    clock = [START]
    with TemporaryDirectory(prefix="c3r-trace-review-") as directory:
        with GovernedTraceStore(
            Path(directory) / "trace.sqlite3", grants=(grant,), clock=lambda: clock[0],
        ) as store:
            first = store.append(_trace("fixture_run_001"), source_id=SOURCE_ID, task_id=TASK_ID)
            checks = {
                "approved_fixture_admitted": len(store.records()) == 1,
                "unapproved_source_rejected": _rejects(lambda: store.append(
                    _trace("fixture_run_002"), source_id="customer_logs", task_id=TASK_ID,
                ), "unapproved source or task"),
                "free_text_rejected": _rejects(lambda: store.append(
                    _trace("fixture_run_003", task_outcome={"status": "email me at a@example.com"}),
                    source_id=SOURCE_ID, task_id=TASK_ID,
                ), "redaction"),
                "artifact_reference_rejected": _rejects(lambda: store.append(
                    _trace("fixture_run_004", artifact_refs=("private_artifact",)),
                    source_id=SOURCE_ID, task_id=TASK_ID,
                ), "redaction"),
            }
            checks["rejected_rows_not_persisted"] = len(store.records()) == 1
            clock[0] = START + timedelta(days=31)
            checks["overdue_purge_blocks_collection"] = _rejects(lambda: store.append(
                _trace("fixture_run_005"), source_id=SOURCE_ID, task_id=TASK_ID,
            ), "retention purge overdue")
            checks["local_expired_row_purged"] = store.purge_expired() == 1
            checks["checkpoint_chain_verifies"] = store.verify() and not store.records()
            second = store.append(
                _trace("fixture_run_006"), source_id=SOURCE_ID, task_id=TASK_ID,
            )
            checks["post_purge_chain_continues"] = (
                second.previous_hash == first.record_hash and store.verify()
            )
    return {
        "evidence_kind": "non_sensitive_local_fixture_dry_run",
        "live_trace_collection_enabled": False,
        "source": SOURCE_ID,
        "task_population": "one C3R-authored synthetic fixture; no customer or product records",
        "checks": checks,
        "all_local_checks_passed": all(checks.values()),
        "not_verified_by_this_run": [
            "deployed encryption and IAM",
            "read/export access audit",
            "daily scheduler and deletion of backups or replicas",
            "independent ledger-head anchor",
            "alert delivery and rollback",
            "live internal-task provenance or outcomes",
        ],
    }


def main() -> None:
    report = run()
    output = REPOSITORY_ROOT / "evidence" / "trace-control-dry-run-v1" / "report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["all_local_checks_passed"]:
        raise SystemExit("local trace-control dry run failed")


if __name__ == "__main__":
    main()

