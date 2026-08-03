from datetime import UTC, datetime, timedelta

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
    scope, variant = plan_minimal_recovery((FailureCode.TABLE_COLUMN_SHIFT,), (page, cell))
    assert scope is cell
    assert variant is PreprocessingVariant.CELL_GEOMETRY
    assert impacted_descendants(
        ("cell-1",),
        (LineageEdge("cell-1", "note-1"), LineageEdge("note-1", "graph-1")),
    ) == ("graph-1", "note-1")


def test_semantic_fault_quarantines_and_quality_drift_rolls_back() -> None:
    health = decide_semantic_health(
        canary_score=0.79, consecutive_failures=3, infrastructure_healthy=True
    )
    assert health.state is SemanticState.QUARANTINED
    assert health.replay_inflight
    drift = detect_quality_drift(baseline=0.99, observed=0.95, maximum_relative_drop=0.02)
    assert drift.rollback_required
