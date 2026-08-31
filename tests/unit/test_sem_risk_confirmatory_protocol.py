from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "research" / "experiments" / "SEM-RISK-CONF-01"


def _source(name: str) -> str:
    return (EXPERIMENT / name).read_text(encoding="utf-8")


def test_confirmatory_scripts_are_syntax_valid_before_freeze() -> None:
    for name in (
        "freeze_protocol.py",
        "build_selection_manifest.py",
        "acquire_selected_inputs.py",
        "run_lane_a_native.py",
        "build_inference_manifests.py",
        "evaluate_confirmatory.py",
    ):
        ast.parse(_source(name), filename=name)


def test_protocol_predeclares_two_disjoint_lanes_and_dev_exclusion() -> None:
    source = _source("freeze_protocol.py")
    assert '"classification": "PROSPECTIVE_CONFIRMATORY_TWO_LANE"' in source
    assert '"cross_lane_disjoint": True' in source
    assert '"sample_size": 64' in source
    assert '"sample_per_subset": 16' in source
    assert '["v1.5", "equation_hard", "layout_hard", "table_hard"]' in source
    assert '"threshold_selection_from_sem_risk_dev_cal_01": True' in source
    assert '"development_pages_in_confirmatory_cohort": True' in source


def test_protocol_freezes_distinct_error_signals_without_ground_truth() -> None:
    source = _source("freeze_protocol.py")
    assert '"lane_a_error_signal": "independent source-native peer disagreement"' in source
    assert '"primary_repeats_lane_b": 3' in source
    assert '"lane_b_error_signal"' in source
    assert "repeat instability" in source.casefold()
    assert '"ground_truth_visible_to_inference_workers": True' in source


def test_thresholds_are_fixed_before_confirmatory_evaluation() -> None:
    source = _source("freeze_protocol.py")
    assert '"semantic_risk_escalation_threshold": 0.25' in source
    assert '"cheap_peer_disagreement_threshold": 0.35' in source
    assert "not fitted on development pages" in source
    assert '"post_result_threshold_or_specialist_mapping_changes": True' in source


def test_formula_only_never_promotes_research_specialist() -> None:
    protocol = _source("freeze_protocol.py")
    evaluator = _source("evaluate_confirmatory.py")
    assert "Formula presence alone never routes away from Paddle" in protocol
    assert "formula_only = flags[\"formula_detected\"] and not structural" in evaluator
    assert "return structural and not formula_only" in evaluator


def test_inference_outputs_are_sealed_before_ground_truth_fetch() -> None:
    source = _source("evaluate_confirmatory.py")
    seal_index = source.index("INFERENCE_SEAL.write_text")
    old_gt_index = source.index("old_gt_items = fetch_gt")
    current_gt_index = source.index("current_gt_items = fetch_gt")
    assert seal_index < old_gt_index < current_gt_index
    assert '"ground_truth_consumed_before_this_seal": False' in source


def test_selection_emits_only_whitelisted_metadata_not_annotations() -> None:
    source = _source("build_selection_manifest.py")
    assert "Selection reads ONLY the two whitelisted page_info fields" in source
    assert '"annotation_content_emitted": False' in source
    assert 'item.get("layout_dets")' not in source


def test_acquisition_never_downloads_ground_truth() -> None:
    source = _source("acquire_selected_inputs.py")
    assert '"ground_truth_acquired": False' in source
    assert "OmniDocBench.json" not in source
