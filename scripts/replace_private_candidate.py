"""Replace only task-created private C3R containers, restoring them on failure.

Run on the deployment host after build, artifact verification and scans. This
never stops the shared DeepSeek service or the VM, nor exposes an interface.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["sudo", "docker", *args], text=True).strip()


def main():
    folder = Path.home() / ".c3r-private-inference"
    previous = folder / "candidate-v2.env"
    current = folder / "candidate-v3.env"
    if current.exists():
        raise RuntimeError("v3 config exists; do not implicitly rotate or replace")
    config = dict(line.split("=", 1) for line in previous.read_text().splitlines())
    if (config.get("C3R_INGRESS_HOST") != "127.0.0.1"
            or config.get("C3R_TRACE_COLLECTION") != "false"
            or config.get("C3R_ONLINE_LEARNING") != "false"):
        raise RuntimeError("replacement is restricted to non-collecting private inference")
    clm_image = docker("image", "inspect", "c3r-clm:hardened-clean-bb42c6c", "--format", "{{.Id}}")
    core_image = docker("image", "inspect", "c3r-core:reviewed-20260930", "--format", "{{.Id}}")
    config["C3R_CLM_CONTAINER_DIGEST"] = clm_image
    descriptor = os.open(current, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in config.items()))
    moved = []
    started = []
    try:
        for name in ("c3r-core-private", "c3r-clm"):
            docker("stop", "--time", "10", name)
            docker("rename", name, name + "-before-v3")
            moved.append(name)
        docker("run", "-d", "--name", "c3r-clm", "--network", "host", "--read-only",
               "--tmpfs", "/tmp:rw,size=256m", "-v", "/mnt/c3r-models/c3r-clm:/artifacts:ro",
               "-e", "C3R_CLM_CONTAINER_DIGEST=" + clm_image, clm_image)
        started.append("c3r-clm")
        docker("run", "-d", "--name", "c3r-core-private", "--network", "host",
               "--env-file", str(current), "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "128",
               "--memory", "512m", "--cpus", "2", core_image)
        started.append("c3r-core-private")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            request = urllib.request.Request("http://127.0.0.1:8088/ready", headers={
                "Authorization": "Bearer " + config["C3R_CLIENT_TOKEN"]})
            try:
                with opener.open(request, timeout=15) as response:
                    if response.status == 200:
                        print(json.dumps({"status": "private_candidate_ready",
                                          "core_image": core_image, "clm_image": clm_image,
                                          "trace_collection": False, "public_access": False}))
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(3)
        raise RuntimeError("private candidate readiness deadline exceeded")
    except BaseException:
        for name in reversed(started):
            docker("stop", "--time", "10", name)
            docker("rename", name, name + "-failed-v3")
        for name in reversed(moved):
            docker("rename", name + "-before-v3", name)
            docker("start", name)
        print(json.dumps({"status": "previous_private_candidate_restored"}))
        raise


if __name__ == "__main__":
    main()
