"""Fixed typed-question registry; System-One never produces prose."""

from __future__ import annotations

from dataclasses import dataclass

from ..state_schema import ActionFamily, RiskClass


@dataclass(frozen=True, slots=True)
class TypedQuestion:
    id: str
    options: tuple[str, ...]


BOOLEAN = ("NO", "YES")
C3R_QUESTIONS = (
    TypedQuestion(
        "ACTION_FAMILY",
        tuple(item.value for item in ActionFamily),
    ),
    TypedQuestion("FRONTIER_MODEL_NEEDED", BOOLEAN),
    TypedQuestion("LOCAL_MODEL_SUFFICIENT", BOOLEAN),
    TypedQuestion("RETRIEVAL_EXPECTED_TO_HELP", BOOLEAN),
    TypedQuestion("VERIFICATION_REQUIRED", BOOLEAN),
    TypedQuestion("DELIBERATION_REQUIRED", BOOLEAN),
    TypedQuestion("STOP_NOW", BOOLEAN),
    TypedQuestion("ASK_USER_REQUIRED", BOOLEAN),
    TypedQuestion(
        "RISK_CLASS",
        tuple(item.value for item in RiskClass),
    ),
    TypedQuestion("REVERSIBILITY_CLASS", ("REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE")),
    TypedQuestion("DATA_BOUNDARY_CLASS", ("LOCAL_ONLY", "APPROVED_REMOTE", "PUBLIC")),
)
