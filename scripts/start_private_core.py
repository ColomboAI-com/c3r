"""Start a loopback-only candidate. Tokens stay in a mode-0600 host file."""
import json
import os
import secrets
import subprocess
from pathlib import Path


def main():
    destination = Path.home() / ".c3r-private-inference"
    destination.mkdir(mode=0o700, exist_ok=True)
    config = destination / "candidate-v2.env"
    if config.exists():
        raise RuntimeError("candidate config already exists; do not rotate implicitly")
    env = {
        "C3R_HOST_ENTRYPOINT": "c3r.production_host:build",
        "C3R_MODE": "production_inference", "C3R_ENABLED": "true",
        "C3R_SYSTEM_ONE": "true", "C3R_SYSTEM_ONE_PROVIDER": "clm",
        "C3R_DELIBERATIVE": "true", "C3R_TRACE_COLLECTION": "false",
        "C3R_ONLINE_LEARNING": "false", "C3R_INGRESS_HOST": "127.0.0.1",
        "PORT": "8088", "C3R_BACKEND_PORT": "8089",
        "C3R_CLM_CONTAINER_DIGEST": "sha256:922fe094c0804fc2b4e327f2dbbe97b749e47de7d8806b2f467cae7ecd0d2dda",
        "C3R_CLIENT_TOKEN": secrets.token_urlsafe(48),
        "C3R_BACKEND_TOKEN": secrets.token_urlsafe(48),
    }
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in env.items()))
    result = subprocess.run([
        "sudo", "docker", "run", "-d", "--name", "c3r-core-private",
        "--network", "host", "--env-file", str(config), "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--memory", "512m", "--cpus", "2",
        "c3r-core:working-20260930",
    ], check=True, capture_output=True, text=True)
    print(json.dumps({"container_id": result.stdout.strip(), "bind": "127.0.0.1:8088",
                      "trace_collection": False}))


if __name__ == "__main__":
    main()
