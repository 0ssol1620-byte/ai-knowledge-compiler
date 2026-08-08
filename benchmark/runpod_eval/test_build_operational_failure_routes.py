from __future__ import annotations

import json
from pathlib import Path

from build_operational_failure_routes import build_operational_failure_routes
from public_core_merge import SUITES


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_builds_routes_only_for_still_failed_operational_cases(tmp_path: Path) -> None:
    composite = tmp_path / "composite"
    for worker in range(4):
        for suite in SUITES:
            cases = []
            if worker == 0 and suite == "parsebench":
                cases = [
                    {"case_id": "recovered", "status": "completed"},
                    {"case_id": "failed", "status": "failed", "error": "timeout"},
                ]
            _write(
                composite / f"worker-{worker:02d}" / suite / "run-summary.json",
                {"runs": [{"repeat_index": 1, "cases": cases}]},
            )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-operational-retry-plan.v1",
            "failed_input_count": 2,
            "failures": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "recovered",
                    "primary_worker_index": 0,
                },
                {
                    "benchmark_id": "parsebench",
                    "case_id": "failed",
                    "primary_worker_index": 0,
                },
            ],
        },
    )
    output = tmp_path / "routes.json"
    result = build_operational_failure_routes(
        composite_root=composite, retry_plan=plan, output_path=output
    )

    assert result["planned_case_count"] == 2
    assert result["recovered_before_alternate_count"] == 1
    assert result["unresolved_case_count"] == 1
    assert result["routes"][0]["case_id"] == "failed"
    assert result["routes"][0]["candidate_models"] == ["paddleocr-vl-1.6"]
