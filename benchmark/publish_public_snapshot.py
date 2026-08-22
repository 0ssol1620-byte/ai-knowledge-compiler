"""Publish a fail-closed, browser-safe benchmark snapshot from approved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPOSITORY_ROOT / "benchmark" / "templates" / "public-snapshot.template.json"
DEFAULT_SCHEMA = REPOSITORY_ROOT / "benchmark" / "schemas" / "public-snapshot.schema.json"
_SHA256 = "sha256:"


def _digest(payload: bytes) -> str:
    return _SHA256 + hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON object required")
    return value


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], str]:
    payload = path.read_bytes()
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: JSON object required")
        rows.append(value)
    if not rows:
        raise ValueError("score record file is empty")
    return rows, _digest(payload)


def _require_digest(value: object, name: str) -> str:
    text = str(value)
    if (
        len(text) != len(_SHA256) + 64
        or not text.startswith(_SHA256)
        or any(character not in "0123456789abcdef" for character in text[len(_SHA256) :])
    ):
        raise ValueError(f"{name} must be a lowercase sha256: digest")
    return text


def _validated_corpus_manifest(path: Path) -> tuple[dict[str, Any], str]:
    payload = path.read_bytes()
    manifest = json.loads(payload)
    if not isinstance(manifest, dict):
        raise ValueError("corpus manifest must be a JSON object")
    required_true = (
        "rights_approved",
        "labels_present",
        "annotation_qa_approved",
        "holdout_isolated",
    )
    missing = [name for name in required_true if manifest.get(name) is not True]
    if missing:
        raise ValueError(f"corpus manifest approval fields are not true: {', '.join(missing)}")
    if int(manifest.get("document_count", 0)) < 150:
        raise ValueError("corpus manifest requires at least 150 documents")
    if int(manifest.get("page_count", 0)) < 1500:
        raise ValueError("corpus manifest requires at least 1500 pages")
    _require_digest(manifest.get("corpus_revision"), "corpus_revision")
    if not str(manifest.get("independent_approver", "")).strip():
        raise ValueError("corpus manifest requires an independent approver")
    if not str(manifest.get("approved_at", "")).strip():
        raise ValueError("corpus manifest requires approved_at")
    return manifest, _digest(payload)


def _same(rows: list[dict[str, Any]], key: str) -> str:
    values = {str(row.get(key, "")).strip() for row in rows}
    if "" in values or len(values) != 1:
        raise ValueError(f"score records must share one non-empty {key}")
    return values.pop()


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _available_mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        number
        for row in rows
        if isinstance(row.get("metrics"), dict)
        and (number := _number(row["metrics"].get(key))) is not None
    ]
    return sum(values) / len(values) if values else None


def _p95(rows: list[dict[str, Any]]) -> float | None:
    values = sorted(
        number
        for row in rows
        if isinstance(row.get("metrics"), dict)
        and (number := _number(row["metrics"].get("latency_ms"))) is not None
    )
    if not values:
        return None
    return values[max(0, math.ceil(len(values) * 0.95) - 1)]


def build_public_snapshot(
    *,
    template: dict[str, Any],
    rows: list[dict[str, Any]],
    score_sha256: str,
    corpus: dict[str, Any],
    corpus_manifest_sha256: str,
    evidence_bundle_sha256: str,
    dataset_id: str,
) -> dict[str, Any]:
    if any(row.get("is_synthetic") is not False for row in rows):
        raise ValueError("synthetic or unclassified score records cannot be published")
    if any(row.get("claim_class") != "internal_result" for row in rows):
        raise ValueError("every score record must have claim_class=internal_result")
    evaluator = _same(rows, "evaluator_version")
    model_revision = _same(rows, "model_revision")
    hardware_profiles = {
        str(row.get("reproducibility", {}).get("hardware_profile", "")).strip()
        for row in rows
        if isinstance(row.get("reproducibility"), dict)
    }
    if "" in hardware_profiles or len(hardware_profiles) != 1:
        raise ValueError("score records must share one hardware profile")
    hardware_profile = hardware_profiles.pop()
    if evaluator != str(template.get("evaluator_version")):
        raise ValueError("score evaluator does not match the public snapshot contract")

    datasets = template.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("public snapshot template datasets must be an array")
    target = next(
        (
            candidate
            for candidate in datasets
            if isinstance(candidate, dict) and candidate.get("id") == dataset_id
        ),
        None,
    )
    if target is None:
        raise ValueError(f"unknown public benchmark dataset: {dataset_id}")

    metrics = {
        "text": _available_mean(rows, "normalized_edit_similarity"),
        "numbers": _available_mean(rows, "numeric_exact_match"),
        "tables": _available_mean(rows, "table_cell_exactness"),
        "provenance": _available_mean(rows, "provenance_coverage"),
        "p95_latency_ms": _p95(rows),
        "cost_per_page_usd": _available_mean(rows, "estimated_cost_usd"),
    }
    required_quality = ("text", "numbers", "tables", "provenance")
    unavailable = [key for key in required_quality if metrics[key] is None]
    if unavailable:
        raise ValueError(f"required public metrics are unavailable: {', '.join(unavailable)}")

    target.update(
        {
            "status": "available",
            "document_count": int(corpus["document_count"]),
            "page_count": int(corpus["page_count"]),
            "metrics": metrics,
            "evidence": {
                "case_count": len(rows),
                "hard_failure_count": sum(bool(row.get("hard_failures")) for row in rows),
                "score_records_sha256": score_sha256,
                "corpus_manifest_sha256": corpus_manifest_sha256,
            },
        }
    )
    template.update(
        {
            "status": "available",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "evidence_bundle_sha256": _require_digest(
                evidence_bundle_sha256,
                "evidence_bundle_sha256",
            ),
            "corpus_revision": _require_digest(
                corpus["corpus_revision"],
                "corpus_revision",
            ),
            "model_revision": model_revision,
            "hardware_profile": hardware_profile,
        }
    )
    return template


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--evidence-bundle-sha256", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows, score_sha256 = _load_jsonl(args.scores)
        corpus, corpus_sha256 = _validated_corpus_manifest(args.corpus_manifest)
        snapshot = build_public_snapshot(
            template=_load_json(args.template),
            rows=rows,
            score_sha256=score_sha256,
            corpus=corpus,
            corpus_manifest_sha256=corpus_sha256,
            evidence_bundle_sha256=args.evidence_bundle_sha256,
            dataset_id=args.dataset_id,
        )
        schema = _load_json(args.schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(snapshot),
            key=lambda error: list(error.path),
        )
        if errors:
            raise ValueError("; ".join(error.message for error in errors[:5]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output.resolve()),
                "output_sha256": _digest(args.output.read_bytes()),
                "dataset_id": args.dataset_id,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
