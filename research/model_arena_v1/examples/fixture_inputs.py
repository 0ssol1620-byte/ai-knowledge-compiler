"""Build a tiny synthetic protocol fixture for local CLI and negative tests.

The three Arena cases below are deliberately not the 1,000-page Arena and the
one calibration case is deliberately not the 100-page calibration corpus.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

H = "sha256:" + "a" * 64
H2 = "sha256:" + "b" * 64
H3 = "sha256:" + "c" * 64


def fixture() -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    preregistration: dict[str, Any] = {
        "schema": "tavonel.arena.preregistration.v1",
        "study_id": "EXAMPLE_ONLY-synthetic-arena-v1",
        "study_kind": "FIXTURE",
        "evidence_class": "SYNTHETIC_FIXTURE",
        "preregistered_at": "2026-09-12T00:00:00Z",
        "evaluation_commit": "d9db24c1bda2079f0933123d1c54607b3b93197b",
        "corpus_requirements": {
            "arena_total": 3,
            "calibration_total": 1,
            "origin_counts": {"PUBLIC": 1, "FAILURE_ZOO": 1, "CLEAN_CONTROL": 1},
            "slice_counts": {"TABLE_HEAVY": 1, "DEGRADED_SCAN": 1, "CLEAN_DIGITAL": 1},
        },
        "frozen_protocol": {
            "renderer_sha256": H,
            "normalizer_sha256": H,
            "evaluator_sha256": H,
            "metrics_sha256": H,
            "failure_policy_sha256": H,
            "cost_definition_sha256": H,
            "timeout_seconds": 120,
            "concurrency": 1,
            "normalization_policy": "deterministic-only",
            "failure_policy": "non-success quality is zero in effective score",
        },
        "models": [
            {
                "model_id": "fixture-local",
                "exact_revision": "fixture-r1",
                "model_receipt_sha256": H,
            },
            {"model_id": "fixture-api", "exact_revision": "fixture-r1", "model_receipt_sha256": H2},
        ],
        "arms": [
            {
                "arm_id": "local-I-standard-interactive",
                "model_id": "fixture-local",
                "input_track": "I",
                "prompt_track": "STANDARD",
                "execution_track": "INTERACTIVE",
                "prompt_receipt_sha256": H,
                "hardware_receipt_sha256": H,
                "price_snapshot_sha256": H,
            },
            {
                "arm_id": "api-N-P-batch",
                "model_id": "fixture-api",
                "input_track": "N",
                "prompt_track": "P",
                "execution_track": "B",
                "prompt_receipt_sha256": H2,
                "hardware_receipt_sha256": H2,
                "price_snapshot_sha256": H2,
                "batch_equivalence_receipt_sha256": H3,
            },
        ],
        "required_layers": ["A", "B", "C", "D", "E"],
        "public_release": {"required_repeats": 1, "current_actual_prices": False},
    }
    corpus: list[dict[str, Any]] = []
    rows = (
        ("cal-1", "CALIBRATION", "family-cal", "PUBLIC", ["TABLE_HEAVY"], "ROUTER_CALIBRATION"),
        ("case-1", "ARENA", "family-a", "PUBLIC", ["TABLE_HEAVY"], "ROUTER_TRAIN"),
        ("case-2", "ARENA", "family-b", "FAILURE_ZOO", ["DEGRADED_SCAN"], "ROUTER_CALIBRATION"),
        ("case-3", "ARENA", "family-c", "CLEAN_CONTROL", ["CLEAN_DIGITAL"], "ROUTER_HOLDOUT"),
    )
    for case_id, kind, family, origin, slices, split in rows:
        corpus.append(
            {
                "case_id": case_id,
                "corpus_kind": kind,
                "source_id": "fixture:" + case_id,
                "source_uri": "fixture://" + case_id,
                "source_sha256": H,
                "document_family_id": family,
                "origin": origin,
                "slices": slices,
                "split": split,
                "license": {
                    "license_id": "FIXTURE-ONLY",
                    "evidence_uri": "fixture://license",
                    "evidence_sha256": H,
                    "publication_allowed": False,
                },
            }
        )
    runs: list[dict[str, Any]] = []
    for arm in preregistration["arms"]:
        for number in range(1, 4):
            status = "TIMEOUT" if arm["arm_id"] == "api-N-P-batch" and number == 2 else "SUCCESS"
            run: dict[str, Any] = {
                "run_id": f"{arm['arm_id']}-case-{number}-r1",
                "case_id": f"case-{number}",
                "arm_id": arm["arm_id"],
                "repeat": 1,
                "status": status,
                "input_artifact_sha256": H,
                "receipt_sha256": H3,
                "latency_ms": 1000 + number,
                "actual_cost_usd": 0.001 * number,
            }
            if status == "SUCCESS":
                run.update(
                    {
                        "raw_output_sha256": H,
                        "normalized_output_sha256": H2,
                        "quality": 0.9 - number / 100,
                    }
                )
            else:
                run["error_class"] = "WALL_CLOCK_TIMEOUT"
            runs.append(run)
    base_metrics = {"quality": 0.8, "coverage": 1.0, "failure_rate": 0.0}
    layers: list[dict[str, Any]] = [
        {
            "record_id": "layer-a",
            "layer": "A",
            "case_id": "case-1",
            "arm": "fixture-local",
            "metrics": base_metrics,
            "public_evaluator_sha256": H,
            "receipt_sha256": H,
        },
        {
            "record_id": "layer-b",
            "layer": "B",
            "case_id": "case-1",
            "arm": "fixture-local",
            "metrics": {
                "content_coverage": 0.8,
                "structure_fidelity": 0.8,
                "table_fidelity": 0.8,
                "reading_order": 0.8,
                "visual_caption_retention": 0.8,
                "provenance_coverage": 0.8,
                "cross_page_continuity": 0.8,
            },
            "receipt_sha256": H,
        },
        {
            "record_id": "layer-c",
            "layer": "C",
            "case_id": "case-1",
            "arm": "fixture-router",
            "metrics": {
                "oracle_regret": 0.1,
                "trust_constraint_violation_rate": 0.0,
                "catastrophic_miss_rate": 0.0,
                "false_escalation_rate": 0.1,
                "missed_escalation_rate": 0.1,
                "cost_usd": 0.01,
                "latency_ms": 10,
            },
            "receipt_sha256": H,
        },
    ]
    fixed_context = {
        "retriever_sha256": H,
        "llm_sha256": H,
        "prompt_sha256": H,
        "corpus_sha256": H,
        "questions_sha256": H,
    }
    downstream_metrics = {
        "answer_correctness": 0.8,
        "answer_completeness": 0.8,
        "citation_correctness": 0.8,
        "retrieval_recall": 0.8,
        "unsupported_claim_rate": 0.0,
        "tokens": 10,
        "latency_ms": 10,
        "cost_usd": 0.01,
    }
    for arm in sorted({"RAW_NATIVE", "SINGLE_PARSER", "TAVONEL"}):
        layers.append(
            {
                "record_id": "layer-d-" + arm.lower(),
                "layer": "D",
                "case_id": "case-1",
                "arm": arm,
                "experiment_id": "fixture-downstream",
                "fixed_context": fixed_context,
                "metrics": downstream_metrics,
                "receipt_sha256": H,
            }
        )
    layers.append(
        {
            "record_id": "layer-e",
            "layer": "E",
            "case_id": "case-1",
            "arm": "fixture-ontology",
            "gold_sha256": H,
            "provenance_sha256": H2,
            "metrics": {
                "entity_precision": 0.8,
                "entity_recall": 0.8,
                "relation_precision": 0.8,
                "relation_recall": 0.8,
                "entity_resolution_precision": 0.8,
                "entity_resolution_recall": 0.8,
                "schema_coverage": 0.8,
                "provenance_coverage": 0.8,
                "graph_consistency": 0.8,
                "update_correctness": 0.8,
            },
            "continuous_update": {
                "modified_fraction": 0.03,
                "impacted_region_recall": 0.8,
                "unnecessary_recompute_ratio": 0.1,
                "stale_knowledge_rate": 0.0,
                "provenance_correctness": 0.9,
                "full_rebuild_equivalence": 1.0,
                "cost_saved": 0.5,
                "latency_saved": 0.5,
            },
            "receipt_sha256": H,
        }
    )
    return preregistration, corpus, runs, layers


def main() -> None:
    parser = argparse.ArgumentParser(description="write the non-public Arena fixture")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    preregistration, corpus, runs, layers = fixture()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "preregistration.json").write_text(
        json.dumps(preregistration, indent=2) + "\n", encoding="utf-8"
    )
    for name, rows in (("corpus.jsonl", corpus), ("runs.jsonl", runs), ("layers.jsonl", layers)):
        (args.output / name).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
