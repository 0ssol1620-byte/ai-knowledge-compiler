from __future__ import annotations

import pytest
from select_highest_impact_failures import select_highest_impact


def _payload() -> dict:
    records = []
    routes = []
    # heavy-a carries 5 failures, heavy-b carries 3, light-c carries 1.
    for case_id, count in (("heavy-a", 5), ("heavy-b", 3), ("light-c", 1)):
        for index in range(count):
            records.append(
                {
                    "benchmark_id": "parsebench",
                    "case_id": case_id,
                    "evaluator_type": "layout",
                    "location_id": f"element-{index}",
                }
            )
        routes.append(
            {
                "benchmark_id": "parsebench",
                "case_id": case_id,
                "request_recovery": True,
                "candidate_models": ["paddleocr-vl-1.6"],
            }
        )
    # A case the official evaluation flagged but the taxonomy cannot recover.
    records.append(
        {
            "benchmark_id": "parsebench",
            "case_id": "nonrecoverable-d",
            "evaluator_type": "unexpected_word_percent",
            "location_id": "element-0",
        }
    )
    routes.append(
        {
            "benchmark_id": "parsebench",
            "case_id": "nonrecoverable-d",
            "request_recovery": False,
            "candidate_models": [],
        }
    )
    return {"record_count": len(records), "records": records, "routes": routes}


def test_selection_takes_the_documents_carrying_the_most_failures() -> None:
    filtered, receipt = select_highest_impact(_payload(), case_limit=2)

    assert receipt["selected_case_count"] == 2
    assert [item["case_id"] for item in receipt["selected_cases"]] == ["heavy-a", "heavy-b"]
    # 8 of the 10 official failures are reached by re-running 2 of 4 cases.
    assert receipt["selected_failure_records"] == 8
    assert receipt["corpus_failure_records"] == 10
    assert receipt["failure_coverage_fraction"] == pytest.approx(0.8)

    assert filtered["record_count"] == 8
    assert {record["case_id"] for record in filtered["records"]} == {"heavy-a", "heavy-b"}
    assert {route["case_id"] for route in filtered["routes"]} == {"heavy-a", "heavy-b"}
    assert filtered["recoverable_case_count"] == 2


def test_selection_never_targets_a_case_without_a_recovery_route() -> None:
    # nonrecoverable-d has an official failure but no route. Ranking it would
    # silently shrink the real selection, so it must be excluded from the pool.
    _filtered, receipt = select_highest_impact(_payload(), case_limit=4)

    selected = {item["case_id"] for item in receipt["selected_cases"]}
    assert "nonrecoverable-d" not in selected
    assert selected == {"heavy-a", "heavy-b", "light-c"}
    assert receipt["recoverable_case_pool"] == 3


def test_selection_records_that_the_result_does_not_generalise() -> None:
    _filtered, receipt = select_highest_impact(_payload(), case_limit=1)

    assert receipt["score_inflation_allowed"] is False
    assert "must not be reported as one" in receipt["extrapolation_policy"]
    assert receipt["receipt_sha256"].startswith("sha256:")


def test_selection_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="case limit must be positive"):
        select_highest_impact(_payload(), case_limit=0)
