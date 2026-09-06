"""Parsing each evaluator's raw output into summary.json and per_case.jsonl.

The fixtures are shaped like the real thing: the OmniDocBench block follows
``benchmark/cache/omnidoc/result/*_metric_result.json``, the ParseBench block
follows ``_evaluation_report.json`` as ``evaluate_parsebench_official.py``
reads it, and the olmOCR block follows what
``arena/scoring/drivers/olmocr_driver.py`` writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arena.scoring import jsonio, parsers
from arena.scoring.errors import EvaluatorBlockedError
from arena.scoring.outputs import SourceIndex, load_source_index
from conftest import Campaign

_PREFIX = "markdown_quick_match"


def _raw(campaign: Campaign, benchmark: str) -> Path:
    return campaign.paths.evaluator_raw(campaign.model_key, benchmark)


def _index(campaign: Campaign) -> SourceIndex:
    return load_source_index(campaign.paths)


# ------------------------------------------------------------------ OmniDocBench


def _write_omnidoc(campaign: Campaign) -> Path:
    step = _raw(campaign, "omnidoc") / "end2end"
    jsonio.write_json_atomic(
        step / f"{_PREFIX}_metric_result.json",
        {
            "text_block": {
                "all": {
                    "Edit_dist": {
                        "ALL_page_avg": 0.0196,
                        "edit_whole": 0.0250,
                        "edit_sample_avg": 0.0205,
                    }
                },
                "page": {"Edit_dist": {"ALL": 0.0196, "language: english": 0.0188}},
            },
            "display_formula": {
                "all": {"Edit_dist": {"ALL_page_avg": 0.2516}},
                "page": {"Edit_dist": {"ALL": 0.2516}},
            },
            "table": {
                "all": {
                    "TEDS": {"all": 0.7973},
                    "TEDS_structure_only": {"all": 0.8613},
                    "Edit_dist": {"ALL_page_avg": 0.1076},
                },
                "page": {"TEDS": {"ALL": 0.8778, "data_source: newspaper": 0.8479}},
            },
            "reading_order": {
                "all": {"Edit_dist": {"ALL_page_avg": 0.0666}},
                "page": {"Edit_dist": {"ALL": 0.0666}},
            },
            "match_debug": {"page_count": 2, "workers": 4},
        },
    )
    jsonio.write_json_atomic(
        step / f"{_PREFIX}_text_block_per_page_edit.json",
        {"PPT_alpha_page_001.png": 0.0, "PPT_beta_page_002.png": 0.25},
    )
    jsonio.write_json_atomic(
        step / f"{_PREFIX}_reading_order_per_page_edit.json",
        {"PPT_alpha_page_001.png": 0.1},
    )
    jsonio.write_json_atomic(
        step / f"{_PREFIX}_table_per_table_TEDS.json",
        {
            "PPT_beta_page_002.png_[0]": {"TEDS": 0.18, "TEDS_structure_only": 0.20},
            "PPT_beta_page_002.png_[1]": {"TEDS": -0.1086, "TEDS_structure_only": 0.0},
            "a_page_nobody_staged.png_[0]": {"TEDS": 0.5, "TEDS_structure_only": 0.5},
        },
    )
    return step


def test_omnidoc_keeps_the_evaluator_metric_names(campaign: Campaign) -> None:
    _write_omnidoc(campaign)

    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    assert parsed.metrics["table"]["TEDS"] == {"all": 0.7973}
    assert parsed.metrics["table"]["TEDS_structure_only"] == {"all": 0.8613}
    assert parsed.metrics["text_block"]["Edit_dist"]["ALL_page_avg"] == 0.0196
    assert parsed.metrics["reading_order"]["Edit_dist"]["ALL_page_avg"] == 0.0666
    assert parsed.per_category["table"]["TEDS"]["data_source: newspaper"] == 0.8479


def test_omnidoc_publishes_no_overall_it_did_not_measure(campaign: Campaign) -> None:
    _write_omnidoc(campaign)

    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    missing = {item.name: item.reason for item in parsed.missing_metrics}
    assert "overall" in missing
    assert "publishes no single overall figure" in missing["overall"]
    assert "overall" not in parsed.metrics


def test_omnidoc_per_case_rows_join_on_case_key(campaign: Campaign) -> None:
    _write_omnidoc(campaign)

    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    rows = {row["case_key"]: row for row in parsed.per_case}
    alpha = rows["omnidocbench-0000000000000000000000a1"]
    beta = rows["omnidocbench-0000000000000000000000a2"]
    assert alpha["metrics"]["text_block.Edit_dist"] == 0.0
    assert alpha["metrics"]["reading_order.Edit_dist"] == 0.1
    assert alpha["sample_id"] == "omnidoc:images/PPT_alpha_page_001"
    assert [entry["TEDS"] for entry in beta["table_teds"]] == [0.18, -0.1086]


def test_omnidoc_negative_teds_survives_unclamped(campaign: Campaign) -> None:
    _write_omnidoc(campaign)

    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    beta = next(
        row for row in parsed.per_case if row["case_key"].endswith("a2")
    )
    assert min(entry["TEDS"] for entry in beta["table_teds"]) == -0.1086


def test_omnidoc_unjoinable_location_is_listed_not_guessed(campaign: Campaign) -> None:
    _write_omnidoc(campaign)

    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    assert parsed.unjoined_locations == (
        {
            "artifact": f"{_PREFIX}_table_per_table_TEDS.json",
            "location": "a_page_nobody_staged.png_[0]",
        },
    )


def test_omnidoc_without_a_metric_result_is_blocked(campaign: Campaign) -> None:
    with pytest.raises(EvaluatorBlockedError, match=r"metric_result\.json is absent"):
        parsers.parse_raw("omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign))


# --------------------------------------------------------------------- ParseBench


def _report(test_id: str, *, success: bool = True, rules: int = 3, passed: int = 2) -> Any:
    rule_results = [{"passed": index < passed, "type": "table"} for index in range(rules)]
    return {
        "test_id": test_id,
        "success": success,
        "error": None if success else "evaluation failed",
        "product_type": "parse",
        "metrics": [
            {
                "metric_name": "rule_pass_rate",
                "value": passed / rules,
                "metadata": {"rule_results": rule_results},
            }
        ],
    }


def _write_parsebench(campaign: Campaign) -> None:
    raw = _raw(campaign, "parsebench")
    jsonio.write_json_atomic(
        raw / "chart" / "_evaluation_report.json",
        {
            "total_examples": 1,
            "successful": 1,
            "failed": 0,
            "aggregate_metrics": {"avg_rule_pass_rate": 0.6667},
            "per_example_results": [_report("chart/quarterly_chart")],
        },
    )
    jsonio.write_json_atomic(
        raw / "text_content" / "_evaluation_report.json",
        {
            "total_examples": 2,
            "successful": 1,
            "failed": 1,
            "aggregate_metrics": {"avg_rule_pass_rate": 0.5},
            "per_example_results": [
                _report("text/policy_letter", rules=4, passed=2),
                _report("text/a_page_nobody_staged", success=False),
            ],
        },
    )


def test_parsebench_metrics_are_reported_per_group(campaign: Campaign) -> None:
    _write_parsebench(campaign)

    parsed = parsers.parse_raw(
        "parsebench", _raw(campaign, "parsebench"), source_index=_index(campaign)
    )

    assert parsed.metrics["chart"]["aggregate_metrics"] == {"avg_rule_pass_rate": 0.6667}
    assert parsed.metrics["chart"]["product_type"] == "parse"
    assert parsed.metrics["text_content"]["failed"] == 1
    assert parsed.counts["total_examples"] == 3


def test_parsebench_absent_group_report_is_a_missing_metric(campaign: Campaign) -> None:
    _write_parsebench(campaign)

    parsed = parsers.parse_raw(
        "parsebench", _raw(campaign, "parsebench"), source_index=_index(campaign)
    )

    missing = {item.name for item in parsed.missing_metrics}
    assert {"layout", "table", "text_formatting", "overall"} <= missing
    assert "layout" not in parsed.metrics


def test_parsebench_rule_counts_reach_the_per_case_rows(campaign: Campaign) -> None:
    _write_parsebench(campaign)

    parsed = parsers.parse_raw(
        "parsebench", _raw(campaign, "parsebench"), source_index=_index(campaign)
    )

    rows = {(row["case_key"], row["group"]): row for row in parsed.per_case}
    chart = rows[("parsebench-0000000000000000000000b1", "chart")]
    assert chart["rule_pass_count"] == 2
    assert chart["rule_fail_count"] == 1
    assert chart["metrics"]["rule_pass_rate"] == pytest.approx(2 / 3)
    assert parsed.counts["rule_pass_count"] == 4
    assert parsed.counts["rule_fail_count"] == 3


def test_parsebench_unknown_test_id_is_listed_not_joined(campaign: Campaign) -> None:
    _write_parsebench(campaign)

    parsed = parsers.parse_raw(
        "parsebench", _raw(campaign, "parsebench"), source_index=_index(campaign)
    )

    assert parsed.unjoined_locations == (
        {
            "artifact": "text_content/_evaluation_report.json",
            "test_id": "text/a_page_nobody_staged",
        },
    )


# ------------------------------------------------------------------- olmOCR-Bench


def _write_olmocr(campaign: Campaign, **overrides: Any) -> None:
    payload: dict[str, Any] = {
        "schema": "tavonel.arena.olmocr-official-result.v1",
        "candidate": campaign.model_key,
        "pdf_count": 2,
        "test_count": 3,
        "candidate_errors": [],
        "overall_score": 0.75,
        "overall_score_definition": "mean of the per-jsonl pass rates",
        "per_jsonl": {
            "arxiv_math.jsonl": {"total": 2, "passed": 1, "pass_rate": 0.5},
            "table_tests.jsonl": {"total": 1, "passed": 1, "pass_rate": 1.0},
        },
        "type_breakdown": {"present": {"test_count": 2, "pass_rate": 0.5}},
        "tests": [
            {
                "test_id": "t1",
                "pdf": "arxiv_math/2502.15977_pg21.pdf",
                "page": 1,
                "type": "present",
                "source_jsonl": "arxiv_math.jsonl",
                "passed": True,
                "explanation": None,
            },
            {
                "test_id": "t2",
                "pdf": "arxiv_math/2502.15977_pg21.pdf",
                "page": 1,
                "type": "present",
                "source_jsonl": "arxiv_math.jsonl",
                "passed": False,
                "explanation": "text not found",
            },
            {
                "test_id": "t3",
                "pdf": "elsewhere/unstaged.pdf",
                "page": 1,
                "type": "table",
                "source_jsonl": "table_tests.jsonl",
                "passed": True,
                "explanation": None,
            },
        ],
    }
    payload.update(overrides)
    jsonio.write_json_atomic(
        _raw(campaign, "olmocr") / "benchmark" / "official-result.json", payload
    )


def test_olmocr_overall_and_categories_come_from_the_evaluator(campaign: Campaign) -> None:
    _write_olmocr(campaign)

    parsed = parsers.parse_raw(
        "olmocr", _raw(campaign, "olmocr"), source_index=_index(campaign)
    )

    assert parsed.metrics["overall_score"] == 0.75
    assert parsed.per_category["per_jsonl"]["arxiv_math.jsonl"]["pass_rate"] == 0.5
    assert parsed.per_category["type_breakdown"]["present"]["test_count"] == 2


def test_olmocr_per_case_rows_carry_individual_tests(campaign: Campaign) -> None:
    _write_olmocr(campaign)

    parsed = parsers.parse_raw(
        "olmocr", _raw(campaign, "olmocr"), source_index=_index(campaign)
    )

    row = next(row for row in parsed.per_case)
    assert row["case_key"] == "olmocr-bench-0000000000000000000000c1"
    assert row["test_count"] == 2
    assert row["passed_count"] == 1
    assert row["pass_rate"] == 0.5
    assert {entry["test_id"] for entry in row["tests"]} == {"t1", "t2"}


def test_olmocr_unstaged_pdf_is_listed_not_joined(campaign: Campaign) -> None:
    _write_olmocr(campaign)

    parsed = parsers.parse_raw(
        "olmocr", _raw(campaign, "olmocr"), source_index=_index(campaign)
    )

    assert parsed.unjoined_locations[0]["pdf"] == "elsewhere/unstaged.pdf"


def test_olmocr_candidate_errors_block_rather_than_score_zero(campaign: Campaign) -> None:
    _write_olmocr(campaign, candidate_errors=["missing MD repeats for x.pdf"])

    with pytest.raises(EvaluatorBlockedError, match="candidate validation errors"):
        parsers.parse_raw("olmocr", _raw(campaign, "olmocr"), source_index=_index(campaign))


def test_olmocr_without_a_result_file_is_blocked(campaign: Campaign) -> None:
    with pytest.raises(EvaluatorBlockedError, match="official result is absent"):
        parsers.parse_raw("olmocr", _raw(campaign, "olmocr"), source_index=_index(campaign))


# ------------------------------------------------------------------- summaries


def test_a_blocked_summary_carries_null_metrics_not_zeros() -> None:
    summary = parsers.blocked_summary(
        key="paddleocr_vl_1_6",
        benchmark="omnidoc",
        provenance={"evaluator_revision": "abc"},
        reason="step 'end2end' exited 1",
        stderr_tail="Traceback ...",
        returncode=1,
    )

    assert summary["status"] == "EVALUATOR_BLOCKED"
    assert summary["metrics"] is None
    assert summary["blocked_returncode"] == 1
    assert summary["stderr_tail"] == "Traceback ..."


def test_a_scored_summary_carries_provenance_and_the_gate_digest(campaign: Campaign) -> None:
    _write_omnidoc(campaign)
    parsed = parsers.parse_raw(
        "omnidoc", _raw(campaign, "omnidoc"), source_index=_index(campaign)
    )

    summary = parsers.build_summary(
        parsed,
        key=campaign.model_key,
        provenance={"evaluator_revision": "abc", "evaluator_lane": "historical"},
        qa_report_sha256="sha256:" + "0" * 64,
    )

    assert summary["status"] == "SCORED"
    assert summary["schema"] == parsers.SUMMARY_SCHEMA
    assert summary["provenance"]["evaluator_lane"] == "historical"
    assert summary["qa_report_sha256"] == "sha256:" + "0" * 64
    assert summary["evaluator_artifacts_sha256"]
