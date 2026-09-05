"""The disagreement matrix, and the honest correlation step that follows scoring."""

from __future__ import annotations

import json
import math

import pytest
from arena.tavonel import correlate, disagreement, jsonio, signals
from arena.tavonel.errors import MissingInputError
from conftest import PRIMARY, TABLE_SPECIALIST, TEXT_SPECIALIST, Campaign


def _rows(campaign: Campaign) -> list[dict]:
    return [
        json.loads(line)
        for line in campaign.paths.disagreement_pairs.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_every_pair_of_models_is_compared_once_per_page(campaign: Campaign) -> None:
    report = disagreement.build_disagreement(campaign.paths)
    models = len(campaign.models)
    assert report.row_count == len(campaign.cases) * models * (models - 1) // 2
    seen = {(row["case_key"], row["model_a"], row["model_b"]) for row in _rows(campaign)}
    assert len(seen) == report.row_count
    for _case, model_a, model_b in seen:
        assert model_a < model_b


def test_the_comparison_is_symmetric(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    left = disagreement.side_features(
        campaign.paths.canonical_path(PRIMARY, "case-table").read_text(encoding="utf-8")
    )
    right = disagreement.side_features(
        campaign.paths.canonical_path(TABLE_SPECIALIST, "case-table").read_text(
            encoding="utf-8"
        )
    )
    forward = disagreement.compare_models(PRIMARY, left, TABLE_SPECIALIST, right)
    backward = disagreement.compare_models(TABLE_SPECIALIST, right, PRIMARY, left)
    assert forward == backward


def test_identical_outputs_agree_completely(campaign: Campaign) -> None:
    disagreement.build_disagreement(campaign.paths)
    row = next(
        row
        for row in _rows(campaign)
        if row["case_key"] == "case-formula"
        and {row["model_a"], row["model_b"]} == {PRIMARY, TEXT_SPECIALIST}
    )
    metrics = row["metrics"]
    assert metrics["text_similarity"] == 1.0
    assert metrics["token_jaccard"] == 1.0
    assert metrics["number_set_disagreement"] == 0.0
    assert metrics["output_length_ratio"] == 1.0
    assert metrics["formula_count_difference"] == 0
    assert metrics["reading_order_disagreement"] == 0.0


def test_an_empty_output_against_a_full_one_is_visible(campaign: Campaign) -> None:
    disagreement.build_disagreement(campaign.paths)
    row = next(
        row
        for row in _rows(campaign)
        if row["case_key"] == "case-empty"
        and {row["model_a"], row["model_b"]} == {PRIMARY, TEXT_SPECIALIST}
    )
    metrics = row["metrics"]
    assert metrics["one_empty_one_nonempty"] is True
    assert metrics["output_length_ratio"] == 0.0
    assert metrics["text_similarity"] < 0.1


def test_a_broken_table_disagrees_on_rows(campaign: Campaign) -> None:
    disagreement.build_disagreement(campaign.paths)
    row = next(
        row
        for row in _rows(campaign)
        if row["case_key"] == "case-table"
        and {row["model_a"], row["model_b"]} == {PRIMARY, TABLE_SPECIALIST}
    )
    assert row["metrics"]["table_row_count_difference"] > 0
    assert row["metrics"]["text_similarity"] < 1.0


def test_a_truncated_output_against_a_complete_one_is_visible(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    disagreement.build_disagreement(campaign.paths)
    row = next(
        row
        for row in _rows(campaign)
        if row["case_key"] == "case-truncated"
        and {row["model_a"], row["model_b"]} == {PRIMARY, TEXT_SPECIALIST}
    )
    assert row["metrics"]["one_truncated_one_complete"] is True


def test_pages_only_one_model_produced_are_not_paired(campaign: Campaign) -> None:
    for model in (TEXT_SPECIALIST, TABLE_SPECIALIST):
        campaign.paths.canonical_path(model, "case-clean").unlink()
        manifest = campaign.paths.frozen_manifest(model)
        rows = [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line and json.loads(line)["case_key"] != "case-clean"
        ]
        jsonio.write_jsonl_atomic(manifest, rows)
    report = disagreement.build_disagreement(campaign.paths)
    assert report.case_count == len(campaign.cases) - 1
    assert all(row["case_key"] != "case-clean" for row in _rows(campaign))


# ----------------------------------------------------------- correlation step


def _write_scores(campaign: Campaign, model: str, scores: dict[str, float]) -> None:
    jsonio.write_json_atomic(
        campaign.paths.model_scores(model),
        {"cases": {case: {"official_score": value} for case, value in scores.items()}},
    )


def test_spearman_is_computed_without_a_third_party_library() -> None:
    assert correlate.spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert correlate.spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0
    assert correlate.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert correlate.spearman([1.0], [1.0]) is None


def test_correlation_needs_the_matrix_first(campaign: Campaign) -> None:
    with pytest.raises(MissingInputError):
        correlate.correlate(campaign.paths, model_key=PRIMARY)


def test_correlation_needs_scores(campaign: Campaign) -> None:
    disagreement.build_disagreement(campaign.paths)
    with pytest.raises(MissingInputError):
        correlate.correlate(campaign.paths, model_key=PRIMARY)


def test_a_disagreement_signal_that_tracks_failure_is_reported_as_supported(
    campaign: Campaign,
) -> None:
    signals.build_signals(campaign.paths)
    disagreement.build_disagreement(campaign.paths)
    # The pages the fixture broke are exactly the pages scored low.
    _write_scores(
        campaign,
        PRIMARY,
        {
            "case-clean": 0.95,
            "case-formula": 0.90,
            "case-table": 0.30,
            "case-truncated": 0.20,
            "case-repetition": 0.10,
            "case-empty": 0.05,
        },
    )
    report = correlate.correlate(campaign.paths, model_key=PRIMARY)
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert report.finding == "SUPPORTED"
    assert payload["cases_used"] == len(campaign.cases)
    assert payload["best_spearman"] is not None
    assert all(item["calibrated"] is False for item in payload["parameters"])


def test_a_signal_that_points_the_wrong_way_is_written_down_as_negative(
    campaign: Campaign,
) -> None:
    signals.build_signals(campaign.paths)
    disagreement.build_disagreement(campaign.paths)
    # Scores inverted: the pages the models disagreed on scored *best*. A
    # correlation of the wrong sign is evidence against the hypothesis, not
    # weak evidence for it.
    _write_scores(
        campaign,
        PRIMARY,
        {
            "case-clean": 0.10,
            "case-formula": 0.20,
            "case-table": 0.95,
            "case-truncated": 0.90,
            "case-repetition": 0.85,
            "case-empty": 0.99,
        },
    )
    report = correlate.correlate(campaign.paths, model_key=PRIMARY)
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert report.finding == "NOT_SUPPORTED"
    assert payload["best_spearman"] > 0
    assert "wrong direction" in payload["finding_statement"]
    assert "negative result" in payload["finding_statement"]
    assert "section 46" in payload["finding_statement"]


def test_a_model_with_no_scored_page_is_not_evaluable(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    disagreement.build_disagreement(campaign.paths)
    _write_scores(campaign, TEXT_SPECIALIST, {"case-clean": 0.9})
    report = correlate.correlate(campaign.paths, model_key=PRIMARY)
    assert report.finding == "NOT_EVALUABLE"
    assert report.cases_used == 0


def test_capture_at_budget_compares_against_the_oracle_ranking(
    campaign: Campaign,
) -> None:
    signals.build_signals(campaign.paths)
    disagreement.build_disagreement(campaign.paths)
    _write_scores(campaign, PRIMARY, {case: 0.05 for case in campaign.cases})
    report = correlate.correlate(campaign.paths, model_key=PRIMARY)
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    capture = payload["per_metric"]["max_text_disagreement"]["capture_at_budget"]
    # Six pages at a ten percent budget rounds down to zero: reported as a
    # reason, not as a zero capture rate.
    assert capture["budget_pages"] == math.floor(len(campaign.cases) * 0.10)
    assert capture["blind_capture"] is None
    assert capture["reason"]
