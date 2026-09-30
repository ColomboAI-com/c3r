"""Fetch immutable public upstream artifacts; no customer data is used."""
import hashlib
import json
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path("/artifacts")
ENCODER_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
HEAD_REVISION = "e939398d4556fcd9400c76fa8c5a513202f42b0a"


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    snapshot_download("Qwen/Qwen3-8B", revision=ENCODER_REVISION,
                      local_dir=ROOT / "encoder", max_workers=4,
                      allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"])
    head = Path(hf_hub_download("Contrastive-LM/CLM-v0.1-8B", "CLM_v0.1-8B.pt",
                               revision=HEAD_REVISION, local_dir=ROOT / "head"))
    files = {str(path.relative_to(ROOT / "encoder")): digest(path)
             for path in sorted((ROOT / "encoder").rglob("*"))
             if path.is_file() and ".cache" not in path.parts}
    manifest = {
        "clm_source_revision": "bb42c6c5bf914fd449bed2f6ca65be80602cb1f7",
        "encoder": "Qwen/Qwen3-8B", "encoder_revision": ENCODER_REVISION,
        "head_revision": HEAD_REVISION, "head_sha256": digest(head),
        "encoder_files": files,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "encoder_files"}),
          flush=True)


if __name__ == "__main__":
    main()
