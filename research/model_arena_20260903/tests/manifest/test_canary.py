from __future__ import annotations

import hashlib
from typing import Any

import pytest
from arena.manifest.canary import build_canary_selection


def _row(benchmark: str, index: int) -> dict[str, Any]:
    return {
        "sample_id": f"{benchmark}:doc{index}",
        "case_key": f"{benchmark}-case{index:03d}",
        "benchmark": benchmark,
        "input_relative_path": f"{benchmark}/inputs/{benchmark}-case{index:03d}.png",
        "input_png_sha256": f"sha256:{index:064d}",
    }


def _rows(benchmark: str, count: int) -> list[dict[str, Any]]:
    return [_row(benchmark, i) for i in range(count)]


def test_selection_is_deterministic_across_calls() -> None:
    rows = _rows("parsebench", 20) + _rows("omnidoc", 20) + _rows("olmocr", 20)
    counts = {"parsebench": 5, "omnidoc": 5, "olmocr": 5}

    first = build_canary_selection(
        rows, campaign_id="C", salt="S", gpu_pages_per_benchmark=3, opus_canary_counts=counts
    )
    second = build_canary_selection(
        rows, campaign_id="C", salt="S", gpu_pages_per_benchmark=3, opus_canary_counts=counts
    )

    assert first == second


def test_selection_order_matches_manual_sha256_ranking() -> None:
    rows = _rows("omnidoc", 10)
    salt = "MY-SALT"
    manual_order = sorted(
        rows, key=lambda r: hashlib.sha256(f"{r['sample_id']}{salt}".encode()).hexdigest()
    )

    selection = build_canary_selection(
        rows,
        campaign_id="C",
        salt=salt,
        gpu_pages_per_benchmark=4,
        opus_canary_counts={"omnidoc": 4},
    )

    expected_sample_ids = [row["sample_id"] for row in manual_order[:4]]
    actual_sample_ids = [s["sample_id"] for s in selection["gpu_canary"]["samples"]]
    assert actual_sample_ids == expected_sample_ids
    assert [s["selection_rank"] for s in selection["gpu_canary"]["samples"]] == [0, 1, 2, 3]


def test_different_salt_can_change_order() -> None:
    rows = _rows("omnidoc", 10)
    counts = {"omnidoc": 4}

    selection_a = build_canary_selection(
        rows, campaign_id="C", salt="salt-a", gpu_pages_per_benchmark=4, opus_canary_counts=counts
    )
    selection_b = build_canary_selection(
        rows, campaign_id="C", salt="salt-b", gpu_pages_per_benchmark=4, opus_canary_counts=counts
    )

    ids_a = [s["sample_id"] for s in selection_a["gpu_canary"]["samples"]]
    ids_b = [s["sample_id"] for s in selection_b["gpu_canary"]["samples"]]
    # Not a hard requirement of the rule, but with a real sha256 across 10
    # items and two different salts collapsing to the identical order would
    # be a suspiciously broken hash - guard against a no-op salt bug.
    assert ids_a != ids_b or len(rows) <= 1


def test_missing_opus_count_for_benchmark_raises() -> None:
    rows = _rows("olmocr", 5)
    with pytest.raises(ValueError, match="olmocr"):
        build_canary_selection(
            rows,
            campaign_id="C",
            salt="S",
            gpu_pages_per_benchmark=2,
            opus_canary_counts={"omnidoc": 2},
        )


def test_fewer_rows_than_target_selects_all_available() -> None:
    rows = _rows("olmocr", 2)
    selection = build_canary_selection(
        rows,
        campaign_id="C",
        salt="S",
        gpu_pages_per_benchmark=5,
        opus_canary_counts={"olmocr": 16},
    )
    assert selection["gpu_canary"]["per_benchmark_selected"]["olmocr"] == 2
    assert selection["opus_canary"]["per_benchmark_selected"]["olmocr"] == 2


def test_zero_gpu_pages_per_benchmark_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_canary_selection(
            [], campaign_id="C", salt="S", gpu_pages_per_benchmark=0, opus_canary_counts={}
        )
