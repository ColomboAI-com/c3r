"""Request-local transport-attempt counters, not GPU work or billing estimates."""
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

_counts: ContextVar[dict[str, int] | None] = ContextVar("c3r_invocations", default=None)


@contextmanager
def capture_invocations() -> Generator[None]:
    token = _counts.set({"system_one_invocations": 0, "system_two_invocations": 0})
    try:
        yield
    finally:
        _counts.reset(token)


def transport_attempt(system: str) -> None:
    counts = _counts.get()
    if counts is not None:
        counts[system + "_invocations"] += 1


def with_invocations(value: Mapping[str, object]) -> dict[str, object]:
    result = dict(value)
    counts = _counts.get()
    if counts is not None:
        previous = result.get("c3r")
        metadata: dict[str, object] = dict(cast(Mapping[str, object], previous)) if isinstance(previous, dict) else {}
        metadata.update(counts)
        metadata["invocation_basis"] = "adapter_transport_attempts"
        result["c3r"] = metadata
    return result
