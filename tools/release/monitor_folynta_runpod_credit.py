#!/usr/bin/env python3
"""Record RunPod credit and campaign spend without invoking an LLM."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

RUNPOD_GRAPHQL = "https://api.runpod.io/graphql"
STOP_TERMINAL = (
    "benchmark/reports/generated/folynta-phase-cost-cleanup-2026-08-05/"
    "terminal-receipt.json"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def read_runpod_key(path: Path) -> str:
    pattern = re.compile(r"^\s*Runpod\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line)
        if match and len(match.group(1).strip()) >= 20:
            return match.group(1).strip()
    raise RuntimeError("RunPod credential is missing or malformed")


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def query_credit(api_key: str) -> dict[str, Any]:
    query = """
query FOLYNTACreditMonitor {
  myself {
    clientBalance
    currentSpendPerHr
    pods { id name desiredStatus costPerHr }
  }
}
"""
    response = httpx.post(
        RUNPOD_GRAPHQL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "folynta-credit-monitor/1.0",
        },
        json={"query": query},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("RunPod GraphQL returned errors")
    myself = payload["data"]["myself"]
    balance = float(myself["clientBalance"])
    spend = float(myself["currentSpendPerHr"])
    pods = [
        {
            "pod_id": str(item["id"]),
            "name": str(item["name"]),
            "desired_status": str(item["desiredStatus"]),
            "cost_per_hour_usd": float(item["costPerHr"]),
        }
        for item in myself["pods"]
        if str(item["name"]).startswith("folynta-")
    ]
    return {
        "schema": "folynta.runpod-credit-monitor-snapshot.v1",
        "observed_at_utc": utc_now(),
        "client_balance_usd": round(balance, 6),
        "current_spend_per_hour_usd": round(spend, 6),
        "credit_exhaustion_hours_at_current_rate": (
            round(balance / spend, 6) if spend > 0 else None
        ),
        "campaign_running_pod_count": sum(
            item["desired_status"] == "RUNNING" for item in pods
        ),
        "campaign_pods": pods,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--deadline-utc", required=True)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--reserve-usd", type=float, default=15.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 60 <= args.poll_seconds <= 1800:
        raise ValueError("poll-seconds must be between 60 and 1800")
    if args.reserve_usd <= 0:
        raise ValueError("reserve-usd must be positive")
    deadline = datetime.fromisoformat(args.deadline_utc.replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        raise ValueError("deadline-utc must include a timezone")

    repository = args.repository_root.resolve()
    output_root = args.output_root.resolve()
    generated = (repository / "benchmark/reports/generated").resolve()
    if generated not in output_root.parents:
        raise ValueError("output-root must stay under benchmark/reports/generated")
    progress = output_root / "credit-snapshots.jsonl"
    terminal = output_root / "terminal-receipt.json"
    reserve_breach = output_root / "reserve-breach.json"
    stop_terminal = repository / STOP_TERMINAL
    api_key = read_runpod_key(args.credential_file.resolve())

    append_jsonl(
        progress,
        {
            "event": "credit_monitor_started",
            "observed_at_utc": utc_now(),
            "poll_seconds": args.poll_seconds,
            "reserve_usd": args.reserve_usd,
        },
    )
    latest: dict[str, Any] | None = None
    while datetime.now(UTC) < deadline.astimezone(UTC):
        try:
            latest = query_credit(api_key)
            append_jsonl(progress, latest)
            if float(latest["client_balance_usd"]) < args.reserve_usd:
                breach = {
                    "schema": "folynta.runpod-credit-reserve-breach.v1",
                    "status": "operator_attention_required",
                    "reserve_usd": args.reserve_usd,
                    "snapshot": latest,
                }
                reserve_breach.write_text(
                    json.dumps(breach, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if stop_terminal.exists():
                result = {
                    "schema": "folynta.runpod-credit-monitor-terminal.v1",
                    "status": "phase_cost_cleanup_terminal_observed",
                    "phase_cost_cleanup_terminal": str(stop_terminal),
                    "latest_snapshot": latest,
                    "completed_at_utc": utc_now(),
                }
                terminal.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return 0
        except Exception as exc:
            append_jsonl(
                progress,
                {
                    "event": "credit_monitor_error",
                    "observed_at_utc": utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )
        time.sleep(args.poll_seconds)

    result = {
        "schema": "folynta.runpod-credit-monitor-terminal.v1",
        "status": "deadline_reached",
        "latest_snapshot": latest,
        "completed_at_utc": utc_now(),
    }
    terminal.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
