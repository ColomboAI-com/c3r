"""Portable signed ledger-head envelopes; deployment must supply independent signing.

This module never holds a private key. A production signer and anchor destination
must be controlled separately from the trace writer (for example, Cloud KMS and
an access-separated evidence project). Local success is not deployment proof.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable


_HASH = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class LedgerHead:
    sequence: int
    record_hash: str
    captured_at: str
    policy_version: str

    def __post_init__(self) -> None:
        if self.sequence < 0 or not _HASH.fullmatch(self.record_hash):
            raise ValueError("invalid ledger head")
        if not self.policy_version or len(self.policy_version) > 64:
            raise ValueError("invalid policy version")
        try:
            instant = datetime.fromisoformat(self.captured_at)
        except ValueError as error:
            raise ValueError("invalid capture timestamp") from error
        if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
            raise ValueError("capture timestamp must be UTC")

    def payload(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SignedLedgerAnchor:
    head: LedgerHead
    key_id: str
    signature_hex: str


def capture_head(
    *, sequence: int, record_hash: str, policy_version: str,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> LedgerHead:
    return LedgerHead(sequence, record_hash, clock().isoformat(), policy_version)


def sign_head(
    head: LedgerHead, *, key_id: str, signer: Callable[[bytes], bytes]
) -> SignedLedgerAnchor:
    if not key_id or len(key_id) > 256:
        raise ValueError("invalid signer key identifier")
    signature = signer(head.payload())
    if not signature:
        raise ValueError("empty signature")
    return SignedLedgerAnchor(head, key_id, signature.hex())


def verify_anchor(
    anchor: SignedLedgerAnchor, *, sequence: int, record_hash: str,
    verifier: Callable[[str, bytes, bytes], bool],
) -> bool:
    if anchor.head.sequence != sequence or anchor.head.record_hash != record_hash:
        return False
    try:
        signature = bytes.fromhex(anchor.signature_hex)
    except ValueError:
        return False
    return bool(signature) and verifier(anchor.key_id, anchor.head.payload(), signature)

