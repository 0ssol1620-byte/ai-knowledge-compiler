from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apply_accepted_quality_candidates import apply_accepted_quality_candidates
from apply_operational_retries import ResultSource
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def _sha(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_case(root: Path, suite: str, case_id: str, markdown: bytes) -> None:
    summary = {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "artifact_manifest_sha256": EXPECTED_ARTIFACT_SHA256,
        "runs": [
            {
                "repeat_index": 1,
                "completed": 1,
                "failed": 0,
                "cases": [
                    {
                        "case_id": case_id,
                        "status": "completed",
                        "markdown_sha256": _sha(markdown),
                        "markdown_characters": len(markdown.decode()),
                    }
                ],
            }
        ],
    }
    summary_path = root / suite / "run-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    markdown_path = root / suite / "markdown-repeat-1" / f"{case_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_bytes(markdown)
    model = root / suite / "repeat-1" / case_id / "vlm" / f"{case_id}_model.json"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps({"source": markdown.decode()}), encoding="utf-8")


def test_only_officially_accepted_case_is_materialized(tmp_path: Path) -> None:
    baselines: list[ResultSource] = []
    candidates: list[ResultSource] = []
    for worker in range(4):
        baseline = tmp_path / f"baseline-{worker}"
        candidate = tmp_path / f"candidate-{worker}"
        baselines.append(ResultSource(worker, baseline))
        candidates.append(ResultSource(worker, candidate))
        for suite in SUITES:
            case_id = f"{suite}-{worker}"
            _write_case(baseline, suite, case_id, b"baseline")
            _write_case(candidate, suite, case_id, b"candidate")
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-staging.v1",
                "recovery_model": "mineru-3.4.4-vlm-quality-retry",
                "input_count": 2,
                "routes": [
                    {
                        "benchmark_id": "parsebench",
                        "case_id": "parsebench-0",
                        "primary_worker_index": 0,
                    },
                    {
                        "benchmark_id": "parsebench",
                        "case_id": "parsebench-1",
                        "primary_worker_index": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    comparison = tmp_path / "comparison.json"
    comparison.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-official-failure-comparison.v1",
                "policy": {
                    "require_strict_failure_record_reduction": True,
                    "forbid_new_failure_codes": True,
                    "forbid_candidate_escalation": True,
                    "unchanged_candidates_are_not_accepted": True,
                },
                "compared_recoverable_case_count": 2,
                "accepted_quality_case_count": 1,
                "accepted_quality_cases": [
                    {
                        "benchmark_id": "parsebench",
                        "case_id": "parsebench-0",
                        "baseline_failure_record_count": 2,
                        "candidate_failure_record_count": 1,
                        "baseline_failure_codes": ["T01", "T02"],
                        "candidate_failure_codes": ["T02"],
                        "new_failure_codes": [],
                        "candidate_escalates": False,
                        "strictly_improved": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "selected"
    receipt = apply_accepted_quality_candidates(
        baseline_sources=tuple(baselines),
        candidate_sources=tuple(candidates),
        selective_plan=plan,
        comparison=comparison,
        output_root=output,
    )

    assert receipt["accepted_case_count"] == 1
    assert (
        output / "worker-00" / "parsebench" / "markdown-repeat-1" / "parsebench-0.md"
    ).read_bytes() == b"candidate"
    assert (
        output / "worker-01" / "parsebench" / "markdown-repeat-1" / "parsebench-1.md"
    ).read_bytes() == b"baseline"
