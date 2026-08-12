#!/usr/bin/env python3
"""Reconcile what the campaign was asked to process against what it delivered.

The campaign plan names every case and the worker it was assigned to. The
collected prediction trees say which cases actually produced output, across the
baseline run and every operational recovery round that followed it. The gap
between the two is the honest unresolved count, and it is the number the
recovery claim rests on.

Two details make this reconciliation less trivial than a file count. The
baseline collection writes a zero-byte placeholder for every case its worker
never finished, so counting files overstates delivery by roughly 1,800. And a
case may appear in several recovery trees, so counting across trees without
deduplicating overstates it again. Both are handled here and asserted rather
than assumed.
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


def load_roster(plan: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Every case the campaign committed to processing, with its assignment."""
    roster: dict[tuple[str, str], dict[str, Any]] = {}
    for suite in plan["suites"]:
        benchmark_id = str(suite["benchmark_id"])
        for shard in suite["shards"]:
            for entry in shard["inputs"]:
                key = (benchmark_id, str(entry["case_id"]))
                if key in roster:
                    raise ValueError(f"case appears in two shards: {key[1]}")
                roster[key] = {
                    "benchmark_id": benchmark_id,
                    "case_id": str(entry["case_id"]),
                    "document_id": entry.get("document_id"),
                    "source_relative_path": entry.get("input_relative_path"),
                    "assigned_worker_index": shard["worker_index"],
                    "shard_id": shard["shard_id"],
                }
    declared = plan.get("total_input_count")
    if declared is not None and len(roster) != declared:
        raise ValueError(
            f"plan declares {declared} inputs but the shards enumerate {len(roster)}"
        )
    return roster


def _benchmark_of(case_id: str) -> str:
    for suite in ("omnidocbench", "parsebench", "olmocr-bench"):
        if case_id.startswith(suite):
            return suite
    raise ValueError(f"cannot attribute case to a benchmark: {case_id}")


def load_delivered(roots: list[Path]) -> dict[tuple[str, str], str]:
    """Cases with a non-empty prediction, credited to the earliest tree that had it.

    Roots are supplied baseline-first. Attribution keeps the *first* tree that
    delivered a case, because a case the baseline already produced was not saved
    by a later recovery round even when a recovery tree also happens to contain
    it. Crediting the later tree would overstate what recovery contributed.
    """
    delivered: dict[tuple[str, str], str] = {}
    for root in roots:
        for markdown in root.rglob("markdown-repeat-1/*.md"):
            if not markdown.read_text(encoding="utf-8", errors="replace").strip():
                # A placeholder for a case this worker never finished.
                continue
            key = (_benchmark_of(markdown.stem), markdown.stem)
            delivered.setdefault(key, root.name)
    return delivered


def load_retry_rounds(plans: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    """The cases each retry round was asked to rescue, in the order they ran."""
    rounds = []
    for label, path in plans:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        attempted = {
            (str(entry["benchmark_id"]), str(entry["case_id"]))
            for entry in payload["failures"]
        }
        declared = payload.get("failed_input_count")
        if declared is not None and len(attempted) != declared:
            raise ValueError(
                f"{label} declares {declared} failed inputs but enumerates {len(attempted)}"
            )
        rounds.append(
            {
                "label": label,
                "attempted": attempted,
                "plan_sha256": payload.get("receipt_sha256"),
            }
        )
    return rounds


def summarise_recovery(
    rounds: list[dict[str, Any]],
    delivered: dict[tuple[str, str], str],
    roster: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """How much of the population that actually needed rescuing was rescued.

    Delivery counted against the whole corpus answers 'did the campaign finish'.
    It does not answer 'when a case broke, did recovery save it', because the
    denominator there is only the cases that broke. That denominator is the
    retry plan, which names exactly the cases each round was asked to rescue.
    """
    per_round = []
    ever_attempted: set[tuple[str, str]] = set()
    for index, entry in enumerate(rounds, start=1):
        attempted = entry["attempted"]
        unknown = attempted - set(roster)
        if unknown:
            raise ValueError(
                f"{entry['label']} attempts {len(unknown)} cases absent from the plan"
            )
        recovered = {case for case in attempted if case in delivered}
        ever_attempted |= attempted
        per_round.append(
            {
                "round": index,
                "label": entry["label"],
                "cases_attempted": len(attempted),
                "cases_recovered": len(recovered),
                "cases_still_missing": len(attempted - recovered),
                "recovery_rate": len(recovered) / len(attempted) if attempted else 0.0,
                "plan_sha256": entry["plan_sha256"],
            }
        )

    recovered_overall = {case for case in ever_attempted if case in delivered}
    still_missing = sorted(ever_attempted - recovered_overall)
    unresolved = set(roster) - set(delivered)
    never_attempted = sorted(unresolved - ever_attempted)

    needed_more_than_one_round = 0
    if len(rounds) > 1:
        first = rounds[0]["attempted"]
        later: set[tuple[str, str]] = set()
        for entry in rounds[1:]:
            later |= entry["attempted"]
        needed_more_than_one_round = len(first & later)

    return {
        "cases_that_needed_recovery": len(ever_attempted),
        "cases_recovered": len(recovered_overall),
        "recovery_rate_on_cases_that_needed_it": (
            len(recovered_overall) / len(ever_attempted) if ever_attempted else 0.0
        ),
        "cases_attempted_but_never_recovered": len(still_missing),
        "cases_unresolved_and_never_attempted": len(never_attempted),
        "cases_requiring_more_than_one_round": needed_more_than_one_round,
        "per_round": per_round,
        "attempted_but_never_recovered_detail": [roster[case] for case in still_missing],
        "unresolved_and_never_attempted_detail": [roster[case] for case in never_attempted],
        "denominator_note": (
            "The denominator is the retry plan, not the corpus. It counts only cases a "
            "round was asked to rescue, so the rate describes recovery effectiveness on "
            "broken cases rather than campaign completion."
        ),
    }


def build_ledger(
    roster: dict[tuple[str, str], dict[str, Any]],
    delivered: dict[tuple[str, str], str],
    *,
    baseline_root_name: str,
    retry_rounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    unknown = sorted(set(delivered) - set(roster))
    if unknown:
        raise ValueError(
            f"{len(unknown)} delivered cases are absent from the campaign plan, "
            f"first: {unknown[0][1]}"
        )

    resolved = sorted(set(roster) & set(delivered))
    unresolved = sorted(set(roster) - set(delivered))

    by_suite: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"planned": 0, "resolved": 0, "unresolved": 0}
    )
    for benchmark_id, _ in roster:
        by_suite[benchmark_id]["planned"] += 1
    for benchmark_id, _ in resolved:
        by_suite[benchmark_id]["resolved"] += 1
    for benchmark_id, _ in unresolved:
        by_suite[benchmark_id]["unresolved"] += 1

    provenance = collections.Counter(delivered[key] for key in resolved)
    baseline_delivered = provenance.get(baseline_root_name, 0)
    recovered = len(resolved) - baseline_delivered

    recovery = (
        summarise_recovery(retry_rounds, delivered, roster) if retry_rounds else None
    )

    return {
        "planned_cases": len(roster),
        "resolved_cases": len(resolved),
        "recovery_outcome": recovery,
        "unresolved_cases": len(unresolved),
        "completion_fraction": len(resolved) / len(roster) if roster else 0.0,
        "delivered_by_baseline_run": baseline_delivered,
        "delivered_by_operational_recovery": recovered,
        "recovery_share_of_corpus": recovered / len(roster) if roster else 0.0,
        "cases_by_suite": {k: dict(v) for k, v in sorted(by_suite.items())},
        "delivered_by_tree": dict(sorted(provenance.items())),
        "unresolved_case_detail": [roster[key] for key in unresolved],
        "counterfactual": (
            f"Without the operational recovery lane, {recovered} of {len(roster)} cases "
            "would carry no output at all. Those documents would be absent from the "
            "corpus rather than merely lower quality."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-plan", required=True, type=Path)
    parser.add_argument("--baseline-root", required=True, type=Path)
    parser.add_argument("--recovery-root", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--retry-plan",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="retry plan receipt naming the cases a round was asked to rescue, "
        "supplied in the order the rounds ran",
    )
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def parse_retry_plan_args(values: list[str]) -> list[tuple[str, Path]]:
    plans = []
    for value in values:
        label, separator, path = value.partition("=")
        if not separator or not label or not path:
            raise ValueError(f"retry plan must be given as LABEL=PATH, got: {value}")
        plans.append((label, Path(path)))
    return plans


def main() -> int:
    args = parse_args()
    plan = json.loads(args.campaign_plan.read_text(encoding="utf-8-sig"))
    roster = load_roster(plan)
    delivered = load_delivered([args.baseline_root, *args.recovery_root])
    retry_rounds = load_retry_rounds(parse_retry_plan_args(args.retry_plan))
    ledger = build_ledger(
        roster,
        delivered,
        baseline_root_name=args.baseline_root.name,
        retry_rounds=retry_rounds,
    )

    receipt = {
        "schema": "folynta.campaign-completion-ledger.v1",
        "question": (
            "Of the cases the campaign committed to processing, how many produced "
            "output, and how many did the operational recovery lane save?"
        ),
        "method": [
            "Read the authoritative case roster from the campaign shard plan.",
            "Treat a case as delivered only when a non-empty prediction exists.",
            "Merge the baseline tree with every operational recovery tree, deduplicating cases.",
            "Report the residue as unresolved, itemised with its source path and assigned worker.",
            "Score each retry round against the cases it was asked to rescue, so recovery "
            "effectiveness is measured on broken cases rather than on the whole corpus.",
        ],
        "campaign_plan_sha256": plan.get("plan_sha256"),
        "prediction_roots": [str(args.baseline_root), *[str(p) for p in args.recovery_root]],
        "score_inflation_allowed": False,
        **ledger,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {k: v for k, v in receipt.items() if k not in {"method", "unresolved_case_detail"}}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
