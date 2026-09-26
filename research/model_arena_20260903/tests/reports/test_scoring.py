"""``arena.reports.scoring``: headline metric selection and document-type mapping."""

from __future__ import annotations

from arena.reports.scoring import document_type_family, headline_metric, metric_rows


def test_headline_metric_missing_summary_is_na_with_reason() -> None:
    cell, key = headline_metric(None, "missing: summary.json")
    assert cell.value is None
    assert cell.reason == "missing: summary.json"
    assert key is None


def test_headline_metric_evaluator_blocked_is_na() -> None:
    cell, key = headline_metric({"status": "EVALUATOR_BLOCKED"}, None)
    assert cell.value is None
    assert "EVALUATOR_BLOCKED" in (cell.reason or "")
    assert key is None


def test_headline_metric_prefers_overall_over_score() -> None:
    cell, key = headline_metric({"overall": 0.5, "score": 0.9}, None)
    assert cell.value == 0.5
    assert key == "overall"


def test_headline_metric_falls_back_through_candidates() -> None:
    cell, key = headline_metric({"final_score": 0.42}, None)
    assert cell.value == 0.42
    assert key == "final_score"


def test_headline_metric_no_recognised_key_reports_available_keys() -> None:
    cell, key = headline_metric({"table_teds": 0.7, "schema": "x"}, None)
    assert cell.value is None
    assert key is None
    assert "table_teds" in (cell.reason or "")
    # provenance keys like "schema" must not be listed as if they were metrics
    assert "'schema'" not in (cell.reason or "")


def test_metric_rows_excludes_provenance_keys() -> None:
    rows = metric_rows({"overall": 0.5, "schema": "x", "provenance": {}, "status": "ok"})
    assert rows == [("overall", 0.5)]


def test_document_type_family_maps_known_aliases() -> None:
    assert document_type_family("Old Scans") == "old_scan"
    assert document_type_family("headers_footers") == "header_footer"
    assert document_type_family("multi-column") == "multi_column"


def test_document_type_family_unknown_returns_none() -> None:
    assert document_type_family("something_unheard_of") is None
