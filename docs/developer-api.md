# C3R developer API: integration candidate

The API code is under qualification. There is **no qualified public endpoint yet**.
Do not treat these examples, local SDK tests or the release branch as a GA claim.
The host/security gates block public traffic, not API implementation.

## Quickstart and authentication

Use an operator-issued project key, never a GPU/provider secret. Keep it in a
server-side secret manager. Keys have `c3r_sk_test_` or `c3r_sk_live_` prefixes;
the prefix does not certify that a deployment has passed release qualification.
The access store retains only salted key hashes and scoped metadata. A newly
issued plaintext key is shown once and cannot be recovered from the store.

Operator configuration uses `C3R_API_AUTH_MODE=keys` and an absolute
`C3R_API_ACCESS_DB` path on a private persistent volume. The database must be
owned by the runtime UID with mode `0600`, inside a `0700` directory with safe
ancestry. Run `python -m c3r.key_management --help` as the same trusted service
identity to create projects, issue scoped/expiring keys, revoke keys and inspect
project-specific metadata. Deliver the show-once key through a secure channel;
never commit or log its output. `C3R_BACKEND_TOKEN` and the distinct internal
readiness token remain private service credentials, not developer keys.

The production composition defaults to key mode and rejects static staging auth.
Start with one gateway instance: database quotas coordinate against that store,
but route capacity is process-local. Database encryption, durable volumes,
metadata retention/deletion, backup access and multi-instance admission need
deployment evidence before public traffic.

Replace `https://<C3R_API_HOST>` only after an approved managed-TLS gateway exists.

```bash
curl "https://<C3R_API_HOST>/v1/responses" \
  -H "Authorization: Bearer $C3R_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"c3r-core","input":"Recommend the safest next computation.","store":false,"max_output_tokens":512}'
```

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["C3R_API_KEY"],
                base_url=os.environ["C3R_BASE_URL"].rstrip("/") + "/v1")
response = client.responses.create(model="c3r-core", input="Recommend the safest next computation.",
                                   store=False, max_output_tokens=512)
print(response.output_text)
```

```typescript
import OpenAI from "openai";
const client = new OpenAI({ apiKey: process.env.C3R_API_KEY,
  baseURL: `${process.env.C3R_BASE_URL!.replace(/\/$/, "")}/v1` });
const response = await client.responses.create({ model: "c3r-core",
  input: "Recommend the safest next computation.", store: false, max_output_tokens: 512 });
console.log(response.output_text);
```

These examples use the unmodified official SDKs. Supported fields are a bounded
text `input`, `model`, `max_output_tokens`, `store:false`, and `stream`. This is
a Responses text subset, not support for tools, images, background jobs, stored
conversations or every OpenAI API feature. See the
[official streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses)
for the SDK event-consumption pattern.

## Models and specialist endpoints

| Endpoint | Purpose | Key scope |
| --- | --- | --- |
| `POST /v1/responses` | Controller-admitted, bounded self-hosted text generation | `responses:write` |
| `POST /v1/system-one` | CLM/Qwen typed inference | `system_one:write` |
| `POST /v1/c3r/rank` | Advisory candidate ranking | `rank:write` |
| `POST /v1/c3r/decide` | Governed recommendation | `decide:write` |
| `GET /v1/models` | Availability of `c3r-core`, `c3r-system-one`, `c3r-verifier` | `models:read` |
| `POST /v1/c3r/execute` | Unsupported remote effects | Always disabled, HTTP 501 |

Model availability is health-derived, not a training/calibration assertion. The
verifier ID does not grant remote execution authority. Ranking remains
`calibrated:false` and `advisory_only`; generation does not claim positive learned
CVoC when it uses the explicit text-only policy fallback.

System One accepts a typed question catalog:

```json
{"model":"c3r-system-one","state":"Payment was duplicated","questions":{"department":{"type":"choice","options":{"billing":"Billing","technical":"Technical"}},"urgent":{"type":"boolean"}}}
```

Ranking accepts bounded candidates:

```json
{"state":"Latency increased","candidates":["inspect queue depth","restart service","increase GPU count"]}
```

Decide accepts task text; action definitions, authority, verifiers and estimates
come from the trusted host, never caller-supplied permissions:

```json
{"goal":"Inspect the incident","current_subgoal":"Choose a safe read-only computation"}
```

The result exposes route, reason category, authority result, conservative CVoC
decision and a trace hash, with `effect_executed:false`. Private reasoning is not
returned. No arbitrary action can be executed by this v0.1 API.

## Streaming

For `/v1/responses`, set `stream:true`. SSE events include `response.created`,
`response.output_text.delta`, `response.output_text.done`, `response.completed`
or `response.failed`. Consume deltas rather than provider reasoning fields.
Closing a stream must cancel the upstream connection and release admission
capacity; cancellation is part of local acceptance and still needs live-provider
qualification. A failed stream is not a completed billable success.

```python
with client.responses.create(model="c3r-core", input="Recommend a safe computation.",
                             stream=True) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
```

## Organizations, projects and limits

Each key belongs to one organization/project and has explicit scopes, expiration
and revocation. The gateway resolves those identities and a generated
`x-request-id` before forwarding. Caller identity headers cannot change tenancy.
There is no public credential-issuance or cross-tenant administration endpoint.

Project RPM, key RPS and route concurrency are separate admission controls.
Bodies and output token counts are bounded. Saturated requests receive HTTP 429,
not an unbounded generation queue. Configured defaults are **not a measured GPU
safe envelope**. Multi-replica quota coordination and the eight-H100 operating
envelope must be qualified before horizontal gateway deployment.

## Errors and request IDs

Developer-key mode uses an error object with `message`, `type`, `code`, `param`
and `request_id`. Every gateway response includes a generated `x-request-id`.
Use this identifier for support; never send a key, prompt or private output.

| HTTP | Meaning |
| --- | --- |
| 400/413/415 | Invalid request, size or content type |
| 401 | Invalid, expired or revoked key |
| 403 | Key lacks endpoint permission |
| 404 | Unsupported route, including `/internal/*` |
| 429 | Rate or capacity exceeded |
| 500/503 | Internal or dependency failure |

`501` remains intentional for `/v1/c3r/execute`. Legacy private staging mode
retains its existing error/auth contract and must not be mistaken for public
developer-key mode.

## Security, privacy and usage

`store:false` is mandatory. Infrastructure/application logging must exclude
prompt bodies, responses, candidates, CLM state and reasoning. The gateway emits
metadata-only usage: request/tenant/project/key identity, route, model, status,
latency and provider-reported token counts where available. Unknown GPU time or
cost stays unknown, never fabricated or used as an exact billing claim.
Exact per-model billing and System-One invocation metering still require measured
runtime integration and a governed metadata retention policy.

Only the managed-TLS gateway may be public. Core, CLM, Qwen, DeepSeek and the
separate authenticated `127.0.0.1` internal readiness channel remain private.
The gateway never forwards `/internal/*`. TLS, network isolation, database
encryption/backups, read/export auditing and alerting are deployment controls;
local tests cannot establish them.

## Acceptance, status and changelog

Local SDK acceptance lives in `tests/test_official_sdk_acceptance.py`. It uses
real C3R HTTP composition and fixture generation, not a GPU qualification run.
The optional unmodified Python and JavaScript SDKs must both be installed to
exercise both tests; a skipped SDK test is not a compatibility PASS.

No availability SLO or public status page is claimed yet. After host approval,
measure three cold starts, 15/30/60-minute mixed traffic, percentiles, TTFT,
tokens/sec, capacity refusals and dependency/rollback drills. Release owner and
independent reviewer must approve exact commits, images and canary evidence.

Candidate changelog: deliberately reconciled PR/readiness lineage; private
worker-aware readiness; hash-only developer keys and tenancy; metadata-only
admission/usage; streaming and SDK acceptance under qualification. No production
tag or public promotion is implied.
