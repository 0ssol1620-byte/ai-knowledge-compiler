from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apply_mineru_quality_candidates import apply_quality_candidates
from apply_operational_retries import ResultSource
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def _sha(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _summary(case_id: str, markdown: bytes) -> dict:
    return {
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


def _write_case(root: Path, suite: str, case_id: str, markdown: bytes) -> None:
    summary = root / suite / "run-summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(_summary(case_id, markdown)), encoding="utf-8")
    markdown_path = root / suite / "markdown-repeat-1" / f"{case_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_bytes(markdown)
    model = root / suite / "repeat-1" / case_id / "vlm" / f"{case_id}_model.json"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text("{}", encoding="utf-8")


def test_successful_quality_output_builds_candidate_without_accepting_it(
    tmp_path: Path,
) -> None:
    baselines: list[ResultSource] = []
    for worker in range(4):
        root = tmp_path / f"baseline-{worker}"
        baselines.append(ResultSource(worker, root))
        for suite in SUITES:
            _write_case(root, suite, f"{suite}-{worker}", b"baseline")
    quality_root = tmp_path / "quality-4"
    _write_case(quality_root, "parsebench", "parsebench-0", b"improved")
    plan = tmp_path / "selective-recovery-receipt.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-selective-recovery-staging.v1",
                "recovery_model": "mineru-3.4.4-vlm-quality-retry",
                "input_count": 1,
                "different_worker_only": True,
                "routes": [
                    {
                        "benchmark_id": "parsebench",
                        "case_id": "parsebench-0",
                        "primary_worker_index": 0,
                        "recovery_worker_index": 4,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "candidate"
    receipt = apply_quality_candidates(
        baseline_sources=tuple(baselines),
        quality_sources=(ResultSource(4, quality_root),),
        selective_plan=plan,
        output_root=output,
    )

    assert receipt["candidate_outputs_applied"] == 1
    assert receipt["final_acceptance_pending_official_evaluation"] is True
    assert (
        output / "worker-00" / "parsebench" / "markdown-repeat-1" / "parsebench-0.md"
    ).read_bytes() == b"improved"
