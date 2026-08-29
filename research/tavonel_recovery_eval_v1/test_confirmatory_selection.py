from __future__ import annotations

import pytest
from confirmatory_selection import (
    STAGE1_FAMILY_QUOTAS,
    EvidenceAnchor,
    SelectionRefused,
    build_evidence_split,
    build_spent_manifest,
    select_stage1,
)


def candidate(family: str, index: int, *, family_id: str | None = None, **extra):
    row = {
        "source_family": family,
        "family_id": family_id or f"{family}-doc-{index // 2}",
        "document_id": f"{family}-document-{index}",
        "page_id": f"page-{index}",
        "source_locator": f"https://example.invalid/{family}/{index}",
        "source_revision": "rev-1",
        "source_sha256": "sha256:" + f"{index:064x}"[-64:],
        "acquisition_identity": f"{family}:{index}:rev-1",
        "metadata": {"page_number": index + 1},
    }
    row.update(extra)
    return row


def full_candidates():
    return [
        candidate(family, index)
        for family, quota in STAGE1_FAMILY_QUOTAS.items()
        for index in range(quota + 10)
    ]


def test_equal_family_quota_is_deterministic_and_outcome_blind():
    spent = build_spent_manifest(exact_spent_ids=(), spent_family_ids=())
    left = select_stage1(full_candidates(), spent)
    right = select_stage1(list(reversed(full_candidates())), spent)
    assert left["cohort_seal_digest"] == right["cohort_seal_digest"]
    assert left["selected_counts"] == {"dart": 100, "drdocbench": 100, "sec": 100}
    assert left["entry_count"] == 300
    assert left["scientific_outcomes_used_for_selection"] is False


def test_outcome_fields_cannot_enter_candidate_selection():
    rows = full_candidates()
    rows[0]["metadata"]["accuracy"] = 0.99
    with pytest.raises(SelectionRefused, match="outcome-like"):
        select_stage1(rows, build_spent_manifest(exact_spent_ids=(), spent_family_ids=()))


def test_family_shortfall_is_fail_closed_not_reallocated():
    rows = full_candidates()
    rows = [
        row
        for row in rows
        if not (row["source_family"] == "sec" and int(row["page_id"].split("-")[-1]) >= 99)
    ]
    with pytest.raises(SelectionRefused, match="quota reallocation is forbidden"):
        select_stage1(rows, build_spent_manifest(exact_spent_ids=(), spent_family_ids=()))


def test_spent_family_exclusion_happens_before_fixed_quota():
    rows = full_candidates()
    spent_family = rows[0]["family_id"]
    result = select_stage1(
        rows,
        build_spent_manifest(exact_spent_ids=(), spent_family_ids=(spent_family,)),
    )
    assert result["excluded_spent_family"] == 2
    assert all(item["family_id"] != spent_family for item in result["entries"])


def test_evaluator_labels_are_forced_to_hidden_side():
    result = build_evidence_split(
        (
            EvidenceAnchor("native-a", "SOURCE_NATIVE", trigger_eligible=True),
            EvidenceAnchor(
                "truth-a", "GROUND_TRUTH", evaluator_label=True, evaluation_eligible=True
            ),
            EvidenceAnchor(
                "dual-a", "SEMANTIC_ANCHOR", trigger_eligible=True, evaluation_eligible=True
            ),
        )
    )
    assert "truth-a" in result["evaluation_anchor_ids"]
    assert "truth-a" not in result["trigger_anchor_ids"]
    assert not (set(result["trigger_anchor_ids"]) & set(result["evaluation_anchor_ids"]))
    assert result["runtime_may_read_evaluation_side"] is False
