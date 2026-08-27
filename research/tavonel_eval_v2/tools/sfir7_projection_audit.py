#!/usr/bin/env python3
"""Audit the parser and projection over the whole snapshot, before any selection.

This is a one-way gate. It runs the real parser and the real projection over all
37.7 million catalogue rows and reports aggregates only: how many rows parsed,
how many were rejected and why, how many could not be projected and why, whether
the catalogue's own identifiers are unique, and whether the declared licence
vocabulary is actually present.

**It computes no capacity or yield quantity.** It applies no eligibility
predicate, performs no ranking and selects nothing. That is the point of running
it first: projection correctness has to be established on its own terms, before
any number exists that could make a particular answer look preferable.

The one aggregate deliberately absent is "how many rows would be eligible". That
is a yield figure, it is one step from a capacity expectation, and knowing it
before the rule runs is exactly the contamination the whole design avoids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_catalog_parser as parser  # noqa: E402
import sfir7_frame as frame  # noqa: E402
import sfir7_projection as projection  # noqa: E402

SCHEMA = "tavonel.sfir7.projection_audit.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"


def audit(catalog: Path, *, progress_rows: int = 2_000_000) -> dict[str, Any]:
    started = time.monotonic()
    rejected: Counter[str] = Counter()
    refused: Counter[str] = Counter()
    licence_seen: Counter[str] = Counter()
    host_seen: Counter[str] = Counter()

    rows = 0
    parsed = 0
    projected = 0
    record_ids_seen: set[str] = set()
    record_id_duplicates: set[str] = set()
    uuids_seen: set[str] = set()
    uuid_duplicates: set[str] = set()
    blank_uuids = 0
    record_id_monotonic = True
    previous_numeric_id = -1

    for record, reason in parser.stream_records(catalog):
        rows += 1
        if rows % progress_rows == 0:
            print(f"    {rows:,} rows in {time.monotonic() - started:.0f}s", flush=True)
        if record is None:
            rejected[reason] += 1
            continue
        parsed += 1

        if record.record_id in record_ids_seen:
            record_id_duplicates.add(record.record_id)
        else:
            record_ids_seen.add(record.record_id)
        if record_id_monotonic:
            if record.record_id.isdigit():
                numeric = int(record.record_id)
                if numeric <= previous_numeric_id:
                    record_id_monotonic = False
                previous_numeric_id = numeric
            else:
                record_id_monotonic = False

        if not record.host_uuid:
            blank_uuids += 1
        elif record.host_uuid in uuids_seen:
            uuid_duplicates.add(record.host_uuid)
        else:
            uuids_seen.add(record.host_uuid)

        host_seen[record.host] += 1
        licence_seen[record.spdx_license_id] += 1

        try:
            projection.project(record)
        except projection.ProjectionRefused as error:
            refused[_refusal_kind(str(error))] += 1
            continue
        projected += 1

    declared = _declared_licences()
    folded = {name.casefold(): count for name, count in licence_seen.items()}
    coverage = {}
    for value in declared:
        spellings = frame.catalog_spellings(value)
        coverage[value] = {
            "spellings_used": list(spellings),
            "rows_present": sum(folded.get(s.casefold(), 0) for s in spellings),
        }

    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "catalog_member": catalog.name,
        "rows_read": rows,
        "rows_parsed": parsed,
        "rows_rejected_by_parser": sum(rejected.values()),
        "parser_rejection_reasons": dict(sorted(rejected.items())),
        "rows_projected": projected,
        "rows_projection_refused": sum(refused.values()),
        "projection_refusal_reasons": dict(sorted(refused.items())),
        "accounting_balances": rows == parsed + sum(rejected.values())
        and parsed == projected + sum(refused.values()),
        "record_id": {
            "distinct": len(record_ids_seen),
            "duplicates": len(record_id_duplicates),
            "duplicate_sample": sorted(record_id_duplicates)[:20],
            "strictly_increasing_integers": record_id_monotonic,
        },
        "host_uuid": {
            "distinct": len(uuids_seen),
            "blank": blank_uuids,
            "shared_by_more_than_one_row": len(uuid_duplicates),
            "shared_sample": sorted(uuid_duplicates)[:20],
            "what_a_shared_uuid_means": (
                "one host repository id appearing on more than one catalogue row. "
                "Across the whole catalogue that is expected -- the same repository "
                "can be indexed under several package entries. It only becomes an "
                "identity question once a roster is selected, which is where "
                "require_identity_coherence runs."
            ),
        },
        "hosts_present": dict(sorted(host_seen.items(), key=lambda kv: -kv[1])),
        "vocabulary_reconciliation_coverage": coverage,
        "every_declared_licence_is_present": all(
            entry["rows_present"] > 0 for entry in coverage.values()
        ),
        "eligibility_applied": False,
        "ranking_applied": False,
        "roots_selected": 0,
        "capacity_or_yield_computed": False,
        "why_no_yield_figure": (
            "how many rows would be eligible is a yield number, one step from a "
            "capacity expectation. Knowing it before the rule runs is the "
            "contamination this design exists to avoid."
        ),
        "wall_clock_seconds": round(time.monotonic() - started, 3),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _refusal_kind(message: str) -> str:
    for needle, kind in (
        ("not exactly owner/repo", "ADDRESS_NOT_OWNER_SLASH_REPO"),
        ("blank owner", "ADDRESS_BLANK_OWNER"),
        ("blank repository", "ADDRESS_BLANK_REPOSITORY"),
        ("not a non-empty string", "ADDRESS_EMPTY"),
        ("projection changed", "PROJECTION_CHANGED_A_VALUE"),
        ("does not reconstruct", "PROJECTION_ROUND_TRIP_FAILED"),
        ("reached the selection record", "PROVENANCE_FIELD_LEAKED_INTO_SELECTION"),
    ):
        if needle in message:
            return kind
    return "UNCLASSIFIED"


def _declared_licences() -> list[str]:
    rule = frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256="sha256:" + "0" * 64,
        snapshot_date_utc="2020-01-12",
    )
    return list(
        next(p.value for p in rule.predicates if p.field == "spdx_license_id")
    )


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--catalog", required=True, type=Path)
    argument_parser.add_argument("--receipt", required=True, type=Path)
    args = argument_parser.parse_args()

    body = audit(args.catalog)
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    verdict = (
        "PROJECTION_CORRECTNESS_PASS"
        if body["accounting_balances"] and body["every_declared_licence_is_present"]
        else "PROJECTION_CORRECTNESS_REFUSED"
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "rows_read": body["rows_read"],
                "rows_parsed": body["rows_parsed"],
                "rows_projected": body["rows_projected"],
                "parser_rejections": body["parser_rejection_reasons"],
                "projection_refusals": body["projection_refusal_reasons"],
                "record_id_duplicates": body["record_id"]["duplicates"],
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0 if verdict == "PROJECTION_CORRECTNESS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
