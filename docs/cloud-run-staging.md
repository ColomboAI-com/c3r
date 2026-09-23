# Cloud Run private staging deployment (fixed-disabled)

C3R's selected standalone hostname strategy is the Google-managed HTTPS URL that
Cloud Run assigns to a service. A custom domain is optional. A **private,
fixed-disabled staging boundary** is deployed at
`https://c3r-staging-795563500003.us-central1.run.app`. It is not a live model
route, governed trace collector, canary, or production service. Cloud Run IAM
authentication is required; public access is a separate release action after
qualification.

On 2026-09-23, the `columboai-frontend` project received a dedicated
`c3r-staging-runtime` service account with no user-managed keys or project roles,
and a private, immutable-tag Docker repository at
`us-central1-docker.pkg.dev/columboai-frontend/c3r-staging`. Its repository IAM
policy has no public binding; Google-managed encryption is reported. Cloud Build
`b25dcb33-5553-4c6d-bc88-1541bfb299bc` built the initial runtime-only source
and pushed digest `sha256:14b88f22a839fc123d639e3a96c29f3b2242ee443174fedd637665d64a872a2f`.
That first image predates the disabled staging host and has **not** been deployed.
The `.gcloudignore` upload manifest was checked to include only the Dockerfile,
`.dockerignore`, and `c3r/` Python source; no data, evidence, papers, or Git metadata.
Registry creation and image publication do not verify service behavior, storage,
retention, alerting, or release readiness.

Cloud Build `d70f1263-a60e-489c-958f-36436ab2875a` published the fixed-disabled
staging host at digest
`sha256:60d4daf25d879c41892a3b1b5fc84638d7289ca75a191059858dd183f1aa1209`.
Cloud Run service `c3r-staging` in `us-central1` runs this digest under the
dedicated service account, with one maximum instance, zero minimum instances,
and no explicit public invoker binding. Its two distinct tokens are pinned
Secret Manager references; values are not in Git or this record. Direct
unauthenticated `/health` returned 403, IAM-authenticated `/health` returned
200, an IAM-only decision request returned 401, and a request with both IAM
and C3R token returned `C3R_DISABLED`, no selected action, and no effect.
The [deployment evidence](../evidence/staging-deployment-v1/report.json) records
these checks without credentials or request bodies.

`c3r.staging_host:build` is an intentionally fixed-disabled, recommendation-only
boundary smoke host. It cannot be turned into a production decision service by
environment flags, performs no external effects or provider calls, and retains no
trace rows. An authenticated private deployment can use it to exercise ingress,
IAM/TLS, startup, monitoring, and rollback, but **not** to collect empirical data
or qualify C3R decisions. A separately reviewed host with measured pre-decision
estimates, durable governed storage, and approved source registry is required later.

An independent, empty C3R trace bucket and retention purge job now exist in
staging. The bucket is not mounted or granted to `c3r-staging`; the purge job's
service account has only bucket-scoped list/delete authority. A 28-day lifecycle
delete rule and daily UTC scheduler are configured, and direct and scheduler-
triggered empty-bucket purges completed. The [retention staging record](../evidence/private-retention-staging-v1/report.json)
distinguishes these observations from the first natural daily run, expired
object/backup deletion, effective inherited IAM, and access auditing. Nothing
about this bucket enables trace collection or production qualification.

## Controls still required before live collection or promotion

1. Wilfried Kouadio (`@wilkont`) is the interim deployment/release owner and
   confirmed interim on-call/rollback operator in the
   [internal-task policy](internal-task-trace-policy.md). Verify the work-email
   alert route and acknowledgement before live internal-task traffic. A C3R-only
   Cloud Monitoring email channel and 5xx policy now exist. Wilfried reported
   receiving and acknowledging a staging drill alert on 2026-09-23; an
   automated mailbox delivery audit and incident response timing remain open.
2. Implement the approved internal-task trace policy: source registry, field
   allowlist, redaction tests, 30-day private deletion including backups, access
   audit, and publication review. The approved scope is only redacted telemetry
   from C3R-controlled internal tasks in private shadow/canary tests; it excludes
   customer and product traffic. Written approval alone does not enable collection.
3. Supply a calibrated, host-owned *pre-decision* estimate source. Example or
   constant values must not be presented as measured production CVoC inputs.
4. Add a durable trace store, independent ledger-head anchor, backup and deletion
   procedure, monitoring, alert thresholds, request budget, and a kill switch.
5. The repository now includes a fail-closed `Dockerfile` and `python -m c3r.serve`
   composition for the tested `C3RIngressServer` and loopback `C3RHTTPServer`.
   The ingress listens on `0.0.0.0:$PORT`, while the backend retains
   its loopback-only invariant. It allowlists `/health`, `/metrics`, and
   `/v1/decisions`, requires a separate client token for protected routes, replaces
   caller credentials with a distinct backend token, and caps body size, response
   size, request rate, concurrency, and upstream wait time. Local tests cover these
   boundaries, backend failure, and local server composition. GitHub CI has
   built and HIGH/CRITICAL-scanned the digest-pinned staging image with zero
   findings in [run 70](https://github.com/ColomboAI-com/c3r/actions/runs/35879315503).
   This scan does not qualify lower severities or deployed controls.
   Bind this ingress only behind Cloud Run's IAM/TLS boundary at staging, with
   tokens from Secret Manager. Do not publish it as a raw unauthenticated port.
6. Establish a private, authenticated service-to-service route to the GPU model;
   never publish the model's localhost inference port. Verify the model checkpoint
   backup before any GPU VM lifecycle change.

`C3R_HOST_ENTRYPOINT=trusted_module:build` is mandatory. The trusted callable must
return a recommendation-only `StandaloneController` and a `RequestFactory` whose
estimate source uses measured, pre-decision values. The container supplies **no**
sample catalog, constant estimates, data collection, or production credentials.
`C3R_CLIENT_TOKEN` and `C3R_BACKEND_TOKEN` are distinct mandatory secrets of at
least 32 characters; `PORT` defaults to 8080 and `C3R_BACKEND_PORT` to 8081.
The currently deployed host is `c3r.staging_host:build`, deliberately
fixed-disabled. A later trusted decision host must be separately reviewed and
deployed. Registry publication and boundary checks are complete only for the
disabled host; durable ledger storage, secret rotation, and live decision tests
remain necessary before governed internal-task traffic.

On 2026-09-23 a second, equivalent disabled revision (`c3r-staging-drill1`)
was deployed, then traffic was explicitly restored 100% to the original
`c3r-staging-00001-zrj` revision. IAM-authenticated `/health` returned 200
after rollback. This proves revision traffic rollback for the disabled staging
host, not incident response timing or a production rollback. Cloud Monitoring
policy `11003571770572095050` watches this service's 5xx request count and
routes to Wilfried's work-email channel. A temporary 2xx notification drill
on 2026-09-23 observed
the authorized health-request metric and opened Monitoring incident
`0.ocyx1hrngr2m` at 15:24:53 UTC, just after the first check and policy
disable. Wilfried subsequently reported receiving and acknowledging the drill
email in his work mailbox. This is operator-reported delivery evidence, not
an automated mailbox audit or response-time SLA test. The drill policy is
disabled; the persistent 5xx policy remains enabled.

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
