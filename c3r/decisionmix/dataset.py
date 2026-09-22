"""Reproducible DecisionMix v1 dataset builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


SCHEMA_VERSION = "c3r.decisionmix.v1"
SPLITS = ("train", "validation", "test")
IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_id: str
    license: str
    source_partition: str
    generator_revision: str

    def validate(self) -> None:
        if not self.source_id or not self.license:
            raise ValueError("source provenance and license are required")
        if IMMUTABLE_REVISION.fullmatch(self.generator_revision) is None:
            raise ValueError("generator_revision must be an immutable hexadecimal digest")


@dataclass(frozen=True, slots=True)
class DecisionMixRecord:
    record_id: str
    compiled_state: Mapping[str, object]
    questions: Mapping[str, object]
    candidate_actions: tuple[Mapping[str, object], ...]
    baseline_action: Mapping[str, object]
    counterfactual_actions: tuple[Mapping[str, object], ...]
    verifier_outcome: Mapping[str, object]
    task_outcome: Mapping[str, object]
    latency_ms: Mapping[str, float]
    cost_usd: Mapping[str, float]
    risk_class: str
    model_or_provider: str
    decision_family: str
    provenance: SourceProvenance

    def validate(self) -> None:
        if not self.record_id:
            raise ValueError("record_id is required")
        if not self.compiled_state or not self.questions or not self.candidate_actions:
            raise ValueError("state, questions, and candidate actions are required")
        if not self.risk_class or not self.decision_family:
            raise ValueError("risk_class and decision_family are required")
        self.provenance.validate()


def deterministic_split(record_id: str, *, seed: str) -> str:
    digest = hashlib.sha256(f"{seed}\x00{record_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


@dataclass(frozen=True, slots=True)
class DecisionMixManifest:
    schema_version: str
    split_seed: str
    split_counts: dict[str, int]
    file_sha256: dict[str, str]
    licenses: list[str]
    source_ids: list[str]


class DecisionMixBuilder:
    def __init__(self, *, split_seed: str) -> None:
        if not split_seed:
            raise ValueError("split_seed is required")
        self._split_seed = split_seed
        self._records: dict[str, list[DecisionMixRecord]] = {name: [] for name in SPLITS}
        self._record_ids: set[str] = set()

    def add(self, record: DecisionMixRecord) -> str:
        record.validate()
        assigned = deterministic_split(record.record_id, seed=self._split_seed)
        if record.record_id in self._record_ids:
            raise ValueError(f"duplicate record_id: {record.record_id}")
        if record.provenance.source_partition == "benchmark_test" and assigned == "train":
            raise ValueError("benchmark test answers cannot enter the training split")
        self._record_ids.add(record.record_id)
        self._records[assigned].append(record)
        return assigned

    def write(self, output_directory: Path) -> DecisionMixManifest:
        output_directory.mkdir(parents=True, exist_ok=True)
        file_sha256: dict[str, str] = {}
        licenses: set[str] = set()
        source_ids: set[str] = set()
        split_counts: dict[str, int] = {}

        for split in SPLITS:
            records = sorted(self._records[split], key=lambda item: item.record_id)
            rows: list[str] = []
            for record in records:
                licenses.add(record.provenance.license)
                source_ids.add(record.provenance.source_id)
                payload = asdict(record)
                payload["split"] = split
                rows.append(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            content = "\n".join(rows) + ("\n" if rows else "")
            filename = f"{split}.jsonl"
            (output_directory / filename).write_text(content, encoding="utf-8", newline="\n")
            file_sha256[filename] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            split_counts[split] = len(records)

        manifest = DecisionMixManifest(
            schema_version=SCHEMA_VERSION,
            split_seed=self._split_seed,
            split_counts=split_counts,
            file_sha256=file_sha256,
            licenses=sorted(licenses),
            source_ids=sorted(source_ids),
        )
        (output_directory / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest
