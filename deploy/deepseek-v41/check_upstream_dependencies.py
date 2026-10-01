"""Reject unknown dependency conflicts; disclose the pinned upstream NCCL override.

The upstream Dockerfile explicitly overrides Torch's NCCL requirement because
DeepEPv2 requires NCCL >=2.30.4. This is not GPU compatibility evidence:
https://github.com/vllm-project/vllm/blob/ac68c3087215e0a4f3cdfa218508c6aada57235d/docker/Dockerfile
"""
import importlib.metadata
import json
import subprocess
import sys

versions = {name: importlib.metadata.version(name)
            for name in ("vllm", "torch", "nvidia-nccl-cu13")}
expected = {"vllm": "0.30.1rc1.dev396+gac68c3087",
            "torch": "2.13.0+cu130", "nvidia-nccl-cu13": "2.30.7"}
if versions != expected:
    raise RuntimeError("Pinned upstream dependency identities changed")
result = subprocess.run([sys.executable, "-m", "pip", "check"],
                        capture_output=True, text=True)
known = ('torch 2.13.0+cu130 has requirement nvidia-nccl-cu13==2.29.7; '
         'platform_system == "Linux", but you have nvidia-nccl-cu13 2.30.7.')
if result.returncode != 1 or result.stdout.strip().splitlines() != [known] or result.stderr.strip():
    raise RuntimeError("Dependency preflight differs from the reviewed upstream override")
print(json.dumps({"known_upstream_nccl_override": known,
                  "other_dependency_errors": [], "tp8_compatibility": "not_yet_tested"}))
