"""Quality vectors, findings, and gate outcomes."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from akc_cir import Confidence, ContractModel
from pydantic import Field


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class QualityStatus(StrEnum):
    PASS = "PASS"  # noqa: S105  # nosec B105
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"  # noqa: S105  # nosec B105
    ESCALATE = "ESCALATE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAIL = "FAIL"


class QualityFinding(ContractModel):
    code: str
    severity: FindingSeverity
    message: str
    block_id: str | None = None
    page_index0: Annotated[int, Field(ge=0)] | None = None
    metric: str | None = None
    observed: str | float | int | bool | None = None
    threshold: str | float | int | None = None


class QualityVector(ContractModel):
    text_fidelity: Confidence | None = None
    numeric_fidelity: Confidence | None = None
    layout_fidelity: Confidence | None = None
    table_fidelity: Confidence | None = None
    hierarchy_validity: Confidence | None = None
    provenance_coverage: Confidence | None = None
    repetition_safety: Confidence | None = None
    language_consistency: Confidence | None = None
    markdown_validity: Confidence | None = None


class QualityEvaluation(ContractModel):
    overall_score: Confidence
    status: QualityStatus
    vector: QualityVector
    findings: tuple[QualityFinding, ...] = ()
    critical_finding_count: Annotated[int, Field(ge=0)] = 0


class AgreementScore(ContractModel):
    normalized_edit_similarity: Confidence
    semantic_similarity: Confidence | None = None
    numeric_token_match: Confidence
    heading_match: Confidence
    table_shape_match: Confidence | None = None
    source_coverage_delta: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
