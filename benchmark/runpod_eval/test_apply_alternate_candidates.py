from __future__ import annotations

import json
from pathlib import Path

import pytest
from apply_accepted_alternate_candidates import apply_accepted_alternate_candidates
from apply_alternate_candidates import apply_alternate_candidates
from apply_operational_retries import ResultSource, _sha256
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")


def _baseline(tmp_path: Path) -> tuple[ResultSource, ...]:
    sources = []
    for worker in range(4):
        root = tmp_path / f"baseline-{worker}"
        for suite in SUITES:
            markdown = root / suite / "markdown-repeat-1" / "case.md"
            markdown.parent.mkdir(parents=True, exist_ok=True)
            markdown.write_text("baseline\n", encoding="utf-8")
            summary = {
                "candidate_id": EXPECTED_CANDIDATE_ID,
                "artifact_manifest_sha256": EXPECTED_ARTIFACT_SHA256,
                "runs": [
                    {
                        "repeat_index": 1,
                        "cases": [
                            {
                                "case_id": "case",
                                "status": "completed",
                                "markdown_sha256": _sha256(markdown),
                                "markdown_characters": 9,
                            }
                        ],
                    }
                ],
            }
            _write(root / suite / "run-summary.json", summary)
            _write(
                root / suite / "repeat-1" / "case" / "vlm" / "case_model.json",
                [[{"bbox": [0, 0, 1, 1], "type": "text", "content": "baseline"}]],
            )
        sources.append(ResultSource(worker, root))
    return tuple(sources)


def test_paddle_candidate_and_strict_acceptance_preserve_composite_identity(
    tmp_path: Path,
) -> None:
    baselines = _baseline(tmp_path)
    recovery_root = tmp_path / "recovery"
    recovery_suite = recovery_root / "worker-01" / "parsebench"
    markdown = recovery_suite / "markdown-repeat-1" / "case.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("recovered\n", encoding="utf-8")
    response = recovery_suite / "repeat-1" / "case.json"
    _write(
        response,
        {
            "error": None,
            "pages": [
                {
                    "res": {
                        "width": 100,
                        "height": 100,
                        "parsing_res_list": [
                            {
                                "block_bbox": [10, 20, 90, 80],
                                "block_content": "recovered",
                                "block_label": "text",
                                "block_order": 1,
                            }
                        ],
                    }
                }
            ],
        },
    )
    _write(
        recovery_suite / "run-summary.json",
        {
            "candidate_id": "paddleocr-vl-1.6",
            "artifact_manifest_sha256": (
                "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
            ),
            "ground_truth_mounted": False,
            "evidence_class": "public-core-shard",
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {
                            "case_id": "case",
                            "status": "completed",
                            "markdown_sha256": _sha256(markdown),
                            "markdown_characters": 10,
                            "artifact_sha256": _sha256(response),
                        }
                    ],
                }
            ],
        },
    )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-selective-recovery-staging.v1",
            "recovery_model": "paddleocr-vl-1.6",
            "different_worker_only": True,
            "input_count": 1,
            "routes": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "case",
                    "primary_worker_index": 0,
                    "recovery_worker_index": 1,
                }
            ],
        },
    )
    candidate_root = tmp_path / "candidate"
    candidate = apply_alternate_candidates(
        baseline_sources=baselines,
        recovery_root=recovery_root,
        selective_plan=plan,
        recovery_model="paddleocr-vl-1.6",
        output_root=candidate_root,
    )
    assert candidate["candidate_outputs_applied"] == 1
    converted = json.loads(
        (
            candidate_root
            / "worker-00"
            / "parsebench"
            / "repeat-1"
            / "case"
            / "vlm"
            / "case_model.json"
        ).read_text(encoding="utf-8")
    )
    assert converted[0][0]["bbox"] == [0.1, 0.2, 0.9, 0.8]

    comparison = tmp_path / "comparison.json"
    decision = {
        "benchmark_id": "parsebench",
        "case_id": "case",
        "baseline_failure_record_count": 2,
        "candidate_failure_record_count": 1,
        "baseline_failure_codes": ["T01", "T02"],
        "candidate_failure_codes": ["T02"],
        "new_failure_codes": [],
        "candidate_escalates": False,
        "strictly_improved": True,
    }
    _write(
        comparison,
        {
            "schema": "folynta.public-core-official-failure-comparison.v1",
            "policy": {
                "require_strict_failure_record_reduction": True,
                "forbid_new_failure_codes": True,
                "forbid_candidate_escalation": True,
                "unchanged_candidates_are_not_accepted": True,
            },
            "compared_recoverable_case_count": 1,
            "accepted_quality_case_count": 1,
            "accepted_quality_cases": [decision],
        },
    )
    accepted = apply_accepted_alternate_candidates(
        baseline_sources=baselines,
        candidate_sources=tuple(
            ResultSource(worker, candidate_root / f"worker-{worker:02d}")
            for worker in range(4)
        ),
        selective_plan=plan,
        comparison=comparison,
        recovery_model="paddleocr-vl-1.6",
        output_root=tmp_path / "accepted",
    )
    assert accepted["accepted_case_count"] == 1
    assert (
        tmp_path
        / "accepted"
        / "worker-00"
        / "parsebench"
        / "markdown-repeat-1"
        / "case.md"
    ).read_text(encoding="utf-8") == "recovered\n"


def test_paddle_can_fill_an_operationally_failed_parsebench_case(
    tmp_path: Path,
) -> None:
    baselines = _baseline(tmp_path)
    failed_summary_path = baselines[0].result_root / "parsebench" / "run-summary.json"
    failed_summary = json.loads(failed_summary_path.read_text(encoding="utf-8"))
    failed_summary["runs"][0]["cases"][0] = {
        "case_id": "case",
        "status": "failed",
        "error": "timeout",
    }
    _write(failed_summary_path, failed_summary)

    recovery_root = tmp_path / "recovery"
    recovery_suite = recovery_root / "worker-01" / "parsebench"
    markdown = recovery_suite / "markdown-repeat-1" / "case.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("recovered\n", encoding="utf-8")
    response = recovery_suite / "repeat-1" / "case.json"
    _write(
        response,
        {
            "error": None,
            "pages": [
                {
                    "res": {
                        "width": 100,
                        "height": 100,
                        "parsing_res_list": [
                            {
                                "block_bbox": [10, 20, 90, 80],
                                "block_content": "recovered",
                                "block_label": "text",
                                "block_order": 1,
                            }
                        ],
                    }
                }
            ],
        },
    )
    _write(
        recovery_suite / "run-summary.json",
        {
            "candidate_id": "paddleocr-vl-1.6",
            "artifact_manifest_sha256": (
                "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
            ),
            "ground_truth_mounted": False,
            "evidence_class": "public-core-shard",
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {
                            "case_id": "case",
                            "status": "completed",
                            "markdown_sha256": _sha256(markdown),
                            "markdown_characters": 10,
                            "artifact_sha256": _sha256(response),
                        }
                    ],
                }
            ],
        },
    )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-selective-recovery-staging.v1",
            "recovery_model": "paddleocr-vl-1.6",
            "different_worker_only": True,
            "input_count": 1,
            "routes": [
                {
                    "benchmark_id": "parsebench",
                    "case_id": "case",
                    "primary_worker_index": 0,
                    "recovery_worker_index": 1,
                }
            ],
        },
    )
    output = tmp_path / "candidate"
    receipt = apply_alternate_candidates(
        baseline_sources=baselines,
        recovery_root=recovery_root,
        selective_plan=plan,
        recovery_model="paddleocr-vl-1.6",
        output_root=output,
        operational_failure_targets=True,
    )

    assert receipt["candidate_outputs_applied"] == 1
    assert receipt["operational_failure_targets"] is True
    summary = json.loads(
        (output / "worker-00" / "parsebench" / "run-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["runs"][0]["cases"][0]["status"] == "completed"
    assert summary["runs"][0]["completed"] == 1
    assert summary["runs"][0]["failed"] == 0


def test_paddle_writes_mergeable_model_payload_for_omnidocbench(
    tmp_path: Path,
) -> None:
    baselines = _baseline(tmp_path)
    suite = "omnidocbench"
    failed_summary_path = baselines[0].result_root / suite / "run-summary.json"
    failed_summary = json.loads(failed_summary_path.read_text(encoding="utf-8"))
    failed_summary["runs"][0]["cases"][0] = {
        "case_id": "case",
        "status": "failed",
        "error": "timeout",
    }
    _write(failed_summary_path, failed_summary)

    recovery_suite = tmp_path / "recovery" / "worker-01" / suite
    markdown = recovery_suite / "markdown-repeat-1" / "case.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("recovered\n", encoding="utf-8")
    response = recovery_suite / "repeat-1" / "case.json"
    _write(
        response,
        {
            "error": None,
            "pages": [
                {
                    "res": {
                        "width": 100,
                        "height": 100,
                        "parsing_res_list": [
                            {
                                "block_bbox": [10, 20, 90, 80],
                                "block_content": "recovered",
                                "block_label": "text",
                                "block_order": 1,
                            }
                        ],
                    }
                }
            ],
        },
    )
    _write(
        recovery_suite / "run-summary.json",
        {
            "candidate_id": "paddleocr-vl-1.6",
            "artifact_manifest_sha256": (
                "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
            ),
            "ground_truth_mounted": False,
            "evidence_class": "public-core-shard",
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {
                            "case_id": "case",
                            "status": "completed",
                            "markdown_sha256": _sha256(markdown),
                            "markdown_characters": 10,
                            "artifact_sha256": _sha256(response),
                        }
                    ],
                }
            ],
        },
    )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-selective-recovery-staging.v1",
            "recovery_model": "paddleocr-vl-1.6",
            "different_worker_only": True,
            "input_count": 1,
            "routes": [
                {
                    "benchmark_id": suite,
                    "case_id": "case",
                    "primary_worker_index": 0,
                    "recovery_worker_index": 1,
                }
            ],
        },
    )
    output = tmp_path / "candidate"
    apply_alternate_candidates(
        baseline_sources=baselines,
        recovery_root=tmp_path / "recovery",
        selective_plan=plan,
        recovery_model="paddleocr-vl-1.6",
        output_root=output,
        operational_failure_targets=True,
    )

    assert (
        output
        / "worker-00"
        / suite
        / "repeat-1"
        / "case"
        / "vlm"
        / "case_model.json"
    ).is_file()


@pytest.mark.parametrize(
    ("suite", "blocks", "expected_markdown", "expected_empty"),
    [
        (
            "parsebench",
            [
                {
                    "block_bbox": [10, 10, 30, 90],
                    "block_content": "182\n183",
                    "block_label": "aside_text",
                    "block_order": None,
                }
            ],
            "182\n183\n",
            False,
        ),
        (
            "parsebench",
            [
                {
                    "block_bbox": [10, 10, 90, 20],
                    "block_content": "running header",
                    "block_label": "header",
                    "block_order": None,
                }
            ],
            "",
            True,
        ),
        (
            "olmocr-bench",
            [
                {
                    "block_bbox": [10, 10, 90, 20],
                    "block_content": "archive header",
                    "block_label": "header",
                    "block_order": None,
                }
            ],
            "archive header\n",
            False,
        ),
    ],
)
def test_dual_empty_markdown_resolution_preserves_recognized_page_semantics(
    tmp_path: Path,
    suite: str,
    blocks: list[dict[str, object]],
    expected_markdown: str,
    expected_empty: bool,
) -> None:
    baselines = _baseline(tmp_path)
    failed_summary_path = baselines[0].result_root / suite / "run-summary.json"
    failed_summary = json.loads(failed_summary_path.read_text(encoding="utf-8"))
    failed_summary["runs"][0]["cases"][0] = {
        "case_id": "case",
        "status": "failed",
        "error": "empty_markdown",
    }
    _write(failed_summary_path, failed_summary)

    recovery_suite = tmp_path / "deepseek" / "worker-01" / suite
    recovery_markdown = recovery_suite / "markdown-repeat-1" / "case.md"
    recovery_markdown.parent.mkdir(parents=True)
    recovery_markdown.write_text("", encoding="utf-8")
    _write(
        recovery_suite / "run-summary.json",
        {
            "candidate_id": "deepseek-ocr-2-3b-transformers",
            "artifact_manifest_sha256": (
                "sha256:77137d41428555c636b04ec5a1617e72c7e3e98afd81502b5c8659f6430421bc"
            ),
            "ground_truth_mounted": False,
            "evidence_class": "public-core-shard",
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {
                            "case_id": "case",
                            "status": "failed",
                            "error": "empty_markdown",
                            "markdown_sha256": _sha256(recovery_markdown),
                            "markdown_characters": 0,
                        }
                    ],
                }
            ],
        },
    )

    paddle_suite = tmp_path / "paddle" / "worker-01" / suite
    paddle_markdown = paddle_suite / "markdown-repeat-1" / "case.md"
    paddle_markdown.parent.mkdir(parents=True)
    paddle_markdown.write_text("", encoding="utf-8")
    response = paddle_suite / "repeat-1" / "case.json"
    _write(
        response,
        {
            "error": "empty_markdown",
            "pages": [
                {
                    "res": {
                        "width": 100,
                        "height": 100,
                        "parsing_res_list": blocks,
                    }
                }
            ],
        },
    )
    _write(
        paddle_suite / "run-summary.json",
        {
            "candidate_id": "paddleocr-vl-1.6",
            "artifact_manifest_sha256": (
                "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
            ),
            "ground_truth_mounted": False,
            "evidence_class": "public-core-shard",
            "runs": [
                {
                    "repeat_index": 1,
                    "cases": [
                        {
                            "case_id": "case",
                            "status": "failed",
                            "error": "empty_markdown",
                            "artifact_sha256": _sha256(response),
                        }
                    ],
                }
            ],
        },
    )
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "schema": "folynta.public-core-selective-recovery-staging.v1",
            "recovery_model": "deepseek-ocr-2",
            "different_worker_only": True,
            "input_count": 1,
            "routes": [
                {
                    "benchmark_id": suite,
                    "case_id": "case",
                    "primary_worker_index": 0,
                    "recovery_worker_index": 1,
                }
            ],
        },
    )
    output = tmp_path / "candidate"
    receipt = apply_alternate_candidates(
        baseline_sources=baselines,
        recovery_root=tmp_path / "deepseek",
        selective_plan=plan,
        recovery_model="deepseek-ocr-2",
        output_root=output,
        operational_failure_targets=True,
        paddle_layout_fallback_root=tmp_path / "paddle",
    )

    assert receipt["candidate_outputs_applied"] == 1
    assert receipt["empty_markdown_failures_resolved"] == 1
    summary = json.loads(
        (output / "worker-00" / suite / "run-summary.json").read_text(
            encoding="utf-8"
        )
    )
    case = summary["runs"][0]["cases"][0]
    assert case["status"] == "completed"
    assert case["semantic_empty_page"] is expected_empty
    assert (
        output / "worker-00" / suite / "markdown-repeat-1" / "case.md"
    ).read_text(encoding="utf-8") == expected_markdown
    model = json.loads(
        (
            output
            / "worker-00"
            / suite
            / "repeat-1"
            / "case"
            / "vlm"
            / "case_model.json"
        ).read_text(encoding="utf-8")
    )
    assert (model == [[]]) is expected_empty
