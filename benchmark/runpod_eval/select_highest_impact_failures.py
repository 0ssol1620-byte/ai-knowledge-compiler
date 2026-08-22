#!/usr/bin/env python3
"""Select the documents that carry most of the official failure mass.

Official evaluation attributes every failure to an exact case, and that mass is
heavily concentrated: on the 5,132-case public core the worst 7% of documents
carry roughly 59% of all failures. Re-running all 3,173 recoverable cases to
reach them is mostly wasted GPU time, so this ranks cases by measured failure
count and emits a filtered failure-record file that the existing selective
recovery lane consumes unchanged.

The selection is deliberately *not* a quality claim. It is a targeting rule, and
the receipt states the rule, the coverage it achieves, and the fact that any
improvement measured on this subset describes the subset and must not be
extrapolated to the corpus.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def select_highest_impact(
    payload: dict[str, Any], *, case_limit: int, per_suite: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = payload.get("records")
    routes = payload.get("routes")
    if not isinstance(records, list) or not isinstance(routes, list):
        raise ValueError("failure record file must carry records and routes arrays")
    if case_limit < 1:
        raise ValueError("case limit must be positive")

    failures_per_case: collections.Counter[tuple[str, str]] = collections.Counter()
    for record in records:
        failures_per_case[(str(record["benchmark_id"]), str(record["case_id"]))] += 1

    recoverable = {
        (str(route["benchmark_id"]), str(route["case_id"]))
        for route in routes
        if route.get("request_recovery")
    }
    # A case with no recovery route cannot be re-run by this lane, so ranking it
    # would silently shrink the real selection.
    candidates = [
        identity for identity in failures_per_case if identity in recoverable
    ]
    if per_suite:
        # Raw ranking is dominated by whichever benchmark emits the most rule
        # checks, which would leave the other two with no measurement at all.
        # Taking the worst N inside each suite keeps every benchmark represented.
        ranked = []
        for suite in sorted({identity[0] for identity in candidates}):
            suite_ranked = sorted(
                (identity for identity in candidates if identity[0] == suite),
                key=lambda identity: (-failures_per_case[identity], identity),
            )
            ranked.extend(suite_ranked[:case_limit])
        ranked.sort(key=lambda identity: (-failures_per_case[identity], identity))
        selected = set(ranked)
    else:
        ranked = sorted(
            candidates,
            key=lambda identity: (-failures_per_case[identity], identity),
        )
        ranked = ranked[:case_limit]
        selected = set(ranked)
    if not selected:
        raise ValueError("no recoverable case carries an official failure")

    selected_records = [
        record
        for record in records
        if (str(record["benchmark_id"]), str(record["case_id"])) in selected
    ]
    selected_routes = [
        route
        for route in routes
        if (str(route["benchmark_id"]), str(route["case_id"])) in selected
    ]

    total_failures = len(records)
    covered = len(selected_records)
    by_suite = collections.Counter(identity[0] for identity in selected)
    by_model: collections.Counter[str] = collections.Counter()
    for route in selected_routes:
        if not route.get("request_recovery"):
            continue
        for model in route.get("candidate_models") or []:
            by_model[str(model)] += 1

    filtered = dict(payload)
    filtered["records"] = selected_records
    filtered["routes"] = selected_routes
    filtered["record_count"] = len(selected_records)
    filtered["recoverable_case_count"] = len(
        {
            (str(route["benchmark_id"]), str(route["case_id"]))
            for route in selected_routes
            if route.get("request_recovery")
        }
    )
    filtered["selection"] = {
        "schema": "folynta.highest-impact-failure-selection.v1",
        "rule": "rank recoverable cases by official failure count, descending, take the top N",
        "case_limit": case_limit,
        "per_suite": per_suite,
    }

    receipt = {
        "schema": "folynta.highest-impact-failure-selection.v1",
        "rule": (
            "rank recoverable cases by official failure count, descending, take the top N "
            "within each benchmark" 
        ) if per_suite else (
            "rank recoverable cases by official failure count, descending, take the top N"
        ),
        "case_limit": case_limit,
        "per_suite": per_suite,
        "selected_case_count": len(selected),
        "recoverable_case_pool": len(recoverable),
        "corpus_failure_records": total_failures,
        "selected_failure_records": covered,
        "failure_coverage_fraction": covered / total_failures if total_failures else 0.0,
        "selected_cases_by_suite": dict(sorted(by_suite.items())),
        "recovery_routes_by_model": dict(sorted(by_model.items())),
        "selected_cases": [
            {
                "benchmark_id": suite,
                "case_id": case_id,
                "official_failure_count": failures_per_case[(suite, case_id)],
            }
            for suite, case_id in ranked
        ],
        "extrapolation_policy": (
            "Any accuracy change measured on this subset describes the selected "
            "documents only. It is not a corpus-level improvement and must not be "
            "reported as one."
        ),
        "score_inflation_allowed": False,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    return filtered, receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure-records", required=True, type=Path)
    parser.add_argument("--case-limit", required=True, type=int)
    parser.add_argument(
        "--per-suite",
        action="store_true",
        help="take the top N inside each benchmark instead of the top N overall",
    )
    parser.add_argument("--output-records", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_records.exists():
        raise FileExistsError(f"selection output already exists: {args.output_records}")
    payload = json.loads(args.failure_records.read_text(encoding="utf-8-sig"))
    filtered, receipt = select_highest_impact(
        payload, case_limit=args.case_limit, per_suite=args.per_suite
    )
    args.output_records.parent.mkdir(parents=True, exist_ok=True)
    args.output_records.write_text(
        json.dumps(filtered, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {k: v for k, v in receipt.items() if k != "selected_cases"}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
