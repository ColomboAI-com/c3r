import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from c3r.decisionmix import (
    DecisionMixBuilder,
    DecisionMixRecord,
    SourceProvenance,
    deterministic_split,
)


def record(record_id: str, *, source_partition: str = "synthetic") -> DecisionMixRecord:
    return DecisionMixRecord(
        record_id=record_id,
        compiled_state={"goal": "choose compute"},
        questions={"STOP_NOW": {"NO": 0.8, "YES": 0.2}},
        candidate_actions=({"id": "stop", "family": "STOP"},),
        baseline_action={"id": "stop"},
        counterfactual_actions=(),
        verifier_outcome={"accepted": True},
        task_outcome={"completed": True},
        latency_ms={"stop": 0.1},
        cost_usd={"stop": 0.0},
        risk_class="READ_ONLY",
        model_or_provider="deterministic",
        decision_family="stop-continue",
        provenance=SourceProvenance(
            source_id="synthetic-c3r-v1",
            license="Apache-2.0",
            source_partition=source_partition,
            generator_revision="a" * 40,
        ),
    )


class DecisionMixTests(unittest.TestCase):
    def test_deterministic_split_is_stable(self) -> None:
        first = deterministic_split("case-123", seed="c3r-v1")
        second = deterministic_split("case-123", seed="c3r-v1")

        self.assertEqual(first, second)
        self.assertIn(first, {"train", "validation", "test"})

    def test_forbids_benchmark_test_answers_in_training(self) -> None:
        builder = DecisionMixBuilder(split_seed="c3r-v1")
        record_id = next(
            f"leak-{index}"
            for index in range(1000)
            if deterministic_split(f"leak-{index}", seed="c3r-v1") == "train"
        )

        with self.assertRaisesRegex(ValueError, "benchmark test"):
            builder.add(record(record_id, source_partition="benchmark_test"))

    def test_rejects_mutable_generator_revision(self) -> None:
        valid = record("mutable")
        invalid = replace(
            valid,
            provenance=replace(valid.provenance, generator_revision="main" * 10),
        )

        with self.assertRaisesRegex(ValueError, "immutable hexadecimal"):
            DecisionMixBuilder(split_seed="c3r-v1").add(invalid)

    def test_exports_jsonl_and_hash_manifest(self) -> None:
        builder = DecisionMixBuilder(split_seed="c3r-v1")
        builder.add(record("one"))
        builder.add(record("two"))
        builder.add(record("three"))

        with tempfile.TemporaryDirectory() as directory:
            manifest = builder.write(Path(directory))

            self.assertEqual(sum(manifest.split_counts.values()), 3)
            self.assertEqual(set(manifest.file_sha256), {"train.jsonl", "validation.jsonl", "test.jsonl"})
            parsed = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["schema_version"], "c3r.decisionmix.v1")
            self.assertEqual(parsed["licenses"], ["Apache-2.0"])


if __name__ == "__main__":
    unittest.main()
