"""Scoped private CLM outage and C3R kill/recovery drills.

Never stops the encoder, shared DeepSeek service or VM. Synthetic API bodies
are discarded; only statuses are reported. This is not a public canary.
"""
import json
import subprocess
import time
from pathlib import Path

import requests


def main():
    config = dict(line.split("=", 1) for line in (
        Path.home() / ".c3r-private-inference/candidate-v3.env").read_text().splitlines())
    if config.get("C3R_INGRESS_HOST") != "127.0.0.1":
        raise RuntimeError("drill restricted to private candidate")
    session = requests.Session()
    session.trust_env = False
    session.headers["Authorization"] = "Bearer " + config["C3R_CLIENT_TOKEN"]
    base = "http://127.0.0.1:8088"
    evidence = []
    stopped = set()

    def docker(*args):
        subprocess.run(["sudo", "docker", *args], check=True, capture_output=True)

    def status(path, payload=None):
        try:
            response = session.request("GET" if payload is None else "POST", base + path,
                                       json=payload, timeout=15)
            return response.status_code
        except requests.RequestException:
            return "unreachable"

    def ready(expected, deadline=120):
        until = time.monotonic() + deadline
        while time.monotonic() < until:
            value = status("/ready")
            if value == expected:
                return value
            time.sleep(2)
        raise RuntimeError("readiness transition deadline exceeded")

    try:
        if status("/ready") != 200:
            raise RuntimeError("private baseline is not ready")
        docker("stop", "--time", "10", "c3r-clm")
        stopped.add("c3r-clm")
        outage = ready(503, deadline=45)
        ranking = status("/v1/system-one", {"state": "Duplicate invoice",
                                           "candidates": ["Billing", "Technical"]})
        fallback = status("/v1/responses", {"model": "c3r-core", "input": "Reply briefly: ready."})
        evidence.append({"drill": "clm_outage", "readiness": outage,
                         "ranking": ranking, "text_only_policy_fallback": fallback,
                         "passed": outage == 503 and ranking == 503 and fallback == 200})
        docker("start", "c3r-clm")
        stopped.remove("c3r-clm")
        evidence.append({"drill": "clm_recovery", "readiness": ready(200), "passed": True})
        docker("stop", "--time", "10", "c3r-core-private")
        stopped.add("c3r-core-private")
        killed = status("/ready")
        evidence.append({"drill": "operator_kill", "readiness": killed,
                         "passed": killed == "unreachable"})
        docker("start", "c3r-core-private")
        stopped.remove("c3r-core-private")
        evidence.append({"drill": "operator_recovery", "readiness": ready(200), "passed": True})
    finally:
        for name in stopped:
            docker("start", name)
        session.close()
    print(json.dumps({"scope": "private_clm_outage_and_operator_recovery_not_canary",
                      "shared_deepseek_stopped": False, "checks": evidence,
                      "all_passed": all(item["passed"] for item in evidence)}, indent=2))
    if not all(item["passed"] for item in evidence):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
