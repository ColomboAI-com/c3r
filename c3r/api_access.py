"""Durable hash-only developer credentials and payload-free tenant metadata.

This store is an operator-owned system boundary. It never retains API plaintext
keys, prompts, output text, candidates, or reasoning. Database IAM/encryption,
backup/metadata-retention policy and multi-instance coordination need deployment
qualification; a local SQLite implementation does not establish those controls.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SCOPES = frozenset({"responses:write", "system_one:write", "rank:write", "decide:write",
                    "models:read"})
KEY = re.compile(r"c3r_sk_(live|test)_([a-f0-9]{24})_([A-Za-z0-9_-]{43})")


@dataclass(frozen=True, slots=True)
class IssuedKey:
    key_id: str
    secret: str


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: str
    project_id: str
    key_id: str
    scopes: frozenset[str]


def _identifier(value: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None:
        raise ValueError("bounded organization/project identifier required")


class AccessStore:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        if (not path.is_absolute() or not path.parent.is_dir()
                or any(p.is_symlink() for p in (path, *path.parents))):
            raise ValueError("non-linked absolute access database path and existing directory required")
        if os.name == "posix":
            for ancestor in path.parents:
                info = ancestor.stat()
                sticky_root = ancestor != path.parent and info.st_uid == 0 and bool(info.st_mode & 0o1000)
                unsafe_mode = bool(info.st_mode & (0o077 if ancestor == path.parent else 0o022))
                if info.st_uid not in {0, os.geteuid()} or (unsafe_mode and not sticky_root):
                    raise ValueError("private operator-owned access database directory required")
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        if not path.is_file():
            raise ValueError("access database must be a regular file")
        if os.name == "posix" and (path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077):
            raise ValueError("access database ownership/mode unsafe")
        self.path, self.clock = path, clock
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS projects (
                    tenant TEXT NOT NULL, id TEXT NOT NULL, rpm INTEGER NOT NULL,
                    key_rps INTEGER NOT NULL, PRIMARY KEY(tenant,id),
                    FOREIGN KEY(tenant) REFERENCES organizations(id));
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL,
                    tenant TEXT NOT NULL, project TEXT NOT NULL, scopes TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL, last_used_at REAL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(tenant,project) REFERENCES projects(tenant,id));
                CREATE TABLE IF NOT EXISTS quota (
                    kind TEXT NOT NULL, tenant TEXT NOT NULL, project TEXT NOT NULL,
                    key_id TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(kind,tenant,project,key_id,window));
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, project TEXT NOT NULL,
                    key_id TEXT, action TEXT NOT NULL, request_id TEXT, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage_records (
                    request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, project TEXT NOT NULL,
                    key_id TEXT NOT NULL, metadata TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection]:
        # No shared connection/thread state; busy waits are bounded.
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=2)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    def create_project(self, tenant: str, project: str, *, rpm: int = 60,
                       key_rps: int = 10) -> None:
        _identifier(tenant)
        _identifier(project)
        if not 1 <= rpm <= 100000 or not 1 <= key_rps <= 10000:
            raise ValueError("bounded rate limits required")
        with self.connect() as connection:
            connection.execute("INSERT OR IGNORE INTO organizations VALUES (?)", (tenant,))
            connection.execute("INSERT INTO projects VALUES (?,?,?,?)", (tenant, project, rpm, key_rps))

    def issue_key(self, tenant: str, project: str, scopes: set[str], *, live: bool = False,
                  expires_at: float | None = None) -> IssuedKey:
        if not scopes or not scopes <= SCOPES:
            raise ValueError("nonempty supported API scopes required")
        if expires_at is not None and not math.isfinite(expires_at):
            raise ValueError("finite expiration required")
        key_id = secrets.token_hex(12)
        plaintext = f"c3r_sk_{'live' if live else 'test'}_{key_id}_" + secrets.token_urlsafe(32)
        salt = secrets.token_bytes(32)
        digest = hmac.new(salt, plaintext.encode(), hashlib.sha256).hexdigest()
        with self.connect() as connection:
            connection.execute("INSERT INTO api_keys VALUES (?,?,?,?,?,?,?,?,?,0)",
                               (key_id, salt.hex(), digest, tenant, project,
                                json.dumps(sorted(scopes)), self.clock(), expires_at, None))
            connection.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,'key_issued',NULL,?)",
                               (tenant, project, key_id, self.clock()))
        return IssuedKey(key_id, plaintext)

    def authenticate(self, plaintext: str) -> Principal | None:
        match = KEY.fullmatch(plaintext)
        if match is None:
            return None
        with self.connect() as connection:
            row = connection.execute("SELECT salt,digest,tenant,project,scopes,expires_at,revoked "
                                     "FROM api_keys WHERE id=?", (match[2],)).fetchone()
            if row is None:
                return None
            salt, digest, tenant, project, scope_json, expiration, revoked = row
            actual = hmac.new(bytes.fromhex(salt), plaintext.encode(), hashlib.sha256).hexdigest()
            if (not hmac.compare_digest(digest, actual) or revoked
                    or (expiration is not None and self.clock() >= expiration)):
                return None
            connection.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (self.clock(), match[2]))
            return Principal(tenant, project, match[2], frozenset(json.loads(scope_json)))

    def revoke_key(self, tenant: str, project: str, key_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE api_keys SET revoked=1 WHERE tenant=? AND project=? AND id=?",
                (tenant, project, key_id)).rowcount
            if changed != 1:
                raise ValueError("key not found in selected project")
            connection.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,'key_revoked',NULL,?)",
                               (tenant, project, key_id, self.clock()))

    def list_keys(self, tenant: str, project: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT id,tenant,project,scopes,created_at,expires_at,"
                                      "last_used_at,revoked FROM api_keys WHERE tenant=? AND project=?",
                                      (tenant, project)).fetchall()
            return [dict(row) for row in rows]

    def dispatch_event(self, principal: Principal, request_id: str) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO audit_events VALUES (NULL,?,?,?,'request_dispatch',?,?)",
                               (principal.tenant_id, principal.project_id, principal.key_id,
                                request_id, self.clock()))

    def record_usage(self, principal: Principal, request_id: str, *, route: str,
                     model: str | None, status: int, latency_ms: float,
                     input_tokens: int | None, output_tokens: int | None,
                     system_one_invocations: int | None,
                     system_two_invocations: int | None,
                     invocation_basis: str | None = None) -> None:
        metadata = {"request_id": request_id, "tenant_id": principal.tenant_id,
                    "project_id": principal.project_id, "api_key_id": principal.key_id,
                    "route": route, "model": model, "status": status,
                    "latency_ms": latency_ms, "timestamp": self.clock(),
                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                    "system_one_invocations": system_one_invocations,
                    "system_two_invocations": system_two_invocations,
                    "invocation_basis": invocation_basis,
                    "gpu_allocation_ms": None, "allocated_cost_usd": None,
                    "cost_basis": "unmeasured"}
        with self.connect() as connection:
            connection.execute("INSERT INTO usage_records VALUES (?,?,?,?,?)",
                               (request_id, principal.tenant_id, principal.project_id,
                                principal.key_id, json.dumps(metadata, allow_nan=False)))

    def project_usage(self, tenant: str, project: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT metadata FROM usage_records WHERE tenant=? AND project=?",
                                      (tenant, project)).fetchall()
            return [cast(dict[str, object], json.loads(row[0])) for row in rows]

    def purge_metadata(self, tenant: str, project: str, *, retention_seconds: int,
                       limit: int = 1000) -> dict[str, object]:
        """Bounded logical deletion in this database only; not backup/physical erase proof."""
        _identifier(tenant)
        _identifier(project)
        if (type(retention_seconds) is not int or not 60 <= retention_seconds <= 30 * 86400
                or type(limit) is not int or not 1 <= limit <= 10000):
            raise ValueError("bounded metadata retention and batch size required")
        cutoff = self.clock() - retention_seconds
        with self.connect() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
            usage = connection.execute(
                "DELETE FROM usage_records WHERE rowid IN (SELECT rowid FROM usage_records "
                "WHERE tenant=? AND project=? AND json_extract(metadata,'$.timestamp')<? "
                "ORDER BY rowid LIMIT ?)", (tenant, project, cutoff, limit)).rowcount
            audit = connection.execute(
                "DELETE FROM audit_events WHERE id IN (SELECT id FROM audit_events "
                "WHERE tenant=? AND project=? AND at<? ORDER BY id LIMIT ?)",
                (tenant, project, cutoff, limit)).rowcount
        return {"usage_deleted": usage, "audit_deleted": audit, "cutoff_utc_seconds": cutoff,
                "batch_limit_per_table": limit, "scope": "selected_project_live_database_only",
                "backup_deletion_verified": False, "physical_erasure_verified": False}

    def admit(self, principal: Principal) -> bool:
        now = int(self.clock())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            limits = connection.execute("SELECT rpm,key_rps FROM projects WHERE tenant=? AND id=?",
                                        (principal.tenant_id, principal.project_id)).fetchone()
            if limits is None:
                return False
            requests = (("key", principal.key_id, now, limits[1]),
                        ("project", "", now // 60 * 60, limits[0]))
            for kind, key_id, window, limit in requests:
                row = connection.execute("SELECT count FROM quota WHERE kind=? AND tenant=? "
                                         "AND project=? AND key_id=? AND window=?",
                                         (kind, principal.tenant_id, principal.project_id,
                                          key_id, window)).fetchone()
                if row is not None and row[0] >= limit:
                    return False
            for kind, key_id, window, _ in requests:
                connection.execute("INSERT INTO quota VALUES (?,?,?,?,?,1) ON CONFLICT "
                                   "(kind,tenant,project,key_id,window) DO UPDATE SET count=count+1",
                                   (kind, principal.tenant_id, principal.project_id, key_id, window))
            connection.execute("DELETE FROM quota WHERE window<?", (now - 120,))
            return True
