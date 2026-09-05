"""Masterplan section 45: a score row walked back to the source page's sha256."""

from __future__ import annotations

import pytest
from arena.scoring import evaluators, jsonio, provenance
from arena.scoring.errors import ProvenanceError
from arena.scoring.outputs import OutputSet, load_model_output_set, load_source_index
from arena.scoring.paths import ScoringPaths
from conftest import IMAGE_DIGEST, MODEL_REVISION, Campaign


def _lane(paths: ScoringPaths) -> evaluators.EvaluatorLane:
    return evaluators.resolve_lane(paths, "omnidoc", "historical")


def _seed_score(campaign: Campaign, *, evaluator_revision: str | None = None) -> OutputSet:
    """Write the summary and per-case rows a chain walk starts from."""

    output_set = load_model_output_set(campaign.paths, campaign.model_key)
    lane = _lane(campaign.paths)
    prov = provenance.build_provenance(campaign.paths, output_set, lane)
    if evaluator_revision is not None:
        prov["evaluator_revision"] = evaluator_revision
    jsonio.write_json_atomic(
        campaign.paths.summary(campaign.model_key, "omnidoc"),
        {"schema": "tavonel.arena.score-summary.v1", "status": "SCORED", "provenance": prov},
    )
    jsonio.write_jsonl_atomic(
        campaign.paths.per_case(campaign.model_key, "omnidoc"),
        [
            {"case_key": row.case_key, "benchmark": "omnidoc"}
            for row in output_set.for_benchmark("omnidoc")
        ],
    )
    return output_set


def _walk(campaign: Campaign) -> provenance.ChainReport:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)
    return provenance.verify_chain(
        campaign.paths,
        output_set,
        _lane(campaign.paths),
        "omnidoc",
        source_index=load_source_index(campaign.paths),
    )


def test_provenance_names_the_contract_fields(campaign: Campaign) -> None:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)

    prov = provenance.build_provenance(campaign.paths, output_set, _lane(campaign.paths))

    assert prov["model_key"] == campaign.model_key
    assert prov["model_revision"] == MODEL_REVISION
    assert prov["runtime_image_digest"] == IMAGE_DIGEST
    assert prov["frozen_manifest_sha256"].startswith("sha256:")
    assert prov["evaluator_lane"] == "historical"
    assert prov["evaluator_repository"].endswith("OmniDocBench.git")
    assert prov["campaign_id"]
    assert prov["scored_at"].endswith("Z")


def test_an_absent_canonicalizer_is_null_with_a_reason(campaign: Campaign) -> None:
    output_set = load_model_output_set(campaign.paths, campaign.model_key)

    prov = provenance.build_provenance(campaign.paths, output_set, _lane(campaign.paths))

    assert prov["normalization_revision"] is None
    assert "canonical.py is not on disk" in prov["normalization_revision_source"]
    assert [entry["field"] for entry in prov["absent_fields"]] == ["normalization_revision"]


def test_a_present_canonicalizer_is_hashed(campaign: Campaign) -> None:
    source = campaign.paths.canonicalizer_source(campaign.model_key)
    jsonio.write_text_atomic(source, "def canonicalize(raw):\n    return raw\n")
    output_set = load_model_output_set(campaign.paths, campaign.model_key)

    prov = provenance.build_provenance(campaign.paths, output_set, _lane(campaign.paths))

    assert prov["normalization_revision"] == jsonio.sha256_file(source)
    assert prov["absent_fields"] == []


def test_the_chain_passes_over_an_intact_tree(campaign: Campaign) -> None:
    _seed_score(campaign)

    report = _walk(campaign)

    assert report.passed
    assert report.checked == 2
    assert report.ok == 2
    assert report.evaluator_link["ok"] is True


def test_the_chain_records_every_masterplan_link(campaign: Campaign) -> None:
    _seed_score(campaign)

    record = _walk(campaign).to_record()

    assert record["chain"] == [
        "score_row",
        "normalized_output",
        "raw_output",
        "inference_receipt",
        "model_revision",
        "runtime_image",
        "source_sha",
    ]


def test_tampered_output_bytes_break_the_chain(campaign: Campaign) -> None:
    _seed_score(campaign)
    campaign.corrupt_canonical(campaign.specs[0].case_key)

    report = _walk(campaign)

    assert not report.passed
    broken = report.failures[0]
    assert broken.case_key == campaign.specs[0].case_key
    assert [step["step"] for step in broken.steps if not step["ok"]] == ["normalized_output"]


def test_a_missing_receipt_breaks_the_chain(campaign: Campaign) -> None:
    _seed_score(campaign)
    jsonio.io_path(campaign.receipt(campaign.specs[0].case_key)).unlink()

    report = _walk(campaign)

    assert not report.passed
    assert "inference_receipt" in [
        step["step"] for step in report.failures[0].steps if not step["ok"]
    ]


def test_a_receipt_naming_another_source_breaks_the_chain(campaign: Campaign) -> None:
    _seed_score(campaign)
    campaign.edit_receipt(campaign.specs[0].case_key, source_sha256="sha256:" + "4" * 64)

    report = _walk(campaign)

    assert not report.passed
    assert "source_sha" in [
        step["step"] for step in report.failures[0].steps if not step["ok"]
    ]


def test_a_summary_scored_at_another_evaluator_revision_breaks_the_link(
    campaign: Campaign,
) -> None:
    _seed_score(campaign, evaluator_revision="0" * 40)

    report = _walk(campaign)

    assert not report.passed
    assert report.evaluator_link["ok"] is False
    assert report.evaluator_link["summary"] == "0" * 40


def test_a_page_with_no_score_row_breaks_the_chain(campaign: Campaign) -> None:
    _seed_score(campaign)
    jsonio.write_jsonl_atomic(campaign.paths.per_case(campaign.model_key, "omnidoc"), [])

    report = _walk(campaign)

    assert not report.passed
    assert all(
        "score_row" in [step["step"] for step in chain.steps if not step["ok"]]
        for chain in report.failures
    )


def test_walking_before_scoring_is_refused(campaign: Campaign) -> None:
    with pytest.raises(ProvenanceError, match="no summary at"):
        _walk(campaign)


def test_the_chain_file_accumulates_per_benchmark(campaign: Campaign) -> None:
    _seed_score(campaign)

    path, digest = provenance.write_chain(campaign.paths, _walk(campaign))
    document = jsonio.read_json(path)

    assert digest.startswith("sha256:")
    assert document["schema"] == provenance.CHAIN_SCHEMA
    assert document["passed"] is True
    assert document["benchmarks"]["omnidoc"]["cases_checked"] == 2
