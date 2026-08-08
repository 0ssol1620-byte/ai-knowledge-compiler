from __future__ import annotations

import json
from pathlib import Path

from build_hybrid_recovery_routes import build_hybrid_recovery_routes


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_routes_only_failed_paddle_cases_and_binds_parse_layout(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    _write(
        base,
        {
            "schema": "folynta.preofficial-operational-failure-routes.v1",
            "routes": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "failed",
                    "primary_worker_index": 0,
                    "request_recovery": True,
                    "candidate_models": ["paddleocr-vl-1.6"],
                },
                {
                    "benchmark_id": "parsebench",
                    "case_id": "passed",
                    "primary_worker_index": 0,
                    "request_recovery": True,
                    "candidate_models": ["paddleocr-vl-1.6"],
                },
            ],
        },
    )
    evidence = tmp_path / "evidence"
    _write(
        evidence / "worker-01" / "parsebench" / "run-summary.json",
        {
            "candidate_id": "paddleocr-vl-1.6",
            "ground_truth_mounted": False,
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {"case_id": "failed", "status": "failed", "error": "empty_markdown"},
                        {"case_id": "passed", "status": "completed"},
                    ],
                }
            ],
        },
    )
    output = tmp_path / "hybrid.json"
    result = build_hybrid_recovery_routes(
        base_routes=base, paddle_evidence_root=evidence, output_path=output
    )

    assert result["unresolved_case_count"] == 1
    assert result["routes"][0]["candidate_models"] == ["deepseek-ocr-2"]
    assert result["routes"][0]["layout_fallback_model"] == "paddleocr-vl-1.6"
    assert result["routes"][0]["paddle_recovery_worker_index"] == 1
