"""Signals: determinism, honest absence, and each named feature on its page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arena.tavonel import features, jsonio, signals
from arena.tavonel.errors import IntegrityError, MissingInputError
from arena.tavonel.paths import ArenaPaths
from conftest import PRIMARY, Campaign, build_campaign


def _record(campaign: Campaign, case_key: str, model: str = PRIMARY) -> dict:
    path = campaign.paths.signals_path(model, case_key)
    return json.loads(path.read_text(encoding="utf-8"))


def test_builds_one_record_per_model_and_case(campaign: Campaign) -> None:
    report = signals.build_signals(campaign.paths)
    assert report.case_count == len(campaign.models) * len(campaign.cases)
    assert report.ok
    for model in campaign.models:
        for case_key in campaign.cases:
            assert campaign.paths.signals_path(model, case_key).is_file()


def test_records_are_byte_identical_when_recomputed(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    first = {
        case_key: campaign.paths.signals_path(PRIMARY, case_key).read_bytes()
        for case_key in campaign.cases
    }
    signals.build_signals(campaign.paths)
    second = {
        case_key: campaign.paths.signals_path(PRIMARY, case_key).read_bytes()
        for case_key in campaign.cases
    }
    assert first == second


def test_signals_sha256_covers_the_body_it_is_stored_with(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    record = _record(campaign, "case-clean")
    recomputed = jsonio.prefixed(jsonio.record_digest(record, exclude=("signals_sha256",)))
    assert record["signals_sha256"] == recomputed


def test_feature_set_version_travels_with_every_record(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    record = _record(campaign, "case-clean")
    assert record["feature_set_version"] == features.FEATURE_SET_VERSION
    assert record["schema"] == signals.SIGNALS_SCHEMA


@pytest.mark.parametrize(
    ("case_key", "feature", "value"),
    [
        ("case-empty", "empty_output", True),
        ("case-clean", "empty_output", False),
        ("case-truncated", "suspicious_truncation", True),
        ("case-clean", "suspicious_truncation", False),
        ("case-table", "table_count", 1),
        ("case-table", "markdown_structural_validity", False),
        ("case-formula", "formula_count", 4),
        ("case-clean", "heading_count", 1),
    ],
)
def test_each_page_trips_its_own_feature(
    campaign: Campaign, case_key: str, feature: str, value: object
) -> None:
    signals.build_signals(campaign.paths)
    assert _record(campaign, case_key)["features"][feature] == value


def test_repetition_is_measured_not_guessed(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    repeated = _record(campaign, "case-repetition")["features"]
    clean = _record(campaign, "case-clean")["features"]
    assert repeated["ngram_repetition_ratio"] > 0.8
    assert repeated["duplicate_paragraph_ratio"] > 0.8
    assert clean["ngram_repetition_ratio"] == 0.0
    assert clean["duplicate_paragraph_ratio"] == 0.0


def test_token_cap_is_read_from_the_registry(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    truncated = _record(campaign, "case-truncated")
    assert truncated["run"]["output_tokens_at_max"] is True
    assert "output_tokens_at_max" in truncated["features"]["truncation_reasons"]
    clean = _record(campaign, "case-clean")
    assert clean["run"]["output_tokens_at_max"] is False


def test_missing_registry_records_the_absence_rather_than_assuming(
    tmp_path: Path,
) -> None:
    campaign = build_campaign(tmp_path / "c")
    campaign.paths.model_registry.unlink()
    signals.build_signals(campaign.paths)
    record = _record(campaign, "case-truncated")
    assert record["run"]["max_output_tokens"] is None
    assert record["run"]["output_tokens_at_max"] is None
    assert "output_tokens_at_max" in record["unavailable"]


def test_missing_geometry_is_null_with_a_reason_never_zero(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path / "c")
    campaign.paths.source_manifest.unlink()
    # Strip the fallback geometry from the receipt too.
    receipt_path = campaign.paths.receipt_path(PRIMARY, "case-clean")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    del receipt["image_width"]
    del receipt["image_height"]
    jsonio.write_json_atomic(receipt_path, receipt)

    signals.build_signals(campaign.paths, [PRIMARY])
    record = _record(campaign, "case-clean")
    assert record["source_geometry"] is None
    assert record["derived"]["output_to_source_ratio"] is None
    assert "source_geometry" in record["unavailable"]
    assert "output_to_source_ratio" in record["unavailable"]


def test_receipt_geometry_is_used_when_the_manifest_row_is_gone(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path / "c")
    campaign.paths.source_manifest.unlink()
    signals.build_signals(campaign.paths, [PRIMARY])
    geometry = _record(campaign, "case-clean")["source_geometry"]
    assert geometry["geometry_source"] == "page_receipt"
    assert geometry["width"] == 400


def test_hash_mismatch_against_the_receipt_is_reported(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path / "c")
    receipt_path = campaign.paths.receipt_path(PRIMARY, "case-clean")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["canonical_output_sha256"] = "sha256:" + "9" * 64
    jsonio.write_json_atomic(receipt_path, receipt)

    report = signals.build_signals(campaign.paths, [PRIMARY])
    assert not report.ok
    assert f"{PRIMARY}/case-clean:canonical" in report.hash_mismatches
    record = _record(campaign, "case-clean")
    assert record["inputs"]["canonical_sha256_matches_receipt"] is False


def test_success_receipt_without_output_is_an_integrity_failure(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path / "c")
    campaign.paths.canonical_path(PRIMARY, "case-clean").unlink()
    campaign.paths.raw_text_path(PRIMARY, "case-clean").unlink()
    with pytest.raises(IntegrityError):
        signals.build_signals(campaign.paths, [PRIMARY])


def test_failed_receipt_without_output_is_recorded_not_invented(tmp_path: Path) -> None:
    campaign = build_campaign(tmp_path / "c")
    campaign.paths.canonical_path(PRIMARY, "case-empty").unlink()
    campaign.paths.raw_text_path(PRIMARY, "case-empty").unlink()
    report = signals.build_signals(campaign.paths, [PRIMARY])
    record = _record(campaign, "case-empty")
    assert record["text_source"] == "none"
    assert "output_text" in record["unavailable"]
    assert f"{PRIMARY}/case-empty" in report.missing_outputs
    assert not report.ok


def test_unknown_model_fails_closed(campaign: Campaign) -> None:
    with pytest.raises(MissingInputError):
        signals.build_signals(campaign.paths, ["no_such_model"])


def test_empty_campaign_root_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(MissingInputError):
        signals.build_signals(ArenaPaths(root=tmp_path / "nothing"))
