# C3R deployment (control plane)

Declarative, reproducible config for the `c3r-core` container. The GPU model
backends (DeepSeek, CLM, Qwen) are separate containers and are not managed here.

## Build
```bash
git clone --branch dev https://github.com/ColomboAI-com/c3r.git
docker build -t c3r-core:dev c3r
# The API image includes hash-pinned PostgreSQL runtime dependencies.
# No package installation is performed at container startup.
```

## Configure
```bash
cp deploy/c3r-core.env.example deploy/c3r-core.env
# set C3R_BACKEND_TOKEN=$(openssl rand -hex 32)
chmod 600 deploy/c3r-core.env     # never commit the real env file
```

## Run
```bash
docker compose -f deploy/docker-compose.yml up -d
curl -fsS http://127.0.0.1:8088/health
```

## nginx (TLS vhost) security headers
The `c3r.colomboai.com` server block proxies to `127.0.0.1:8088` and SHOULD add:
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer" always;
```

## Rollback
```bash
docker rm -f c3r-core-private
docker rename c3r-core-private-prev c3r-core-private && docker start c3r-core-private
# or pin a known-good image: c3r-core-private:prev-dev / :prev-pr7
```

## Keys
```bash
docker exec c3r-core-private python -m c3r.key_management \
  --database /data/access/access.sqlite3 issue --tenant <t> --project <p> \
  --scope responses:write --scope system_one:write --scope rank:write \
  --scope decide:write --scope models:read --live --ttl-seconds 31536000
```
Deliver the printed key via a secret store, never chat/logs.

For the optional PostgreSQL backend, install the `postgres` extra and inject
`C3R_API_ACCESS_DSN` through the approved secret store. Serving and administration
must select the same backend and database. Do not pass a DSN on the command line:

```bash
python -m c3r.key_management --backend postgres --dsn-env C3R_API_ACCESS_DSN \
  project --tenant <t> --project <p>
python -m c3r.key_management --backend postgres --dsn-env C3R_API_ACCESS_DSN \
  issue --tenant <t> --project <p> --scope models:read --scope responses:write
python -m c3r.key_management --backend postgres --dsn-env C3R_API_ACCESS_DSN \
  purge --tenant <t> --project <p> --retention-seconds 2592000
```

The backend also defaults from `C3R_API_ACCESS_BACKEND` when set. PostgreSQL
commands reject `--database` to prevent silently administering a SQLite file.
The SQLite `backup`/`restore` commands do not support PostgreSQL; qualify its
database backup, deletion and recovery procedure separately. Local parity tests
do not qualify a deployed database, TLS, backups, IAM or production traffic.

## PostgreSQL transport

The packaged driver is pinned with every transitive universal wheel in
`deploy/requirements-postgres.lock`. Connection strings default to certificate-
and hostname-verified TLS (`sslmode=verify-full`), with no plaintext fallback.
For a private database CA, add `sslrootcert=/run/c3r/database-ca.pem` and mount
that public CA certificate read-only. The key-administration CLI uses the same
transport policy as the API.

`sslmode=disable` is permitted only when explicitly selected for a literal
loopback address or `localhost`, such as an approved local encrypted proxy or
a disposable test database. This setting does not itself qualify that proxy.
Remote plaintext, weak TLS modes, duplicate/unknown query options and empty
certificate paths are refused. Passwords belong in the approved secret channel,
not shell history or source control.

A built image and local database tests do not establish production database
IAM, at-rest encryption, recoverability, network admission or runtime readiness.
Those remain deployment gates. Keep research collection and online learning off.

## Local packaged-image qualification

With Docker, Bash, Python and OpenSSL available, build the API image and run:

```bash
bash deploy/qualify_postgres_image.sh --run-local c3r-core:dev
```

This creates two disposable PostgreSQL fixtures on a network-isolated local
Docker engine, without host ports. It runs the repository tests inside the
actual API image, checking trusted TLS, wrong-host/untrusted/plaintext refusal,
scoped keys, quotas and payload-free metadata. Test authentication is deliberately
fixture-only, not a production database policy. Only public test files and a
throwaway public CA certificate are mounted into the API container. The generated
fixture key and owned containers are removed; cleanup failure fails qualification.
The test-app run is bounded to 180 seconds. No GCP resource or GPU service is used.

CI runs this qualification before image scans and artifact preservation. A local
pass is still not approval to deploy or evidence of a live production database.
