"""``python -m arena.scoring`` - order enforcement, dry runs, exit codes."""

from __future__ import annotations

import pytest
from arena.constants import HISTORICAL_EVALUATOR_PINS
from arena.scoring import jsonio
from arena.scoring.cli import main
from conftest import Campaign


def _argv(campaign: Campaign, command: str, *extra: str) -> list[str]:
    return [
        command,
        "--model",
        campaign.model_key,
        "--root",
        str(campaign.root),
        "--repo-root",
        str(campaign.root / "repo"),
        *extra,
    ]


# ------------------------------------------------------------------------ qa


def test_qa_writes_a_report_per_benchmark_and_exits_zero(campaign: Campaign) -> None:
    assert main(_argv(campaign, "qa")) == 0

    for benchmark in ("omnidoc", "parsebench", "olmocr"):
        document = jsonio.read_json(campaign.paths.qa_report(campaign.model_key, benchmark))
        assert document["passed"] is True
        assert document["benchmark"] == benchmark


def test_qa_exits_non_zero_when_the_gate_is_red(campaign: Campaign) -> None:
    campaign.corrupt_canonical(campaign.specs[0].case_key)

    assert main(_argv(campaign, "qa", "--benchmark", "omnidoc")) == 1


def test_qa_dry_run_writes_nothing(campaign: Campaign, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_argv(campaign, "qa", "--dry-run")) == 0

    assert "[dry-run] would run the section 44 gate" in capsys.readouterr().out
    assert not jsonio.io_path(campaign.paths.qa_report(campaign.model_key, "omnidoc")).exists()


# ------------------------------------------------------------------- prepare


def test_prepare_refuses_before_the_gate_has_run(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(campaign, "prepare", "--benchmark", "omnidoc")) == 1

    assert "no QA report" in capsys.readouterr().err


def test_prepare_writes_inputs_and_a_receipt_after_a_green_gate(campaign: Campaign) -> None:
    main(_argv(campaign, "qa", "--benchmark", "omnidoc"))
    gt = campaign.root / "repo" / "gt" / "OmniDocBench.json"
    jsonio.write_json_atomic(gt, {})

    assert (
        main(_argv(campaign, "prepare", "--benchmark", "omnidoc", "--gt-path", str(gt))) == 0
    )

    root = campaign.paths.evaluator_input(campaign.model_key, "omnidoc")
    receipt = jsonio.read_json(root / "_prepare-receipt.json")
    assert receipt["written"] == 2
    assert (root / "markdown" / "PPT_alpha_page_001.md").is_file()
    assert receipt["config_sha256"].startswith("sha256:")
    assert (root / "markdown").is_dir()


def test_prepare_refuses_when_the_gate_is_red(campaign: Campaign) -> None:
    campaign.set_campaign_manifest_count("omnidoc", 99)
    main(_argv(campaign, "qa", "--benchmark", "omnidoc"))

    assert main(_argv(campaign, "prepare", "--benchmark", "omnidoc")) == 1


# --------------------------------------------------------------------- score


def test_score_dry_run_prints_the_exact_commands(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(campaign, "score", "--benchmark", "omnidoc", "--dry-run")) == 0

    printed = capsys.readouterr().out
    assert "git clone --no-checkout" in printed
    assert f"checkout {HISTORICAL_EVALUATOR_PINS['omnidoc']}" in printed
    assert "python -m pip install -e ." in printed
    assert "pdf_validation.py --config" in printed
    assert "watchdog" in printed


def test_score_dry_run_prints_the_parsebench_group_commands(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(campaign, "score", "--benchmark", "parsebench", "--dry-run")) == 0

    printed = capsys.readouterr().out
    assert "uv run parse-bench evaluation run" in printed
    assert "--group=text_formatting" in printed
    assert "--product_type=layout_detection" in printed


def test_score_dry_run_touches_no_evaluator_checkout(campaign: Campaign) -> None:
    main(_argv(campaign, "score", "--benchmark", "omnidoc", "--dry-run"))

    assert not jsonio.io_path(campaign.paths.evaluator_checkouts).exists()


# --------------------------------------------------------------------- parse


def _write_olmocr_raw(campaign: Campaign) -> None:
    jsonio.write_json_atomic(
        campaign.paths.evaluator_raw(campaign.model_key, "olmocr")
        / "benchmark"
        / "official-result.json",
        {
            "candidate": campaign.model_key,
            "candidate_errors": [],
            "test_count": 2,
            "pdf_count": 2,
            "overall_score": 1.0,
            "per_jsonl": {"tables.jsonl": {"total": 2, "passed": 2, "pass_rate": 1.0}},
            "type_breakdown": {"table": {"test_count": 2, "pass_rate": 1.0}},
            "tests": [
                {
                    "test_id": "t1",
                    "pdf": "tables/table_two.pdf",
                    "page": 1,
                    "type": "table",
                    "source_jsonl": "tables.jsonl",
                    "passed": True,
                    "explanation": None,
                },
                {
                    "test_id": "t2",
                    "pdf": "arxiv_math/2502.15977_pg21.pdf",
                    "page": 1,
                    "type": "present",
                    "source_jsonl": "tables.jsonl",
                    "passed": True,
                    "explanation": None,
                },
            ],
        },
    )


def test_parse_writes_summary_per_case_and_scores_json(campaign: Campaign) -> None:
    main(_argv(campaign, "qa", "--benchmark", "olmocr"))
    _write_olmocr_raw(campaign)

    assert main(_argv(campaign, "parse", "--benchmark", "olmocr")) == 0

    summary = jsonio.read_json(campaign.paths.summary(campaign.model_key, "olmocr"))
    assert summary["status"] == "SCORED"
    assert summary["metrics"]["overall_score"] == 1.0
    assert summary["provenance"]["evaluator_revision"] == HISTORICAL_EVALUATOR_PINS["olmocr"]
    rows = jsonio.read_jsonl(campaign.paths.per_case(campaign.model_key, "olmocr"))
    assert [row["case_key"] for row in rows] == [
        "olmocr-bench-0000000000000000000000c1",
        "olmocr-bench-0000000000000000000000c2",
    ]
    scores = jsonio.read_json(campaign.paths.scores_json(campaign.model_key))
    assert scores["benchmarks"]["olmocr"]["status"] == "SCORED"


def test_parse_records_a_blocked_evaluator_instead_of_zeros(campaign: Campaign) -> None:
    main(_argv(campaign, "qa", "--benchmark", "olmocr"))

    assert main(_argv(campaign, "parse", "--benchmark", "olmocr")) == 2

    summary = jsonio.read_json(campaign.paths.summary(campaign.model_key, "olmocr"))
    assert summary["status"] == "EVALUATOR_BLOCKED"
    assert summary["metrics"] is None
    scores = jsonio.read_json(campaign.paths.scores_json(campaign.model_key))
    assert scores["benchmarks"]["olmocr"]["status"] == "EVALUATOR_BLOCKED"


def test_parse_refuses_before_the_gate(campaign: Campaign) -> None:
    _write_olmocr_raw(campaign)

    assert main(_argv(campaign, "parse", "--benchmark", "olmocr")) == 1


# ---------------------------------------------------------------- provenance


def test_provenance_walks_the_chain_and_writes_it(campaign: Campaign) -> None:
    main(_argv(campaign, "qa", "--benchmark", "olmocr"))
    _write_olmocr_raw(campaign)
    main(_argv(campaign, "parse", "--benchmark", "olmocr"))

    assert main(_argv(campaign, "provenance", "--benchmark", "olmocr")) == 0

    document = jsonio.read_json(campaign.paths.provenance_chain(campaign.model_key))
    assert document["benchmarks"]["olmocr"]["passed"] is True


def test_provenance_reports_a_broken_chain_with_a_non_zero_exit(campaign: Campaign) -> None:
    main(_argv(campaign, "qa", "--benchmark", "olmocr"))
    _write_olmocr_raw(campaign)
    main(_argv(campaign, "parse", "--benchmark", "olmocr"))
    campaign.corrupt_canonical("olmocr-bench-0000000000000000000000c2")

    assert main(_argv(campaign, "provenance", "--benchmark", "olmocr")) == 1

    document = jsonio.read_json(campaign.paths.provenance_chain(campaign.model_key))
    assert document["benchmarks"]["olmocr"]["passed"] is False


# --------------------------------------------------------------------- misc


def test_an_unknown_model_is_refused(
    campaign: Campaign, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        "qa",
        "--model",
        "not_a_model",
        "--root",
        str(campaign.root),
    ]

    assert main(argv) == 1
    assert "has no frozen manifest" in capsys.readouterr().err
