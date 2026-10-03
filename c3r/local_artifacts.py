"""Fresh bounded local-file checks against an independently pinned host manifest.

Hashing a receipt file proves only that file, never the weights described in it.
The release operator owns the required-file inventory and its out-of-band pin.
"""
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import cast

MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 65536
SHA256 = re.compile(r"[a-f0-9]{64}")


def _read_regular(path: Path, maximum: int) -> bytes:
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("artifact must be an absolute non-linked local file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("artifact is not a bounded regular file")
        data = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())
        if (len(data) > maximum or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise ValueError("artifact changed during verification")
        return data


class PinnedLocalArtifacts:
    def __init__(self, manifest: Path, expected_sha256: str) -> None:
        if SHA256.fullmatch(expected_sha256) is None:
            raise ValueError("independent required-file manifest SHA-256 pin required")
        self.manifest, self.expected_sha256 = manifest, expected_sha256

    def verify(self) -> bool:
        try:
            raw = _read_regular(self.manifest, MAX_MANIFEST_BYTES)
            if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
                return False
            parsed: object = json.loads(raw)
            if not isinstance(parsed, dict):
                return False
            manifest = cast(dict[str, object], parsed)
            entries = manifest.get("files")
            if (set(manifest) != {"schema", "files"}
                    or manifest.get("schema") != "c3r-required-local-files-v1"
                    or not isinstance(entries, list)):
                return False
            rows = cast(list[object], entries)
            if not 1 <= len(rows) <= 32:
                return False
            files: list[tuple[Path, str, int]] = []
            for raw_entry in rows:
                if not isinstance(raw_entry, dict):
                    return False
                entry = cast(dict[str, object], raw_entry)
                path, sha, maximum = entry.get("path"), entry.get("sha256"), entry.get("max_bytes")
                if (set(entry) != {"path", "sha256", "max_bytes"}
                        or not isinstance(path, str) or not isinstance(sha, str)
                        or SHA256.fullmatch(sha) is None or type(maximum) is not int
                        or not 1 <= maximum <= MAX_TOTAL_BYTES):
                    return False
                files.append((Path(path), sha, maximum))
            if (len({str(path) for path, _, _ in files}) != len(files)
                    or sum(maximum for _, _, maximum in files) > MAX_TOTAL_BYTES):
                return False
            return all(hashlib.sha256(_read_regular(path, maximum)).hexdigest() == sha
                       for path, sha, maximum in files)
        except (OSError, ValueError, TypeError, RecursionError):
            return False
