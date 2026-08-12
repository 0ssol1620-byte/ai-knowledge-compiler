#!/usr/bin/env python3
"""Record an explicit, budget-bounded decision about which recovery lanes run.

The official evaluation of the 5,132-case public core routes 3,173 cases into a
MinerU quality retry and, behind it, 2,702 PaddleOCR-VL and 1,544
DeepSeek-OCR-2 alternate-recovery candidates. Executing all of them costs more
GPU time than the remaining RunPod balance covers, so the operator decides which
lanes run. That decision has to be evidence, not a silent omission: the release
controllers read this receipt, and the final report and patent index quote the
candidate counts alongside what was actually executed.

Nothing here scores, selects, or improves anything. It only records a scope
decision and the live provider balance that motivated it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx

GRAPHQL = "https://api.runpod.io/graphql"
BALANCE_QUERY = """
query FolyntaDecisionBalance {
  myself { clientBalance currentSpendPerHr }
}
"""


def load_runpod_key(credential_file: Path) -> str:
    for line in credential_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*Runpod\s*[=:]\s*(\S+)\s*$", line, re.IGNORECASE)
        if match:
            return match.group(1)
    raise SystemExit("Runpod key not found in credential file")


def read_balance(credential_file: Path) -> dict[str, float]:
    response = httpx.post(
        GRAPHQL,
        headers={
            "Authorization": f"Bearer {load_runpod_key(credential_file)}",
            "Accept": "application/json",
            "User-Agent": "folynta-execution-decision/1.0",
        },
        json={"query": BALANCE_QUERY},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("RunPod GraphQL returned errors")
    myself = payload["data"]["myself"]
    return {
        "client_balance_usd": float(myself["clientBalance"]),
        "current_spend_per_hour_usd": float(myself["currentSpendPerHr"]),
    }


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_decision(
    *,
    failure_summary: dict[str, Any],
    balance: dict[str, float],
    execute_quality_retry: bool,
    execute_alternate_recovery: bool,
    execute_stratified_audit: bool,
    reason: str,
    decided_by: str,
) -> dict[str, Any]:
    route_counts = failure_summary.get("recovery_route_counts_by_model", {})
    decision: dict[str, Any] = {
        "schema": "folynta.recovery-execution-decision.v1",
        "decided_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "decided_by": decided_by,
        "reason": reason,
        "execute_mineru_quality_retry": execute_quality_retry,
        "execute_post_selection_alternate_recovery": execute_alternate_recovery,
        "execute_stratified_audit": execute_stratified_audit,
        "provider_balance_at_decision": balance,
        "candidate_scope": {
            "official_failure_record_count": int(failure_summary["record_count"]),
            "mineru_quality_retry_case_count": int(
                failure_summary["recoverable_case_count"]
            ),
            "alternate_recovery_route_case_counts_by_model": {
                str(model): int(count) for model, count in sorted(route_counts.items())
            },
        },
        "coverage_statement": (
            "Reported accuracy is the complete official evaluation of all 5,132 "
            "public-core cases produced by MinerU 3.4.4-VLM after operational "
            "recovery. Lanes recorded as not executed contribute no measured "
            "improvement and no improvement from them is claimed."
        ),
        "score_inflation_allowed": False,
    }
    decision["decision_sha256"] = canonical_hash(decision)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failure-summary", required=True, type=Path)
    parser.add_argument("--credential-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--decided-by", default="operator")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--execute-quality-retry", action="store_true")
    parser.add_argument("--execute-alternate-recovery", action="store_true")
    parser.add_argument("--no-stratified-audit", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"execution decision already recorded: {args.output}")
    failure_summary = json.loads(args.failure_summary.read_text(encoding="utf-8"))
    if failure_summary.get("schema") != "folynta.public-failure-record-summary.v1":
        raise ValueError("failure summary schema is invalid")
    decision = build_decision(
        failure_summary=failure_summary,
        balance=read_balance(args.credential_file.resolve()),
        execute_quality_retry=bool(args.execute_quality_retry),
        execute_alternate_recovery=bool(args.execute_alternate_recovery),
        execute_stratified_audit=not args.no_stratified_audit,
        reason=args.reason,
        decided_by=args.decided_by,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
