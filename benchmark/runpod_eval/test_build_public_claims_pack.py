"""The generator that decides what may go on a public page had no tests.

Nine of its fifteen claims shipped a path to an evidence file with no hash
beside it, and four ParseBench numbers were transcribed by hand rather than read
from the summary they cited. Both are the kind of defect that stays invisible
until someone regenerates an evaluation and the website quietly keeps the old
figure next to a citation that still looks legitimate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from build_public_claims_pack import (
    APPROVED,
    CONDITIONAL,
    WITHHELD,
    _check_evidence_is_bound,
    _check_rates_carry_denominators,
    _count_rate,
    _evidence,
    _group_metric,
    _olmocr_score_definition,
    render_markdown,
)

OLMOCR_SUMMARY = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "artifacts"
    / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
    "__olmocr-bench__evaluation-summary.json"
)


def _summary() -> dict[str, object]:
    return {
        "groups": [
            {
                "group": "text_content",
                "aggregate_metrics": {"avg_content_faithfulness": 0.83761234},
            },
            {"group": "table", "aggregate_metrics": {"avg_grits_con": 0.90174}},
        ]
    }


def test_a_metric_is_read_from_the_summary_not_transcribed() -> None:
    assert _group_metric(_summary(), "text_content", "avg_content_faithfulness") == 0.8376
    assert _group_metric(_summary(), "table", "avg_grits_con") == 0.9017


def test_a_renamed_group_fails_loudly_instead_of_reporting_a_stale_number() -> None:
    with pytest.raises(KeyError):
        _group_metric(_summary(), "tables", "avg_grits_con")


def test_a_missing_metric_is_not_silently_defaulted() -> None:
    with pytest.raises(KeyError):
        _group_metric(_summary(), "table", "avg_teds")


def test_evidence_binds_the_path_and_the_hash_together(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "summary.json"
    target.parent.mkdir()
    target.write_text('{"score": 1}', encoding="utf-8")

    bound = _evidence(tmp_path, target)

    assert bound["evidence"] == "reports/summary.json"
    assert bound["evidence_sha256"].startswith("sha256:")


def test_several_files_produce_parallel_lists(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")

    bound = _evidence(tmp_path, first, second)

    assert bound["evidence"] == ["a.json", "b.json"]
    assert len(bound["evidence_sha256"]) == 2
    assert bound["evidence_sha256"][0] != bound["evidence_sha256"][1]


def test_a_citation_to_a_file_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    # The product-pipeline claim shipped "packages/.../blueprints.py; packages/..."
    # as one string. It resolved to nothing, and nothing checked.
    with pytest.raises(FileNotFoundError):
        _evidence(tmp_path, tmp_path / "never-written.json")


def test_a_path_without_a_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="inconsistently"):
        _check_evidence_is_bound(
            [{"id": "x", "status": APPROVED, "evidence": "some/file.json"}]
        )


def test_a_hash_without_a_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="inconsistently"):
        _check_evidence_is_bound(
            [{"id": "x", "status": APPROVED, "evidence_sha256": "sha256:00"}]
        )


def test_a_publishable_claim_must_cite_something() -> None:
    with pytest.raises(ValueError, match="cites no evidence"):
        _check_evidence_is_bound([{"id": "x", "status": CONDITIONAL}])


def test_a_withheld_claim_may_cite_nothing() -> None:
    # Withheld claims exist precisely because the measurement has not been made.
    _check_evidence_is_bound([{"id": "x", "status": WITHHELD}])


def test_bound_claims_pass_the_check() -> None:
    _check_evidence_is_bound(
        [
            {
                "id": "x",
                "status": APPROVED,
                "evidence": "a.json",
                "evidence_sha256": "sha256:00",
            }
        ]
    )


def test_the_markdown_carries_the_constraint_in_both_languages() -> None:
    pack = {
        "how_to_use": ["a"],
        "global_rules": ["b"],
        "claims": [
            {
                "id": "completion-rate",
                "status": APPROVED,
                "headline_ko": "완주율",
                "headline_en": "Completion rate",
                "numbers": {"rate": 0.9998},
                "must_say": "정확도가 아닙니다.",
                "must_say_en": "This is not accuracy.",
                "evidence": "ledger.json",
            }
        ],
    }

    rendered = render_markdown(pack)

    assert "정확도가 아닙니다." in rendered
    assert "This is not accuracy." in rendered
    assert "ledger.json" in rendered


def test_a_must_say_rate_without_a_denominator_is_refused() -> None:
    # The sentence benchmark-accuracy shipped: a rate whose whole was wrong.
    with pytest.raises(ValueError, match="without a denominator"):
        _check_rates_carry_denominators(
            [
                {
                    "id": "x",
                    "status": APPROVED,
                    "must_say_en": "84.8% of the 8,413 checks pass.",
                }
            ]
        )


def test_a_korean_must_say_rate_is_checked_too() -> None:
    with pytest.raises(ValueError, match="without a denominator"):
        _check_rates_carry_denominators(
            [{"id": "x", "status": APPROVED, "must_say": "문서의 72.3%에 오류가 있습니다."}]
        )


def test_a_rate_written_with_its_denominator_passes() -> None:
    assert _count_rate(7137, 8413) == "7,137/8,413 (84.8%)"
    _check_rates_carry_denominators(
        [
            {
                "id": "x",
                "status": APPROVED,
                "must_say": f"검사 기준으로는 {_count_rate(7137, 8413)}가 통과했습니다.",
                "must_say_en": f"{_count_rate(7137, 8413)} of the checks pass.",
            }
        ]
    )


@pytest.mark.parametrize(("part", "whole"), [(1, 0), (9, 8), (-1, 8)])
def test_an_impossible_rate_is_refused(part: int, whole: int) -> None:
    with pytest.raises(ValueError, match="is not a rate"):
        _count_rate(part, whole)


def test_a_pending_claim_that_no_longer_needs_the_exemption_fails() -> None:
    with pytest.raises(ValueError, match="remove it from _BARE_RATE_PENDING"):
        _check_rates_carry_denominators(
            [{"id": "customer-facing-fidelity", "status": APPROVED, "must_say_en": "x"}]
        )


def _synthetic_olmocr_summary(overall: float) -> dict[str, object]:
    return {
        "label": "SYNTHETIC",
        "overall_score": overall,
        "test_count": 10,
        "rule_failure_count": 3,
        "per_jsonl": {
            "a.jsonl": {"pass_rate": 0.5, "passed": 1, "total": 2},
            "b.jsonl": {"pass_rate": 0.75, "passed": 6, "total": 8},
        },
    }


def test_the_overall_score_is_confirmed_to_be_the_type_average() -> None:
    assert _olmocr_score_definition(_synthetic_olmocr_summary(0.625)) == {
        "types": 2,
        "checks_passed": 7,
        "checks_total": 10,
    }


def test_a_check_level_overall_score_is_refused() -> None:
    # 7/10 is the micro rate; a sentence calling the score a type average would be false.
    with pytest.raises(ValueError, match="mean of the per-type pass rates"):
        _olmocr_score_definition(_synthetic_olmocr_summary(0.7))


def test_per_type_counts_that_do_not_add_up_are_refused() -> None:
    summary = _synthetic_olmocr_summary(0.625)
    summary["rule_failure_count"] = 4
    with pytest.raises(ValueError, match="do not add up"):
        _olmocr_score_definition(summary)


def test_the_cited_olmocr_artifact_is_a_type_average_of_eight() -> None:
    if not OLMOCR_SUMMARY.is_file():
        pytest.skip("olmOCR-Bench summary artifact is not in this checkout")
    summary = json.loads(OLMOCR_SUMMARY.read_text(encoding="utf-8-sig"))
    assert _olmocr_score_definition(summary) == {
        "types": 8,
        "checks_passed": 7137,
        "checks_total": 8413,
    }
    assert round(summary["overall_score"] * 100, 1) == 80.6


def test_the_shipped_pack_has_a_constraint_on_every_publishable_number() -> None:
    """A number on a public page without a stated constraint is the failure mode
    the pack exists to prevent, so it is checked against the shipped artifact."""
    repository = Path(__file__).resolve().parents[2]
    pack_path = repository / "docs" / "evidence" / "folynta-public-claims-pack.json"
    if not pack_path.is_file():
        pytest.skip("claims pack has not been generated in this checkout")

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    unconstrained = [
        claim["id"]
        for claim in pack["claims"]
        if claim["status"] in (APPROVED, CONDITIONAL)
        and claim.get("numbers")
        and not (
            claim.get("must_say") or claim.get("conditions")
        )
    ]
    assert unconstrained == []

    unbound = [
        claim["id"]
        for claim in pack["claims"]
        if bool(claim.get("evidence")) != bool(claim.get("evidence_sha256"))
    ]
    assert unbound == []

    _check_rates_carry_denominators(pack["claims"])
    accuracy = next(c for c in pack["claims"] if c["id"] == "benchmark-accuracy")
    checks = _count_rate(
        accuracy["numbers"]["checks_passed"], accuracy["numbers"]["checks_total"]
    )
    assert checks in accuracy["must_say"]
    assert checks in accuracy["must_say_en"]
    assert "unweighted mean" in accuracy["must_say_en"]
