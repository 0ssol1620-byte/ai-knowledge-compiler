#!/usr/bin/env python3
"""Classify live public-core workers before cross-Pod operational retry."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")


@dataclass(frozen=True, slots=True)
class WorkerResult:
    worker_index: int
    result_root: Path


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_lines(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        return ()
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"non-object JSONL record at {path}:{line_number}")
        records.append(payload)
    return tuple(records)


def classify_workers(
    *, worker_results: tuple[WorkerResult, ...], output_path: Path
) -> dict[str, Any]:
    workers = sorted(worker_results, key=lambda value: value.worker_index)
    if [worker.worker_index for worker in workers] != [0, 1, 2, 3]:
        raise ValueError("exactly worker indices 0, 1, 2, and 3 are required")

    classifications: list[dict[str, Any]] = []
    for worker in workers:
        failed_case_count = 0
        failing_suites: list[str] = []
        suite_details: list[dict[str, Any]] = []
        for suite in SUITES:
            summary_path = worker.result_root / suite / "run-summary.json"
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            runs = payload.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"unexpected baseline summary: {summary_path}")
            completed = int(runs[0]["completed"])
            failed = int(runs[0]["failed"])
            input_count = int(payload["input_count"])
            if completed + failed != input_count:
                raise ValueError(f"incomplete accounting in {summary_path}")
            if failed:
                failing_suites.append(suite)
                failed_case_count += failed
            suite_details.append(
                {
                    "benchmark_id": suite,
                    "input_count": input_count,
                    "completed": completed,
                    "failed": failed,
                    "return_code": int(runs[0].get("return_code", 0)),
                }
            )

        watchdog_events = tuple(
            item
            for item in _json_lines(worker.result_root / "stall-watchdog.jsonl")
            if item.get("event") == "suite_stall_detected"
        )
        stall_suites = sorted({str(item.get("suite", "")) for item in watchdog_events})
        quarantine_reasons: list[str] = []
        if len(watchdog_events) >= 2:
            quarantine_reasons.append("repeated_suite_stall")
        if quarantine_reasons:
            state = "QUARANTINED"
        elif failed_case_count or watchdog_events:
            state = "DEGRADED"
        else:
            state = "HEALTHY"
        classifications.append(
            {
                "worker_index": worker.worker_index,
                "state": state,
                "retry_eligible": state != "QUARANTINED",
                "failed_case_count": failed_case_count,
                "failing_suite_count": len(failing_suites),
                "failing_suites": failing_suites,
                "stall_event_count": len(watchdog_events),
                "stall_suites": stall_suites,
                "quarantine_reasons": quarantine_reasons,
                "suites": suite_details,
            }
        )

    eligible = [
        int(item["worker_index"])
        for item in classifications
        if bool(item["retry_eligible"])
    ]
    quarantined = [
        int(item["worker_index"])
        for item in classifications
        if not bool(item["retry_eligible"])
    ]
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-operational-worker-health.v1",
        "classification_policy": {
            "quarantine_on_stall_events_gte": 2,
            "multi_suite_case_failures_alone_quarantine": False,
            "multi_suite_case_failures_state": "DEGRADED",
            "single_operational_failure_state": "DEGRADED",
            "quarantined_workers_retry_eligible": False,
        },
        "workers": classifications,
        "eligible_retry_workers": eligible,
        "quarantined_worker_indices": quarantined,
        "replacement_required": len(eligible) < 2,
        "replacement_scope": (
            "frozen_primary_pool_only; separately validated expansion workers are "
            "not inputs to this classifier"
        ),
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def _worker_result(value: str) -> WorkerResult:
    try:
        index, path = value.split("=", 1)
        return WorkerResult(int(index), Path(path))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("worker result must be INDEX=PATH") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-result", action="append", type=_worker_result, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = classify_workers(
        worker_results=tuple(args.worker_result), output_path=args.output.resolve()
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 2 if receipt["replacement_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkerResult", "classify_workers"]
