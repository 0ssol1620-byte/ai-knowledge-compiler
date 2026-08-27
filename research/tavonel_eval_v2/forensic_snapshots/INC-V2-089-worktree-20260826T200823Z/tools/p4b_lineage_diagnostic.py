#!/usr/bin/env python3
"""Why G_P4B_B_LINEAGE failed. A diagnostic, not a re-score.

**This does not change the P4b verdict.** P4b is FAIL and stays FAIL. The gate
was frozen over `pair_id` and is evaluated over `pair_id`; nothing here is
substituted for it, and no threshold is touched.

What this measures is whether the cohort could have satisfied that gate at all.
The P4b question construction may draw on title, document type, heading and
parent heading. If two lineages are identical in every one of those fields, no
question the protocol permits can route between them, and the gate is testing
the corpus rather than the method.

The output is the material P4c needs to build a cohort that can be measured.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=NS / "receipts" / "p0b-corpus-manifest.json"
    )
    parser.add_argument(
        "--p4b",
        type=Path,
        default=NS / "receipts" / "latest" / "p4b-retrieval-validity.json",
    )
    args = parser.parse_args()

    pointer = json.loads(args.p4b.read_text(encoding="utf-8"))
    result = json.loads((NS.parents[1] / pointer["points_to"]).read_text(encoding="utf-8"))
    corpus = json.loads(args.manifest.read_text(encoding="utf-8"))
    natural = [pair for pair in corpus["pairs"] if pair["group"] == "natural"]

    by_source: Counter[str] = Counter(pair["source_id"] for pair in natural)
    collisions = {source: count for source, count in sorted(by_source.items()) if count > 1}
    pairs_sharing = sum(count for count in collisions.values())

    rows = [row for row in result["stage_B_rows"] if row.get("state") == "SCORED"]
    pair_to_source = {pair["pair_id"]: pair["source_id"] for pair in natural}

    # The same measure the gate takes, at document granularity instead of
    # revision-pair granularity. Reported as a diagnostic; NOT the gate.
    at_source = 0
    for row in rows:
        wanted = pair_to_source.get(row["pair_id"])
        units = row.get("top_units") or []
        if units and all(pair_to_source.get(unit.split("|", 1)[0]) == wanted for unit in units):
            at_source += 1
    source_level = at_source / len(rows) if rows else 0.0

    body = {
        "schema": "tavonel.v2.p4b_lineage_diagnostic.v1",
        "is_a_gate_result": False,
        "changes_the_p4b_verdict": False,
        "p4b_verdict": result["verdict"],
        "p4b_receipt": pointer["points_to"],
        "p4b_receipt_file_sha256": pointer["points_to_file_sha256"],
        "question": (
            "could this cohort have satisfied G_P4B_B_LINEAGE under any question "
            "the protocol permits?"
        ),
        "cohort_shape": {
            "natural_pairs": len(natural),
            "distinct_source_documents": len(by_source),
            "pairs_sharing_a_source_document_with_another_pair": pairs_sharing,
            "source_documents_with_more_than_one_pair": collisions,
        },
        "finding": (
            "the gate is defined over pair_id, and %d of %d natural pairs share "
            "their source document with at least one other pair. Two revision "
            "pairs of the same document are identical in title, document type, "
            "heading path and heading, so no question drawing only on those "
            "fields can route between them. The gate was measuring a distinction "
            "the permitted question construction cannot express." % (pairs_sharing, len(natural))
        ),
        "diagnostic_measures": {
            "gate_as_frozen_lineage_at_1_over_pair_id": result["stage_B_measures"][
                "lineage_at_1_B"
            ],
            "same_measure_over_source_document": source_level,
            "warning": (
                "the second number is NOT the gate and does not replace it. It is "
                "reported so P4c knows whether the routing failure is in the "
                "method or in the cohort's granularity."
            ),
        },
        "what_p4c_needs": [
            "a lineage granularity the permitted fields can address — one pair "
            "per source document, or a title field that carries the revision "
            "window",
            "sec_edgar titles that distinguish two filings of the same form by "
            "the same issuer; ticker and CIK alone do not",
            "a fresh cohort and a fresh protocol; this one is spent",
        ],
        "not_claimed": (
            "that the method routes adequately. Routing was not demonstrated on "
            "this cohort, and this diagnostic does not demonstrate it either."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable("p4b-lineage-diagnostic", body, tool=Path(__file__).resolve())
    print(
        json.dumps(
            {
                "distinct_source_documents": len(by_source),
                "pairs_sharing_a_document": pairs_sharing,
                "gate_value": result["stage_B_measures"]["lineage_at_1_B"],
                "diagnostic_source_level": round(source_level, 4),
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
