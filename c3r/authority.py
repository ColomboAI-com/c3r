"""Attestation primitives shared across independent authority boundaries."""

from __future__ import annotations

import hashlib
import hmac


def sign_fields(key: bytes, *fields: str) -> str:
    if len(key) < 16:
        raise ValueError("attestation keys must contain at least 16 bytes")
    payload = "\x00".join(fields).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def attestation_matches(attestation: str, key: bytes, *fields: str) -> bool:
    expected = sign_fields(key, *fields)
    return hmac.compare_digest(attestation, expected)
