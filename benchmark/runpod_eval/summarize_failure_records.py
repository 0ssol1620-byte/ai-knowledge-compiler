#!/usr/bin/env python3
"""Emit the scalar summary of a public-benchmark failure-record file.

The public-core record file reaches ~77 MB for 5,132 cases and 43,394 official
evaluator decisions. PowerShell's ``ConvertFrom-Json`` materialises one
``PSCustomObject`` per node, so the release controllers spent tens of minutes
and about a gigabyte of working set just to recover two integers and a route
count. This reads the file once and prints only the scalars the controllers
consume, so they can parse a few hundred bytes instead.

The counts are recomputed from the arrays rather than trusted, so a truncated
or hand-edited record file fails here instead of silently steering a controller.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records")
    routes = payload.get("routes")
    escalations = payload.get("escalations")
    if not isinstance(records, list) or not isinstance(routes, list):
        raise ValueError("failure record file must carry records and routes arrays")
    declared = int(payload.get("record_count", -1))
    if declared != len(records):
        raise ValueError(
            f"record_count disagrees with records: {declared} vs {len(records)}"
        )

    recovery_routes = [
        route for route in routes if isinstance(route, dict) and route.get("request_recovery")
    ]
    route_counts: dict[str, int] = {}
    for route in recovery_routes:
        for model in route.get("candidate_models") or []:
            route_counts[str(model)] = route_counts.get(str(model), 0) + 1

    recoverable = {
        str(route.get("case_id")) for route in recovery_routes if route.get("case_id")
    }
    declared_recoverable = int(payload.get("recoverable_case_count", -1))
    if declared_recoverable != len(recoverable):
        raise ValueError(
            "recoverable_case_count disagrees with routes: "
            f"{declared_recoverable} vs {len(recoverable)}"
        )

    return {
        "schema": "folynta.public-failure-record-summary.v1",
        "record_count": declared,
        "recoverable_case_count": declared_recoverable,
        "nonrecoverable_case_count": int(payload.get("nonrecoverable_case_count", 0)),
        "escalation_count": len(escalations) if isinstance(escalations, list) else 0,
        "route_count": len(routes),
        "recovery_route_count": len(recovery_routes),
        "recovery_route_counts_by_model": dict(sorted(route_counts.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure-records", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.failure_records.read_text(encoding="utf-8"))
    print(json.dumps(summarize(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
