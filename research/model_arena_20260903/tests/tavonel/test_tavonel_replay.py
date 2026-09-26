"""Replay: the composite tree points at real, hash-matched frozen files."""

from __future__ import annotations

import json

import pytest
from arena.tavonel import freeze, jsonio, replay, signals, variants
from arena.tavonel.errors import IntegrityError, MissingInputError
from conftest import PRIMARY, TABLE_SPECIALIST, TEXT_SPECIALIST, Campaign


def _rows(campaign: Campaign, variant: str) -> dict[str, dict]:
    manifest = campaign.paths.replay_manifest(variant)
    return {
        row["case_key"]: row
        for row in (
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line
        )
    }


def _freeze(campaign: Campaign, variant: str) -> None:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variant)


def test_replay_copies_the_chosen_output_and_records_its_hash(campaign: Campaign) -> None:
    _freeze(campaign, variants.VARIANT_C)
    report = replay.replay_variant(campaign.paths, variant=variants.VARIANT_C)
    assert report.resolved == len(campaign.cases)
    assert report.unresolved == 0

    for case_key, row in _rows(campaign, variants.VARIANT_C).items():
        source = campaign.paths.root / row["chosen_canonical_path"]
        composite = campaign.paths.root / row["composite_canonical_path"]
        assert source.is_file()
        assert composite.is_file()
        assert composite.read_bytes() == source.read_bytes()
        digest = jsonio.prefixed(jsonio.sha256_hex(composite.read_bytes()))
        assert row["chosen_canonical_sha256"] == digest
        assert row["composite_canonical_sha256"] == digest
        assert row["unresolved"] is False
        assert composite.name == f"{case_key}.md"


def test_the_composite_tree_is_copies_not_links(campaign: Campaign) -> None:
    _freeze(campaign, variants.VARIANT_A)
    replay.replay_variant(campaign.paths, variant=variants.VARIANT_A)
    for case_key in campaign.cases:
        path = campaign.paths.replay_canonical_path(variants.VARIANT_A, case_key)
        assert not path.is_symlink()


def test_replay_follows_the_route_rather_than_the_primary(campaign: Campaign) -> None:
    _freeze(campaign, variants.VARIANT_C)
    replay.replay_variant(campaign.paths, variant=variants.VARIANT_C)
    rows = _rows(campaign, variants.VARIANT_C)
    assert rows["case-clean"]["chosen_model_key"] == PRIMARY
    assert rows["case-truncated"]["chosen_model_key"] == TEXT_SPECIALIST
    assert rows["case-table"]["chosen_model_key"] == TABLE_SPECIALIST
    composite = campaign.paths.replay_canonical_path(variants.VARIANT_C, "case-table")
    assert composite.read_text(encoding="utf-8") == (
        campaign.paths.canonical_path(TABLE_SPECIALIST, "case-table").read_text(
            encoding="utf-8"
        )
    )


def test_a_page_with_no_output_for_the_chosen_model_stays_unresolved(
    campaign: Campaign,
) -> None:
    _freeze(campaign, variants.VARIANT_C)
    # Remove the specialist's frozen output for one routed page.
    campaign.paths.canonical_path(TEXT_SPECIALIST, "case-truncated").unlink()
    manifest = campaign.paths.frozen_manifest(TEXT_SPECIALIST)
    rows = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line)["case_key"] != "case-truncated"
    ]
    jsonio.write_jsonl_atomic(manifest, rows)

    report = replay.replay_variant(campaign.paths, variant=variants.VARIANT_C)
    assert report.unresolved == 1
    row = _rows(campaign, variants.VARIANT_C)["case-truncated"]
    assert row["unresolved"] is True
    assert "no frozen output" in row["unresolved_reason"]
    assert row["composite_canonical_path"] is None
    assert not campaign.paths.replay_canonical_path(
        variants.VARIANT_C, "case-truncated"
    ).exists()


def test_a_manifest_hash_that_does_not_match_the_bytes_stops_the_replay(
    campaign: Campaign,
) -> None:
    _freeze(campaign, variants.VARIANT_A)
    manifest = campaign.paths.frozen_manifest(PRIMARY)
    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row["case_key"] == "case-clean":
            row["canonical_sha256"] = "sha256:" + "7" * 64
        rows.append(row)
    jsonio.write_jsonl_atomic(manifest, rows)

    with pytest.raises(IntegrityError):
        replay.replay_variant(campaign.paths, variant=variants.VARIANT_A)


def test_a_manifest_claiming_a_missing_success_output_fails_closed(
    campaign: Campaign,
) -> None:
    _freeze(campaign, variants.VARIANT_A)
    campaign.paths.canonical_path(PRIMARY, "case-clean").unlink()
    with pytest.raises(MissingInputError):
        replay.replay_variant(campaign.paths, variant=variants.VARIANT_A)


def test_replay_requires_a_frozen_route_set(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    with pytest.raises(MissingInputError):
        replay.replay_variant(campaign.paths, variant=variants.VARIANT_A)


def test_the_summary_counts_pages_per_model(campaign: Campaign) -> None:
    _freeze(campaign, variants.VARIANT_C)
    report = replay.replay_variant(campaign.paths, variant=variants.VARIANT_C)
    summary = json.loads(report.summary_path.read_text(encoding="utf-8"))
    assert summary["total_cases"] == len(campaign.cases)
    assert sum(summary["pages_per_model"].values()) == summary["resolved_cases"]
    assert summary["manifest_sha256"] == report.manifest_sha256


def test_the_oracle_label_is_in_every_path_and_row(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    for model in (PRIMARY, TEXT_SPECIALIST):
        jsonio.write_json_atomic(
            campaign.paths.model_scores(model),
            {
                "cases": {
                    case: {"official_score": 0.9 if model == TEXT_SPECIALIST else 0.2}
                    for case in campaign.cases
                }
            },
        )
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_E)
    report = replay.replay_variant(campaign.paths, variant=variants.VARIANT_E)
    assert variants.ORACLE_LABEL in str(report.manifest_path)
    assert variants.ORACLE_LABEL in str(report.canonical_dir)
    for row in _rows(campaign, variants.VARIANT_E).values():
        assert row["deployability"] == variants.ORACLE_LABEL
    summary = json.loads(report.summary_path.read_text(encoding="utf-8"))
    assert summary["deployability"] == variants.ORACLE_LABEL
