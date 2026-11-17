"""Real gateway + PostgreSQL fixtures; no production traffic or actual model calls."""
import importlib.util
import json
import os
import threading
import time
import unittest
import uuid
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.api_access import AccessStore
from c3r.ingress_proxy import C3RIngressServer
from c3r.pg_access import PostgresAccessStore
from tests.test_api_access_http import BACKEND_TOKEN, Upstream, UpstreamServer

DSN = os.environ.get("C3R_TEST_PG_DSN", "")


@unittest.skipUnless(DSN and importlib.util.find_spec("pg8000"), "requires disposable PostgreSQL")
class PostgresGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        now = time.time()
        self.store = PostgresAccessStore(DSN, clock=lambda: now)
        self.addCleanup(self.store.close)
        self.tenant, self.project = "fixture" + uuid.uuid4().hex, "app"
        self.store.create_project(self.tenant, self.project, rpm=100)
        self.key = self.store.issue_key(self.tenant, self.project, {"models:read"},
                                        expires_at=time.time() + 600)
        self.upstream = UpstreamServer(("127.0.0.1", 0), Upstream)
        self.upstream.stream_release = threading.Event()
        self.upstream.cancelled = threading.Event()
        self.upstream.pending_headers = threading.Event()
        self.gateway = C3RIngressServer(upstream_port=self.upstream.server_port,
            upstream_token=BACKEND_TOKEN, client_token="unused-staging-token-with-at-least-32-characters",
            host="127.0.0.1", port=0, access_store=cast(AccessStore, self.store))
        self.threads = [threading.Thread(target=server.serve_forever, daemon=True)
                        for server in (self.upstream, self.gateway)]
        for thread in self.threads:
            thread.start()
        self.addCleanup(self.stop_servers)

    def stop_servers(self) -> None:
        for server in (self.gateway, self.upstream):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)

    def call(self, key: str, route: str = "/v1/models", payload: dict[str, str] | None = None) -> int:
        request = Request(f"http://127.0.0.1:{self.gateway.server_port}" + route,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode())
        try:
            with urlopen(request, timeout=3) as response:
                return response.status
        except HTTPError as error:
            error.close()
            return error.code

    def test_persisted_key_revocation_and_scope_cross_the_real_gateway(self) -> None:
        self.assertEqual(self.call(self.key.secret), 200)
        self.assertEqual(self.call(self.key.secret, "/v1/responses", {"input": "fixture"}), 403)
        second = PostgresAccessStore(DSN)
        try:
            self.assertIsNotNone(second.authenticate(self.key.secret))
            second.revoke_key(self.tenant, self.project, self.key.key_id)
        finally:
            second.close()
        self.assertEqual(self.call(self.key.secret), 401)

    def test_project_quota_is_shared_across_keys_and_tenants_remain_separate(self) -> None:
        other = "fixture" + uuid.uuid4().hex
        self.store.create_project(other, self.project, rpm=1)
        keys = [self.store.issue_key(other, self.project, {"models:read"},
                expires_at=time.time() + 600) for _ in range(2)]
        self.assertEqual(self.call(keys[0].secret), 200)
        self.assertEqual(self.call(keys[1].secret), 429)
        self.assertEqual(self.call(self.key.secret), 200)
        self.assertEqual(len(self.store.project_usage(other, self.project)), 2)
        self.assertEqual(len(self.store.project_usage(self.tenant, self.project)), 1)

    def test_success_and_refusal_metadata_exclude_payloads(self) -> None:
        key = self.store.issue_key(self.tenant, self.project, {"responses:write"},
                                   expires_at=time.time() + 600)
        self.assertEqual(self.call(key.secret, "/v1/responses",
            {"model": "c3r-core", "input": "PRIVATE_REQUEST_MARKER"}), 200)
        rows = self.store.project_usage(self.tenant, self.project)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input_tokens"], 13)
        self.assertEqual(rows[0]["output_tokens"], 7)
        self.assertNotIn("PRIVATE_REQUEST_MARKER", json.dumps(rows))
        self.assertNotIn("PRIVATE_RETURN_MARKER", json.dumps(rows))
        self.assertNotIn(key.secret, json.dumps(rows))
