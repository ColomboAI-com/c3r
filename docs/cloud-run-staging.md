# Cloud Run staging decision (not a deployment record)

C3R's selected standalone hostname strategy is the Google-managed HTTPS URL that
Cloud Run assigns to a service. A custom domain is optional. **No C3R Cloud Run
service has been deployed**, so this document does not claim a URL, live model route,
or completed canary. The first deployment must require IAM authentication; making
it public is a separate release action after qualification.

## Preconditions before creating a service

1. Name an accountable deployment/release owner and an on-call/rollback contact.
2. Approve an internal-task trace policy: source owner, permitted fields, redaction
   tests, retention/deletion, access, and public-artifact scope. The current user
   authorization allows only redacted telemetry from C3R-controlled internal tasks
   in private shadow/canary tests; it excludes customer and product traffic.
3. Supply a calibrated, host-owned *pre-decision* estimate source. Example or
   constant values must not be presented as measured production CVoC inputs.
4. Add a durable trace store, independent ledger-head anchor, backup and deletion
   procedure, monitoring, alert thresholds, request budget, and a kill switch.
5. Package a trusted ingress adapter. Cloud Run requires the ingress container to
   listen on `0.0.0.0:$PORT`, while `C3RHTTPServer` deliberately binds only to
   loopback. Do not loosen that invariant merely to make a container start. An
   authenticated ingress must forward to the loopback boundary without trusting
   caller-supplied policy, estimates, verification, or approvals.
6. Establish a private, authenticated service-to-service route to the GPU model;
   never publish the model's localhost inference port. Verify the model checkpoint
   backup before any GPU VM lifecycle change.

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
