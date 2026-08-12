from __future__ import annotations

import json
from pathlib import Path

import pytest
from compare_official_failure_records import (
    compare_failure_records,
    validate_accepted_decision,
)


def _write(path: Path, *, routes: list[dict], record_counts: dict[str, int]) -> None:
    records = []
    for case_id, count in record_counts.items():
        records.extend(
            {
                "benchmark_id": "parsebench",
                "case_id": case_id,
            }
            for _ in range(count)
        )
    path.write_text(json.dumps({"routes": routes, "records": records}), encoding="utf-8")


def _route(case_id: str, codes: list[str]) -> dict:
    return {
        "benchmark_id": "parsebench",
        "case_id": case_id,
        "request_recovery": True,
        "escalate": False,
        "failure_codes": codes,
        "candidate_models": ["paddleocr-vl-1.6"],
    }


def test_only_strict_no_new_code_reductions_are_accepted(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    routes = [_route("resolved", ["F01"]), _route("same", ["F01"]), _route("new", ["F01"])]
    _write(baseline, routes=routes, record_counts={"resolved": 2, "same": 1, "new": 2})
    _write(
        candidate,
        routes=[_route("same", ["F01"]), _route("new", ["F01", "B01"])],
        record_counts={"same": 1, "new": 1},
    )

    result = compare_failure_records(
        baseline_path=baseline,
        candidate_path=candidate,
        output_path=tmp_path / "comparison.json",
    )

    assert result["accepted_quality_case_count"] == 1
    assert result["accepted_quality_cases"][0]["case_id"] == "resolved"
    assert result["persistent_case_count"] == 2
    assert result["regressed_candidate_case_count"] == 1
    assert result["routes"] == result["persistent_routes"]
    assert {route["selected_source"] for route in result["routes"]} == {"baseline"}


def test_improved_case_with_remaining_failures_stays_routed(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _write(
        baseline,
        routes=[_route("partial", ["F01", "R01"])],
        record_counts={"partial": 2},
    )
    _write(
        candidate,
        routes=[_route("partial", ["F01"])],
        record_counts={"partial": 1},
    )

    result = compare_failure_records(
        baseline_path=baseline,
        candidate_path=candidate,
        output_path=tmp_path / "comparison.json",
    )

    assert result["accepted_quality_case_count"] == 1
    assert result["persistent_case_count"] == 1
    assert result["routes"][0]["failure_codes"] == ["F01"]
    assert result["routes"][0]["selected_source"] == "quality_candidate"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_failure_record_count", 2),
        ("new_failure_codes", ["B01"]),
        ("candidate_escalates", True),
        ("strictly_improved", False),
        ("candidate_failure_codes", ["F01", "B01"]),
    ],
)
def test_accepted_decision_validator_rejects_policy_tampering(
    field: str, value: object
) -> None:
    decision = {
        "baseline_failure_record_count": 2,
        "candidate_failure_record_count": 1,
        "baseline_failure_codes": ["F01"],
        "candidate_failure_codes": ["F01"],
        "new_failure_codes": [],
        "candidate_escalates": False,
        "strictly_improved": True,
    }
    decision[field] = value

    with pytest.raises(ValueError):
        validate_accepted_decision(decision)
