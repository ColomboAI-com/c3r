# C3R deployment (control plane)

Declarative, reproducible config for the `c3r-core` container. The GPU model
backends (DeepSeek, CLM, Qwen) are separate containers and are not managed here.

## Build
```bash
git clone --branch dev https://github.com/ColomboAI-com/c3r.git
docker build -t c3r-core:dev c3r
# Postgres backend (scale-out) also needs the driver in the image:
#   add `RUN pip install pg8000` to the Dockerfile, or build with the postgres extra.
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
