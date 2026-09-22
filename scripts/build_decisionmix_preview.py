"""Build the deterministic, synthetic DecisionMix v1 preview artifact."""

from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from c3r.decisionmix import DecisionMixBuilder, DecisionMixRecord, SourceProvenance
from c3r.state_schema import ActionFamily


GENERATOR_REVISION = "0000000000000000000000000000000000000001"
OUTPUT = REPOSITORY_ROOT / "data" / "decisionmix-v1-preview"


def build() -> None:
    builder = DecisionMixBuilder(split_seed="c3r-decisionmix-v1-preview-2026-09-21")
    for family_index, family in enumerate(ActionFamily):
        for example_index in range(16):
            record_id = f"synthetic-{family.value.lower()}-{example_index:03d}"
            budget = round(0.25 + (example_index % 8) * 0.25, 2)
            builder.add(
                DecisionMixRecord(
                    record_id=record_id,
                    compiled_state={
                        "schema_version": "c3r.state.v1",
                        "goal": "Select the safest useful next computation",
                        "current_subgoal": f"Evaluate {family.value}",
                        "budget": {"usd": budget},
                        "data_boundary": "local",
                        "state_compilation_confidence": 1.0,
                    },
                    questions={
                        "ACTION_FAMILY": family.value,
                        "STOP_NOW": "YES" if family is ActionFamily.STOP else "NO",
                    },
                    candidate_actions=(
                        {
                            "id": f"candidate-{family.value.lower()}",
                            "family": family.value,
                            "risk_class": "READ_ONLY",
                        },
                        {"id": "stop", "family": "STOP", "risk_class": "READ_ONLY"},
                    ),
                    baseline_action={"id": "stop", "family": "STOP"},
                    counterfactual_actions=(
                        {"id": "ask-user", "family": "ASK_USER"},
                    ),
                    verifier_outcome={"accepted": True, "fixture": True},
                    task_outcome={
                        "success": True,
                        "synthetic": True,
                        "utility": round(0.5 + family_index * 0.02, 3),
                    },
                    latency_ms={"candidate": float(5 + example_index), "baseline": 1.0},
                    cost_usd={"candidate": budget / 100.0, "baseline": 0.0},
                    risk_class="READ_ONLY",
                    model_or_provider="synthetic-fixture",
                    decision_family=family.value,
                    provenance=SourceProvenance(
                        source_id="c3r-synthetic-preview-generator",
                        license="Apache-2.0",
                        source_partition="synthetic",
                        generator_revision=GENERATOR_REVISION,
                    ),
                )
            )
    manifest = builder.write(OUTPUT)
    print(f"wrote {sum(manifest.split_counts.values())} records to {OUTPUT}")


if __name__ == "__main__":
    build()
