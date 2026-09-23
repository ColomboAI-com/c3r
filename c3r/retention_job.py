"""Bounded deletion check for the dedicated private C3R trace bucket.

This is a retention backstop, not permission to collect traces. The bucket name,
cutoff, and API host are pinned so a deployment argument cannot target other data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


BUCKET = "colomboai-c3r-private-traces-795563500003"
DELETE_AFTER_DAYS = 28
_STORAGE_API = "https://storage.googleapis.com/storage/v1/b/" + BUCKET + "/o"
_METADATA_TOKEN = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)


@dataclass(frozen=True, slots=True)
class StoredObject:
    name: str
    generation: int
    created_at: datetime


class ObjectClient(Protocol):
    def list_all(self) -> tuple[StoredObject, ...]: ...

    def delete_if_generation(self, obj: StoredObject) -> None: ...


def _created_at(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("object creation time must include UTC offset")
    return parsed.astimezone(timezone.utc)


def purge(client: ObjectClient, *, now: datetime) -> dict[str, object]:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("purge clock must be UTC")
    cutoff = now - timedelta(days=DELETE_AFTER_DAYS)
    before = client.list_all()
    if len(before) > 100_000 or len({item.name for item in before}) != len(before):
        raise ValueError("bucket inventory is too large or contains duplicate names")
    expired = tuple(item for item in before if item.created_at <= cutoff)
    for item in expired:
        client.delete_if_generation(item)
    remaining = client.list_all()
    if any(item.created_at <= cutoff for item in remaining):
        raise RuntimeError("expired objects remain after purge; collection must stay disabled")
    return {
        "bucket": BUCKET,
        "cutoff_utc": cutoff.isoformat(),
        "objects_before": len(before),
        "expired_candidates": len(expired),
        "objects_after": len(remaining),
        "expired_remaining": 0,
        "trace_collection_enabled": False,
    }


class GcsJsonClient:
    """Cloud Run service-identity transport for one pinned GCS bucket."""

    def __init__(self) -> None:
        request = Request(_METADATA_TOKEN, headers={"Metadata-Flavor": "Google"})
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
        token = data.get("access_token")
        if not isinstance(token, str) or len(token) < 20:
            raise RuntimeError("Cloud Run service identity token unavailable")
        self._authorization = "Bearer " + token

    def _request(self, method: str, url: str) -> dict[str, object] | None:
        request = Request(url, method=method, headers={"Authorization": self._authorization})
        with urlopen(request, timeout=30) as response:
            if method == "DELETE":
                return None
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError("invalid GCS response")
        return data

    def list_all(self) -> tuple[StoredObject, ...]:
        found: list[StoredObject] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            query = {"maxResults": "1000", "fields": "items(name,generation,timeCreated),nextPageToken"}
            if page_token is not None:
                query["pageToken"] = page_token
            data = self._request("GET", _STORAGE_API + "?" + urlencode(query))
            assert data is not None
            items = data.get("items", [])
            if not isinstance(items, list):
                raise ValueError("invalid GCS object list")
            for raw in items:
                if not isinstance(raw, dict):
                    raise ValueError("invalid GCS object metadata")
                name, generation, created = (
                    raw.get("name"), raw.get("generation"), raw.get("timeCreated")
                )
                if not isinstance(name, str) or not name or not isinstance(created, str):
                    raise ValueError("invalid GCS object metadata")
                if not isinstance(generation, str) or not generation.isdecimal():
                    raise ValueError("invalid GCS object generation")
                found.append(StoredObject(name, int(generation), _created_at(created)))
                if len(found) > 100_000:
                    raise ValueError("bucket inventory exceeds purge limit")
            next_token = data.get("nextPageToken")
            if next_token is None:
                return tuple(found)
            if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                raise ValueError("invalid or repeated GCS page token")
            seen_tokens.add(next_token)
            page_token = next_token

    def delete_if_generation(self, obj: StoredObject) -> None:
        if not obj.name or obj.generation <= 0:
            raise ValueError("invalid deletion target")
        url = _STORAGE_API + "/" + quote(obj.name, safe="") + "?" + urlencode(
            {"ifGenerationMatch": str(obj.generation)}
        )
        self._request("DELETE", url)


def main() -> None:
    result = purge(GcsJsonClient(), now=datetime.now(timezone.utc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
