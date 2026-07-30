from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from benchmark.publish_public_snapshot import (
    DEFAULT_SCHEMA,
    DEFAULT_TEMPLATE,
    build_public_snapshot,
)

DIGEST = "sha256:" + "a" * 64


def _row(*, synthetic: bool = False, claim_class: str = "internal_result") -> dict[str, object]:
    return {
        "benchmark_case_id": "dart-001",
        "claim_class": claim_class,
        "is_synthetic": synthetic,
        "evaluator_version": "22.4-22.8-v1.0.0",
        "model_revision": "b" * 40,
        "hard_failures": [],
        "metrics": {
            "normalized_edit_similarity": 0.98,
            "numeric_exact_match": 1.0,
            "table_cell_exactness": 0.91,
            "provenance_coverage": 1.0,
            "latency_ms": 1200,
            "estimated_cost_usd": 0.0012,
        },
        "reproducibility": {"hardware_profile": "serverless_24gb"},
    }


def _corpus() -> dict[str, object]:
    return {
        "rights_approved": True,
        "labels_present": True,
        "annotation_qa_approved": True,
        "holdout_isolated": True,
        "document_count": 150,
        "page_count": 1500,
        "corpus_revision": DIGEST,
        "independent_approver": "quality-owner",
        "approved_at": "2026-07-30T00:00:00Z",
    }


def _template() -> dict[str, object]:
    return json.loads(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))


def test_public_snapshot_requires_real_approved_evidence() -> None:
    snapshot = build_public_snapshot(
        template=_template(),
        rows=[_row(), {**_row(), "benchmark_case_id": "dart-002"}],
        score_sha256=DIGEST,
        corpus=_corpus(),
        corpus_manifest_sha256=DIGEST,
        evidence_bundle_sha256=DIGEST,
        dataset_id="ko-dart",
    )
    dataset = next(item for item in snapshot["datasets"] if item["id"] == "ko-dart")
    assert snapshot["status"] == "available"
    assert dataset["status"] == "available"
    assert dataset["metrics"]["text"] == pytest.approx(0.98)
    assert dataset["metrics"]["p95_latency_ms"] == 1200
    assert dataset["evidence"]["case_count"] == 2
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(snapshot)) == []


@pytest.mark.parametrize(
    "row",
    [
        _row(synthetic=True),
        _row(claim_class="contract_test"),
        {**_row(), "metrics": {**_row()["metrics"], "table_cell_exactness": None}},
    ],
)
def test_public_snapshot_rejects_synthetic_unapproved_or_incomplete_rows(
    row: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        build_public_snapshot(
            template=copy.deepcopy(_template()),
            rows=[row],
            score_sha256=DIGEST,
            corpus=_corpus(),
            corpus_manifest_sha256=DIGEST,
            evidence_bundle_sha256=DIGEST,
            dataset_id="ko-dart",
        )


def test_default_unavailable_snapshot_is_schema_valid() -> None:
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    snapshot = json.loads(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(snapshot)) == []
