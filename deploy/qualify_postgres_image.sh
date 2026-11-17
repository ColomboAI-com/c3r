#!/usr/bin/env bash
# Local disposable fixture only; no deployment or production credentials.
set -euo pipefail
if [[ "$#" != 2 || "$1" != --run-local ]]; then
  echo 'Usage: qualify_postgres_image.sh --run-local IMAGE' >&2
  exit 2
fi
image="$2"
[[ "$image" != -* && -n "$image" ]] || exit 2
export MSYS_NO_PATHCONV=1
endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
case "$endpoint" in
  unix:///var/run/docker.sock|npipe:////./pipe/dockerDesktopLinuxEngine) ;;
  *) echo 'Only the local qualification engine is admitted' >&2; exit 2 ;;
esac
# Bind every operation to the endpoint checked above, even if context state changes.
docker() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
    docker --host "$endpoint" "$@"
}
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$root"
api_id="$(docker image inspect --format '{{.Id}}' "$image")"
[[ "$api_id" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 2
pg_image='postgres@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f'
if ! docker image inspect "$pg_image" >/dev/null 2>&1; then
  docker pull "$pg_image" >/dev/null
fi
run_id="$(python -c 'import uuid; print(uuid.uuid4().hex)')"
scratch="$(mktemp -d -t c3r-pg-fixture.XXXXXXXX)"
tls_name="c3r-pg-${run_id}-tls"
plain_name="c3r-pg-${run_id}-plain"
api_name="c3r-pg-${run_id}-api"
cleanup() {
  original_status="$?"
  trap - EXIT
  cleanup_status=0
  for name in "$api_name" "$plain_name" "$tls_name"; do
    if id="$(docker inspect --format '{{.Id}}' "$name" 2>/dev/null)"; then
      owner="$(docker inspect --format '{{index .Config.Labels "io.c3r.fixture"}}' "$id")" || cleanup_status=1
      if [[ "${owner:-}" == "$run_id" ]]; then
        docker rm --force --volumes "$id" >/dev/null || cleanup_status=1
      else
        cleanup_status=1
      fi
    fi
  done
  if remaining="$(docker ps --all --quiet --no-trunc --filter "label=io.c3r.fixture=$run_id")"; then
    [[ -z "$remaining" ]] || cleanup_status=1
  else
    cleanup_status=1
  fi
  rm -f -- "$scratch/server.key" "$scratch/server.crt" || cleanup_status=1
  rmdir -- "$scratch" || cleanup_status=1
  if [[ "$cleanup_status" == 0 ]]; then
    echo POSTGRES_FIXTURE_CLEANUP_PASS
  else
    echo POSTGRES_FIXTURE_CLEANUP_FAILED >&2
    exit 1
  fi
  exit "$original_status"
}
trap cleanup EXIT
stage=certificate
trap 'echo "POSTGRES_FIXTURE_STAGE_FAILED:$stage" >&2' ERR
host_path() {
  if [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]]; then
    cygpath -aw -- "$1"
  else
    realpath -- "$1"
  fi
}
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj /CN=c3r-owned-postgres-fixture -addext subjectAltName=IP:127.0.0.1 \
  -keyout "$(host_path "$scratch/server.key")" -out "$(host_path "$scratch/server.crt")" >/dev/null
fixture_mount="type=bind,source=$(host_path "$scratch"),target=/certs,readonly"
common=(--detach --label "io.c3r.fixture=$run_id" --memory 384m --cpus 1
  --tmpfs /var/lib/postgresql/data:rw,size=256m --tmpfs /tmp:rw,size=16m
  --env POSTGRES_HOST_AUTH_METHOD=trust)
stage=tls-fixture
tls_id="$(docker run "${common[@]}" --name "$tls_name" --network none \
  --mount "$fixture_mount" "$pg_image" sh -c \
  'cp /certs/server.key /tmp/server.key && chmod 600 /tmp/server.key && chown postgres:postgres /tmp/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/certs/server.crt -c ssl_key_file=/tmp/server.key')"
stage=plaintext-fixture
plain_id="$(docker run "${common[@]}" --name "$plain_name" --network "container:$tls_id" \
  "$pg_image" postgres -p 5433 -c ssl=off)"
stage=fixture-readiness
for pair in "$tls_id:5432" "$plain_id:5433"; do
  ready=false
  for attempt in {1..50}; do
    if docker exec "${pair%:*}" pg_isready -h 127.0.0.1 -p "${pair##*:}" -U postgres >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 0.2
  done
  [[ "$ready" == true ]] || { echo 'Fixture readiness failed' >&2; exit 1; }
done
mounts=()
for directory in tests; do
  mounts+=(--mount "type=bind,source=$(host_path "$root/$directory"),target=/app/$directory,readonly")
done
for file in scripts/run_controlled_pairs.py scripts/run_trace_control_dry_run.py \
  .github/scripts/secret_summary.py deploy/deepseek-v41/launch.py deploy/deepseek-v41/h100-production.env; do
  mounts+=(--mount "type=bind,source=$(host_path "$root/$file"),target=/app/$file,readonly")
done
ca='sslmode=verify-full&sslrootcert=/fixtures/ca.pem'
stage=container-test-suite
timeout --signal=TERM --kill-after=10s 180s env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH docker --host "$endpoint" run --rm --name "$api_name" \
  --label "io.c3r.fixture=$run_id" --network "container:$tls_id" --read-only \
  --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,size=128m "${mounts[@]}" \
  --mount "type=bind,source=$(host_path "$scratch/server.crt"),target=/fixtures/ca.pem,readonly" \
  --env "C3R_TEST_PG_DSN=postgresql://postgres@127.0.0.1:5432/postgres?$ca" \
  --env C3R_TEST_PG_UNTRUSTED_DSN=postgresql://postgres@127.0.0.1:5432/postgres \
  --env "C3R_TEST_PG_WRONG_HOST_DSN=postgresql://postgres@127.0.0.2:5432/postgres?$ca" \
  --env "C3R_TEST_PG_PLAINTEXT_DSN=postgresql://postgres@127.0.0.1:5433/postgres?$ca" \
  "$api_id" python -m unittest discover -s tests -v
