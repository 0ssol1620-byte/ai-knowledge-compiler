#!/usr/bin/env python3
"""Bind official public-benchmark failures to exact artifacts and recovery routes."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmark.v6.public_failure_adapter import (
    PUBLIC_FAILURE_RULES,
    EvaluatorFailureRecord,
    adapt_failure,
)

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
_SCOPE_ORDER = {"cell": 0, "row": 1, "table": 2, "region": 3, "page": 4, "document": 5}


@dataclass(frozen=True, slots=True)
class EvaluationSource:
    benchmark_id: str
    evaluation_root: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _safe(value: str) -> str:
    """Render an ASCII identifier the recovery taxonomy accepts.

    ``EvaluatorFailureRecord`` requires ``[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}``.
    ``str.isalnum`` is Unicode-aware, so CJK page names used to survive the fold
    and then fail validation. Folding them to ``-`` is lossy and could collapse
    two distinct locations into one identity, so a SHA-256 prefix of the
    original value is appended whenever the fold or the length cap loses
    information.
    """
    rendered = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._:/-")
        else "-"
        for character in value
    )
    if rendered == value and len(value) <= 512:
        return rendered.strip("-") or "unknown"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    stem = rendered[:495].strip("-")
    return f"{stem}-{digest}" if stem else f"location-{digest}"


def _load(path: Path) -> dict[str, Any]:
    # PowerShell-written receipts carry a UTF-8 BOM; utf-8-sig reads both shapes.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _failure_paths(source: EvaluationSource) -> tuple[Path, Path]:
    summary = source.evaluation_root / "evaluation-summary.json"
    if source.benchmark_id == "omnidocbench":
        failure = source.evaluation_root / "repeat-1" / "official-element-failures.json"
    else:
        failure = source.evaluation_root / "official-rule-failures.json"
    return summary, failure


def _prediction_lookup(merged_root: Path, benchmark_id: str) -> dict[str, dict[str, Any]]:
    payload = _load(merged_root / "indexes" / f"{benchmark_id}-cases.json")
    result = {str(record["case_id"]): record for record in payload.get("records", [])}
    if len(result) != int(payload.get("input_count", -1)):
        raise ValueError(f"merged case index coverage is invalid: {benchmark_id}")
    return result


def _models_for_codes(codes: set[str], request_recovery: bool) -> list[str]:
    if not request_recovery:
        return []
    models: list[str] = []
    if "B01" in codes:
        models.append("deepseek-ocr-2")
    if codes & {"F01", "T05", "R01", "N01", "G01", "P01"}:
        models.append("paddleocr-vl-1.6")
    if not models:
        models.append("paddleocr-vl-1.6")
    return models


def build_failure_records(
    *,
    merged_root: Path,
    evaluations: tuple[EvaluationSource, ...],
    output_path: Path,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"failure record output already exists: {output_path}")
    by_suite = {source.benchmark_id: source for source in evaluations}
    if set(by_suite) != set(SUITES) or len(by_suite) != len(evaluations):
        raise ValueError("exactly one official evaluation source per public benchmark is required")

    records: list[dict[str, Any]] = []
    raw_predictions: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for benchmark_id in SUITES:
        source = by_suite[benchmark_id]
        summary_path, failure_path = _failure_paths(source)
        summary = _load(summary_path)
        failures = _load(failure_path)
        revision = str(summary.get("evaluator_revision", ""))
        evidence_sha256 = _sha256(failure_path)
        indexes = _prediction_lookup(merged_root, benchmark_id)
        if int(failures.get("failure_count", -1)) != len(failures.get("failures", [])):
            raise ValueError(f"official failure count is invalid: {benchmark_id}")
        for index, failure in enumerate(failures["failures"]):
            case_id = str(failure["case_id"])
            indexed = indexes.get(case_id)
            if indexed is None or indexed.get("status") != "completed":
                raise ValueError(f"official failure is not bound to a completed case: {case_id}")
            evaluator_type = _safe(str(failure["evaluator_type"]))
            location = _safe(str(failure.get("location_id") or f"failure-{index}"))
            identity = (benchmark_id, case_id, evaluator_type, location)
            if identity in seen:
                raise ValueError(f"duplicate official failure identity: {identity}")
            seen.add(identity)
            prediction_sha256 = str(indexed.get("markdown_sha256"))
            if benchmark_id == "parsebench" and evaluator_type == "layout":
                prediction_sha256 = str(indexed.get("model_sha256"))
            record = EvaluatorFailureRecord(
                benchmark_id=benchmark_id,
                case_id=case_id,
                evaluator_revision=revision,
                evaluator_type=evaluator_type,
                location_id=location,
                prediction_sha256=prediction_sha256,
                authority_sha256=evidence_sha256,
                failure_evidence_sha256=evidence_sha256,
                passed=False,
                score=float(failure.get("score", 0.0)),
            )
            if evaluator_type not in PUBLIC_FAILURE_RULES[benchmark_id]:
                escalations.append(
                    {
                        "benchmark_id": benchmark_id,
                        "case_id": case_id,
                        "evaluator_type": evaluator_type,
                        "location_id": location,
                        "reason": "unmapped_official_evaluator_failure",
                    }
                )
                record.validate()
            else:
                prediction = adapt_failure(record)
                if prediction is None:
                    raise AssertionError("failed official record produced no failure prediction")
                raw_predictions.append(
                    {
                        "benchmark_id": benchmark_id,
                        **asdict(prediction),
                        "failure_codes": sorted(prediction.failure_codes),
                    }
                )
            records.append({**asdict(record), "source_failure": failure})
        evidence.append(
            {
                "benchmark_id": benchmark_id,
                "evaluator_revision": revision,
                "evaluation_summary_sha256": _sha256(summary_path),
                "failure_evidence_sha256": evidence_sha256,
                "failure_count": int(failures["failure_count"]),
            }
        )

    routes_by_case: dict[tuple[str, str], dict[str, Any]] = {}
    for prediction in raw_predictions:
        key = (str(prediction["benchmark_id"]), str(prediction["item_id"]))
        route = routes_by_case.setdefault(
            key,
            {
                "benchmark_id": key[0],
                "case_id": key[1],
                "failure_codes": set(),
                "scope_levels": set(),
                "scope_ids": set(),
                "request_recovery": False,
                "escalate": False,
            },
        )
        route["failure_codes"].update(prediction["failure_codes"])
        if prediction["scope_level"]:
            route["scope_levels"].add(prediction["scope_level"])
            route["scope_ids"].add(prediction["scope_id"])
        route["request_recovery"] = route["request_recovery"] or bool(
            prediction["request_recovery"]
        )
        route["escalate"] = route["escalate"] or bool(prediction["escalate"])
    routes: list[dict[str, Any]] = []
    for route in routes_by_case.values():
        scopes = sorted(route.pop("scope_levels"), key=lambda value: _SCOPE_ORDER[value])
        codes = set(route["failure_codes"])
        route["failure_codes"] = sorted(codes)
        route["minimum_scope_level"] = scopes[0] if scopes else None
        route["scope_ids"] = sorted(route["scope_ids"])
        route["candidate_models"] = _models_for_codes(codes, route["request_recovery"])
        routes.append(route)

    payload = {
        "schema": "folynta.public-official-failure-records.v1",
        "record_count": len(records),
        "recoverable_case_count": sum(route["request_recovery"] for route in routes),
        "nonrecoverable_case_count": sum(not route["request_recovery"] for route in routes),
        "escalation_count": len(escalations),
        "evidence": evidence,
        "records": records,
        "raw_predictions": raw_predictions,
        "routes": sorted(routes, key=lambda item: (item["benchmark_id"], item["case_id"])),
        "escalations": escalations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {**payload, "output_sha256": _sha256(output_path)}


def _evaluation(value: str) -> EvaluationSource:
    try:
        benchmark_id, path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("evaluation must be BENCHMARK_ID=PATH") from exc
    return EvaluationSource(benchmark_id, Path(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged-root", type=Path, required=True)
    parser.add_argument("--evaluation", action="append", type=_evaluation, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_failure_records(
        merged_root=args.merged_root.resolve(),
        evaluations=tuple(args.evaluation),
        output_path=args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "record_count": result["record_count"],
                "recoverable_case_count": result["recoverable_case_count"],
                "output_sha256": result["output_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EvaluationSource", "build_failure_records"]
