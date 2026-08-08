"""Failure-taxonomy front door for the existing smallest-scope recovery planner."""

from __future__ import annotations

from enum import StrEnum

from .recovery import PreprocessingVariant, RecoveryPlanner, RecoveryScope


class FailureCode(StrEnum):
    PAGE_OMISSION = "P01"
    BLOCK_OMISSION = "B01"
    BOTTOM_ROW_OMISSION = "T01"
    MIDDLE_ROW_OMISSION = "T02"
    EXTRA_ROWS = "T03"
    WRONG_TABLE = "T04"
    COLUMN_SHIFT = "T05"
    DIGIT_MUTATION = "N01"
    SIGN_SCALE_ERROR = "N02"
    READING_ORDER = "R01"
    CROSS_PAGE_SPLIT = "C01"
    FORMULA_CORRUPTION = "F01"
    GROUNDING_MISMATCH = "G01"
    HALLUCINATION = "H01"
    REPETITION = "H02"
    NOTE_SPLIT_ERROR = "K01"
    WRONG_ENTITY_MERGE = "K02"
    UNSUPPORTED_RELATION = "K03"


_FAILURE_VARIANTS = {
    FailureCode.PAGE_OMISSION: PreprocessingVariant.PAGE_RERENDER_ALT_PARSER,
    FailureCode.BLOCK_OMISSION: PreprocessingVariant.REGION_CROP,
    FailureCode.BOTTOM_ROW_OMISSION: PreprocessingVariant.OVERLAPPING_TILE,
    FailureCode.MIDDLE_ROW_OMISSION: PreprocessingVariant.ROW_BAND_TILE,
    FailureCode.EXTRA_ROWS: PreprocessingVariant.CANDIDATE_REJECT,
    FailureCode.WRONG_TABLE: PreprocessingVariant.TARGET_SELECTION,
    FailureCode.COLUMN_SHIFT: PreprocessingVariant.CELL_GEOMETRY,
    FailureCode.DIGIT_MUTATION: PreprocessingVariant.NATIVE_AUTHORITY_RECONSTRUCTION,
    FailureCode.SIGN_SCALE_ERROR: PreprocessingVariant.CANONICAL_NUMERIC,
    FailureCode.READING_ORDER: PreprocessingVariant.LAYOUT_SPECIALIST,
    FailureCode.CROSS_PAGE_SPLIT: PreprocessingVariant.PAGE_PAIR_STITCH,
    FailureCode.FORMULA_CORRUPTION: PreprocessingVariant.FORMULA_SPECIALIST,
    FailureCode.GROUNDING_MISMATCH: PreprocessingVariant.SOURCE_REMAP,
    FailureCode.HALLUCINATION: PreprocessingVariant.CANDIDATE_REJECT,
    FailureCode.REPETITION: PreprocessingVariant.CANDIDATE_REJECT,
    FailureCode.NOTE_SPLIT_ERROR: PreprocessingVariant.NOTE_RECOMPILE,
    FailureCode.WRONG_ENTITY_MERGE: PreprocessingVariant.ENTITY_SPLIT,
    FailureCode.UNSUPPORTED_RELATION: PreprocessingVariant.RELATION_REMOVE,
}


def plan_minimal_recovery(
    failures: tuple[FailureCode, ...], scopes: tuple[RecoveryScope, ...]
) -> tuple[RecoveryScope, PreprocessingVariant]:
    if not failures:
        raise ValueError("recovery requires a registered failure code")
    scope = RecoveryPlanner.minimum_valid_scope(
        frozenset(code.value for code in failures), scopes
    )
    variants = tuple(_FAILURE_VARIANTS[code] for code in failures)
    authority = PreprocessingVariant.AUTHORITY_MAPPING
    variant = authority if authority in variants else sorted(variants, key=str)[0]
    return scope, variant


__all__ = ["FailureCode", "plan_minimal_recovery"]
