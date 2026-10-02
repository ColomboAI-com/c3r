"""Independent file identities from the immutable upstream HF revision API.

Small files use Git blob identities; LFS objects use upstream SHA-256 identities.
These are release pins, not hashes accepted from the downloaded local manifest.
"""
import hashlib
from pathlib import Path

REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
LFS = {
    "model-00001-of-00005.safetensors": "31d6a825ae35f11fb85b195b4c42c146c051e446433125a215336abdf95cbf5f",
    "model-00002-of-00005.safetensors": "5991236cea6fe21f3d43cab0f0e84448734fbbe0789816202989f2ddc9d18282",
    "model-00003-of-00005.safetensors": "c5185c4794be2d8a9784d5753c9922db38df478ce11f9ed0b415b7304d896836",
    "model-00004-of-00005.safetensors": "b5ee7de71fbf17db3d5704e0c8f2bc7d005ca9e1d7ca2aeb19827b0cfcaa917a",
    "model-00005-of-00005.safetensors": "20c2d6366ab85c90786ccdd829cd2b9e7d30ef3b2ebbb998280e7e4014b542ff",
    "tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
}
GIT_BLOBS = {
    "config.json": "d46195ac87f837ad233d02b2f80f148bf7c005e0",
    "generation_config.json": "20a8a9156fc8c3f25295ca067f61fdf120d517c5",
    "merges.txt": "31349551d90c7606f325fe0f11bbb8bd5fa0d7c7",
    "model.safetensors.index.json": "2b85c00f1b118961cd7a477e2bba0fe197a4ce1a",
    "tokenizer_config.json": "417d038a63fa3de29cfde265caedae14d1a58d92",
    "vocab.json": "4783fe10ac3adce15ac8f358ef5462739852c569",
}


def verify_encoder(root: Path) -> None:
    expected = set(LFS) | set(GIT_BLOBS)
    actual = {str(path.relative_to(root)) for path in root.rglob("*")
              if path.is_file() and ".cache" not in path.parts}
    if actual != expected:
        raise RuntimeError("encoder file inventory does not match pinned release")
    for filename in sorted(expected):
        path = root / filename
        if path.is_symlink():
            raise RuntimeError("encoder release must use ordinary read-only files")
        hasher = hashlib.sha256() if filename in LFS else hashlib.sha1()
        if filename in GIT_BLOBS:
            hasher.update(f"blob {path.stat().st_size}\0".encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != (LFS.get(filename) or GIT_BLOBS[filename]):
            raise RuntimeError("encoder content does not match independent upstream identity")
