from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.quality_launch import EvaluationError, evaluate_suite, load_json

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "tests" / "quality_launch" / "golden_suite.json"
CANDIDATE = ROOT / "tests" / "quality_launch" / "reference_candidate.json"


def _inputs() -> tuple[dict[str, object], dict[str, object]]:
    return load_json(SUITE), load_json(CANDIDATE)


def test_reference_candidate_qualifies_all_required_dimensions() -> None:
    suite, candidate = _inputs()
    report = evaluate_suite(suite, candidate, repo_root=ROOT)

    assert report["verdict"] == "qualified"
    assert report["passed_dimensions"] == report["total_dimensions"] == 10
    assert report["evidence_boundary"]["runpod_execution"] == "not_observed"
    assert report["evidence_boundary"]["production_runtime_claim"] is False
    assert all(source["verified"] for source in report["sources"])


@pytest.mark.parametrize(
    ("mutator", "failed_dimension"),
    [
        (
            lambda value: value["dimensions"]["ocr_text"]["documents"][0].update(text="bad"),
            "ocr_text",
        ),
        (
            lambda value: value["dimensions"]["citations"]["citations"][0].update(page_index0=9),
            "citations",
        ),
        (
            lambda value: value["dimensions"]["entity_resolution"].update(
                clusters=[["platform-title", "services-row"]]
            ),
            "entity_resolution",
        ),
        (
            lambda value: value["dimensions"]["claims"]["labels"].update(
                {"c-public-filing": "entailment"}
            ),
            "claims",
        ),
        (
            lambda value: value["dimensions"]["temporal_authority"]["facts"][0].update(
                temporal_source="unknown"
            ),
            "temporal_authority",
        ),
        (
            lambda value: value["dimensions"]["ontology_graph"]["edges"][0].update(
                target="missing"
            ),
            "ontology_graph",
        ),
        (
            lambda value: value["dimensions"]["adaptive_chunking"]["chunks"][0].update(
                token_count=1201
            ),
            "adaptive_chunking",
        ),
        (
            lambda value: value["dimensions"]["retrieval"]["queries"][0].update(retrieved=[]),
            "retrieval",
        ),
        (
            lambda value: value["dimensions"]["downstream_ai"].update(
                compiled=value["dimensions"]["downstream_ai"]["raw"]
            ),
            "downstream_ai",
        ),
    ],
)
def test_critical_regressions_fail_closed(mutator: object, failed_dimension: str) -> None:
    suite, candidate = _inputs()
    mutated = copy.deepcopy(candidate)
    mutator(mutated)  # type: ignore[operator]

    report = evaluate_suite(suite, mutated, repo_root=ROOT)
    failures = {row["name"] for row in report["dimensions"] if not row["passed"]}

    assert report["verdict"] == "not_qualified"
    assert failed_dimension in failures


def test_missing_dimension_is_not_interpreted_as_zero_or_skipped() -> None:
    suite, candidate = _inputs()
    del candidate["dimensions"]["claims"]

    with pytest.raises(EvaluationError, match="missing required dimension: claims"):
        evaluate_suite(suite, candidate, repo_root=ROOT)


def test_fixture_hash_drift_fails_before_scoring() -> None:
    suite, candidate = _inputs()
    suite["sources"][0]["sha256"] = "sha256:" + "0" * 64

    with pytest.raises(EvaluationError, match="source fixture drift"):
        evaluate_suite(suite, candidate, repo_root=ROOT)


def test_acceptance_report_conforms_to_published_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    suite, candidate = _inputs()
    report = evaluate_suite(suite, candidate, repo_root=ROOT)
    schema_path = ROOT / "docs" / "quality_launch" / "acceptance-report.schema.json"

    jsonschema.Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(
        report
    )
