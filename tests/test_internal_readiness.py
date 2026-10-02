"""Authenticated maintenance HTTP behavior, independent from public ingress."""
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.internal_readiness import InternalReadinessServer
from c3r.local_artifacts import PinnedLocalArtifacts

TOKEN = "maintenance-test-token-with-more-than-thirty-two-characters"


class InternalReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api_servers = tuple(ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
                                 for _ in range(2))
        self.api_workers = tuple(threading.Thread(target=server.serve_forever, daemon=True)
                                 for server in self.api_servers)
        for worker in self.api_workers:
            worker.start()

    def tearDown(self) -> None:
        for server, worker in zip(self.api_servers, self.api_workers):
            if worker.is_alive():
                server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_stopped_api_worker_revokes_ready_even_when_provider_checks_are_positive(self):
        report: dict[str, object] = {
            "runtime": True, "clm_qwen": True, "deepseek": True,
            "required_local_artifact_files": True,
            "required_local_artifact_manifest_sha256": "a" * 64,
        }
        self.api_servers[0].shutdown()
        self.api_workers[0].join(timeout=2)
        status, body = self.call(InternalReadinessServer(
            token=TOKEN, port=0, probe=lambda: report, api_workers=self.api_workers))
        self.assertEqual((status, body["status"]), (503, "not_ready"))
        self.assertFalse(cast(dict[str, object], body["checks"])["runtime"])

    def call(self, server: InternalReadinessServer, path: str = "/internal/ready", *,
             token: str = TOKEN, method: str = "GET",
             bind_api_workers: bool = True) -> tuple[int, dict[str, object]]:
        if bind_api_workers and not server.api_workers:
            server.api_workers = self.api_workers
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}" + path,
                              headers={"Authorization": "Bearer " + token}, method=method)
            try:
                with urlopen(request, timeout=2) as response:
                    return int(response.status), cast(dict[str, object], json.load(response))
            except HTTPError as error:
                return error.code, cast(dict[str, object], json.load(error))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_missing_readiness_evidence_is_not_ready(self):
        status, body = self.call(InternalReadinessServer(token=TOKEN, port=0))
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "not_ready")

    def test_positive_provider_report_without_api_workers_is_not_ready(self):
        report: dict[str, object] = {
            "runtime": True, "clm_qwen": True, "deepseek": True,
            "required_local_artifact_files": True,
            "required_local_artifact_manifest_sha256": "a" * 64,
        }
        status, body = self.call(InternalReadinessServer(
            token=TOKEN, port=0, probe=lambda: report), bind_api_workers=False)
        self.assertEqual((status, body["status"]), (503, "not_ready"))

    def test_worker_exit_during_provider_check_revokes_ready(self):
        def external_probe() -> dict[str, object]:
            self.api_servers[1].shutdown()
            self.api_workers[1].join(timeout=2)
            return {"runtime": True, "clm_qwen": True, "deepseek": True,
                    "required_local_artifact_files": True,
                    "required_local_artifact_manifest_sha256": "a" * 64}

        status, body = self.call(InternalReadinessServer(
            token=TOKEN, port=0, probe=external_probe, api_workers=self.api_workers))
        self.assertEqual((status, body["status"]), (503, "not_ready"))
        self.assertFalse(cast(dict[str, object], body["checks"])["runtime"])

    def test_shutdown_request_revokes_ready_while_api_workers_still_run(self):
        stopping = threading.Event()

        def external_probe() -> dict[str, object]:
            stopping.set()
            return {"runtime": True, "clm_qwen": True, "deepseek": True,
                    "required_local_artifact_files": True,
                    "required_local_artifact_manifest_sha256": "a" * 64}

        status, body = self.call(InternalReadinessServer(
            token=TOKEN, port=0, probe=external_probe,
            api_workers=self.api_workers, stopping=stopping))
        self.assertEqual((status, body["status"]), (503, "not_ready"))

    def test_changed_required_file_revokes_readiness_on_next_request(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            artifact = root / "artifact"
            artifact.write_bytes(b"abc")
            manifest = root / "required-files.json"
            manifest.write_text(json.dumps({"schema": "c3r-required-local-files-v1", "files": [{
                "path": str(artifact), "sha256":
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                "max_bytes": 3}]}))
            pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
            verifier = PinnedLocalArtifacts(manifest, pin)

            def provider_readback():
                return {"runtime": True, "clm_qwen": True, "deepseek": True,
                        "required_local_artifact_files": verifier.verify(),
                        "required_local_artifact_manifest_sha256": pin}

            status, body = self.call(InternalReadinessServer(
                token=TOKEN, port=0, probe=provider_readback))
            self.assertEqual((status, body["status"]), (200, "ready"))
            self.assertEqual(body["required_local_artifact_manifest_sha256"], pin)
            artifact.write_bytes(b"xyz")
            status, body = self.call(InternalReadinessServer(
                token=TOKEN, port=0, probe=provider_readback))
            self.assertEqual((status, body["status"]), (503, "not_ready"))

    def test_other_tokens_and_routes_cannot_use_the_internal_channel(self):
        for path, token, method, expected in (
            ("/internal/ready", "wrong", "GET", 401),
            ("/health", TOKEN, "GET", 404),
            ("/v1/responses", TOKEN, "POST", 405),
        ):
            with self.subTest(path=path, method=method):
                status, _ = self.call(InternalReadinessServer(token=TOKEN, port=0),
                                      path, token=token, method=method)
                self.assertEqual(status, expected)


    def test_provider_loss_never_reuses_a_previous_ready_result(self):
        external_health: dict[str, object] = {
            "runtime": True, "clm_qwen": True, "deepseek": True,
            "required_local_artifact_files": True,
            "required_local_artifact_manifest_sha256": "a" * 64,
        }
        self.assertEqual(self.call(InternalReadinessServer(
            token=TOKEN, port=0, probe=lambda: external_health))[0], 200)
        for check in ("runtime", "clm_qwen", "deepseek", "required_local_artifact_files"):
            external_health[check] = False
            status, body = self.call(InternalReadinessServer(
                token=TOKEN, port=0, probe=lambda: external_health))
            self.assertEqual((status, body["status"]), (503, "not_ready"))
            external_health[check] = True

    def test_unqualified_file_manifests_do_not_admit_recovery(self):
        with tempfile.TemporaryDirectory() as scratch:
            manifest = Path(scratch) / "required.json"
            invalid: tuple[dict[str, object], ...] = (
                {"schema": "c3r-required-local-files-v1", "files": []},
                {"schema": "c3r-required-local-files-v1", "files": [{
                    "path": scratch, "sha256": "a" * 64, "max_bytes": 3}]},
                {"schema": "c3r-required-local-files-v1", "files": [{
                    "path": str(manifest), "sha256": "a" * 64,
                    "max_bytes": 67108865}]},
            )
            for payload in invalid:
                manifest.write_text(json.dumps(payload))
                pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
                verifier = PinnedLocalArtifacts(manifest, pin)
                status, body = self.call(InternalReadinessServer(
                    token=TOKEN, port=0, probe=lambda: {
                        "runtime": True, "clm_qwen": True, "deepseek": True,
                        "required_local_artifact_files": verifier.verify(),
                        "required_local_artifact_manifest_sha256": pin,
                    }))
                self.assertEqual((status, body["status"]), (503, "not_ready"))

    def test_provider_exception_remains_not_ready_without_error_details(self):
        def unavailable() -> dict[str, object]:
            raise RuntimeError("private-provider-error-must-not-be-disclosed")

        status, body = self.call(InternalReadinessServer(token=TOKEN, port=0, probe=unavailable))
        self.assertEqual((status, body["status"]), (503, "not_ready"))
        self.assertNotIn("private-provider", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
