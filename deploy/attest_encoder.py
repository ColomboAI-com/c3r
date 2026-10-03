"""Run as the deployment operator; inspect the encoder's actual mounted files.

Output belongs in private deployment evidence. This is a trusted host readback,
not hardware-backed remote attestation. No Docker socket is given to CLM.
"""
import json
import subprocess
from pathlib import Path

from encoder_identity import REVISION, verify_encoder

IMAGE = "sha256:00d577a6a63281e15336029d5bcee4e9a2cf182214a4f20ba6111b1c8e79893d"


def main():
    info = json.loads(subprocess.check_output([
        "docker", "inspect", "c3r-qwen-encoder"], text=True))[0]
    image = json.loads(subprocess.check_output([
        "docker", "image", "inspect", info["Image"]], text=True))[0]
    if not any(value.endswith("@" + IMAGE) for value in image["RepoDigests"]):
        raise RuntimeError("encoder container image is not the approved immutable digest")
    args = info["Config"]["Cmd"]
    if (not info["State"]["Running"] or "/encoder" not in args
            or "pooling" not in args or "qwen3-8b" not in args):
        raise RuntimeError("encoder process configuration mismatch")
    mounts = [mount for mount in info["Mounts"] if mount["Destination"] == "/encoder"]
    if len(mounts) != 1 or mounts[0]["RW"]:
        raise RuntimeError("encoder artifact mount must be read-only")
    # This namespace path proves which files the running encoder sees, rather
    # than verifying a separate copy downloaded beside it.
    verify_encoder(Path(f'/proc/{info["State"]["Pid"]}/root/encoder'))
    print(json.dumps({
        "encoder_revision": REVISION, "encoder_container_digest": IMAGE,
        "encoder_container_id": info["Id"], "encoder_content_verified": True,
        "binding_basis": "host_docker_inspect_and_running_process_mount_hashes",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
