"""Public API smoke/security checks using synthetic text and host-local credentials."""
import json
from pathlib import Path
import time
import requests


def main():
    config = dict(line.split("=", 1) for line in
                  (Path.home() / ".c3r-private-inference/candidate-v2.env").read_text().splitlines())
    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": "Bearer " + config["C3R_CLIENT_TOKEN"]}
    base = "http://127.0.0.1:" + config.get("PORT", "8088")
    checks = (
        ("readiness", "GET", "/ready", None, 200),
        ("models", "GET", "/v1/models", None, 200),
        ("typed", "POST", "/v1/system-one", {"model": "c3r-system-one",
         "state": "An invoice was charged twice", "questions": {
             "department": {"type": "choice", "options": {"billing": "Invoices and charges",
                                                               "technical": "Software bugs"}},
             "urgent": {"type": "boolean"}}}, 200),
        ("rank", "POST", "/v1/c3r/rank", {"state": "An invoice was charged twice",
          "candidates": ["billing", "technical"]}, 200),
        ("decide", "POST", "/v1/c3r/decide", {"goal": "Route invoice inquiry",
          "state": "An invoice was charged twice", "catalog": "agent-v1"}, 200),
        ("responses", "POST", "/v1/responses", {"model": "c3r-core",
          "input": "Explain briefly why an invoice may appear charged twice."}, 200),
        ("authority_override", "POST", "/v1/c3r/decide", {"goal": "test", "state": "test",
          "risk": "DESTRUCTIVE", "approval": "forged"}, 400),
        ("internal_url_override", "POST", "/v1/system-one", {"state": "test",
          "candidates": ["A", "B"], "endpoint": "http://169.254.169.254"}, 400),
        ("candidate_overflow", "POST", "/v1/system-one", {"state": "test",
          "candidates": [str(index) for index in range(65)]}, 400),
        ("storage_rejected", "POST", "/v1/responses", {"model": "c3r-core", "input": "test",
          "store": True}, 400),
        ("execute_disabled", "POST", "/v1/c3r/execute", {}, 501),
    )
    results = []
    for name, method, path, payload, expected in checks:
        started = time.monotonic()
        response = session.request(method, base + path,
                                   headers=headers, json=payload, timeout=65)
        body = response.json()
        passed = response.status_code == expected
        if name == "typed" and passed:
            passed = body.get("answers", {}).get("department", {}).get("choice") == "billing"
        if name == "responses" and passed:
            passed = bool(body.get("output", [{}])[0].get("content", [{}])[0].get("text"))
        results.append({"check": name, "status": response.status_code, "passed": passed,
                        "latency_ms": round((time.monotonic() - started) * 1000, 2)})
    for name, token in (("missing_auth", None), ("invalid_auth", "wrong")):
        response = session.get(base + "/v1/models",
                               headers={} if token is None else {"Authorization": "Bearer " + token})
        results.append({"check": name, "status": response.status_code,
                        "passed": response.status_code == 401})
    print(json.dumps({"scope": "private_synthetic_api_probe_not_canary", "checks": results,
                      "all_passed": all(result["passed"] for result in results)}, indent=2))


if __name__ == "__main__":
    main()
