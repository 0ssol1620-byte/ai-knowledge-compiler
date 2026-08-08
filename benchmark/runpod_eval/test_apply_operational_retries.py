from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apply_operational_retries import ResultSource, apply_operational_retries
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def test_completed_different_worker_retry_creates_non_mutating_composite(tmp_path: Path) -> None:
    primary_root = tmp_path / "primary"
    sources = []
    for worker in range(4):
        worker_root = primary_root / f"worker-{worker:02d}"
        sources.append(ResultSource(worker, worker_root))
        for suite in SUITES:
            case_id = f"{suite}-{worker}"
            failed = worker == 0 and suite == "parsebench"
            _write(
                worker_root / suite / "run-summary.json",
                {
                    "runs": [
                        {
                            "repeat_index": 1,
                            "completed": 0 if failed else 1,
                            "failed": 1 if failed else 0,
                            "cases": [
                                {
                                    "case_id": case_id,
                                    "status": "failed" if failed else "completed",
                                    "markdown_sha256": _hash(b"" if failed else b"primary"),
                                    "markdown_characters": 0 if failed else 7,
                                }
                            ],
                        }
                    ]
                },
            )
            markdown = worker_root / suite / "markdown-repeat-1" / f"{case_id}.md"
            markdown.parent.mkdir(parents=True, exist_ok=True)
            markdown.write_bytes(b"" if failed else b"primary")

    retry_root = tmp_path / "retry-worker-04"
    case_id = "parsebench-0"
    markdown_content = b"recovered"
    model_content = b"[]"
    _write(
        retry_root / "parsebench" / "run-summary.json",
        {
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
                            "markdown_sha256": _hash(markdown_content),
                            "markdown_characters": len(markdown_content),
                        }
                    ],
                }
            ],
        },
    )
    retry_markdown = retry_root / "parsebench" / "markdown-repeat-1" / f"{case_id}.md"
    retry_markdown.parent.mkdir(parents=True, exist_ok=True)
    retry_markdown.write_bytes(markdown_content)
    retry_model = retry_root / "parsebench" / "repeat-1" / case_id / "vlm" / f"{case_id}_model.json"
    retry_model.parent.mkdir(parents=True, exist_ok=True)
    retry_model.write_bytes(model_content)

    plan_path = tmp_path / "retry-plan.json"
    _write(
        plan_path,
        {
            "failed_input_count": 1,
            "different_worker_only": True,
            "failures": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": case_id,
                    "primary_worker_index": 0,
                    "retry_worker_index": 4,
                }
            ],
        },
    )
    output = tmp_path / "composite"
    receipt = apply_operational_retries(
        primary_sources=tuple(sources),
        retry_sources=(ResultSource(4, retry_root),),
        retry_plan=plan_path,
        output_root=output,
    )

    assert receipt["accepted"] == 1
    assert receipt["unresolved"] == 0
    assert receipt["case_outcomes"][0]["benchmark_id"] == "parsebench"
    assert receipt["case_outcomes"][0]["accepted"] is True
    original = json.loads(
        (primary_root / "worker-00" / "parsebench" / "run-summary.json").read_text()
    )
    composite = json.loads(
        (output / "worker-00" / "parsebench" / "run-summary.json").read_text()
    )
    assert original["runs"][0]["cases"][0]["status"] == "failed"
    assert composite["runs"][0]["cases"][0]["status"] == "completed"
    assert composite["operational_retry_overlay"][0]["retry_worker_index"] == 4
    assert (
        output / "worker-00" / "parsebench" / "markdown-repeat-1" / f"{case_id}.md"
    ).read_bytes() == markdown_content
