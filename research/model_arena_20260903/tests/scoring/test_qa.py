"""The masterplan section 44 gate: green on a clean tree, red on each break."""

from __future__ import annotations

from pathlib import Path

import pytest
from arena.scoring import jsonio, qa
from arena.scoring.errors import InputError, QaGateError
from arena.scoring.outputs import load_model_output_set, load_output_set, load_source_index
from arena.scoring.paths import ScoringPaths
from conftest import Campaign, CaseSpec, build_campaign


def _gate(campaign: Campaign, benchmark: str = "omnidoc") -> qa.QaReport:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)
    return qa.run_qa_gate(campaign.paths, output_set, benchmark)


def _check(report: qa.QaReport, name: str) -> qa.QaCheck:
    for check in report.checks:
        if check.name == name:
            return check
    raise AssertionError(f"no check named {name!r} in {[c.name for c in report.checks]}")


def test_clean_tree_passes_every_blocking_check(campaign: Campaign) -> None:
    report = _gate(campaign)

    assert report.passed
    assert report.blocking_failures == ()
    assert report.sample_count == 2
    assert report.success_count == 2
    assert _check(report, "sample_count_exact").data == {"observed": 2, "expected": 2}


def test_every_benchmark_in_the_set_is_gated(campaign: Campaign) -> None:
    for benchmark in ("omnidoc", "parsebench", "olmocr"):
        assert _gate(campaign, benchmark).passed


def test_sample_count_mismatch_blocks(campaign: Campaign) -> None:
    campaign.set_campaign_manifest_count("omnidoc", 3)

    report = _gate(campaign)

    assert not report.passed
    assert "sample_count_exact" in report.blocking_failures
    assert _check(report, "sample_count_exact").data["expected"] == 3


def test_a_missing_campaign_manifest_fails_closed(campaign: Campaign) -> None:
    campaign.remove_campaign_manifest()

    report = _gate(campaign)

    check = _check(report, "sample_count_exact")
    assert check.state == "FAIL"
    assert "campaign_manifest.json is absent" in check.detail
    assert "fails closed" in check.detail


def test_duplicate_case_key_blocks(campaign: Campaign) -> None:
    duplicated = campaign.specs[0].case_key
    campaign.duplicate_row(duplicated)

    report = _gate(campaign)

    assert "duplicate_case_keys" in report.blocking_failures
    assert _check(report, "duplicate_case_keys").data["sample"] == [duplicated]


def test_missing_case_key_blocks_and_is_listed(campaign: Campaign) -> None:
    dropped = campaign.specs[1].case_key
    campaign.drop_row(dropped)

    report = _gate(campaign)

    assert "missing_case_keys" in report.blocking_failures
    assert _check(report, "missing_case_keys").data["missing_sample"] == [dropped]


def test_hash_mismatch_blocks(campaign: Campaign) -> None:
    tampered = campaign.specs[0].case_key
    campaign.corrupt_canonical(tampered)

    report = _gate(campaign)

    assert "output_hashes_present_and_match" in report.blocking_failures
    problem = _check(report, "output_hashes_present_and_match").data["sample"][0]
    assert problem == {
        "case_key": tampered,
        "field": "canonical",
        "problem": "hash mismatch",
        "recorded": problem["recorded"],
        "recomputed": problem["recomputed"],
    }
    assert problem["recorded"] != problem["recomputed"]


def test_missing_output_file_blocks(campaign: Campaign) -> None:
    case_key = campaign.specs[0].case_key
    jsonio.io_path(campaign.canonical(case_key)).unlink()

    report = _gate(campaign)

    assert "output_hashes_present_and_match" in report.blocking_failures
    assert _check(report, "output_hashes_present_and_match").data["sample"][0][
        "problem"
    ] == "file missing"


def test_invalid_utf8_blocks(campaign: Campaign) -> None:
    case_key = campaign.specs[0].case_key
    campaign.write_invalid_utf8(case_key)

    report = _gate(campaign)

    assert "invalid_utf8" in report.blocking_failures
    assert _check(report, "invalid_utf8").data["sample"] == [case_key]


def test_zero_byte_output_is_recorded_but_does_not_block(campaign: Campaign) -> None:
    case_key = campaign.specs[0].case_key
    campaign.empty_canonical(case_key)

    report = _gate(campaign)

    assert report.passed, "an empty output is a result, not an integrity violation"
    zero = _check(report, "zero_byte_outputs")
    assert zero.blocking is False
    assert zero.data["sample"] == [case_key]


def test_blank_source_and_empty_extraction_are_counted_apart(tmp_path: Path) -> None:
    blank, busy = (
        CaseSpec(
            benchmark="omnidoc",
            case_key="omnidocbench-0000000000000000000000d1",
            source_relative_path="images/blank_page_001.png",
            media_type="image",
            page_index=1,
            markdown="",
            is_probably_blank=True,
        ),
        CaseSpec(
            benchmark="omnidoc",
            case_key="omnidocbench-0000000000000000000000d2",
            source_relative_path="images/dense_page_002.png",
            media_type="image",
            page_index=2,
            markdown="",
            is_probably_blank=False,
        ),
    )
    campaign = build_campaign(tmp_path / "arena", specs=(blank, busy))

    report = _gate(campaign)

    data = _check(report, "blank_source_vs_empty_extraction").data
    assert data["empty_on_blank_source_count"] == 1
    assert data["empty_on_blank_source_sample"] == [blank.case_key]
    assert data["empty_on_nonblank_source_count"] == 1
    assert data["empty_on_nonblank_source_sample"] == [busy.case_key]
    assert report.passed, "section 41 counts them; it does not change any score"


def test_two_model_revisions_block(campaign: Campaign) -> None:
    campaign.edit_receipt(campaign.specs[0].case_key, model_revision="f" * 40)

    report = _gate(campaign)

    assert "model_revision_unique" in report.blocking_failures
    assert len(_check(report, "model_revision_unique").data["observed_revisions"]) == 2


def test_source_hash_mismatch_blocks(campaign: Campaign) -> None:
    campaign.edit_receipt(campaign.specs[0].case_key, source_sha256="sha256:" + "9" * 64)

    report = _gate(campaign)

    assert "source_hash_match" in report.blocking_failures


def test_two_run_configs_block(campaign: Campaign) -> None:
    campaign.edit_receipt(campaign.specs[0].case_key, inference_config_sha256="sha256:" + "1" * 64)

    report = _gate(campaign)

    assert "run_config_hash_match" in report.blocking_failures


def test_run_config_registry_comparison_is_reported_when_skipped(campaign: Campaign) -> None:
    report = _gate(campaign)

    check = _check(report, "run_config_hash_match")
    assert check.state == "PASS"
    assert check.data["registry_comparison"] == "skipped: registry entry absent"


def test_run_config_disagreeing_with_the_registry_blocks(campaign: Campaign) -> None:
    jsonio.write_json_atomic(
        campaign.paths.model_registry,
        {
            "models": {
                campaign.model_key: {
                    "model_key": campaign.model_key,
                    "prompt_id": "a_different_prompt",
                    "inference_config_sha256": "sha256:" + "7" * 64,
                }
            }
        },
    )

    report = _gate(campaign)

    assert "run_config_hash_match" in report.blocking_failures
    assert "a_different_prompt" in _check(report, "run_config_hash_match").detail


def test_missing_page_receipt_blocks(campaign: Campaign) -> None:
    jsonio.io_path(campaign.receipt(campaign.specs[0].case_key)).unlink()

    report = _gate(campaign)

    assert "page_receipts_present" in report.blocking_failures


def test_adapter_failures_are_listed_without_blocking(campaign: Campaign) -> None:
    campaign.edit_receipt(
        campaign.specs[0].case_key, status="FAILED", error_class="OUTPUT_MALFORMED"
    )

    report = _gate(campaign)

    listed = _check(report, "adapter_failures")
    assert listed.blocking is False
    assert listed.data["sample"][0]["error_class"] == "OUTPUT_MALFORMED"


def test_report_round_trips_and_gates_the_next_step(campaign: Campaign) -> None:
    report = _gate(campaign)
    path, digest = qa.write_qa_report(campaign.paths, report)

    assert digest.startswith("sha256:")
    document = qa.require_qa_passed(campaign.paths, campaign.model_key, "omnidoc")
    assert document["passed"] is True
    assert document["schema"] == qa.QA_REPORT_SCHEMA
    assert jsonio.sha256_file(path) == digest


def test_a_red_report_refuses_the_next_step(campaign: Campaign) -> None:
    campaign.set_campaign_manifest_count("omnidoc", 99)
    qa.write_qa_report(campaign.paths, _gate(campaign))

    with pytest.raises(QaGateError, match="is red"):
        qa.require_qa_passed(campaign.paths, campaign.model_key, "omnidoc")


def test_an_absent_report_refuses_the_next_step(campaign: Campaign) -> None:
    with pytest.raises(QaGateError, match="no QA report"):
        qa.require_qa_passed(campaign.paths, campaign.model_key, "omnidoc")


def test_unknown_benchmark_is_refused(campaign: Campaign) -> None:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)

    with pytest.raises(InputError, match="unknown benchmark"):
        qa.run_qa_gate(campaign.paths, output_set, "not_a_benchmark")


def test_a_missing_source_manifest_is_refused(tmp_path: Path) -> None:
    paths = ScoringPaths(root=tmp_path, repo_root=tmp_path)

    with pytest.raises(InputError, match=r"source_manifest\.jsonl is absent"):
        load_source_index(paths)


def test_naming_neither_model_nor_variant_is_refused(campaign: Campaign) -> None:
    with pytest.raises(InputError, match="exactly one"):
        load_output_set(campaign.paths)
