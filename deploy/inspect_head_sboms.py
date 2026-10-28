"""Explain package/SBOM discrepancies without suppressing scanner findings."""
import importlib.metadata
import json
from pathlib import Path

TARGETS = {"msgpack", "setuptools", "urllib3"}
results = []
for path in Path("/usr/local/lib").rglob("*.cdx.json"):
    document = json.loads(path.read_text())
    for component in document.get("components", []):
        name = component.get("name", "")
        if name not in TARGETS:
            continue
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "not_installed"
        results.append({"sbom": str(path), "package": name,
                        "sbom_version": component.get("version"),
                        "installed_distribution_version": actual})
print(json.dumps(results, indent=2))
