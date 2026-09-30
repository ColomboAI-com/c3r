"""Stateless, non-authoritative CLM inference, separate from governed actions."""

from __future__ import annotations

from collections.abc import Mapping
import json
import time
from typing import cast

from .clm_adapter import ClmAdapter


def _text(value: object, limit: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("nonempty bounded text required")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError("object required")
    return cast(Mapping[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("array required")
    return cast(list[object], value)


class SystemOneInference:
    """Typed questions and arbitrary strings: scores are NOT success probabilities."""

    def __init__(self, adapter: ClmAdapter) -> None:
        self.adapter = adapter

    def _rank(self, context: str, question: str, options: tuple[str, ...],
              deadline: float) -> tuple[float, ...]:
        try:
            return self.adapter.rank_text(context, question, options, deadline=deadline)
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise RuntimeError("CLM inference unavailable") from error

    def infer(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) - {"model", "state", "questions", "candidates"}:
            raise ValueError("unsupported System-One fields")
        model = payload.get("model", "c3r-system-one")
        if model not in {"c3r-system-one", "c3r-verifier"}:
            raise ValueError("unsupported ranking model")
        state = payload.get("state")
        if isinstance(state, dict):
            context = json.dumps(state, allow_nan=False, ensure_ascii=False, sort_keys=True)
        else:
            context = _text(state, 32768)
        if len(context.encode("utf-8")) > 32768:
            raise ValueError("state too large")
        if ("questions" in payload) == ("candidates" in payload):
            raise ValueError("provide either questions or candidates")
        # One total deadline, not a fresh timeout for each question.
        deadline = time.monotonic() + self.adapter.timeout_seconds
        result: dict[str, object] = {
            "model": model, "provider": "clm", "calibrated": False,
            "effect_executed": False, "scope": "advisory_only",
        }
        if "candidates" in payload:
            raw = _list(payload["candidates"])
            if not 1 <= len(raw) <= 64:
                raise ValueError("candidate count out of bounds")
            options = tuple(_text(option) for option in raw)
            if len(set(options)) != len(options):
                raise ValueError("candidates must be unique")
            scores = self._rank(context, "NEXT_ACTION", options, deadline)
            result["ranked"] = [
                {"candidate": option, "score": score}
                for option, score in sorted(zip(options, scores), key=lambda pair: pair[1],
                                            reverse=True)
            ]
            return result
        questions = _mapping(payload["questions"])
        if not 1 <= len(questions) <= 16:
            raise ValueError("question count out of bounds")
        # Validate ALL questions before making any provider calls.
        prepared: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = []
        for name, value in questions.items():
            name = _text(name, 128)
            value = _mapping(value)
            if set(value) - {"type", "options", "criteria", "instructions"}:
                raise ValueError("invalid question")
            kind = value.get("type")
            instructions = value.get("instructions", name)
            prompt = _text(instructions)
            if "options" in value and "criteria" in value:
                raise ValueError("ambiguous options")
            raw = value.get("options", value.get("criteria"))
            if kind == "choice":
                raw = _mapping(raw)
                if not 2 <= len(raw) <= 64:
                    raise ValueError("choice requires option descriptions")
                keys = tuple(_text(key, 128) for key in raw)
                options = tuple(_text(description) for description in raw.values())
            elif kind in {"boolean", "noul"}:
                keys = ("false", "true")
                if raw is not None:
                    raw = _mapping(raw)
                    if set(raw) != {"false", "true"}:
                        raise ValueError("boolean criteria require false and true")
                    options = tuple(_text(raw[key]) for key in keys)
                else:
                    options = (f"false: No. This is false: {prompt}",
                               f"true: Yes. This is true: {prompt}")
            elif kind == "score":
                raw = _list(raw)
                if not 2 <= len(raw) <= 64:
                    raise ValueError("score requires ordered levels")
                options = tuple(_text(item) for item in raw)
                keys = tuple(str(index) for index in range(len(options)))
            else:
                raise ValueError("unsupported question type")
            if len(set(options)) != len(options) or any(len(option) > 1024 for option in options):
                raise ValueError("options must be unique and bounded")
            prepared.append((name, cast(str, kind), prompt, keys, options))
        if sum(len(options) for _, _, _, _, options in prepared) > 64:
            raise ValueError("total options exceeds budget")
        answers: dict[str, object] = {}
        for name, kind, prompt, keys, options in prepared:
            scores = self._rank(context, prompt, options, deadline)
            answer: dict[str, object] = {"scores": dict(zip(keys, scores))}
            if kind == "choice":
                answer["choice"] = keys[max(range(len(scores)), key=lambda index: scores[index])]
            elif kind in {"boolean", "noul"}:
                answer["score"] = scores[1]
            else:
                answer["score"] = sum(index * score for index, score in enumerate(scores))
            answers[name] = answer
        result["answers"] = answers
        return result
