"""Failure-taxonomy front door for the existing smallest-scope recovery planner."""

from __future__ import annotations

from enum import StrEnum

from .models import RegionLevel
from .recovery import PreprocessingVariant, RecoveryPlanner, RecoveryScope


class FailureCode(StrEnum):
    PAGE_OMISSION = "P01"
    PAGE_DUPLICATION = "P02"
    READING_ORDER = "L01"
    TABLE_SHAPE = "T01"
    TABLE_COLUMN_SHIFT = "T02"
    NUMERIC_MISMATCH = "N01"
    NUMERIC_AUTHORITY_MISMATCH = "N02"
    SOURCE_ANCHOR_MISSING = "E01"
    INDEPENDENCE_MISSING = "E02"
    KNOWLEDGE_ORPHAN = "K01"
    KNOWLEDGE_EVIDENCE_MISSING = "K02"
    KNOWLEDGE_CONTRADICTION = "K03"


_FAILURE_VARIANTS = {
    FailureCode.PAGE_OMISSION: PreprocessingVariant.OVERLAPPING_TILE,
    FailureCode.PAGE_DUPLICATION: PreprocessingVariant.CROP_MARGIN,
    FailureCode.READING_ORDER: PreprocessingVariant.TILE,
    FailureCode.TABLE_SHAPE: PreprocessingVariant.CELL_GEOMETRY,
    FailureCode.TABLE_COLUMN_SHIFT: PreprocessingVariant.CELL_GEOMETRY,
    FailureCode.NUMERIC_MISMATCH: PreprocessingVariant.OCR_EXACT,
    FailureCode.NUMERIC_AUTHORITY_MISMATCH: PreprocessingVariant.AUTHORITY_MAPPING,
    FailureCode.SOURCE_ANCHOR_MISSING: PreprocessingVariant.CROP_MARGIN,
    FailureCode.INDEPENDENCE_MISSING: PreprocessingVariant.OCR_EXACT,
    FailureCode.KNOWLEDGE_ORPHAN: PreprocessingVariant.TILE,
    FailureCode.KNOWLEDGE_EVIDENCE_MISSING: PreprocessingVariant.CROP_MARGIN,
    FailureCode.KNOWLEDGE_CONTRADICTION: PreprocessingVariant.OCR_EXACT,
}


def plan_minimal_recovery(
    failures: tuple[FailureCode, ...], scopes: tuple[RecoveryScope, ...]
) -> tuple[RecoveryScope, PreprocessingVariant]:
    if not failures:
        raise ValueError("recovery requires a registered failure code")
    scope = RecoveryPlanner.smallest_scope(scopes)
    variants = tuple(_FAILURE_VARIANTS[code] for code in failures)
    authority = PreprocessingVariant.AUTHORITY_MAPPING
    variant = authority if authority in variants else sorted(variants, key=str)[0]
    if FailureCode.PAGE_OMISSION in failures and scope.level is not RegionLevel.PAGE:
        page_scope = next((item for item in scopes if item.level is RegionLevel.PAGE), None)
        if page_scope is not None:
            scope = page_scope
    return scope, variant


__all__ = ["FailureCode", "plan_minimal_recovery"]
