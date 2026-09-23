# Cloud Run staging decision (not a deployment record)

C3R's selected standalone hostname strategy is the Google-managed HTTPS URL that
Cloud Run assigns to a service. A custom domain is optional. **No C3R Cloud Run
service has been deployed**, so this document does not claim a URL, live model route,
or completed canary. The first deployment must require IAM authentication; making
it public is a separate release action after qualification.

## Preconditions before creating a service

1. The user designated ColomboAI's `@wilkont` account as interim deployment and
   release owner in the [internal-task policy](internal-task-trace-policy.md). Name
   a reachable on-call and rollback contact before hosting traffic.
2. Implement the approved internal-task trace policy: source registry, field
   allowlist, redaction tests, 30-day private deletion including backups, access
   audit, and publication review. The approved scope is only redacted telemetry
   from C3R-controlled internal tasks in private shadow/canary tests; it excludes
   customer and product traffic. Written approval alone does not enable collection.
3. Supply a calibrated, host-owned *pre-decision* estimate source. Example or
   constant values must not be presented as measured production CVoC inputs.
4. Add a durable trace store, independent ledger-head anchor, backup and deletion
   procedure, monitoring, alert thresholds, request budget, and a kill switch.
5. Package the tested `C3RIngressServer` with the loopback `C3RHTTPServer` in one
   container. The ingress can listen on `0.0.0.0:$PORT`, while the backend retains
   its loopback-only invariant. It allowlists `/health`, `/metrics`, and
   `/v1/decisions`, requires a separate client token for protected routes, replaces
   caller credentials with a distinct backend token, and caps body size, response
   size, request rate, concurrency, and upstream wait time. Local tests cover these
   boundaries and backend failure; no Cloud Run image or service has been built.
   Bind this ingress only behind Cloud Run's IAM/TLS boundary at staging, with
   tokens from Secret Manager. Do not publish it as a raw unauthenticated port.
6. Establish a private, authenticated service-to-service route to the GPU model;
   never publish the model's localhost inference port. Verify the model checkpoint
   backup before any GPU VM lifecycle change.

The ingress code is a transport boundary, not a deployment composition or a
production authorization system. A container entrypoint, host-owned measured
estimates, durable ledger storage, secret rotation, and end-to-end Cloud Run tests
remain necessary before staging traffic.

## Staged promotion

| Stage | Access and effect authority | Evidence required to advance |
| --- | --- | --- |
| Offline replay | No cloud endpoint or external effects | Reproducible internal-task pairs, source manifest, independent outcomes and held-out partition. |
| Private shadow | IAM-protected HTTPS URL; recommendation-only; internal tasks | Auth, rate-limit, redaction, ledger, provider-outage, rollback and kill-switch traces. |
| Private read-only canary | Restricted invokers; no external effects | Predeclared latency/cost/safety thresholds and independently reviewed run evidence. |
| Public read-only launch | Explicit public-access approval; still no external effects | Security review, owner/on-call, abuse controls, reproducible empirical claims, release-copy audit. |
| Reversible effects | Separate authority and approval | Complete mediation and reversible canary evidence. Not implied by the public read-only launch. |

Keep the Hugging Face model and dataset labeled as previews until trained weights,
empirical data, held-out calibration, and reproducible evaluation artifacts exist.
MC-1 remains outside the standalone launch scope, not complete under the directive.

Cloud Run references: [HTTPS service URL and invoking services](https://docs.cloud.google.com/run/docs/triggering/https-request),
[IAM service authentication](https://docs.cloud.google.com/run/docs/authenticating/overview),
[public versus authenticated deployment](https://docs.cloud.google.com/run/docs/deploying),
and [container listening contract](https://docs.cloud.google.com/run/docs/container-contract).
