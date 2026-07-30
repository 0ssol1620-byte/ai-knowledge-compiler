from __future__ import annotations

import copy

import pytest

from benchmark.evaluators.masterplan_metrics import (
    EVALUATOR_VERSION,
    MASTERPLAN_METRIC_KEYS,
    evaluate_masterplan_metrics,
)
from benchmark.evaluators.merge_gate import evaluate_merge_gate


def block(
    block_id: str,
    block_type: str,
    bbox: list[int],
    *,
    text: str = "",
    page_index: int = 0,
    **extra: object,
) -> dict:
    return {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "source_refs": [{"page_index": page_index, "bbox1000": bbox}],
        **extra,
    }


def table() -> dict:
    return {
        "row_count": 1,
        "column_count": 2,
        "header_row_count": 1,
        "cells": [
            {
                "row_index0": 0,
                "column_index0": 0,
                "row_span": 1,
                "column_span": 1,
                "text": "A",
            },
            {
                "row_index0": 0,
                "column_index0": 1,
                "row_span": 1,
                "column_span": 1,
                "text": "B",
            },
        ],
    }


def rich_case() -> tuple[dict, dict]:
    blocks = [
        block("h1", "heading", [0, 0, 900, 100], text="제목", heading_level=1),
        block("p1", "paragraph", [0, 100, 900, 300], text="가격은 ₩10입니다."),
        block(
            "f1",
            "figure",
            [0, 300, 500, 700],
            text="figure",
        ),
        block(
            "c1",
            "caption",
            [0, 700, 500, 760],
            text="그림 1",
            caption_for_block_id="f1",
        ),
        block("ft1", "footer", [0, 950, 900, 1000], text="footer"),
        block(
            "t1",
            "table",
            [500, 300, 900, 700],
            text="A B",
            table=table(),
        ),
        block(
            "eq1",
            "formula",
            [0, 760, 500, 900],
            text="x+y",
            formula_latex=r"\left(x+y\right)",
        ),
    ]
    truth = {
        "text": "한글, 가격은 ₩10입니다. 모델 X-1 v2.",
        "reading_order": [item["block_id"] for item in blocks],
        "blocks": blocks,
        "heading_outline": [{"level": 1, "text": "제목"}],
        "token_annotations": {
            "dates": ["2026-07-30"],
            "currencies": ["KRW"],
            "percentages": ["10%"],
            "units": ["kg"],
            "serials": ["X-1"],
            "models": ["AKC"],
            "versions": ["v2"],
        },
        "multi_page_table_merges": [["t1", "t2"]],
        "knowledge_evaluation": {
            "notes": [
                {
                    "note_id": "n1",
                    "title": "Note",
                    "source_block_ids": ["p1"],
                }
            ],
            "relations": [{"source": "n1", "target": "n2", "type": "supports"}],
            "conflicts": ["conflict-1"],
        },
        "rag_evaluation": {
            "queries": [
                {
                    "query_id": "q1",
                    "relevant_ids": ["p1", "t1"],
                    "citation_ids": ["p1"],
                    "stale_version_ids": ["old"],
                    "unanswerable": False,
                    "required_evidence_groups": [["p1"], ["t1"]],
                }
            ]
        },
        "router_evaluation": {"pages": []},
    }
    output = copy.deepcopy(truth)
    output["knowledge_evaluation"]["summary_claims"] = [{"source_block_ids": ["p1"]}]
    output["knowledge_evaluation"]["user_edit_pair"] = {
        "before": "same",
        "after": "same",
    }
    output["rag_evaluation"]["queries"][0].update(
        {
            "retrieved_ids": ["p1", "t1"],
            "citation_ids": ["p1", "t1"],
            "answer_claims": [{"citation_ids": ["p1"]}],
            "rejected_version_ids": ["old"],
            "refused": False,
        }
    )
    output["router_evaluation"] = {
        "pages": [
            {
                "document_class": "scan",
                "first_pass_failed": True,
                "escalated": True,
                "fallback": True,
                "quality_after_escalation": 0.9,
                "variable_cost": 0.2,
                "latency_ms": 100,
                "best_route_quality": 0.95,
                "chosen_route_quality": 0.9,
            },
            {
                "document_class": "scan",
                "first_pass_failed": False,
                "escalated": False,
                "fallback": False,
                "variable_cost": 0.1,
                "latency_ms": 50,
                "best_route_quality": 0.8,
                "chosen_route_quality": 0.8,
            },
        ]
    }
    output["verified_human_metrics"] = {
        "title_quality_human_score": {
            "value": 0.8,
            "reviewer_count": 2,
            "rubric_version": "title-rubric-1",
            "evidence_sha256": "sha256:" + "a" * 64,
        }
    }
    return truth, output


def test_complete_metric_surface_is_versioned_and_exact_case_is_measured() -> None:
    truth, output = rich_case()
    metrics = evaluate_masterplan_metrics(truth, output)

    assert EVALUATOR_VERSION == "22.4-22.8-v1.0.0"
    assert set(metrics) == set(MASTERPLAN_METRIC_KEYS)
    assert metrics["hangul_syllable_corruption_rate"] == 0.0
    assert metrics["hangul_jamo_corruption_rate"] == 0.0
    assert metrics["punctuation_accuracy"] == 1.0
    assert metrics["block_detection_precision_iou50"] == 1.0
    assert metrics["block_type_macro_f1_iou50"] == 1.0
    assert metrics["reading_order_kendall_tau"] == 1.0
    assert metrics["caption_association_accuracy"] == 1.0
    assert metrics["heading_level_accuracy"] == 1.0
    assert metrics["table_span_accuracy"] == 1.0
    assert metrics["multi_page_table_merge_accuracy"] == 1.0
    assert metrics["formula_exact_match"] == 1.0
    assert metrics["equation_block_recall_iou50"] == 1.0
    assert metrics["source_bbox_iou"] == 1.0
    assert metrics["note_split_precision"] == 1.0
    assert metrics["title_quality_human_score"] == 0.8
    assert metrics["evidence_completeness"] == 1.0
    assert metrics["rag_recall_at_5"] == 1.0
    assert metrics["rag_mrr"] == 1.0
    assert metrics["rag_answer_groundedness"] == 1.0
    assert metrics["router_escalation_recall"] == 1.0
    assert metrics["router_false_escalation_rate"] == 0.0
    assert metrics["router_cost_per_page_by_class"] == {"scan": pytest.approx(0.15)}
    assert metrics["router_latency_ms_per_page_by_class"] == {"scan": 75.0}
    assert metrics["router_route_regret"] == pytest.approx(0.025)
    assert metrics["review_time_ms"] is None


def test_annotations_are_unavailable_instead_of_invented() -> None:
    metrics = evaluate_masterplan_metrics(
        {"text": "Plain text", "blocks": [], "reading_order": []},
        {
            "text": "Plain text",
            "blocks": [],
            "reading_order": [],
            "verified_human_metrics": {
                "title_quality_human_score": {
                    "value": 1.0,
                    "reviewer_count": 1,
                    "rubric_version": "",
                    "evidence_sha256": "not-a-hash",
                }
            },
        },
    )

    assert metrics["hangul_jamo_corruption_rate"] is None
    assert metrics["title_quality_human_score"] is None
    assert metrics["rag_recall_at_10"] is None
    assert metrics["router_route_regret"] is None
    assert metrics["multi_page_table_merge_accuracy"] is None


def score_record(
    case_id: str,
    *,
    numeric: float = 1.0,
    unsupported: float = 0.0,
    cost: float = 1.0,
    schema_validity: float = 1.0,
    failures: list[str] | None = None,
) -> dict:
    return {
        "benchmark_case_id": case_id,
        "metrics": {
            "schema_validity": schema_validity,
            "numeric_exact_match": numeric,
            "unsupported_claim_rate": unsupported,
            "normalized_edit_similarity": 1.0,
            "estimated_cost_usd": cost,
        },
        "hard_failures": failures or [],
    }


def test_merge_gate_passes_equal_records_and_requires_cost_approval() -> None:
    baseline = [score_record("a"), score_record("b")]
    equal = evaluate_merge_gate(baseline, copy.deepcopy(baseline))
    assert equal.passed
    assert not equal.approval_required

    expensive = [
        score_record("a", cost=1.2),
        score_record("b", cost=1.2),
    ]
    blocked = evaluate_merge_gate(baseline, expensive)
    assert not blocked.passed
    assert blocked.approval_required
    assert "cost_regression_requires_approval" in blocked.reasons

    approved = evaluate_merge_gate(
        baseline,
        expensive,
        approve_cost_regression=True,
    )
    assert approved.passed
    assert not approved.approval_required


def test_merge_gate_fails_closed_on_schema_number_unsupported_and_infra() -> None:
    baseline = [score_record("a")]
    candidate = [
        score_record(
            "a",
            numeric=0.0,
            unsupported=0.1,
            schema_validity=0.0,
            failures=["gpu_oom"],
        )
    ]
    decision = evaluate_merge_gate(baseline, candidate)

    assert not decision.passed
    assert "schema_invalid:a" in decision.reasons
    assert "critical_number_regression:a" in decision.reasons
    assert "unsupported_content_increase:a" in decision.reasons
    assert "infra_failure_rate_above_threshold" in decision.reasons
