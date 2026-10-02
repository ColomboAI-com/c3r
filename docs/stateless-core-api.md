# C3R Core API v1: stateless inference contract

## Optional internal maintenance readiness channel

The new channel is code-only until separately deployed and qualified. Configure
`C3R_INTERNAL_READY_PORT` and a distinct `C3R_INTERNAL_READY_TOKEN` to start an
additional listener in the same Core process, bound only to `127.0.0.1`.
`GET /internal/ready` requires its own Bearer token; the public ingress does not
forward this route. It uses fresh CLM/Qwen and DeepSeek probes, not cached public
readiness. Authentication or any missing/failed check keeps recovery unqualified.
The runtime check also requires both actual backend and ingress serving workers
to be alive before and after provider probing, and no shutdown request pending.
This is a worker-liveness prerequisite, not proof that every API request works;
the deployment acceptance and recovery drills remain separate requirements.

The production host also requires `C3R_INTERNAL_ARTIFACT_MANIFEST` and its
independently supplied `C3R_INTERNAL_ARTIFACT_MANIFEST_SHA256`. The pinned JSON
schema is `{"schema":"c3r-required-local-files-v1","files":[{"path":"/absolute/file",
"sha256":"<64 lowercase hex characters>","max_bytes":123}]}`. The nonempty list
allows at most 32 non-linked regular files and at most 64 MiB combined declared
byte limits; the manifest itself is limited to 64 KiB. Files are hashed freshly.
The response binds the manifest SHA and explicitly scopes verification to these
local files. Hashing a weight receipt proves only that receipt, **not DeepSeek
weights**. The deployment operator must independently approve the required-file
inventory, bind actual model mounts/images, and verify listener ownership and
root-controlled credential delivery before maintenance can rely on it.

This is a **separate release scope** from governed research collection. It may
serve read-only, verified recommendations using the upstream CLM ranker without
C3R-trained weights or an empirical DecisionMix release. It does **not** confer
permission to execute external effects or make calibrated success claims.

## Operating modes

`C3R_MODE=production_inference` fails startup unless the trusted host enables
decisions and a System-One path, rejects external effect execution, and uses the in-process
`EphemeralTraceSink`. It rejects `C3R_TRACE_COLLECTION=true` and
`C3R_ONLINE_LEARNING=true`. This sink computes a response hash but stores no
trace rows or cross-request chain. Ordinary aggregate counts are allowed;
request bodies, state, options, and tokens are not logged by the HTTP boundary.

`C3R_MODE=research_collection` is a separate future mode. Existing internal-task
admission, retention, reviewer, and publication controls continue to apply
there. Merely setting the mode does not authorize or activate collection.

The default mode is `staging`, preserving existing deployments. No mode
implicitly turns on a provider or grants action authority.

## API

The external ingress supports standard `Authorization: Bearer <token>` for SDK
clients. Private IAM staging also supports a separate `X-C3R-Token`; the
loopback backend uses a different bearer token. Requests are JSON objects and
bounded to 64 KiB. The trusted host owns the action catalog, policy, verifier,
measured CVoC estimates, and provider connectivity. Callers cannot override
those fields.

| Route | Contract |
| --- | --- |
| `GET /health` | Process liveness only. |
| `GET /ready` | Authenticated. Returns 503 until decisions and System-One are enabled **and** the host's provider probe succeeds. It is not a complete launch attestation. |
| `GET /v1/models` | OpenAI-style `object: list`, `data` discovery of `c3r-core`, `c3r-system-one`, and advisory `c3r-verifier`. CLM models are non-generative. No model claims empirical calibration. |
| `POST /v1/c3r/decide` | Runs the controller and returns a read-only recommendation or explicit fallback. |
| `POST /v1/c3r/rank` | Direct, read-only ranking of arbitrary candidate strings. No action catalog is required and nothing is executed. |
| `POST /v1/system-one` | Typed `choice`, `boolean`/`noul`, and ordered `score` questions, or direct candidate ranking. Relative scores are not task-success probabilities or authority. |
| `POST /v1/c3r/execute` | Returns 501. External effects are unsupported. |
| `POST /v1/responses` | Text-only Responses subset for `c3r-core`: string `input`, bounded `max_output_tokens`, `store: false`, `stream: false`. Generation uses local DeepSeek, not CLM. Tools, storage, streaming and other fields are rejected. |

`POST /v1/decisions` remains the compatibility route. Example:

```http
POST /v1/c3r/decide
Content-Type: application/json
Authorization: Bearer <client-secret>

{"goal":"Find record","current_subgoal":"Search approved index"}
```

The response includes `selected_action_id`, `route`, `reason`,
`authority_result`, `effect_executed: false`, and a request-local `trace_hash`.
A direct ranking response includes `ranked` entries with `candidate` and
`score`, plus `calibrated: false` and `scope: advisory_only`. Provider failure
returns 503; invalid or over-budget requests return 400.
Raw CLM scores cannot safely be converted into task-success probabilities by a
fixed cap. The host currently supplies **no positive quality estimates**; governed
decisions stop when conservative CVoC is non-positive. For an explicit text-only
Responses request, the host may select the admitted DELIBERATE candidate as a
named policy fallback after independent read-only verification. This is not a
positive learned CVoC claim. Generation stays inside the controller, honors its
enable flags, and cannot execute effects.

```json
{"model":"c3r-system-one","state":"An invoice was charged twice",
 "questions":{"department":{"type":"choice","options":{
   "billing":"Invoices and charges","technical":"Software bugs"}},
   "urgent":{"type":"boolean"}}}
```

System-One budgets: 32 KiB state, at most 16 questions and 64 total options;
candidate strings are unique and at most 1024 characters. Responses accepts at
most 4096 characters / 16 KiB input and 2048 output tokens. `c3r-verifier` is an
advisory ranker, not the independent authority verifier.

## Production composition

`C3R_HOST_ENTRYPOINT=c3r.production_host:build` constructs the real compiler,
host-owned registry, advisory CLM ranking, CVoC, independent verifier, ephemeral
sink, and text-generation path. `C3R_DELIBERATIVE=true` is required. The general,
browser, research and tool-routing catalogs contain recommendations only;
retrieval and browser/tool execution are not implemented capabilities.

CLM source, Qwen revision and head revision/hash are pinned. The loopback CLM
wrapper checks loaded head and encoder files at startup, disables its embedding
and action caches, and exposes `/internal/clm/artifact`. Its container identity
is a **deployment-host readback**, not a cryptographic remote attestation.
Encoder checks use immutable upstream Git-blob/LFS identities, not hashes trusted
from the local manifest. `deploy/attest_encoder.py` independently checks the
running encoder's mounted files, read-only mount and immutable container image.
Readiness compares artifact pins and runs actual CLM ranking and bounded DeepSeek
generation. Checks coalesce for 15 seconds; only booleans and expiry timestamps
are cached. Model discovery reports ranking availability independently of
DeepSeek. Disable switches take effect immediately before typed inference, not
after the health-cache expires.

## Production gates

The private candidate has returned real CLM rankings and DeepSeek text through
the assembled API. This is **not a public production launch**. Public TLS routing,
complete image scanning, sustainable load/SLO measurements, outage and rollback
drills, canary evidence, and release authorization must still be qualified.
Deployment cost/quality estimates must not be described as measured until their
evidence exists. Before public traffic, qualify:

The CPU head candidate built with `deploy/Dockerfile.clm-hardened` and the
reviewed API image passed fresh HIGH/CRITICAL scans. Use that hardened build
recipe for the head; `deploy/Dockerfile.clm` is the unqualified baseline recipe,
not a production recommendation. This does **not** clear the separate Qwen and
shared DeepSeek model-serving image. Its scan findings still require review or
remediation. The short private load pilot and CLM outage/operator recovery drills
are recorded in private evidence; they are not sustained SLOs or public canaries.

1. Immutable CLM and Qwen encoder artifacts, provider health/timeout/fallback,
   and revision attestations.
2. Host-supplied catalog, measured estimates, read-only verifier, data-boundary
   policy, and tenant isolation. Prove high-risk and forged-authority rejection.
3. TLS, authentication, authorization, secrets, least-privilege runtime IAM,
   rate/size/concurrency limits, and no payload retention in application and
   infrastructure logs.
4. Independent build/tests, vulnerability scan, load and outage tests, live
   application acceptance, alert delivery, rollback, and staged canary with
   predeclared abort thresholds.
5. Accountable release-owner approval against the evidence. Research collection
   or C3R-specific training is not a prerequisite for this **stateless** scope.

Until those gates pass, neither `/health` nor local unit tests imply a live
production service. MC-1 integration is explicitly excluded; the first public
endpoint must be dedicated to C3R.
