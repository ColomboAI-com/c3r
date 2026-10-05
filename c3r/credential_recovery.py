"""Read-only credential backup and hash-bound offline recovery; no payload copies."""
import hashlib
import hmac
import os
import re
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .api_access import AccessStore

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
CREDENTIAL_TABLES = (
    ("organizations", "id"),
    ("projects", "tenant,id,rpm,key_rps"),
    ("api_keys", "id,salt,digest,tenant,project,scopes,created_at,expires_at,last_used_at,revoked"),
)


@contextmanager
def credential_source(path: Path, expected_sha256: str | None) -> Generator[sqlite3.Connection]:
    AccessStore.validate_path(path)
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("existing unlinked credential source required")
    if os.name == "posix" and (path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077):
        raise ValueError("private credential source ownership/mode required")
    if expected_sha256 is None:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    else:
        if re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None:
            raise ValueError("approved backup hash required")
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise ValueError("unbound snapshot sidecar")
        with path.open("rb") as artifact:
            raw = artifact.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError("credential snapshot exceeds recovery bound")
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
            raise ValueError("credential snapshot hash mismatch")
        # SQLite receives only these hash-verified bytes, never the pathname or
        # journal state. Concurrent source mutation cannot change the restored data.
        connection = sqlite3.connect(":memory:", timeout=2)
        try:
            connection.deserialize(raw)
        except sqlite3.Error:
            connection.close()
            raise
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("credential source integrity check failed")
        for table, columns in CREDENTIAL_TABLES:
            connection.execute(f"SELECT {columns} FROM {table} LIMIT 0")
        if expected_sha256 is not None and connection.execute(
                "SELECT version FROM credential_snapshot").fetchall() != [(1,)]:
            raise ValueError("versioned credential snapshot required")
        yield connection
    finally:
        connection.close()


def copy_credentials(source_path: Path, destination: Path, *,
                     expected_sha256: str | None = None) -> dict[str, object]:
    """Copy credentials into a new file; restore always revokes keys for secure reissue."""
    restore = expected_sha256 is not None
    AccessStore.validate_path(destination)
    if destination.resolve() != destination:
        raise ValueError("non-redirected destination required")
    with credential_source(source_path, expected_sha256) as source:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        target = AccessStore(destination)
        counts: dict[str, int] = {}
        with target.connect() as output:
            for table, columns in CREDENTIAL_TABLES:
                rows = source.execute(f"SELECT {columns} FROM {table}")
                placeholders = ",".join("?" for _ in columns.split(","))
                output.executemany(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", rows)
                counts[table] = output.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if restore:
                output.execute("UPDATE api_keys SET revoked=1")
            else:
                output.execute("CREATE TABLE credential_snapshot (version INTEGER NOT NULL)")
                output.execute("INSERT INTO credential_snapshot VALUES (1)")
            if output.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("credential relationships invalid")
    with destination.open("r+b") as artifact:
        os.fsync(artifact.fileno())
        if os.fstat(artifact.fileno()).st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("credential snapshot exceeds recovery bound")
        digest = hashlib.file_digest(artifact, "sha256").hexdigest()
    return {"status": "restored_keys_revoked" if restore else "credential_snapshot_created",
            "organizations_copied": counts["organizations"], "projects_copied": counts["projects"],
            "keys_copied": counts["api_keys"], "sha256": digest,
            "requires_key_rotation": restore, "scope": "credentials_and_project_limits_only",
            "encryption_verified": False, "backup_deletion_verified": False}
