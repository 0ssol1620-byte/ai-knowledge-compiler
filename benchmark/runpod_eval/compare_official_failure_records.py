#!/usr/bin/env python3
"""Select strict no-regression quality improvements from official failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _route_lookup(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for route in payload.get("routes", []):
        key = (str(route["benchmark_id"]), str(route["case_id"]))
        if key in result:
            raise ValueError(f"duplicate official failure route: {key}")
        result[key] = route
    return result


def _record_counts(payload: dict[str, Any]) -> dict[tuple[str, str], int]:
    counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    for record in payload.get("records", []):
        counts[(str(record["benchmark_id"]), str(record["case_id"]))] += 1
    return dict(counts)


def validate_accepted_decision(decision: dict[str, Any]) -> None:
    baseline_count = int(decision.get("baseline_failure_record_count", -1))
    candidate_count = int(decision.get("candidate_failure_record_count", -1))
    baseline_codes = {
        str(value) for value in decision.get("baseline_failure_codes", [])
    }
    candidate_codes = {
        str(value) for value in decision.get("candidate_failure_codes", [])
    }
    new_codes = {str(value) for value in decision.get("new_failure_codes", [])}
    if (
        baseline_count < 1
        or candidate_count < 0
        or candidate_count >= baseline_count
        or decision.get("strictly_improved") is not True
        or bool(decision.get("candidate_escalates"))
        or new_codes
        or not candidate_codes.issubset(baseline_codes)
    ):
        raise ValueError("accepted official comparison decision violates policy")


def compare_failure_records(
    *, baseline_path: Path, candidate_path: Path, output_path: Path
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"comparison output already exists: {output_path}")
    baseline = _load(baseline_path)
    candidate = _load(candidate_path)
    baseline_routes = _route_lookup(baseline)
    candidate_routes = _route_lookup(candidate)
    baseline_counts = _record_counts(baseline)
    candidate_counts = _record_counts(candidate)

    accepted: list[dict[str, Any]] = []
    persistent: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for key, baseline_route in sorted(baseline_routes.items()):
        if baseline_route.get("request_recovery") is not True:
            continue
        candidate_route = candidate_routes.get(key)
        baseline_codes = set(str(value) for value in baseline_route.get("failure_codes", []))
        candidate_codes = (
            set(str(value) for value in candidate_route.get("failure_codes", []))
            if candidate_route
            else set()
        )
        baseline_count = baseline_counts.get(key, 0)
        candidate_count = candidate_counts.get(key, 0)
        new_codes = sorted(candidate_codes - baseline_codes)
        candidate_escalates = bool(candidate_route and candidate_route.get("escalate"))
        strictly_improved = (
            candidate_count < baseline_count
            and not new_codes
            and not candidate_escalates
        )
        comparison = {
            "benchmark_id": key[0],
            "case_id": key[1],
            "baseline_failure_record_count": baseline_count,
            "candidate_failure_record_count": candidate_count,
            "baseline_failure_codes": sorted(baseline_codes),
            "candidate_failure_codes": sorted(candidate_codes),
            "new_failure_codes": new_codes,
            "candidate_escalates": candidate_escalates,
            "strictly_improved": strictly_improved,
        }
        comparisons.append(comparison)
        if strictly_improved:
            validate_accepted_decision(comparison)
            accepted.append(comparison)
            # A quality retry may remove only part of a case's official
            # failures. Keep the improved candidate, but continue routing its
            # remaining failures to the alternate-model stage.
            if candidate_count > 0 and candidate_route is not None:
                route = dict(candidate_route)
                route["selected_source"] = "quality_candidate"
                persistent.append(route)
            continue
        # Rejected quality candidates are reverted to the baseline artifact,
        # so their recovery route must also come from the baseline evaluation.
        route = dict(baseline_route)
        route["selected_source"] = "baseline"
        persistent.append(route)
        if candidate_count > baseline_count or new_codes or candidate_escalates:
            regressions.append(comparison)

    payload = {
        "schema": "folynta.public-core-official-failure-comparison.v1",
        "baseline_failure_records_sha256": _sha256(baseline_path),
        "candidate_failure_records_sha256": _sha256(candidate_path),
        "policy": {
            "require_strict_failure_record_reduction": True,
            "forbid_new_failure_codes": True,
            "forbid_candidate_escalation": True,
            "unchanged_candidates_are_not_accepted": True,
        },
        "compared_recoverable_case_count": len(comparisons),
        "accepted_quality_case_count": len(accepted),
        "persistent_case_count": len(persistent),
        "regressed_candidate_case_count": len(regressions),
        "accepted_quality_cases": accepted,
        "persistent_routes": persistent,
        "routes": persistent,
        "regressions": regressions,
        "comparisons": comparisons,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**payload, "output_sha256": _sha256(output_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare_failure_records(
        baseline_path=args.baseline.resolve(),
        candidate_path=args.candidate.resolve(),
        output_path=args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "accepted_quality_case_count": result["accepted_quality_case_count"],
                "persistent_case_count": result["persistent_case_count"],
                "regressed_candidate_case_count": result[
                    "regressed_candidate_case_count"
                ],
                "output_sha256": result["output_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["compare_failure_records", "validate_accepted_decision"]
