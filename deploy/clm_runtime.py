"""Loopback CLM service with measured artifact identity and no prompt caches."""
import hashlib
import json
import os
from pathlib import Path

import requests
import torch
import uvicorn
from clm.embedder import Embedder
from clm.engine import Engine
from clm.server import create_app
from encoder_identity import REVISION, verify_encoder

SOURCE = "bb42c6c5bf914fd449bed2f6ca65be80602cb1f7"
HEAD_SHA256 = "b2b4a8c9c2d39263eff78a351eb909a342ce9b3bf21a3f07c1d1bf15f1c4eda5"
ROOT = Path("/artifacts")


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class LocalSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def request(self, method, url, **kwargs):
        if not url.startswith("http://127.0.0.1:8090/"):
            raise ValueError("encoder origin must stay loopback")
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    actual_source = Path("/opt/clm/source-revision").read_text().strip()
    if actual_source != SOURCE or manifest["clm_source_revision"] != SOURCE:
        raise RuntimeError("CLM source mismatch")
    head = ROOT / "head/CLM_v0.1-8B.pt"
    actual_head = digest(head)
    if actual_head != HEAD_SHA256 or manifest["head_sha256"] != actual_head:
        raise RuntimeError("CLM head mismatch")
    if manifest["encoder_revision"] != REVISION:
        raise RuntimeError("encoder revision mismatch")
    verify_encoder(ROOT / "encoder")
    embedder = Embedder(max_tokens=8192, cache_size=0, batch=8, timeout=10)
    embedder.session = LocalSession()
    engine = Engine(embedder=embedder, checkpoint=str(head), device="cpu", action_cache=0)
    app = create_app(engine, ui=False)
    artifact = {key: value for key, value in manifest.items() if key != "encoder_files"}
    artifact.update({
        "container_digest": os.environ.get("C3R_CLM_CONTAINER_DIGEST", "unattested"),
        "container_digest_source": "deployment_host_readback",
        "head_requires_vllm": False, "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda, "embedding_cache_size": 0,
        "action_cache_enabled": False, "head_device": "cpu",
        "encoder_content_verified": True,
        "encoder_identity_basis": "immutable_upstream_git_blobs_and_lfs_sha256",
    })

    @app.get("/internal/clm/artifact")
    def loaded_artifact():
        return artifact

    uvicorn.run(app, host="127.0.0.1", port=8700, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
