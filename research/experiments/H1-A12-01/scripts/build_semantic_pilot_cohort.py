"""Freeze a minimal semantic-recovery pilot cohort from public failure routes.

Selection uses only route metadata and public failure codes. Ground truth and
reference answers are not copied into the cohort; they stay local to later
scoring. This script does not execute a model or recovery arm.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GENERATED = ROOT / "benchmark/reports/generated"
OUTPUT = (
    ROOT
    / "research/experiments/H1-A12-01/cohorts/semantic-divergence-pilot-v1.json"
)

STRATA = ("R01", "B01", "N01", "F01", "G01", "H01")
PER_STRATUM = 8


def _source_file() -> Path:
    candidates = [path for path in GENERATED.glob("*.json") if path.is_file()]
    if not candidates:
        raise RuntimeError("no generated public failure-record JSON found")
    source = max(candidates, key=lambda path: path.stat().st_size)
    data = json.loads(source.read_text(encoding="utf-8"))
    required = {"records", "routes", "escalations", "schema"}
    if not required.issubset(data):
        raise RuntimeError("largest generated JSON is not the public failure-record pack")
    return source


def build() -> dict[str, object]:
    source = _source_file()
    data = json.loads(source.read_text(encoding="utf-8"))
    routes = data["routes"]
    if not isinstance(routes, list):
        raise RuntimeError("public failure routes must be a list")

    selected: list[dict[str, object]] = []
    used_case_ids: set[str] = set()
    counts: dict[str, int] = {}
    available: dict[str, int] = {}

    for code in STRATA:
        eligible = [
            route
            for route in routes
            if isinstance(route, dict)
            and route.get("request_recovery") is True
            and code in (route.get("failure_codes") or [])
            and len(route.get("candidate_models") or []) >= 2
            and str(route.get("case_id")) not in used_case_ids
        ]
        eligible.sort(
            key=lambda route: (
                str(route.get("benchmark_id", "")),
                str(route.get("case_id", "")),
            )
        )
        available[code] = len(eligible)
        chosen = eligible[:PER_STRATUM]
        if len(chosen) != PER_STRATUM:
            raise RuntimeError(
                f"stratum {code} has {len(chosen)} eligible cases; "
                f"requires {PER_STRATUM}"
            )
        counts[code] = len(chosen)
        for route in chosen:
            case_id = str(route["case_id"])
            used_case_ids.add(case_id)
            selected.append(
                {
                    "stratum": code,
                    "benchmark_id": route.get("benchmark_id"),
                    "case_id": case_id,
                    "failure_codes": list(route.get("failure_codes") or []),
                    "candidate_models": list(route.get("candidate_models") or []),
                    "minimum_scope_level": route.get("minimum_scope_level"),
                    "scope_ids": list(route.get("scope_ids") or []),
                }
            )

    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "schema": "tavonel.h1-a12-semantic-pilot-cohort.v1",
        "experiment_id": "H1-A12-01",
        "status": "FROZEN_SELECTION_NOT_EXECUTED",
        "source_failure_record_sha256": source_sha,
        "source_failure_record_bytes": source.stat().st_size,
        "selection": {
            "strata": list(STRATA),
            "per_stratum": PER_STRATUM,
            "requires_request_recovery": True,
            "requires_at_least_two_candidate_models": True,
            "stable_order": "benchmark_id,case_id",
            "ground_truth_included": False,
        },
        "eligible_counts_before_selection": available,
        "counts_by_stratum": counts,
        "case_count": len(selected),
        "cases": selected,
        "claim_boundary": (
            "Cohort selection only; no recovery arm has been executed and no "
            "quality/cost conclusion is allowed."
        ),
    }


def main() -> int:
    result = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CASE_COUNT={result['case_count']}")
    print(f"OUTPUT_SHA256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
