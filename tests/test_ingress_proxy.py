import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.ingress_proxy import C3RIngressServer


CLIENT_TOKEN = "client-token-that-is-long-enough-for-tests"
UPSTREAM_TOKEN = "upstream-token-that-is-long-enough-for-tests"


class _UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        self.server.seen.append((self.path, dict(self.headers), b""))
        self._reply(200, {"status": "ok"})

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.server.seen.append((self.path, dict(self.headers), self.rfile.read(length)))
        self._reply(200, {"route": "recommendation"})

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class IngressProxyTests(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.upstream.seen = []
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.ingress = C3RIngressServer(
            upstream_port=self.upstream.server_port,
            client_token=CLIENT_TOKEN,
            upstream_token=UPSTREAM_TOKEN,
            host="127.0.0.1",
            port=0,
            upstream_timeout_seconds=0.5,
        )
        self.ingress_thread = threading.Thread(target=self.ingress.serve_forever, daemon=True)
        self.ingress_thread.start()
        self.base = f"http://127.0.0.1:{self.ingress.server_port}"

    def tearDown(self):
        self.ingress.shutdown()
        self.ingress.server_close()
        self.ingress_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)

    def request(self, path, *, method="GET", token=CLIENT_TOKEN, payload=None):
        headers = {"Authorization": "Bearer cloud-run-identity-token"}
        if token is not None:
            headers["X-C3R-Token"] = token
        body = None if payload is None else json.dumps(payload).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_private_decision_forwards_only_internal_authorization(self):
        status, body = self.request("/v1/decisions", method="POST", payload={"goal": "inspect"})
        self.assertEqual((status, body["route"]), (200, "recommendation"))
        path, headers, forwarded = self.upstream.seen[-1]
        self.assertEqual(path, "/v1/decisions")
        self.assertEqual(headers["Authorization"], f"Bearer {UPSTREAM_TOKEN}")
        self.assertNotIn("X-C3R-Token", headers)
        self.assertEqual(json.loads(forwarded), {"goal": "inspect"})

    def test_missing_or_wrong_client_token_never_reaches_upstream(self):
        for token in (None, "wrong"):
            status, body = self.request("/v1/decisions", method="POST", token=token,
                                        payload={"goal": "inspect"})
            self.assertEqual((status, body["error"]), (401, "unauthorized"))
        self.assertEqual(self.upstream.seen, [])

    def test_health_is_unprivileged_but_metrics_require_token(self):
        self.assertEqual(self.request("/health", token=None)[0], 200)
        self.assertEqual(self.request("/metrics", token=None)[0], 401)

    def test_rejects_unknown_path_without_contacting_upstream(self):
        self.assertEqual(self.request("/admin")[0], 404)
        self.assertEqual(self.request("/v1/decisions?debug=1", method="POST",
                                      payload={"goal": "inspect"})[0], 404)
        self.assertEqual(self.upstream.seen, [])

    def test_rejects_ambiguous_framing_and_non_json_body(self):
        for headers in (
            {"Content-Type": "text/plain"},
            {"Transfer-Encoding": "chunked"},
            {"Content-Length": "2, 3"},
        ):
            request = Request(
                self.base + "/v1/decisions",
                data=b"{}",
                headers={"X-C3R-Token": CLIENT_TOKEN, **headers},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=2)
            self.assertIn(raised.exception.code, {400, 413, 415})
        self.assertEqual(self.upstream.seen, [])

    def test_upstream_failure_is_not_mistaken_for_success(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        status, body = self.request("/v1/decisions", method="POST", payload={"goal": "inspect"})
        self.assertEqual((status, body["error"]), (503, "upstream_unavailable"))

    def test_upstream_route_must_be_loopback_and_secrets_distinct(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            C3RIngressServer(upstream_host="example.com", upstream_port=8081,
                             client_token=CLIENT_TOKEN, upstream_token=UPSTREAM_TOKEN,
                             host="127.0.0.1", port=0)
        with self.assertRaisesRegex(ValueError, "different"):
            C3RIngressServer(upstream_port=8081, client_token=CLIENT_TOKEN,
                             upstream_token=CLIENT_TOKEN, host="127.0.0.1", port=0)


if __name__ == "__main__":
    unittest.main()
