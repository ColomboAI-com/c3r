# C3R Core API v1: stateless inference contract

This is a **separate release scope** from governed research collection. It may
serve read-only, verified recommendations using the upstream CLM ranker without
C3R-trained weights or an empirical DecisionMix release. It does **not** confer
permission to execute external effects or make calibrated success claims.

## Operating modes

`C3R_MODE=production_inference` fails startup unless the trusted host enables
decisions, rejects external effect execution, and uses the in-process
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

The external ingress requires `X-C3R-Token` behind a TLS/IAM boundary; the
loopback backend uses a different bearer token. Requests are JSON objects and
bounded to 64 KiB. The trusted host owns the action catalog, policy, verifier,
measured CVoC estimates, and provider connectivity. Callers cannot override
those fields.

| Route | Contract |
| --- | --- |
| `GET /health` | Process liveness only. |
| `GET /ready` | Authenticated. Returns 503 until decisions are enabled **and** the host's provider probe succeeds. It is not a complete launch attestation. |
| `GET /v1/models` | Authenticated model-like discovery of `c3r-core` and `c3r-system-one`, each labeled non-generative and uncalibrated. Availability follows the provider probe. |
| `POST /v1/c3r/decide` | Runs the controller and returns a read-only recommendation or explicit fallback. |
| `POST /v1/c3r/rank` | Same safe controller path, plus available advisory candidate scores. No score is represented as probability of task success. |
| `POST /v1/system-one` | Same controller path with System-One status and fallback. This is **not** arbitrary typed-question inference. |
| `POST /v1/c3r/execute` | Returns 501. External effects are unsupported. |
| `POST /v1/responses` | Returns 501. This release is not OpenAI Responses API-compatible and CLM is not a text generator. |

`POST /v1/decisions` remains the compatibility route. Example:

```http
POST /v1/c3r/decide
Content-Type: application/json
X-C3R-Token: <client-secret>

{"goal":"Find record","current_subgoal":"Search approved index"}
```

The response includes `selected_action_id`, `route`, `reason`,
`authority_result`, `effect_executed: false`, and a request-local `trace_hash`.
A ranking response additionally includes `candidate_ranking` entries with
`system_one_score` and `calibrated: false`. An empty ranking and abstention are
normal when CLM is unavailable or control questions lack held-out calibration.
Raw CLM scores cannot safely be converted into task-success probabilities by a
fixed cap; CVoC remains driven by trusted, measured host estimates.

## Production gates

This repository currently has no trusted production host catalog/estimate
source, live CLM/Qwen provider deployment, approved dedicated public hostname,
or production canary. Before public traffic, qualify:

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
