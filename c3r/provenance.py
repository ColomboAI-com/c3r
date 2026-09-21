"""Helpers for evidence-bearing state fields."""

from __future__ import annotations

import hashlib

from .state_schema import Provenance


def provenance_for(*, source: str, observed_at: str, content: str) -> Provenance:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return Provenance(source=source, observed_at=observed_at, digest=digest)

