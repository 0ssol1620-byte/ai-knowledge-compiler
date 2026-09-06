#!/usr/bin/env python3
"""Measure the catalogue's own vocabulary, before any eligibility rule is applied.

SFIR7's eligibility predicates were declared while SFIR6 was still blind, which
is what makes them outcome-independent. They were also declared without having
seen the catalogue -- so they name values in *SPDX's* vocabulary and *our*
casing, and the catalogue writes its own.

That gap is dangerous in one specific way. A predicate value the catalogue never
uses matches nothing, and a filter that is unconditionally false for one value
silently narrows the universe to the values that happen to spell correctly.
Nothing downstream can see it: the roster is smaller and every row in it is real.
It is INC-V2-106's shape applied to a filter instead of a request.

So the vocabulary is measured first, and reported, and only then is the
predicate's *spelling* reconciled against it. What is eligible does not change --
the same ten licence families, the same host, the same dates. Only the strings
change, and only to the ones the publisher actually wrote.

**This pass computes no capacity number.** It counts rows and tallies field
values. It applies no eligibility, performs no ranking, and selects nothing, so
it cannot be a way of discovering which predicate spelling yields a bigger
roster.
"""

from __future__ import annotations

import argparse
import csv
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

SCHEMA = "tavonel.sfir7.catalog_vocabulary.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

#: Fields whose complete value set is small enough to record in full.
ENUMERATED_FIELDS = ("Host Type", "Status", "Fork")

#: Licence is long-tailed; the full tally is kept but only the head is printed.
LICENSE_FIELD = "License"

FIELD_SIZE_LIMIT = 64 * 1024 * 1024


def measure(path: Path, *, progress_rows: int = 2_000_000) -> dict[str, Any]:
    csv.field_size_limit(FIELD_SIZE_LIMIT)
    tallies: dict[str, Counter[str]] = {field: Counter() for field in ENUMERATED_FIELDS}
    licenses: Counter[str] = Counter()
    rows = 0
    short_rows = 0
    started = time.monotonic()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = {name: position for position, name in enumerate(header)}
        needed = [*ENUMERATED_FIELDS, LICENSE_FIELD]
        missing = [name for name in needed if name not in index]
        if missing:
            raise SystemExit(f"catalogue header lacks {missing!r}")
        highest = max(index[name] for name in needed)
        for row in reader:
            rows += 1
            if len(row) <= highest:
                short_rows += 1
                continue
            for field in ENUMERATED_FIELDS:
                tallies[field][row[index[field]].strip()] += 1
            licenses[row[index[LICENSE_FIELD]].strip()] += 1
            if rows % progress_rows == 0:
                print(f"    {rows:,} rows in {time.monotonic() - started:.0f}s", flush=True)
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "catalog_member": path.name,
        "rows_total": rows,
        "short_rows": short_rows,
        "enumerated": {
            field: dict(sorted(tallies[field].items(), key=lambda kv: (-kv[1], kv[0])))
            for field in ENUMERATED_FIELDS
        },
        "license_distinct_values": len(licenses),
        "license_tally": dict(sorted(licenses.items(), key=lambda kv: (-kv[1], kv[0]))),
        "eligibility_applied": False,
        "ranking_applied": False,
        "roots_selected": 0,
        "capacity_number_computed": False,
        "why_this_runs_before_the_rule": (
            "a predicate value the catalogue never uses matches nothing, and a filter that "
            "is unconditionally false for one value silently narrows the universe to the "
            "values that happen to spell correctly. Measuring the vocabulary first makes "
            "that visible instead of invisible."
        ),
        "what_may_change_after_this": (
            "the SPELLING of a declared predicate value, reconciled to the publisher's own "
            "vocabulary. Not which licences are eligible, not the host, not the dates, not "
            "N. The set of licence families stays exactly as declared."
        ),
        "wall_clock_seconds": round(time.monotonic() - started, 3),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    body = measure(args.catalog)
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
    head = list(body["license_tally"].items())[:25]
    summary = {"rows": body["rows_total"], "hosts": body["enumerated"]["Host Type"]}
    print(json.dumps(summary, indent=1))
    print("licence head:", json.dumps(head, indent=1))
    print("receipt:", args.receipt.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
