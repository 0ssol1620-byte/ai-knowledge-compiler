"""Scoring a TAVONEL composite variant rather than one model's frozen outputs.

A composite draws pages from several models on purpose, so two of the section
44 checks have no meaning for it. They are marked ``NOT_APPLICABLE`` with the
reason rather than quietly passed, and a page the variant could not resolve is
counted rather than given text.
"""

from __future__ import annotations

import pytest
from arena.scoring import evaluators, jsonio, qa
from arena.scoring.errors import InputError
from arena.scoring.outputs import load_composite_output_set, load_source_index
from arena.scoring.provenance import build_provenance
from conftest import Campaign, add_composite


def _gate(campaign: Campaign, variant: str, benchmark: str = "omnidoc") -> qa.QaReport:
    output_set = load_composite_output_set(campaign.paths, variant)
    return qa.run_qa_gate(campaign.paths, output_set, benchmark)


def _check(report: qa.QaReport, name: str) -> qa.QaCheck:
    return next(check for check in report.checks if check.name == name)


def test_a_composite_is_loaded_from_its_replay_manifest(campaign: Campaign) -> None:
    variant = add_composite(campaign)

    output_set = load_composite_output_set(campaign.paths, variant)

    assert output_set.kind == "composite"
    assert output_set.variant == variant
    assert output_set.model_key is None
    assert len(output_set.rows) == len(campaign.specs)
    assert output_set.rows[0].producing_model_key == campaign.model_key


def test_a_composite_passes_the_gate_with_two_checks_marked_inapplicable(
    campaign: Campaign,
) -> None:
    variant = add_composite(campaign)

    report = _gate(campaign, variant)

    assert report.passed
    for name in ("model_revision_unique", "run_config_hash_match"):
        check = _check(report, name)
        assert check.state == "NOT_APPLICABLE"
        assert "several models by design" in check.detail


def test_an_unresolved_page_is_counted_and_carries_no_text(campaign: Campaign) -> None:
    unresolved = campaign.specs[0].case_key
    variant = add_composite(campaign, unresolved=(unresolved,))

    report = _gate(campaign, variant)

    check = _check(report, "unresolved_composite_pages")
    assert check.blocking is False
    assert check.data["sample"] == [unresolved]
    output_set = load_composite_output_set(campaign.paths, variant)
    row = next(row for row in output_set.rows if row.case_key == unresolved)
    assert row.unresolved is True
    assert row.status != "SUCCESS"
    assert not jsonio.io_path(row.canonical_path).exists()


def test_a_tampered_composite_page_still_blocks(campaign: Campaign) -> None:
    variant = add_composite(campaign)
    jsonio.write_text_atomic(
        campaign.paths.composite_canonical(variant, campaign.specs[0].case_key), "changed\n"
    )

    report = _gate(campaign, variant)

    assert "output_hashes_present_and_match" in report.blocking_failures


def test_an_unresolved_page_is_skipped_when_the_input_is_laid_out(campaign: Campaign) -> None:
    unresolved = campaign.specs[0].case_key
    variant = add_composite(campaign, unresolved=(unresolved,))
    output_set = load_composite_output_set(campaign.paths, variant)

    result = evaluators.prepare_inputs(
        campaign.paths,
        key=variant,
        benchmark="omnidoc",
        rows=output_set.for_benchmark("omnidoc"),
        source_index=load_source_index(campaign.paths),
        pipeline_name=f"tavonel-arena-{variant}",
    )

    assert result.written == 1
    assert result.skipped[0]["case_key"] == unresolved
    assert "no frozen output" in result.skipped[0]["reason"]


def test_composite_provenance_says_why_a_single_revision_is_absent(
    campaign: Campaign,
) -> None:
    variant = add_composite(campaign)
    output_set = load_composite_output_set(campaign.paths, variant)
    lane = evaluators.resolve_lane(campaign.paths, "omnidoc", "historical")

    prov = build_provenance(campaign.paths, output_set, lane)

    assert prov["output_set_kind"] == "composite"
    assert prov["model_key"] is None
    assert prov["normalization_revision"] is None
    assert "mixes canonicalisers" in prov["normalization_revision_source"]
    # One model produced every page here, so the revision is still recoverable.
    assert prov["model_revision"] is not None


def test_a_missing_replay_manifest_is_refused(campaign: Campaign) -> None:
    with pytest.raises(InputError, match="has no composite manifest"):
        load_composite_output_set(campaign.paths, "e_oracle")
