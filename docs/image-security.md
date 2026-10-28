# Staging image vulnerability triage

The first GitHub Actions image scan, [run 48](https://github.com/ColomboAI-com/c3r/actions/runs/35868557321),
failed its HIGH/CRITICAL gate. Its Trivy JSON artifact reported **46 HIGH, zero
CRITICAL** entries: 44 in the Debian 13.7 base image and two Python packaging
packages (`jaraco.context` 5.3.0 and `wheel` 0.45.1). Many Debian entries
repeated the same CVE across `util-linux` subpackages and had no fixed version
listed. They have not been waived or marked safe.

The container now uses the official Python 3.11 Alpine 3.24 runtime image and
copies only the stdlib-based `c3r` package. It does not run `pip install` or
retain the vulnerable `jaraco.context` and `wheel` packaging packages. The
intermediate [run 50](https://github.com/ColomboAI-com/c3r/actions/runs/35869194641)
had zero HIGH/CRITICAL Alpine OS findings but two HIGH Python packaging
findings. [Run 52](https://github.com/ColomboAI-com/c3r/actions/runs/35869500670)
showed that uninstalling those names alone did not remove copies vendored
inside `setuptools`; the runtime therefore removes `setuptools` itself, which
C3R does not import. The image runs as UID/GID 10001 and is smoke-imported in
CI before scanning. [Run 56](https://github.com/ColomboAI-com/c3r/actions/runs/35870568965)
passed the three-version Python test matrix, built the digest-pinned image,
smoke-imported C3R, and scanned it with Trivy v0.74.0. Its retained JSON
artifact reports **zero HIGH and zero CRITICAL findings** for the scanned
image. This is a point-in-time result, not a waiver for the earlier image or a
guarantee against future disclosures. Lower-severity findings were outside the
configured HIGH/CRITICAL scan and have not been triaged by this report.

Even a clean scan is only one security gate. A production image still needs
registry publication, signature/SBOM, deployment IAM and network
review, and the live safety qualification in `standalone-launch.md`.
