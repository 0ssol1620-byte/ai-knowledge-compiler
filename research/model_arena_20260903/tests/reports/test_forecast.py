"""arena.reports.forecast: a forecast only from a PASS canary, never a measurement."""

from __future__ import annotations

import json
from pathlib import Path

from arena.reports.forecast import SAFETY_MARGIN, build, forecast_model, render_markdown

PASS_PROOF = {
    "model_key": "olmocr2",
    "canary_verdict": "PASS",
    "pod_id": "m3idmn3u5dau9b",
    "gpu_type": "NVIDIA GeForce RTX 4090",
    "listed_rate_usd_per_hour": 0.74,
    "model_loading_seconds": 232.0,
    "pages_attempted": 15,
    "page_runtime_seconds": {"min": 1.29, "max": 16.635, "mean": 9.0},
}


def test_missing_proof_yields_no_number() -> None:
    row = forecast_model("paddleocr_vl_1_6", None, pages=5132)
    assert row.forecast_usd is None
    assert row.reason_if_missing is not None
    assert row.canary_pages == 0


def test_fail_canary_yields_no_number() -> None:
    proof = dict(PASS_PROOF, canary_verdict="FAIL")
    row = forecast_model("olmocr2", proof, pages=5132)
    assert row.forecast_usd is None
    assert "FAIL" in (row.reason_if_missing or "")


def test_pass_canary_forecast_arithmetic() -> None:
    row = forecast_model("olmocr2", PASS_PROOF, pages=1000)
    # 1000 pages x 9 s = 9000 s = 2.5 h inference, + 232 s load = 2.5644 h
    assert row.inference_hours_1_pod == 2.5
    assert row.gpu_hours_total == round(2.5 + 232 / 3600, 3)
    assert row.forecast_usd == round((2.5 + 232 / 3600) * 0.74, 2)
    assert row.forecast_usd_with_margin == round(row.forecast_usd * (1 + SAFETY_MARGIN), 2)
    assert row.wall_hours_by_pods is not None
    assert row.wall_hours_by_pods["2"] < row.wall_hours_by_pods["1"]
    assert "15-page real canary" in row.basis


def test_gpu_count_multiplies_cost() -> None:
    two = dict(PASS_PROOF, gpu_count=2)
    one = forecast_model("x", PASS_PROOF, pages=100)
    both = forecast_model("x", two, pages=100)
    assert one.forecast_usd is not None and both.forecast_usd is not None
    assert abs(both.forecast_usd - 2 * one.forecast_usd) < 0.02


def test_build_reports_absent_authorization(tmp_path: Path) -> None:
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "canary-proof-olmocr2.json").write_text(
        json.dumps(PASS_PROOF), encoding="utf-8"
    )
    payload = build(tmp_path, model_keys=("olmocr2", "glm_ocr"), pages=10)
    assert payload["kind"] == "FORECAST"
    assert "ABSENT" in payload["authorization_state"]
    assert payload["totals"]["models_with_forecast"] == 1
    assert payload["totals"]["models_without_forecast"] == ["glm_ocr"]
    text = render_markdown(payload)
    assert "not measured" in text
    assert "| olmocr2 | PASS (15p) |" in text
