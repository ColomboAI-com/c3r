import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from c3r.candidate_compiler import CandidateCompiler
from c3r.cvoc import RobustCvocController
from c3r.feature_flags import FeatureFlags
from c3r.runtime import StandaloneController
from c3r.serve import build_servers, load_host_builder
from c3r.staging_host import build as staging_build
from c3r.state_compiler import StateCompiler
from c3r.telemetry.ephemeral import EphemeralTraceSink
from c3r.verifier_firewall import VerifierFirewall, VerifierPolicy
from tests.test_http_service import HostFactory
from tests.test_runtime import controller

CLIENT_TOKEN = "client-token-with-at-least-thirty-two-characters"
BACKEND_TOKEN = "backend-token-with-at-least-thirty-two-characters"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def config():
    return {
        "C3R_HOST_ENTRYPOINT": "trusted_host:build",
        "C3R_CLIENT_TOKEN": CLIENT_TOKEN,
        "C3R_BACKEND_TOKEN": BACKEND_TOKEN,
        "PORT": str(free_port()),
        "C3R_BACKEND_PORT": str(free_port()),
    }


class ServeTests(unittest.TestCase):
    def test_internal_token_without_explicit_internal_port_fails_startup(self):
        values = config()
        values.update({"C3R_HOST_ENTRYPOINT": "c3r.staging_host:build",
                       "C3R_INTERNAL_READY_TOKEN": "internal-test-token-never-an-api-token"})
        result = subprocess.run([sys.executable, "-m", "c3r.serve"],
                                env={**os.environ, **values}, capture_output=True,
                                text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("C3R_INTERNAL_READY_PORT", result.stderr)

    def test_module_entrypoint_starts_production_host_without_claiming_provider_readiness(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        values = config()
        values.update({
            "C3R_HOST_ENTRYPOINT": "c3r.production_host:build",
            "C3R_MODE": "production_inference", "C3R_ENABLED": "true",
            "C3R_API_ACCESS_DB": os.path.join(scratch.name, "access.sqlite3"),
            "C3R_SYSTEM_ONE": "true", "C3R_DELIBERATIVE": "true",
            "C3R_SYSTEM_ONE_PROVIDER": "clm", "C3R_TRACE_COLLECTION": "false",
            "C3R_ONLINE_LEARNING": "false", "C3R_INGRESS_HOST": "127.0.0.1",
            "C3R_CLM_CONTAINER_DIGEST": "sha256:" + "a" * 64,
            "C3R_INTERNAL_READY_PORT": str(free_port()),
            "C3R_INTERNAL_READY_TOKEN": "internal-token-distinct-from-both-api-tokens",
        })
        process = subprocess.Popen([sys.executable, "-m", "c3r.serve"],
                                   env={**os.environ, **values}, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    with urlopen("http://127.0.0.1:" + values["PORT"] + "/health", timeout=1) as response:
                        self.assertEqual(json.load(response)["status"], "ok")
                        break
                except OSError:
                    if process.poll() is not None:
                        self.fail("production entrypoint exited before health was reachable")
                    time.sleep(0.05)
            else:
                self.fail("production entrypoint did not become reachable")
            req = Request("http://127.0.0.1:" + values["C3R_INTERNAL_READY_PORT"] +
                          "/internal/ready", headers={"Authorization": "Bearer " +
                          values["C3R_INTERNAL_READY_TOKEN"]})
            with self.assertRaises(HTTPError) as failure:
                urlopen(req, timeout=2)
            self.assertEqual(failure.exception.code, 503)
            self.assertEqual(json.load(failure.exception)["status"], "not_ready")
            with self.assertRaises(HTTPError) as public_failure:
                urlopen("http://127.0.0.1:" + values["PORT"] + "/internal/ready", timeout=2)
            self.assertEqual(public_failure.exception.code, 404)
        finally:
            process.terminate()
            process.communicate(timeout=5)

    def test_production_entrypoint_requires_key_mode_database_before_binding(self):
        values = config()
        values.update({"C3R_HOST_ENTRYPOINT": "c3r.production_host:build",
                       "C3R_MODE": "production_inference", "C3R_ENABLED": "true",
                       "C3R_SYSTEM_ONE": "true", "C3R_SYSTEM_ONE_PROVIDER": "clm",
                       "C3R_DELIBERATIVE": "true", "C3R_CLM_CONTAINER_DIGEST": "sha256:" + "a" * 64})
        result = subprocess.run([sys.executable, "-m", "c3r.serve"],
                                env={**os.environ, **values}, capture_output=True,
                                text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("C3R_API_ACCESS_DB", result.stderr)

    def test_missing_host_or_secret_fails_before_binding(self):
        values = config()
        del values["C3R_HOST_ENTRYPOINT"]
        with self.assertRaisesRegex(ValueError, "C3R_HOST_ENTRYPOINT"):
            build_servers(values)
        values = config()
        del values["C3R_CLIENT_TOKEN"]
        with self.assertRaisesRegex(ValueError, "C3R_CLIENT_TOKEN"):
            build_servers(values)

    def test_invalid_port_and_equal_tokens_fail(self):
        values = config()
        values["PORT"] = "0"
        with self.assertRaisesRegex(ValueError, "PORT"):
            build_servers(values, builder_loader=lambda _: lambda: (controller()[0], HostFactory()))
        values = config()
        values["C3R_BACKEND_TOKEN"] = CLIENT_TOKEN
        with self.assertRaisesRegex(ValueError, "different"):
            build_servers(values, builder_loader=lambda _: lambda: (controller()[0], HostFactory()))

    def test_effect_enabled_host_is_rejected(self):
        class EffectCapableRuntime:
            effect_execution_enabled = True

        with self.assertRaisesRegex(ValueError, "recommendation-only"):
            build_servers(
                config(),
                builder_loader=lambda _: lambda: (
                    EffectCapableRuntime(), HostFactory()
                ),
            )

    def test_host_reference_must_be_explicit(self):
        for reference in ("module", "module:", ":build", "module:bad.name"):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                load_host_builder(reference)

    def test_composed_health_path(self):
        backend, ingress = build_servers(
            config(),
            builder_loader=lambda _: lambda: (controller()[0], HostFactory()),
        )
        threads = [
            threading.Thread(target=backend.serve_forever, daemon=True),
            threading.Thread(target=ingress.serve_forever, daemon=True),
        ]
        try:
            for thread in threads:
                thread.start()
            with urlopen(f"http://127.0.0.1:{ingress.server_port}/health", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'{"status":"ok"}')
        finally:
            ingress.shutdown()
            backend.shutdown()
            ingress.server_close()
            backend.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_production_mode_rejects_persistent_and_disabled_hosts(self):
        values = config()
        values["C3R_MODE"] = "production_inference"
        with self.assertRaisesRegex(ValueError, "ephemeral trace sink"):
            build_servers(
                values, builder_loader=lambda _: lambda: (controller()[0], HostFactory()),
            )
        with self.assertRaisesRegex(ValueError, "decisions enabled"):
            build_servers(values, builder_loader=lambda _: staging_build)

    def test_production_mode_rejects_collection_and_online_learning(self):
        for key in ("C3R_TRACE_COLLECTION", "C3R_ONLINE_LEARNING"):
            values = config()
            values["C3R_MODE"] = "production_inference"
            values[key] = "true"
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_servers(values, builder_loader=lambda _: staging_build)

    def test_production_mode_requires_system_one_path(self):
        runtime = StandaloneController(
            flags=FeatureFlags(enabled_requested=True),
            compiler=StateCompiler(), candidates=CandidateCompiler(),
            cvoc=RobustCvocController(),
            verifier=VerifierFirewall({}, VerifierPolicy(default_verifier="none"),
                                      attestation_key=b"test-key"),
            ledger=EphemeralTraceSink(),
        )
        values = config()
        values["C3R_MODE"] = "production_inference"
        with self.assertRaisesRegex(ValueError, "System-One"):
            build_servers(values, builder_loader=lambda _: lambda: (runtime, HostFactory()))


if __name__ == "__main__":
    unittest.main()

