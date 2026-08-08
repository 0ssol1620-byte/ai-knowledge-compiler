from __future__ import annotations

import json
from pathlib import Path

from benchmark.v6.public_failure_adapter import _IDENTIFIER
from build_public_failure_records import (
    EvaluationSource,
    _safe,
    build_failure_records,
)

HASH_A = "sha256:" + "a" * 64
REVISION = "c" * 40


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_official_failures_are_bound_and_routed_by_failure_family(tmp_path: Path) -> None:
    merged = tmp_path / "merged"
    case_ids = {
        "parsebench": "parsebench-a",
        "omnidocbench": "omnidocbench-a",
        "olmocr-bench": "olmocr-bench-a",
    }
    for suite, case_id in case_ids.items():
        _write(
            merged / "indexes" / f"{suite}-cases.json",
            {
                "input_count": 1,
                "records": [
                    {
                        "case_id": case_id,
                        "status": "completed",
                        "markdown_sha256": HASH_A,
                        "model_sha256": HASH_A,
                    }
                ],
            },
        )

    parse_root = tmp_path / "parse-eval"
    _write(parse_root / "evaluation-summary.json", {"evaluator_revision": REVISION})
    _write(
        parse_root / "official-rule-failures.json",
        {
            "failure_count": 1,
            "failures": [
                {
                    "case_id": case_ids["parsebench"],
                    "evaluator_type": "missing_specific_word",
                    "location_id": "rule-1",
                    "score": 0.0,
                }
            ],
        },
    )
    omni_root = tmp_path / "omni-eval"
    _write(omni_root / "evaluation-summary.json", {"evaluator_revision": REVISION})
    _write(
        omni_root / "repeat-1" / "official-element-failures.json",
        {
            "failure_count": 1,
            "failures": [
                {
                    "case_id": case_ids["omnidocbench"],
                    "evaluator_type": "text_block",
                    "location_id": "edit:page-a",
                    "score": 0.8,
                }
            ],
        },
    )
    olm_root = tmp_path / "olm-eval"
    _write(olm_root / "evaluation-summary.json", {"evaluator_revision": REVISION})
    _write(
        olm_root / "official-rule-failures.json",
        {
            "failure_count": 1,
            "failures": [
                {
                    "case_id": case_ids["olmocr-bench"],
                    "evaluator_type": "math",
                    "location_id": "math-rule-1",
                    "score": 0.0,
                }
            ],
        },
    )
    output = tmp_path / "failure-records.json"
    result = build_failure_records(
        merged_root=merged,
        evaluations=(
            EvaluationSource("parsebench", parse_root),
            EvaluationSource("omnidocbench", omni_root),
            EvaluationSource("olmocr-bench", olm_root),
        ),
        output_path=output,
    )

    assert result["record_count"] == 3
    assert result["recoverable_case_count"] == 3
    routes = {item["case_id"]: item for item in result["routes"]}
    assert routes[case_ids["parsebench"]]["candidate_models"] == ["deepseek-ocr-2"]
    assert routes[case_ids["omnidocbench"]]["failure_codes"] == ["B01"]
    assert routes[case_ids["olmocr-bench"]]["candidate_models"] == [
        "paddleocr-vl-1.6"
    ]
    assert result["escalation_count"] == 0


def test_non_ascii_locations_stay_valid_and_distinct_identifiers() -> None:
    # str.isalnum is Unicode-aware, so CJK page names used to survive the fold
    # and then fail the ASCII-only recovery-taxonomy identifier check.
    ascii_only = "edit_distance:exam_paper_en_page_002.png"
    assert _safe(ascii_only) == ascii_only

    first = _safe("edit_distance:book_en_[搬书匠#20][HTML5 Canvas].2011.英文版_page_208.png")
    second = _safe("edit_distance:book_en_[搬书匠#375][HTML5 Canvas].2011.英文版_page_208.png")
    for rendered in (first, second):
        assert _IDENTIFIER.fullmatch(rendered), rendered
    assert first != second
