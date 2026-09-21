"""Attestation primitives shared across independent authority boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json

from .state_schema import ActionCandidate


def action_fingerprint(candidate: ActionCandidate) -> str:
    canonical = {
        "family": candidate.family.value,
        "id": candidate.id,
        "optimistic_utility": candidate.optimistic_utility,
        "payload": sorted(candidate.payload),
        "requested_verifier": candidate.requested_verifier,
        "risk_class": candidate.risk_class.value,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sign_fields(key: bytes, *fields: str) -> str:
    if len(key) < 16:
        raise ValueError("attestation keys must contain at least 16 bytes")
    payload = "\x00".join(fields).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def attestation_matches(attestation: str, key: bytes, *fields: str) -> bool:
    expected = sign_fields(key, *fields)
    return hmac.compare_digest(attestation, expected)
