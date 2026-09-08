"""Per-execution observability record (program §50).

One record per router execution, carrying exactly the §50 fields: source
version, the three revisions, route and candidates, speculation, queue time,
runtime digest, retry, verifier, escalation, region recovery, final
disposition, evidence locator, cost, latency.

**No raw source content, ever.** §50 ends "no raw sensitive content", and the
type enforces it rather than trusting the caller: every free-text-shaped field
is a constrained identifier -- bounded length, no whitespace, no control
characters. A caller who tries to log a paragraph of the customer's document
gets a `ValidationError`, not a leak. Reason codes are drawn from a bounded
token shape for the same reason.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from akc_cir import ContractModel
from pydantic import Field, field_validator

from .execution_plan import VerificationPolicy
from .models import Route

#: An identifier, not prose. Bounded, and no whitespace or control characters --
#: which is what a sentence from a source document would contain.
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:@/#+-]+$")]
ReasonCode = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:#-]+$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class FinalDisposition(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_AFTER_RECOVERY = "accepted_after_recovery"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class RouterExecutionRecord(ContractModel):
    """§50, field for field. Nothing in it can carry document text."""

    unit_id: Identifier
    source_version_id: Identifier
    planner_revision: Identifier
    feature_revision: Identifier
    portfolio_revision: Identifier

    route: Route
    candidate_routes: tuple[Route, ...]
    speculative_routes: tuple[Route, ...] = ()

    queue_time_ms: Annotated[float, Field(ge=0.0)] = 0.0
    latency_ms: Annotated[float, Field(ge=0.0)] = 0.0
    #: Resolved container digest of the runtime that ran, never a mutable tag.
    runtime_digest: Digest | None = None

    retry_count: Annotated[int, Field(ge=0)] = 0
    verifier: VerificationPolicy = VerificationPolicy.NONE
    verifier_passed: bool | None = None
    escalations: tuple[ReasonCode, ...] = ()
    region_recovery_count: Annotated[int, Field(ge=0)] = 0

    final_disposition: FinalDisposition
    #: A pointer into the evidence store, never the evidence itself.
    evidence_locator: Identifier | None = None

    cost_credits: Annotated[float, Field(ge=0.0)] = 0.0
    reason_codes: tuple[ReasonCode, ...] = ()
    calibrated: bool = False

    @field_validator("candidate_routes")
    @classmethod
    def enforce_candidates_present(cls, value: tuple[Route, ...]) -> tuple[Route, ...]:
        if len(set(value)) != len(value):
            raise ValueError("candidate routes must not repeat")
        return value

    @field_validator("escalations", "reason_codes")
    @classmethod
    def enforce_bounded_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 64:
            raise ValueError("a record carries at most 64 codes; this is not a log sink")
        return value


__all__ = ["FinalDisposition", "RouterExecutionRecord"]
