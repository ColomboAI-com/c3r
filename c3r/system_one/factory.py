"""Explicit construction of the default CLM System-One path.

No mutable upstream model alias or unfitted calibration is silently promoted.
The host owns secrets, artifacts, and the enable flag.
"""

from __future__ import annotations

from collections.abc import Mapping

from .calibration import TemperatureCalibrator
from .clm_adapter import ClmAdapter
from .fast_path import CalibratedFastPath


def build_default_clm_fast_path(
    values: Mapping[str, str], *, calibrator: TemperatureCalibrator
) -> CalibratedFastPath:
    """Build CLM; require a host-declared immutable artifact revision.

    This does not attest the live server's artifacts. Deployment must verify
    encoder/head hashes independently before enabling real decisions.
    """
    revision = values.get("C3R_CLM_ARTIFACT_REVISION", "")
    endpoint = values.get("C3R_CLM_URL", "http://127.0.0.1:8700")
    timeout = float(values.get("C3R_CLM_TIMEOUT_MS", "500")) / 1000
    return CalibratedFastPath(
        adapter=ClmAdapter(
            revision=revision,
            endpoint=endpoint,
            api_key=values.get("C3R_CLM_API_KEY"),
            timeout_seconds=timeout,
        ),
        calibrator=calibrator,
        maximum_decision_seconds=timeout,
    )
