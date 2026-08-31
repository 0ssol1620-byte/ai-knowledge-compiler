from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "research" / "experiments" / "SEM-RISK-DEV-CAL-01" / "run_calibration.py"
PROTOCOL = ROOT / "research" / "experiments" / "SEM-RISK-DEV-CAL-01" / "protocol.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("semantic_risk_dev_cal", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_is_explicitly_retrospective_development_only() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))

    assert protocol["classification"] == "RETROSPECTIVE_DEVELOPMENT_CALIBRATION_ONLY"
    assert protocol["gpu_policy"] == {"new_inference_allowed": False, "external_gpu_cost_usd": 0.0}
    assert protocol["threshold_selection_rule"].startswith("No production threshold")
    assert 0.55 in protocol["predeclared_thresholds"]["semantic_risk"]


def test_critical_token_extraction_covers_dates_versions_amounts_and_percentages() -> None:
    runner = _load_runner()
    tokens = set(
        runner.extract_critical_tokens(
            "Contract 2026-09-30, firmware v1.5.3, price $1,250.50, rate 12.5%, delta -7.2."
        )
    )

    assert "2026-09-30" in tokens
    assert "v1.5.3" in tokens
    assert "$1,250.50" in tokens
    assert "12.5%" in tokens
    assert "-7.2" in tokens


def test_custom_damage_is_bounded_and_detects_critical_value_corruption() -> None:
    runner = _load_runner()
    gt = {
        "semantic_text": "model n2 version 1.5.3 contract date 2026-09-30",
        "ordered_text": "model n2 version 1.5.3 contract date 2026-09-30",
        "table_text": "model version n2 1.5.3",
        "formula_text": "",
        "has_table": True,
        "has_formula": False,
    }
    good = runner.page_damage(gt, "| Model | Version |\n|---|---|\n| N2 | 1.5.3 |\nContract date 2026-09-30")
    bad = runner.page_damage(gt, "| Model | Version |\n|---|---|\n| N2 | 1.5.8 |\nContract date 2028-09-30")

    assert 0.0 <= good["damage"] <= 1.0
    assert 0.0 <= bad["damage"] <= 1.0
    assert good["critical_token_error"] == 0.0
    assert bad["critical_token_error"] > good["critical_token_error"]
    assert bad["damage"] > good["damage"]


def test_routing_observables_are_ground_truth_independent_by_api_construction() -> None:
    runner = _load_runner()
    primary = (
        "Version 1.5.3\n|A|B|",
        "Version 1.5.3\n|A|B|",
        "Version 1.5.8\n|A|B|",
    )
    strong = (
        "Version 1.5.3\n|A|B|",
        "Version 1.5.3\n|A|B|",
        "Version 1.5.3\n|A|B|",
    )

    first = runner.routing_observables(primary, strong)
    second = runner.routing_observables(primary, strong)

    assert first == second
    assert "current_semantic_risk" in first
    assert first["primary_critical_token_repeat_instability"] > 0.0
    assert 0.0 <= first["current_semantic_risk"] <= 1.0


def test_page_alignment_fails_closed_if_any_repeat_is_missing_a_page(tmp_path: Path) -> None:
    runner = _load_runner()
    paddle = tmp_path / "paddle"
    mineru = tmp_path / "mineru"
    for model in (paddle, mineru):
        for repeat in (1, 2, 3):
            directory = model / f"markdown-repeat-{repeat}"
            directory.mkdir(parents=True)
            for key in ("a", "b"):
                (directory / f"{key}.md").write_text(key, encoding="utf-8")
    (paddle / "markdown-repeat-2" / "b.md").unlink()
    gt_items = [
        {"layout_dets": [], "page_info": {"image_path": "a.jpg"}},
        {"layout_dets": [], "page_info": {"image_path": "b.jpg"}},
    ]

    with pytest.raises(RuntimeError, match="page mismatch"):
        runner.verify_page_alignment(gt_items, paddle, mineru, 2)


def test_policy_accounting_charges_strong_parser_only_for_real_semantic_risk_escalations() -> None:
    runner = _load_runner()
    records = [
        {
            "primary_damage": 0.4,
            "strong_damage": 0.1,
            "gt_critical_token_count": 1,
            "primary_critical_token_damage": 1.0,
            "strong_critical_token_damage": 0.0,
        },
        {
            "primary_damage": 0.1,
            "strong_damage": 0.2,
            "gt_critical_token_count": 0,
            "primary_critical_token_damage": 0.0,
            "strong_critical_token_damage": 0.0,
        },
    ]
    economics = {
        "primary_latency_seconds_per_page": 1.0,
        "primary_cost_usd_per_page": 1.0,
        "strong_latency_seconds_per_page": 10.0,
        "strong_cost_usd_per_page": 10.0,
    }

    row = runner._policy_row("semantic_risk>=x", records, [True, False], economics)
    disagreement_row = runner._policy_row(
        "strong_disagreement_proxy>=x",
        records,
        [True, False],
        economics,
        observation_requires_strong_all_pages=True,
    )

    assert row["estimated_parser_cost_usd"] == 12.0
    assert row["estimated_parser_latency_seconds_sequential"] == 12.0
    assert disagreement_row["estimated_parser_cost_usd"] == 22.0
    assert disagreement_row["estimated_parser_latency_seconds_sequential"] == 22.0
    assert row["mean_selected_parser_damage"] < 0.25


def test_real_preserved_inputs_align_18x3_without_running_inference() -> None:
    runner = _load_runner()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    located = runner.locate_inputs(protocol)
    gt_items = json.loads(located["gt"].read_text(encoding="utf-8"))

    keys = runner.verify_page_alignment(gt_items, located["paddle"], located["mineru"], 18)

    assert len(keys) == 18
