from datetime import UTC, datetime, timedelta

import pytest
from akc_parallel_runtime.drift import detect_quality_drift
from akc_parallel_runtime.first_verified import VerifiedCandidate, select_first_verified
from akc_parallel_runtime.impact_scope import LineageEdge, impacted_descendants
from akc_parallel_runtime.models import RegionLevel
from akc_parallel_runtime.recovery import PreprocessingVariant, RecoveryScope
from akc_parallel_runtime.recovery_planner import FailureCode, plan_minimal_recovery
from akc_parallel_runtime.semantic_health import SemanticState, decide_semantic_health


def test_first_verified_ignores_fast_unverified_candidate() -> None:
    now = datetime.now(UTC)
    winner = select_first_verified(
        (
            VerifiedCandidate("fast", now, 3, 0, "a" * 64),
            VerifiedCandidate("verified", now + timedelta(milliseconds=1), 6, 0, "b" * 64),
        )
    )
    assert winner is not None and winner.attempt_id == "verified"


def test_recovery_and_replay_remain_minimal() -> None:
    cell = RecoveryScope(RegionLevel.CELL, "cell-1", ("source://cell",))
    page = RecoveryScope(RegionLevel.PAGE, "page-1", ("source://page",))
    scope, variant = plan_minimal_recovery((FailureCode.COLUMN_SHIFT,), (page, cell))
    assert scope is cell
    assert variant is PreprocessingVariant.CELL_GEOMETRY
    assert impacted_descendants(
        ("cell-1",),
        (LineageEdge("cell-1", "note-1"), LineageEdge("note-1", "graph-1")),
    ) == ("graph-1", "note-1")


@pytest.mark.parametrize(
    ("failure", "expected_level", "expected_variant"),
    (
        (
            FailureCode.PAGE_OMISSION,
            RegionLevel.PAGE,
            PreprocessingVariant.PAGE_RERENDER_ALT_PARSER,
        ),
        (FailureCode.BLOCK_OMISSION, RegionLevel.REGION, PreprocessingVariant.REGION_CROP),
        (FailureCode.BOTTOM_ROW_OMISSION, RegionLevel.ROW, PreprocessingVariant.OVERLAPPING_TILE),
        (FailureCode.MIDDLE_ROW_OMISSION, RegionLevel.ROW, PreprocessingVariant.ROW_BAND_TILE),
        (FailureCode.EXTRA_ROWS, RegionLevel.TABLE, PreprocessingVariant.CANDIDATE_REJECT),
        (FailureCode.WRONG_TABLE, RegionLevel.TABLE, PreprocessingVariant.TARGET_SELECTION),
        (FailureCode.COLUMN_SHIFT, RegionLevel.CELL, PreprocessingVariant.CELL_GEOMETRY),
        (
            FailureCode.DIGIT_MUTATION,
            RegionLevel.CELL,
            PreprocessingVariant.NATIVE_AUTHORITY_RECONSTRUCTION,
        ),
        (FailureCode.SIGN_SCALE_ERROR, RegionLevel.CELL, PreprocessingVariant.CANONICAL_NUMERIC),
        (FailureCode.READING_ORDER, RegionLevel.REGION, PreprocessingVariant.LAYOUT_SPECIALIST),
        (
            FailureCode.CROSS_PAGE_SPLIT,
            RegionLevel.PAGE_PAIR,
            PreprocessingVariant.PAGE_PAIR_STITCH,
        ),
        (
            FailureCode.FORMULA_CORRUPTION,
            RegionLevel.REGION,
            PreprocessingVariant.FORMULA_SPECIALIST,
        ),
        (FailureCode.GROUNDING_MISMATCH, RegionLevel.REGION, PreprocessingVariant.SOURCE_REMAP),
        (FailureCode.HALLUCINATION, RegionLevel.REGION, PreprocessingVariant.CANDIDATE_REJECT),
        (FailureCode.REPETITION, RegionLevel.REGION, PreprocessingVariant.CANDIDATE_REJECT),
        (FailureCode.NOTE_SPLIT_ERROR, RegionLevel.REGION, PreprocessingVariant.NOTE_RECOMPILE),
        (FailureCode.WRONG_ENTITY_MERGE, RegionLevel.REGION, PreprocessingVariant.ENTITY_SPLIT),
        (
            FailureCode.UNSUPPORTED_RELATION,
            RegionLevel.REGION,
            PreprocessingVariant.RELATION_REMOVE,
        ),
    ),
)
def test_masterplan_failure_taxonomy_has_exact_minimum_scope_and_strategy(
    failure: FailureCode,
    expected_level: RegionLevel,
    expected_variant: PreprocessingVariant,
) -> None:
    scopes = tuple(
        RecoveryScope(level, level.value, (f"source://{level.value}",))
        for level in (
            RegionLevel.CELL,
            RegionLevel.ROW,
            RegionLevel.TABLE,
            RegionLevel.REGION,
            RegionLevel.PAGE,
            RegionLevel.PAGE_PAIR,
            RegionLevel.DOCUMENT,
        )
    )

    selected_scope, selected_variant = plan_minimal_recovery((failure,), scopes)

    assert selected_scope.level is expected_level
    assert selected_variant is expected_variant


def test_semantic_fault_quarantines_and_quality_drift_rolls_back() -> None:
    health = decide_semantic_health(
        canary_score=0.79, consecutive_failures=3, infrastructure_healthy=True
    )
    assert health.state is SemanticState.QUARANTINED
    assert health.replay_inflight
    drift = detect_quality_drift(baseline=0.99, observed=0.95, maximum_relative_drop=0.02)
    assert drift.rollback_required
