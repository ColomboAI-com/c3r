"""PostgreSQL-backed access store: same contract as ``AccessStore`` for multi-replica C3R.

This externalizes keys, projects, quota, usage, and audit to a shared Postgres so
stateless core replicas share one durable, concurrency-correct credential and
rate-limit store. Like the SQLite store it never retains API plaintext keys,
prompts, output text, candidates, or reasoning; only salted HMAC-SHA256 digests
and payload-free metadata. The driver (pg8000, pure-Python) is imported lazily so
the default SQLite path stays dependency-free.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import queue
import re
import secrets
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from typing import Any, cast
from urllib.parse import unquote, urlparse

from .api_access import KEY, SCOPES, IssuedKey, Principal


def _identifier(value: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None:
        raise ValueError("bounded organization/project identifier required")

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS organizations (id text PRIMARY KEY);",
    (
        "CREATE TABLE IF NOT EXISTS projects ("
        " tenant text NOT NULL, id text NOT NULL, rpm integer NOT NULL, key_rps integer NOT NULL,"
        " PRIMARY KEY(tenant,id), FOREIGN KEY(tenant) REFERENCES organizations(id));"
    ),
    (
        "CREATE TABLE IF NOT EXISTS api_keys ("
        " id text PRIMARY KEY, salt text NOT NULL, digest text NOT NULL, tenant text NOT NULL,"
        " project text NOT NULL, scopes text NOT NULL, created_at double precision NOT NULL,"
        " expires_at double precision, last_used_at double precision, revoked integer NOT NULL DEFAULT 0,"
        " FOREIGN KEY(tenant,project) REFERENCES projects(tenant,id));"
    ),
    (
        "CREATE TABLE IF NOT EXISTS quota ("
        " kind text NOT NULL, tenant text NOT NULL, project text NOT NULL, key_id text NOT NULL,"
        " window_start bigint NOT NULL, count integer NOT NULL,"
        " PRIMARY KEY(kind,tenant,project,key_id,window_start));"
    ),
    (
        "CREATE TABLE IF NOT EXISTS audit_events ("
        " id bigserial PRIMARY KEY, tenant text NOT NULL, project text NOT NULL, key_id text,"
        " action text NOT NULL, request_id text, at double precision NOT NULL);"
    ),
    (
        "CREATE TABLE IF NOT EXISTS usage_records ("
        " request_id text PRIMARY KEY, tenant text NOT NULL, project text NOT NULL,"
        " key_id text NOT NULL, metadata text NOT NULL);"
    ),
)


class PostgresAccessStore:
    """Drop-in replacement for ``AccessStore`` backed by a shared Postgres database."""

    def __init__(self, dsn: str, *, clock: Callable[[], float] = time.time, pool_size: int = 8) -> None:
        if not dsn:
            raise ValueError("Postgres DSN required")
        if pool_size < 1:
            raise ValueError("pool size must be positive")
        parsed = urlparse(dsn)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError("Postgres DSN must use the postgres(ql) scheme")
        import pg8000.dbapi as driver  # pyright: ignore[reportMissingImports]  # lazy: postgres backend only

        self._driver: Any = driver
        self.clock = clock
        self._params: dict[str, Any] = {
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 5432,
            "database": (parsed.path or "/").lstrip("/") or "postgres",
        }
        self._pool: queue.Queue[Any] = queue.Queue(maxsize=pool_size)
        self._size = pool_size
        self._lock = threading.Lock()
        self._created = 0
        with self._cursor() as cursor:
            for statement in _SCHEMA:
                cursor.execute(statement)

    def _new_connection(self) -> Any:
        return self._driver.connect(**self._params)

    def _acquire(self) -> Any:
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._size:
                    self._created += 1
                    return self._new_connection()
        return self._pool.get()

    def _discard(self, connection: Any) -> None:
        with suppress(Exception):
            connection.close()
        with self._lock:
            self._created -= 1

    def _release(self, connection: Any) -> None:
        try:
            self._pool.put_nowait(connection)
        except queue.Full:
            self._discard(connection)

    @contextmanager
    def _cursor(self) -> Generator[Any]:
        connection: Any = self._acquire()
        cursor = None
        try:
            cursor = connection.cursor()
            yield cursor
            connection.commit()
        except BaseException:
            # A failed transaction leaves the connection in an aborted state; drop it
            # rather than returning a poisoned connection to the pool.
            self._discard(connection)
            connection = None
            raise
        finally:
            if cursor is not None:
                with suppress(Exception):
                    cursor.close()
            if connection is not None:
                self._release(connection)

    def create_project(self, tenant: str, project: str, *, rpm: int = 60, key_rps: int = 10) -> None:
        _identifier(tenant)
        _identifier(project)
        if not 1 <= rpm <= 100000 or not 1 <= key_rps <= 10000:
            raise ValueError("bounded rate limits required")
        with self._cursor() as cursor:
            cursor.execute("INSERT INTO organizations (id) VALUES (%s) ON CONFLICT DO NOTHING", (tenant,))
            cursor.execute("INSERT INTO projects (tenant,id,rpm,key_rps) VALUES (%s,%s,%s,%s)",
                           (tenant, project, rpm, key_rps))

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
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO api_keys (id,salt,digest,tenant,project,scopes,created_at,expires_at,"
                "last_used_at,revoked) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,0)",
                (key_id, salt.hex(), digest, tenant, project, json.dumps(sorted(scopes)),
                 self.clock(), expires_at))
            cursor.execute("INSERT INTO audit_events (tenant,project,key_id,action,request_id,at) "
                           "VALUES (%s,%s,%s,'key_issued',NULL,%s)", (tenant, project, key_id, self.clock()))
        return IssuedKey(key_id, plaintext)

    def authenticate(self, plaintext: str) -> Principal | None:
        match = KEY.fullmatch(plaintext)
        if match is None:
            return None
        with self._cursor() as cursor:
            cursor.execute("SELECT salt,digest,tenant,project,scopes,expires_at,revoked "
                           "FROM api_keys WHERE id=%s", (match[2],))
            row = cursor.fetchone()
            if row is None:
                return None
            salt, digest, tenant, project, scope_json, expiration, revoked = row
            actual = hmac.new(bytes.fromhex(salt), plaintext.encode(), hashlib.sha256).hexdigest()
            if (not hmac.compare_digest(digest, actual) or revoked
                    or (expiration is not None and self.clock() >= expiration)):
                return None
            cursor.execute("UPDATE api_keys SET last_used_at=%s WHERE id=%s", (self.clock(), match[2]))
            return Principal(tenant, project, match[2], frozenset(json.loads(scope_json)))

    def revoke_key(self, tenant: str, project: str, key_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("UPDATE api_keys SET revoked=1 WHERE tenant=%s AND project=%s AND id=%s",
                           (tenant, project, key_id))
            if cursor.rowcount != 1:
                raise ValueError("key not found in selected project")
            cursor.execute("INSERT INTO audit_events (tenant,project,key_id,action,request_id,at) "
                           "VALUES (%s,%s,%s,'key_revoked',NULL,%s)", (tenant, project, key_id, self.clock()))

    def list_keys(self, tenant: str, project: str) -> list[dict[str, object]]:
        columns = ("id", "tenant", "project", "scopes", "created_at", "expires_at", "last_used_at", "revoked")
        with self._cursor() as cursor:
            cursor.execute("SELECT id,tenant,project,scopes,created_at,expires_at,last_used_at,revoked "
                           "FROM api_keys WHERE tenant=%s AND project=%s", (tenant, project))
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def dispatch_event(self, principal: Principal, request_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("INSERT INTO audit_events (tenant,project,key_id,action,request_id,at) "
                           "VALUES (%s,%s,%s,'request_dispatch',%s,%s)",
                           (principal.tenant_id, principal.project_id, principal.key_id,
                            request_id, self.clock()))

    def record_usage(self, principal: Principal, request_id: str, *, route: str,
                     model: str | None, status: int, latency_ms: float,
                     input_tokens: int | None, output_tokens: int | None,
                     system_one_invocations: int | None, system_two_invocations: int | None,
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
        with self._cursor() as cursor:
            cursor.execute("INSERT INTO usage_records (request_id,tenant,project,key_id,metadata) "
                           "VALUES (%s,%s,%s,%s,%s)",
                           (request_id, principal.tenant_id, principal.project_id, principal.key_id,
                            json.dumps(metadata, allow_nan=False)))

    def project_usage(self, tenant: str, project: str) -> list[dict[str, object]]:
        with self._cursor() as cursor:
            cursor.execute("SELECT metadata FROM usage_records WHERE tenant=%s AND project=%s",
                           (tenant, project))
            return [cast(dict[str, object], json.loads(row[0])) for row in cursor.fetchall()]

    def purge_metadata(self, tenant: str, project: str, *, retention_seconds: int,
                       limit: int = 1000) -> dict[str, object]:
        _identifier(tenant)
        _identifier(project)
        if (type(retention_seconds) is not int or not 60 <= retention_seconds <= 30 * 86400
                or type(limit) is not int or not 1 <= limit <= 10000):
            raise ValueError("bounded metadata retention and batch size required")
        cutoff = self.clock() - retention_seconds
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM usage_records WHERE request_id IN (SELECT request_id FROM usage_records "
                "WHERE tenant=%s AND project=%s AND (metadata::jsonb->>'timestamp')::double precision<%s "
                "ORDER BY request_id LIMIT %s)", (tenant, project, cutoff, limit))
            usage = cursor.rowcount
            cursor.execute(
                "DELETE FROM audit_events WHERE id IN (SELECT id FROM audit_events "
                "WHERE tenant=%s AND project=%s AND at<%s ORDER BY id LIMIT %s)",
                (tenant, project, cutoff, limit))
            audit = cursor.rowcount
        return {"usage_deleted": usage, "audit_deleted": audit, "cutoff_utc_seconds": cutoff,
                "batch_limit_per_table": limit, "scope": "selected_project_shared_database_only",
                "backup_deletion_verified": False, "physical_erasure_verified": False}

    def admit(self, principal: Principal) -> bool:
        now = int(self.clock())
        with self._cursor() as cursor:
            cursor.execute("SELECT rpm,key_rps FROM projects WHERE tenant=%s AND id=%s",
                           (principal.tenant_id, principal.project_id))
            limits = cursor.fetchone()
            if limits is None:
                return False
            requests = (("key", principal.key_id, now, limits[1]),
                        ("project", "", now // 60 * 60, limits[0]))
            for kind, key_id, window, limit in requests:
                cursor.execute("SELECT count FROM quota WHERE kind=%s AND tenant=%s AND project=%s "
                               "AND key_id=%s AND window_start=%s FOR UPDATE",
                               (kind, principal.tenant_id, principal.project_id, key_id, window))
                row = cursor.fetchone()
                if row is not None and row[0] >= limit:
                    return False
            for kind, key_id, window, _ in requests:
                cursor.execute(
                    "INSERT INTO quota (kind,tenant,project,key_id,window_start,count) "
                    "VALUES (%s,%s,%s,%s,%s,1) ON CONFLICT (kind,tenant,project,key_id,window_start) "
                    "DO UPDATE SET count=quota.count+1",
                    (kind, principal.tenant_id, principal.project_id, key_id, window))
            cursor.execute("DELETE FROM quota WHERE window_start<%s", (now - 120,))
            return True
