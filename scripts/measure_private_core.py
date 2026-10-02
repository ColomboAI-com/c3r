"""Pilot load probe: aggregate synthetic-request timings, never training traces.

Admission responses are reported, not misrepresented as successful inference.
This short run is neither a sustained SLO test nor a public canary.
"""
import concurrent.futures
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import requests


def main():
    config = dict(line.split("=", 1) for line in (
        Path.home() / ".c3r-private-inference" /
        os.environ.get("C3R_PROBE_CONFIG", "candidate-v3.env")).read_text().splitlines())
    token = config["C3R_CLIENT_TOKEN"]
    base = "http://127.0.0.1:" + config.get("PORT", "8088")

    def call(_):
        session = requests.Session()
        session.trust_env = False
        started = time.monotonic()
        try:
            response = session.post(base + "/v1/c3r/rank", headers={
                "Authorization": "Bearer " + token}, json={
                "state": "An invoice was charged twice.",
                "candidates": ["Billing", "Technical"]}, timeout=15)
            status = str(response.status_code)
        except requests.RequestException:
            status = "transport_failure"
        finally:
            session.close()
        return status, (time.monotonic() - started) * 1000

    profiles = []
    for concurrency in (1, 10, 25, 50, 100):
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(call, range(concurrency)))
        elapsed = time.monotonic() - started
        successful = sorted(latency for status, latency in results if status == "200")
        counts = dict(Counter(status for status, _ in results))
        profile = {"concurrency": concurrency, "requests": len(results),
                   "statuses": counts, "elapsed_seconds": round(elapsed, 3),
                   "successful_requests_per_second": round(len(successful) / elapsed, 3),
                   "successful_p50_ms": None if not successful else round(
                       successful[(len(successful) - 1) // 2], 2),
                   "successful_p95_ms": None if not successful else round(
                       successful[math.ceil(len(successful) * .95) - 1], 2)}
        profiles.append(profile)
        # Predeclared abort: transport failure or unexpected server failures.
        if any(status not in {"200", "429", "503"} for status in counts):
            print(json.dumps({"scope": "private_synthetic_load_pilot", "aborted": True,
                              "profiles": profiles}, indent=2))
            raise SystemExit(1)
    print(json.dumps({"scope": "private_synthetic_load_pilot_not_slo_or_canary",
                      "currency_cost": "unqualified_no_billing_allocation",
                      "profiles": profiles}, indent=2))


if __name__ == "__main__":
    main()
