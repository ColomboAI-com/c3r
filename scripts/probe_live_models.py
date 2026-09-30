"""Non-sensitive loopback inference drill. Does not store task traces."""
import json
import time
import requests


def main():
    session = requests.Session()
    session.trust_env = False
    probes = (
        ("clm", "http://127.0.0.1:8700/v1/rank", {
            "model": "clm-latest", "context": "The customer was charged twice for an invoice.",
            "question": "Which department handles this request?",
            "answers": ["Billing: invoices and charges", "Technical: software bugs"],
        }),
        ("deepseek", "http://127.0.0.1:8000/v1/chat/completions", {
            "model": "/model", "max_tokens": 512, "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with one sentence: what is an invoice?"}],
        }),
    )
    for name, url, payload in probes:
        started = time.monotonic()
        response = session.post(url, json=payload, timeout=60, allow_redirects=False)
        body = response.json()
        if name == "deepseek":
            # Never record the reasoning field, even for a synthetic probe.
            choices = body.get("choices", [])
            body = {"final_text": choices[0].get("message", {}).get("content") if choices else None,
                    "finish_reason": choices[0].get("finish_reason") if choices else None,
                    "usage": body.get("usage")}
        print(json.dumps({"provider": name, "status": response.status_code,
                          "latency_ms": round((time.monotonic() - started) * 1000, 2),
                          "result": body}), flush=True)


if __name__ == "__main__":
    main()
