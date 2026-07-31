from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.public_suite import (
    PublicSuiteError,
    _load_registry,
    adapt_cir,
    audit_isolation,
    compare_runs,
    critical_evaluate,
    evaluate_reproducibility,
    freeze_predictions,
    sign_report,
    verify_registry,
)


def _cir() -> dict[str, object]:
    return {
        "blocks": [
            {
                "id": "b1",
                "order": 0,
                "type": "paragraph",
                "normalized_text": "Revenue was (1,234.50) USD.",
                "source_refs": [{"page_index0": 0, "bbox1000": [10, 20, 900, 100]}],
            },
            {
                "id": "b2",
                "order": 1,
                "type": "formula",
                "formula_latex": "x^2",
                "source_refs": [{"page_index0": 0, "bbox1000": [10, 120, 500, 200]}],
            },
            {
                "id": "other-page",
                "order": 2,
                "type": "paragraph",
                "normalized_text": "not page zero",
                "source_refs": [{"page_index0": 1, "bbox1000": [10, 20, 500, 100]}],
            },
        ]
    }


def test_registry_is_complete_and_valid_offline() -> None:
    registry = _load_registry()
    result = verify_registry(
        registry_path=Path("benchmark/benchmark-registry.lock.yaml"),
        online=False,
    )
    assert result["ok"] is True
    assert {entry["id"] for entry in registry["benchmarks"]} == {
        "omnidocbench",
        "parsebench",
        "olmocr-bench",
    }


@pytest.mark.parametrize("benchmark_id", ["omnidocbench", "parsebench", "olmocr-bench"])
def test_cir_adapters_never_require_ground_truth(benchmark_id: str) -> None:
    output = adapt_cir(_cir(), benchmark_id=benchmark_id, page_index=0)
    encoded = json.dumps(output).casefold()
    assert "revenue was" in encoded
    assert "not page zero" not in encoded
    assert "ground_truth" not in encoded


def test_prediction_freeze_and_isolation_audit(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    (predictions / "page-1.json").write_text('{"markdown":"safe"}\n', encoding="utf-8")
    manifest_path = tmp_path / "prediction-manifest.json"
    manifest = freeze_predictions(
        input_dir=predictions,
        output_manifest=manifest_path,
        candidate="parser-router-v1",
    )
    ground_truth = tmp_path / "evaluator-only-ground-truth"
    ground_truth.mkdir()
    audit = audit_isolation(
        inference_manifest=manifest_path,
        ground_truth_root=ground_truth,
    )
    assert manifest["ground_truth_present"] is False
    assert audit["prediction_immutable"] is True


def test_freeze_rejects_ground_truth_named_files(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    (predictions / "ground_truth.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PublicSuiteError, match="GT-like"):
        freeze_predictions(
            input_dir=predictions,
            output_manifest=tmp_path / "manifest.json",
            candidate="candidate-v1",
        )


def test_critical_evaluator_fails_closed() -> None:
    report = critical_evaluate(
        [
            {
                "case_id": "case-1",
                "runtime_failure": False,
                "missing_prediction": False,
                "error_codes": ["critical_numeric_mutation"],
            }
        ]
    )
    assert report["gate_passed"] is False
    assert report["critical_failure_count"] == 1


def test_comparison_requires_identical_environment_and_no_regression() -> None:
    common = {
        "benchmark_id": "parsebench",
        "dataset_revision": "a" * 40,
        "evaluator_commit": "b" * 40,
        "environment_sha256": "sha256:" + "c" * 64,
        "critical_failure_count": 0,
        "runtime_failure_count": 0,
        "missing_prediction_count": 0,
        "gt_leakage_count": 0,
    }
    incumbent = {**common, "candidate": "v1", "metrics": {"official_overall": 0.8, "tables": 0.8}}
    candidate = {**common, "candidate": "v2", "metrics": {"official_overall": 0.81, "tables": 0.8}}
    assert compare_runs(candidate, incumbent)["gate_passed"] is True
    candidate["environment_sha256"] = "sha256:" + "d" * 64
    with pytest.raises(PublicSuiteError, match="environment_sha256"):
        compare_runs(candidate, incumbent)


def test_unsigned_report_is_explicitly_not_signed() -> None:
    result = sign_report({"benchmark_id": "parsebench"}, key_path=None)
    assert result["signature"] is None
    assert result["signature_status"] == "unsigned_external_key_required"


def test_reproducibility_requires_three_stable_identical_runs() -> None:
    common = {
        "benchmark_id": "parsebench",
        "candidate": "v2",
        "dataset_revision": "a" * 40,
        "evaluator_commit": "b" * 40,
        "environment_sha256": "sha256:" + "c" * 64,
        "critical_failure_count": 0,
        "runtime_failure_count": 0,
        "missing_prediction_count": 0,
        "gt_leakage_count": 0,
    }
    runs = [
        {**common, "metrics": {"official_overall": value, "tables": 0.8}}
        for value in (0.81, 0.812, 0.809)
    ]
    assert evaluate_reproducibility(runs)["gate_passed"] is True
    runs[2]["metrics"]["official_overall"] = 0.79
    assert evaluate_reproducibility(runs)["gate_passed"] is False


def test_reproducibility_rejects_incomplete_repeat_set() -> None:
    with pytest.raises(PublicSuiteError, match="exactly three"):
        evaluate_reproducibility([])
