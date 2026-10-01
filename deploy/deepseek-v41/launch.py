"""Canonical pinned launch; never stops workloads, pulls images, or reboots a node."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(__file__).with_name("h100-production.env").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError("duplicate canonical setting")
        values[key] = value
    return values


def server_args(config: dict[str, str]) -> list[str]:
    if config["LANGUAGE_MODEL_ONLY"] != "true" or config["ENGRAM_CPU_OFFLOAD"] != "true":
        raise ValueError("qualification requires text-only Engram CPU offload")
    return [
        "--model", "/model", "--served-model-name", "/model", "deepseek-v4.1-flash",
        "--tensor-parallel-size", config["TP"], "--language-model-only",
        "--tokenizer-mode", config["TOKENIZER_MODE"],
        "--reasoning-parser", config["REASONING_PARSER"],
        "--tool-call-parser", config["TOOL_CALL_PARSER"], "--enable-auto-tool-choice",
        "--engram-config", '{"cpu_offload":true}',
        "--max-model-len", config["MAX_MODEL_LEN"],
        "--max-num-seqs", config["MAX_NUM_SEQS"],
        "--max-num-batched-tokens", config["MAX_NUM_BATCHED_TOKENS"],
        "--gpu-memory-utilization", config["GPU_MEMORY_UTILIZATION"],
        "--generation-config", "vllm",
        "--host", "0.0.0.0", "--port", "8000", "--no-enable-log-requests",
    ]


def verify_checkpoint(model: Path, config: dict[str, str]) -> None:
    manifest = json.loads(Path(__file__).with_name("checkpoint-manifest.json").read_text())
    if (manifest["model_id"] != config["CHECKPOINT"]
            or manifest["revision"] != config["CHECKPOINT_REVISION"]):
        raise RuntimeError("upstream manifest/config identity mismatch")
    expected_paths = {item["path"] for item in manifest["files"]}
    for path in model.rglob("*"):
        relative = path.relative_to(model)
        if path.is_symlink():
            raise RuntimeError("checkpoint symlinks are not admitted")
        if (path.is_file() and relative.as_posix() not in expected_paths
                and relative.parts[:2] != (".cache", "huggingface")):
            raise RuntimeError("unexpected unpinned checkpoint file")
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe checkpoint path")
        path = model / relative
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(model)
                or path.stat().st_size != item["size"]):
            raise RuntimeError("checkpoint file admission failed")
        digest = hashlib.sha256() if item["lfs_sha256"] else hashlib.sha1()
        if not item["lfs_sha256"]:
            digest.update(b"blob " + str(item["size"]).encode() + b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != (item["lfs_sha256"] or item["git_blob_id"]):
            raise RuntimeError("checkpoint content differs from pinned upstream revision")
    print(json.dumps({"checkpoint_verified": True, "files": len(manifest["files"])}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--cache-path", required=True, type=Path)
    parser.add_argument("--name", default="c3r-deepseek-qualified")
    parser.add_argument("--port", type=int, default=18000,
                        help="Loopback qualification port; production cutover is separately approved")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--server-args", action="store_true",
                        help="Print canonical serving arguments for real upstream parser validation")
    args = parser.parse_args()
    config = load_config()
    if args.server_args:
        print(json.dumps(server_args(config)))
        return
    model, cache = args.model_path.resolve(), args.cache_path.resolve()
    if (not model.is_dir() or not cache.is_dir() or model.is_relative_to(cache)
            or cache.is_relative_to(model)):
        raise ValueError("distinct existing checkpoint and private cache directories required")
    if not 1 <= args.port <= 65535 or not args.name.startswith("c3r-deepseek-"):
        raise ValueError("invalid scoped name or loopback port")
    command = [
        "docker", "run", "-d", "--name", args.name, "--gpus", "all",
        "--network", "bridge", "-p", f"127.0.0.1:{args.port}:8000",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--shm-size", "16g", "--memory", config["HOST_RAM_LIMIT_GIB"] + "g",
        "--memory-swap", config["HOST_RAM_LIMIT_GIB"] + "g",
        "--tmpfs", "/tmp:rw,mode=1777,size=2g",
        "--mount", f"type=bind,src={model},dst=/model,readonly",
        "--mount", f"type=bind,src={cache},dst=/runtime",
        "-e", "VLLM_CACHE_ROOT=/runtime/vllm", "-e", "XDG_CACHE_HOME=/runtime/.cache",
        "-e", "FLASHINFER_WORKSPACE_BASE=/runtime/flashinfer",
        config["VLLM_IMAGE_ID"], *server_args(config),
    ]
    if not args.execute:
        print(json.dumps({"command": command, "qualification_status": "pending"}))
        return
    if config["VLLM_IMAGE_ID"] == "sha256:10b3c8fe9c38f6e87dfef21c8d0e457f76ab89b32892bb37a056375b25ddbf85":
        raise RuntimeError("known failed compiler preflight; rebuild, scan and repin before execution")
    verify_checkpoint(model, config)
    # Fail before allocating: only the already built immutable image is eligible.
    subprocess.run(["docker", "image", "inspect", config["VLLM_IMAGE_ID"]],
                   check=True, stdout=subprocess.DEVNULL, timeout=20)
    gpu_rows = subprocess.check_output([
        "nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"
    ], text=True, timeout=15).splitlines()
    if len(gpu_rows) != int(config["TP"]):
        raise RuntimeError("expected eight measured GPUs")
    for row in gpu_rows:
        total, free = map(int, row.split(","))
        if free < total * float(config["GPU_MEMORY_UTILIZATION"]) + int(config["MIN_GPU_FREE_MIB"]):
            raise RuntimeError("insufficient co-resident headroom; do not overlap model engines")
    memory = {line.split(":")[0]: int(line.split()[1])
              for line in Path("/proc/meminfo").read_text().splitlines()
              if line.split(":")[0] in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}}
    if (memory["MemAvailable"] < int(config["HOST_RAM_LIMIT_GIB"]) * 1024**2 + memory["MemTotal"] * .2
            or memory["SwapTotal"] != memory["SwapFree"]):
        raise RuntimeError("host-RAM reserve or no-swap gate failed")
    subprocess.run(command, check=True, timeout=60)


if __name__ == "__main__":
    main()
