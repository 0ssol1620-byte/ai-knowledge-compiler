"""D10 pod lifetimes and D13 per-model stall floors."""

from __future__ import annotations

from datetime import UTC, datetime

from arena.controller.paths import CampaignPaths
from arena.controller.watchdogs import (
    CANARY_MAX_POD_LIFETIME_SECONDS,
    FULL_RUN_MAX_POD_LIFETIME_SECONDS,
    WorkerObservation,
    lifetime_expiry,
    max_pod_lifetime_seconds,
    model_stall_thresholds,
)
from tests.controller.conftest import MODEL_KEY, write_runtime_json

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


def test_canary_pods_live_two_hours_and_full_run_pods_six() -> None:
    assert CANARY_MAX_POD_LIFETIME_SECONDS == 2 * 3600
    assert FULL_RUN_MAX_POD_LIFETIME_SECONDS == 6 * 3600
    assert max_pod_lifetime_seconds("canary") == 2 * 3600
    assert max_pod_lifetime_seconds("inference") == 6 * 3600


def test_a_canary_pod_past_two_hours_is_expired() -> None:
    worker = WorkerObservation(
        worker_id="w0",
        model_key=MODEL_KEY,
        state="READY",
        last_heartbeat_at="2026-09-03T11:59:30Z",
        pod_provisioned_at="2026-09-03T09:30:00Z",  # 2.5 h before NOW
    )
    finding = lifetime_expiry(
        worker, now=NOW, max_lifetime_seconds=CANARY_MAX_POD_LIFETIME_SECONDS
    )
    assert finding is not None
    assert finding.kind == "max_lifetime"
    # The same pod is still inside a full-run pod's allowance.
    assert (
        lifetime_expiry(
            worker, now=NOW, max_lifetime_seconds=FULL_RUN_MAX_POD_LIFETIME_SECONDS
        )
        is None
    )


def test_the_stall_threshold_never_drops_below_the_page_timeout(
    paths: CampaignPaths,
) -> None:
    write_runtime_json(paths, per_page_timeout_seconds=900)
    # A fast canary p95 must not shorten a runtime whose pages take minutes.
    thresholds = model_stall_thresholds(
        paths, (MODEL_KEY,), canary_p95_seconds={MODEL_KEY: 4.0}
    )
    assert thresholds[MODEL_KEY] == 900.0


def test_a_slow_canary_raises_the_threshold_above_the_floor(
    paths: CampaignPaths,
) -> None:
    write_runtime_json(paths, per_page_timeout_seconds=300)
    thresholds = model_stall_thresholds(
        paths, (MODEL_KEY,), canary_p95_seconds={MODEL_KEY: 200.0}
    )
    assert thresholds[MODEL_KEY] == 600.0  # 3 x p95, masterplan section 15.5


def test_a_model_without_a_runtime_json_gets_no_invented_threshold(
    paths: CampaignPaths,
) -> None:
    write_runtime_json(paths)
    thresholds = model_stall_thresholds(paths, (MODEL_KEY, "glm_ocr"))
    assert MODEL_KEY in thresholds
    assert "glm_ocr" not in thresholds
