# API qualification follow-on candidate

This candidate is separate from frozen PR #7 source `7d3a93f`. It is not deployed,
image-qualified or a production approval. External execution remains HTTP 501;
tenant identity remains scoped-key-derived and caller override headers rejected.

The gateway bounds accepted connection workers to 32 by default, before parsing
headers or reading bodies. `C3RIngressServer(max_connections=...)` permits an
operator-tested integer limit from 1 to 4096. Saturation closes the newly accepted
transport without allocating a worker: no identity has been authenticated, so this
is not a tenant usage event or an HTTP 429 guarantee. Existing per-route and global
dispatch limits remain separate. Idle transports time out after five seconds;
these limits are not measured GPU capacity or distributed admission.

Authenticated refusals and observed pre-header disconnects produce at most one
payload-free usage outcome (499 for an observed disconnect). Unknown identities
are not invented. If storage fails, requests fail closed, but durable accounting
cannot be claimed for an unavailable database. Connection refusal is not recorded
as billable model work.

CLM ranking, structured ProviderAdapter deliberation and OpenAI-compatible text generation count request-local transport
attempts at their adapter dispatch boundaries, including attempted failures. SSE
terminal responses carry the same counters. `invocation_basis` is explicitly
`adapter_transport_attempts`: counts are not successful GPU executions, completed
generations, cost allocation, or model labels inferred from routing. Uninstrumented
providers, readiness probes outside request capture and absent upstream metadata
remain unknown; the counters do not cover arbitrary provider internals or retries.
Zero means no instrumented transport attempt in that captured backend request.

The trusted operator CLI adds project-scoped bounded logical deletion:

```text
python -m c3r.key_management --database <absolute-private-path> purge \
  --tenant <approved-tenant> --project <approved-project> \
  --retention-seconds 2592000 --limit 1000
```

Retention is bounded to 60 seconds through 30 days. Each invocation deletes at most
the requested limit per usage/audit table, only for the selected project and only
rows older than its cutoff. Repeat through an approved scheduler until backlog is
cleared; no scheduler is installed by this change. Keys/projects are not deleted.
SQLite secure-delete is enabled for this purge, but the receipt explicitly does
not claim physical erasure or backup/copy deletion. Deployments must independently
inventory and delete database snapshots, replicas, exported metadata, journals and
backups within their approved retention policy. Encryption, IAM, backup restore,
TLS, alerts, external monitoring and live no-payload logging remain deployment
qualification gates, not properties established by these local fixture tests.
