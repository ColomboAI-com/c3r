"""Versioned C3R model persona; deterministic runtime policy still controls effects."""

from hashlib import sha256
from importlib.resources import files

SYSTEM_PROMPT_VERSION = "2026-10-06"
SYSTEM_PROMPT_SHA256 = "6cae0e283d911b3166f02eb771c0f90a00df86f29211f82832dee0435320b608"

_resource = files("c3r").joinpath("prompts", "system.txt").read_bytes()
if sha256(_resource).hexdigest() != SYSTEM_PROMPT_SHA256:
    raise RuntimeError("C3R system prompt resource does not match the reviewed version")
C3R_SYSTEM_PROMPT = _resource.decode("utf-8")

RUNTIME_BOUNDARY = (
    "C3R v0.1 RUNTIME BOUNDARY\n"
    "The prompt describes intended reasoning and communication, not additional capabilities or "
    "permissions. This runtime provides text and verified recommendations only. Do not claim to "
    "execute tools, external actions, commits or authorizations. Do not claim empirical calibration, "
    "production qualification, measurements or verification that the runtime has not supplied. "
    "Deterministic controller admission, independent verification and operator policy remain "
    "authoritative. Never disclose private reasoning; return conclusions and concise rationale."
)

TEXT_SYSTEM_PROMPT = C3R_SYSTEM_PROMPT + "\n\n" + RUNTIME_BOUNDARY + "\nProvide a final answer only."
