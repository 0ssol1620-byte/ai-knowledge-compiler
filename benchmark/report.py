"""Render a clearly labeled Markdown benchmark report from score JSONL."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def average(records: list[dict[str, Any]], metric: str) -> float | None:
    values = [
        record.get("metrics", {}).get(metric)
        for record in records
        if isinstance(record.get("metrics", {}).get(metric), (int, float))
    ]
    return statistics.fmean(values) if values else None


def display(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.4f}"


def render(records: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["provider"])].append(record)
    synthetic = bool(records) and all(record.get("is_synthetic") for record in records)
    lines = [
        "# AKC Benchmark Report",
        "",
        "> CONTRACT TEST ONLY — NOT A QUALITY CLAIM OR MODEL-PROMOTION RESULT."
        if synthetic
        else (
            "> INTERNAL RESULT — verify corpus rights, environment, and approvals "
            "before publication."
        ),
        "",
        (
            "| Provider | Cases | CER | Numeric exact | Order | Provenance | "
            "Unsupported | Hard failures |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in sorted(grouped):
        provider_records = grouped[provider]
        failures = sum(bool(record.get("hard_failures")) for record in provider_records)
        lines.append(
            (
                "| {provider} | {count} | {cer} | {numeric} | {order} | "
                "{provenance} | {unsupported} | {failures} |"
            ).format(
                provider=provider,
                count=len(provider_records),
                cer=display(average(provider_records, "cer")),
                numeric=display(average(provider_records, "numeric_exact_match")),
                order=display(average(provider_records, "reading_order_pair_accuracy")),
                provenance=display(average(provider_records, "provenance_coverage")),
                unsupported=display(average(provider_records, "unsupported_claim_rate")),
                failures=failures,
            )
        )
    lines.extend(
        [
            "",
            "## Promotion blockers",
            "",
            (
                "- Structured table, formula, heading, and date/unit annotations "
                "must be present wherever those metrics apply; unavailable values "
                "cannot qualify a candidate."
            ),
            "- `table_teds` is AKC's documented deterministic surrogate, not official TEDS.",
            "- Exact model/container/hardware/runtime metadata is required.",
            "- Synthetic contract records are excluded from Pareto and champion decisions.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = load(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(records), encoding="utf-8", newline="\n")
    print(f"wrote report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
