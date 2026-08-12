from __future__ import annotations

from pathlib import Path


def test_public_core_worker_is_case_bounded_and_resume_safe() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (
        repository
        / "infra/runpod/v6/bootstrap/run-mineru-3.4.4-public-core-worker.sh"
    ).read_text(encoding="utf-8")

    assert 'CASE_TIMEOUT_SECONDS="${CASE_TIMEOUT_SECONDS:-900}"' in source
    assert 'BATCH_SIZE="${BATCH_SIZE:-1}"' in source
    assert "--batch-size \"$BATCH_SIZE\"" in source
    assert "--timeout-seconds \"$CASE_TIMEOUT_SECONDS\"" in source
    assert "--resume-interrupted" in source
    assert "suite_reused_complete" in source
    assert "suite_resume_started" in source


def test_stalled_public_core_recovery_preserves_evidence_and_bounds_cases() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (
        repository / "benchmark/runpod_eval/remote_recover_stalled_public_core.sh"
    ).read_text(encoding="utf-8")

    assert "live_stall_detected_case_bounded_recovery" in source
    assert "stall-watchdog.jsonl" in source
    assert "straggler-live-stall-recovery.txt" in source
    assert "--resume-interrupted" in source
    assert "--batch-size $BATCH_SIZE" in source
    assert "--timeout-seconds $CASE_TIMEOUT_SECONDS" in source
    assert "live_stall_recovery_relaunched" in source


def test_stalled_public_core_guard_routes_current_suite_to_recovery() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (
        repository / "benchmark/runpod_eval/remote_guard_stalled_public_core.sh"
    ).read_text(encoding="utf-8")

    assert "remote_recover_stalled_public_core.sh" in source
    assert 'SUITE="$suite"' in source
    assert "STALL_THRESHOLD_SECONDS" in source
    assert "CASE_TIMEOUT_SECONDS=900" in source
    assert "BATCH_SIZE=1" in source
    assert "status != 4 && status != 5" in source
