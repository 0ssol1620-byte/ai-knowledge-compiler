#!/usr/bin/env python3
"""Publish the measured OmniDocBench demo portfolio from evidence summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "benchmark/templates/omnidoc-demo-candidates.json"
DEFAULT_SCHEMA = ROOT / "benchmark/schemas/model-evaluation-public-snapshot.schema.json"
DEFAULT_BUNDLE = ROOT / "benchmark/reports/model-evaluation-evidence-bundle-2026-08-01.json"
DEFAULT_SNAPSHOT = ROOT / "apps/web/src/data/benchmark-public-snapshot.json"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON object required")
    return value


def mean_metric(evidence: dict[str, Any], name: str) -> float:
    return float(evidence["valid_partial_metrics"][name]["mean"])


def build(registry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    bundle_candidates: list[dict[str, Any]] = []
    identities: list[str] = []
    evaluator_revision = str(registry["evaluator_version"]).split("@", 1)[-1]
    for candidate in registry["candidates"]:
        evidence_path = ROOT / candidate["evidence_path"]
        evidence = load(evidence_path)
        if evidence["promotion_status"] != "eligible_partial_metrics":
            raise ValueError(f"{candidate['id']}: formal promotion gate not met")
        if evidence["model_id"] != candidate["id"]:
            raise ValueError(f"{candidate['id']}: evidence model identity mismatch")
        if evidence["evaluator_revision"] != evaluator_revision:
            raise ValueError(f"{candidate['id']}: evaluator revision mismatch")
        if evidence["corpus"]["ground_truth_mounted_on_inference_worker"] is not False:
            raise ValueError(f"{candidate['id']}: inference ground-truth isolation failed")
        repeat_count = int(evidence["repeat_count"])
        page_count = int(evidence["corpus"]["page_count"])
        stability = evidence["repeat_stability"]
        if repeat_count < 3 or stability["status"] != "available":
            raise ValueError(f"{candidate['id']}: repeat evidence is incomplete")
        inference_sha = str(evidence["sources"]["inference_run_summary"]["sha256"])
        evidence_sha = digest(evidence_path)
        datasets.append(
            {
                "id": candidate["id"],
                "label": candidate["label"],
                "source": f"{page_count} pages x {repeat_count} blind repeats",
                "status": "available",
                "document_count": page_count,
                "page_count": page_count,
                "metrics": {
                    "text_edit_companion": 1
                    - mean_metric(evidence, "text_edit_distance_page_average"),
                    "formula_edit_companion": 1
                    - mean_metric(evidence, "formula_edit_distance_page_average"),
                    "table_teds": mean_metric(evidence, "table_teds_sample_average"),
                    "table_structure_teds": mean_metric(
                        evidence, "table_teds_structure_sample_average"
                    ),
                    "table_edit_companion": 1
                    - mean_metric(evidence, "table_edit_distance_page_average"),
                    "reading_order_companion": 1
                    - mean_metric(evidence, "reading_order_edit_distance_page_average"),
                    "mean_latency_ms": float(
                        evidence["performance"]["seconds_per_page"]["mean"]
                    )
                    * 1_000,
                    "cost_per_page_usd": float(
                        evidence["performance"][
                            "estimated_provider_cost_per_page_usd"
                        ]["mean"]
                    ),
                    "exact_repeat_ratio": float(stability["exact_repeat_ratio"]),
                },
                "evidence": {
                    "case_count": page_count * repeat_count,
                    "hard_failure_count": 0,
                    "repeat_count": repeat_count,
                    "evidence_summary_sha256": evidence_sha,
                    "inference_run_summary_sha256": inference_sha,
                    "ground_truth_sha256": registry["ground_truth_sha256"],
                },
            }
        )
        bundle_candidates.append(
            {
                "id": candidate["id"],
                "model_identity": candidate["model_identity"],
                "evidence_summary_sha256": evidence_sha,
                "inference_run_summary_sha256": inference_sha,
            }
        )
        identities.append(candidate["model_identity"])
    bundle = {
        "schema_version": "2.0.0",
        "claim_class": "internal_reproducibility_evidence",
        "corpus": registry["corpus_revision"],
        "ground_truth_sha256": registry["ground_truth_sha256"],
        "evaluator": registry["evaluator_version"],
        "ground_truth_mounted_on_inference_workers": False,
        "candidates": bundle_candidates,
        "unavailable_metrics": ["cdm", "overall"],
        "publication_boundary": (
            "Official partial metrics on the demo subset; not a full leaderboard "
            "result."
        ),
    }
    snapshot = {
        "schema_version": "1.1",
        "status": "available",
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "evaluator_version": registry["evaluator_version"],
        "evidence_bundle_sha256": None,
        "corpus_revision": registry["corpus_revision"],
        "model_revision": " + ".join(identities),
        "hardware_profile": registry["hardware_profile"],
        "datasets": datasets,
    }
    return bundle, snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--bundle-output", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--snapshot-output", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()
    bundle, snapshot = build(load(args.registry.resolve()))
    args.bundle_output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    snapshot["evidence_bundle_sha256"] = digest(args.bundle_output)
    schema = load(args.schema.resolve())
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(snapshot)
    )
    if errors:
        raise ValueError("; ".join(error.message for error in errors[:5]))
    args.snapshot_output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "candidate_count": len(snapshot["datasets"]),
                "formal_case_count": sum(
                    row["evidence"]["case_count"] for row in snapshot["datasets"]
                ),
                "bundle_sha256": snapshot["evidence_bundle_sha256"],
                "snapshot_sha256": digest(args.snapshot_output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
