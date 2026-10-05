"""Executable Laya SDK backend with immutable Hub and license verification."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from typing import Protocol, cast

from ..state_schema import CompiledState
from .question_registry import TypedQuestion


@dataclass(frozen=True, slots=True)
class HubModelMetadata:
    sha: str
    license: str


class LayaAgent(Protocol):
    def predict(
        self,
        state: object,
        questions: object,
    ) -> Mapping[str, object]: ...


MetadataResolver = Callable[[str, str], HubModelMetadata]
SnapshotFetcher = Callable[[str, str], str]
AgentLoader = Callable[[str, str | None], LayaAgent]


class _SnapshotDownloader(Protocol):
    def __call__(
        self, *, repo_id: str, revision: str, allow_patterns: list[str]
    ) -> str: ...


class _SdkAgentLoader(Protocol):
    def __call__(self, path: str, *, device: str | None) -> LayaAgent: ...


def _resolve_metadata(model_id: str, revision: str) -> HubModelMetadata:
    try:
        from huggingface_hub import HfApi
    except ImportError as error:
        raise RuntimeError("install the 'laya' extra to use the live Laya backend") from error
    info = HfApi().model_info(repo_id=model_id, revision=revision)
    card_data = info.card_data
    if card_data is not None and hasattr(card_data, "to_dict"):
        card_data = card_data.to_dict()
    license_name = str((card_data or {}).get("license", ""))
    return HubModelMetadata(sha=str(info.sha), license=license_name)


def _fetch_snapshot(model_id: str, revision: str) -> str:
    try:
        hub = import_module("huggingface_hub")
    except ImportError as error:
        raise RuntimeError("install the 'laya' extra to use the live Laya backend") from error
    download: object = getattr(hub, "snapshot_download", None)
    if not callable(download):
        raise TypeError("installed Hub SDK has no snapshot_download callable")
    # Describe only the documented keyword subset used here, not the SDK's
    # unrelated optional parameters. Callability is checked, not attested.
    snapshot_download = cast(_SnapshotDownloader, download)
    return str(
        snapshot_download(
            repo_id=model_id,
            revision=revision,
            allow_patterns=[
                "rl_agent_config.json",
                "model.safetensors",
                "tokenizer/*",
                "encoder/*",
                "LICENSE*",
                "NOTICE*",
            ],
        )
    )


def _load_agent(path: str, device: str | None) -> LayaAgent:
    try:
        laya = import_module("laya")
    except ImportError as error:
        raise RuntimeError("install the 'laya' extra to use the live Laya backend") from error
    load: object = getattr(laya, "load", None)
    if not callable(load):
        raise TypeError("installed Laya SDK has no load callable")
    # The optional SDK contract is load(path, device=...) -> prediction agent;
    # this annotation does not grant its predictions authority or calibration.
    loader = cast(_SdkAgentLoader, load)
    return loader(path, device=device)


class PinnedLayaBackend:
    """Load one exact Apache-2.0 Laya revision, then expose logits to C3R."""

    def __init__(
        self,
        *,
        model_id: str,
        revision: str,
        device: str | None = None,
        expected_license: str = "apache-2.0",
        metadata_resolver: MetadataResolver = _resolve_metadata,
        snapshot_fetcher: SnapshotFetcher = _fetch_snapshot,
        agent_loader: AgentLoader = _load_agent,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.device = device
        self.expected_license = expected_license
        self._metadata_resolver = metadata_resolver
        self._snapshot_fetcher = snapshot_fetcher
        self._agent_loader = agent_loader
        self._agent: LayaAgent | None = None

    def prepare(self) -> LayaAgent:
        if self._agent is not None:
            return self._agent
        metadata = self._metadata_resolver(self.model_id, self.revision)
        if metadata.sha != self.revision:
            raise ValueError("Hub resolved a different model revision")
        if metadata.license.lower() != self.expected_license.lower():
            raise ValueError(
                f"upstream license mismatch: expected {self.expected_license}, "
                f"found {metadata.license or 'missing'}"
            )
        snapshot = self._snapshot_fetcher(self.model_id, self.revision)
        self._agent = self._agent_loader(snapshot, self.device)
        return self._agent

    def __call__(
        self,
        state: CompiledState,
        questions: tuple[TypedQuestion, ...],
    ) -> Mapping[str, tuple[float, ...]]:
        agent = self.prepare()
        laya_questions = {
            question.id: {
                "type": "choice",
                "instructions": f"Select the calibrated C3R value for {question.id}.",
                "criteria": {
                    option: option.lower().replace("_", " ")
                    for option in question.options
                },
            }
            for question in questions
        }
        result = agent.predict(asdict(state), laya_questions)
        raw_answers = cast(Mapping[str, Mapping[str, object]], result.get("answers", {}))
        logits: dict[str, tuple[float, ...]] = {}
        for question in questions:
            answer = raw_answers.get(question.id, {})
            raw_probabilities = cast(Mapping[str, float], answer.get("probabilities", {}))
            probabilities = tuple(float(raw_probabilities.get(option, 0.0)) for option in question.options)
            if (
                not probabilities
                or not all(math.isfinite(value) and value >= 0 for value in probabilities)
                or sum(probabilities) <= 0
            ):
                continue
            logits[question.id] = tuple(math.log(max(value, 1e-12)) for value in probabilities)
        return logits
