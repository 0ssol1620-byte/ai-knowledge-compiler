"""``arena.opus.canary_receipt`` -- the shared-schema canary receipt (D37)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.core import receipts as core_receipts
from arena.opus import cli as opus_cli
from arena.opus.canary_receipt import CanaryReceiptError, build_canary_receipt
from arena.opus.command import OPUS_DECLARED_MODEL
from arena.opus.paths import atomic_write_json

RUNTIME_IMAGE_DIGEST = "subscription:claude-code-2.1.252-claude-opus-5"


def _page_receipt(
    case_key: str,
    *,
    status: str = "SUCCESS",
    wall_seconds: float = 15.0,
    started_at: str = "2026-09-03T08:00:00.000Z",
    finished_at: str = "2026-09-03T08:00:15.000Z",
    error_class: str | None = None,
    output_chars: int = 1200,
) -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.page-receipt.v1",
        "case_key": case_key,
        "sample_id": f"omnidoc:images/{case_key}",
        "benchmark": "omnidoc",
        "model_key": "opus5_subscription",
        "model_revision": OPUS_DECLARED_MODEL,
        "status": status,
        "error_class": error_class,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_seconds": wall_seconds,
        "receipt_schema_valid": True,
        "canonical_lossy": False if status == "SUCCESS" else None,
        "output_chars": output_chars if status == "SUCCESS" else 0,
        "api_equivalent_list_price_usd": 0.03 if status == "SUCCESS" else None,
        "price_snapshot_sha256": "sha256:" + "a" * 64,
        "queue_ms": 0,
        "load_ms": 0,
        "preprocess_ms": 0,
        "inference_ms": int(wall_seconds * 1000),
        "postprocess_ms": 0,
        "total_ms": int(wall_seconds * 1000),
    }


def _successful_pages(n: int) -> list[dict[str, Any]]:
    return [
        _page_receipt(
            f"case-{i:04d}",
            wall_seconds=10.0 + i,
            started_at=f"2026-09-03T08:00:{i:02d}.000Z",
            finished_at=f"2026-09-03T08:00:{i + 10:02d}.000Z",
        )
        for i in range(n)
    ]


def test_build_canary_receipt_all_success_is_pass() -> None:
    pages = _successful_pages(10)
    document = build_canary_receipt(
        pages, runtime_image_digest=RUNTIME_IMAGE_DIGEST, written_at="2026-09-03T09:00:00.000Z",
    )
    assert document["status"] == "PASS"
    assert document["fail_reasons"] == []
    assert document["page_count"] == 10
    assert document["success_count"] == 10
    assert document["failed_count"] == 0
    assert document["gpu_type"] is None
    assert document["pod_id"] is None
    assert document["runtime_mode"] == "subscription"
    assert document["gpu_hours_projected"] == 0.0
    assert document["raw_gpu_cost_projected_usd"] == 0.0
    assert isinstance(document["wall_time_hours_projected"], float)
    assert document["warm_sec_per_page"] > 0
    assert {c["criterion"] for c in document["criteria"]} == set(core_receipts.CANARY_CRITERIA)
    # Validates against the real schema, not a hand-rolled check.
    core_receipts.validate(document, schema_name="canary-receipt")


def test_build_canary_receipt_infra_capacity_failure_still_passes() -> None:
    """D40: one INFRA_CAPACITY page is not a hard crash or a deterministic bug."""
    pages = [
        *_successful_pages(9),
        _page_receipt(
            "case-capacity",
            status="FAILED",
            error_class="INFRA_CAPACITY",
            wall_seconds=200.0,
            started_at="2026-09-03T08:00:09.500Z",
            finished_at="2026-09-03T08:03:29.500Z",
        ),
    ]
    document = build_canary_receipt(
        pages, runtime_image_digest=RUNTIME_IMAGE_DIGEST, written_at="2026-09-03T09:00:00.000Z",
    )
    assert document["status"] == "PASS"
    assert document["page_count"] == 10
    assert document["success_count"] == 9
    assert document["failed_count"] == 1
    by_id = {c["criterion"]: c for c in document["criteria"]}
    assert by_id["zero_hard_crash"]["passed"] is True
    assert by_id["zero_deterministic_runtime_bug"]["passed"] is True
    core_receipts.validate(document, schema_name="canary-receipt")


def test_build_canary_receipt_hard_crash_fails() -> None:
    pages = [
        *_successful_pages(9),
        _page_receipt(
            "case-crash",
            status="FAILED",
            error_class="UNKNOWN",
            wall_seconds=1.0,
            started_at="2026-09-03T08:00:09.500Z",
            finished_at="2026-09-03T08:00:10.500Z",
        ),
    ]
    document = build_canary_receipt(
        pages, runtime_image_digest=RUNTIME_IMAGE_DIGEST, written_at="2026-09-03T09:00:00.000Z",
    )
    assert document["status"] == "FAIL"
    assert document["fail_reasons"]
    core_receipts.validate(document, schema_name="canary-receipt")


def test_build_canary_receipt_wrong_revision_fails() -> None:
    pages = _successful_pages(5)
    pages[2]["model_revision"] = "claude-sonnet-5"
    document = build_canary_receipt(
        pages, runtime_image_digest=RUNTIME_IMAGE_DIGEST, written_at="2026-09-03T09:00:00.000Z",
    )
    assert document["status"] == "FAIL"
    by_id = {c["criterion"]: c for c in document["criteria"]}
    assert by_id["correct_model_revision"]["passed"] is False
    core_receipts.validate(document, schema_name="canary-receipt")


def test_build_canary_receipt_full_run_projection_shape() -> None:
    pages = _successful_pages(10)
    document = build_canary_receipt(
        pages,
        runtime_image_digest=RUNTIME_IMAGE_DIGEST,
        written_at="2026-09-03T09:00:00.000Z",
        full_run_page_count=5132,
        workers=2,
    )
    projection = document["full_run_projection"]
    assert projection["page_count"] == 5132
    assert projection["workers"] == 2
    assert projection["wall_time_hours_projected_p50"] > 0
    assert (
        projection["wall_time_hours_projected_p90"]
        >= projection["wall_time_hours_projected_p50"]
    )
    assert projection["api_equivalent_price_floor_usd_p50"] > 0
    assert projection["api_equivalent_price_floor_is_a_floor"] is True


def test_build_canary_receipt_no_pages_raises() -> None:
    with pytest.raises(CanaryReceiptError):
        build_canary_receipt(
            [], runtime_image_digest=RUNTIME_IMAGE_DIGEST, written_at="2026-09-03T09:00:00.000Z"
        )


def test_build_canary_receipt_no_successes_raises() -> None:
    pages = [
        _page_receipt("case-only-failure", status="FAILED", error_class="INFRA_CAPACITY")
    ]
    with pytest.raises(CanaryReceiptError):
        build_canary_receipt(
            pages, runtime_image_digest=RUNTIME_IMAGE_DIGEST,
            written_at="2026-09-03T09:00:00.000Z",
        )


def test_canary_receipt_cli_reads_receipts_on_disk_and_spends_nothing(
    isolated_run_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m arena.opus canary-receipt`` never launches the claude CLI."""
    # isolated_run_root redirects arena.opus.paths' module-level constants, but
    # cli.py imported CANARY_DIR and SHARED_CANARY_RECEIPT_PATH by value; both
    # must be redirected here too, so this test never touches the real
    # namespace's receipts/ directory.
    canary_dir = isolated_run_root / "canary"
    canary_receipts_dir = canary_dir / "receipts"
    canary_receipts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(opus_cli, "CANARY_DIR", canary_dir)
    shared_target = isolated_run_root.parent / "receipts" / "canary-opus5_subscription.json"
    monkeypatch.setattr(opus_cli, "SHARED_CANARY_RECEIPT_PATH", shared_target)

    for page in _successful_pages(6):
        atomic_write_json(
            canary_receipts_dir / f"{page['case_key']}.json", page, where="test-fixture"
        )

    def fake_resolve_config(_args: Any) -> tuple[Any, str, None]:
        class _Cfg:
            pass

        return _Cfg(), "2.1.252 (Claude Code)", None

    monkeypatch.setattr(opus_cli, "_resolve_config", fake_resolve_config)

    class _Args:
        workers = 2

    exit_code = opus_cli.cmd_canary_receipt(_Args())
    assert exit_code == opus_cli.EXIT_OK

    written = json.loads(shared_target.read_text(encoding="utf-8"))
    assert written["status"] == "PASS"
    assert written["page_count"] == 6
    core_receipts.validate(written, schema_name="canary-receipt")
