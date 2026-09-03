#!/usr/bin/env python3
"""Does corpus-v7 supply what PROTOCOL_V2 requires, class by class?

The v2 endpoint was reported NOT RUN for one reason: **0 revision-sensitive
questions** against a required 60. The Family B corpora were consecutive revision
pairs -- edits minutes apart -- and structured facts do not move in that window.
9 of 23 documents had parsable infoboxes and not one attribute changed.

corpus-v7 was acquired against that diagnosis: snapshots at 2023-06-30 and
2026-06-30, a minimum separation of 1,095 days, and a per-article cap of three
primary attributes selected by a frozen hash order rather than by outcome.

This checks class by class whether the corpus reaches each frozen minimum. It
**does not build the question set and does not run the endpoint.** Sufficiency is
a precondition, not a result; the three arms, the leakage metric and the McNemar
comparison are all downstream and untouched.

A class that reaches its minimum is `SUFFICIENT`. A class whose availability
cannot be determined from the acquisition receipt alone is `UNDETERMINED` -- never
`SUFFICIENT`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ACQ = EXP / "receipts" / "acquisition-v7-2026-08-19.json"
INTEGRITY = EXP / "receipts" / "v7-corpus-integrity-2026-08-19.json"

#: PROTOCOL_V2 section 1, frozen before any corpus existed.
MINIMUMS = {
    "simple_retrieval": 40,
    "revision_sensitive": 60,
    "conflicting_evidence": 30,
    "multi_document": 30,
    "provenance_sensitive": 40,
}
#: PROTOCOL_V2 also requires the primary class to spread across articles.
MIN_ARTICLES_WITH_PRIMARY = 20


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    acq = json.loads(ACQ.read_text(encoding="utf-8"))
    integrity = json.loads(INTEGRITY.read_text(encoding="utf-8"))

    if not integrity.get("all_gates_pass"):
        print("REFUSING: corpus integrity gates did not all pass")
        return 2

    records = acq.get("records", [])
    primary = acq.get("primary_revision_sensitive_retained", 0)
    articles = acq.get("articles_with_primary", 0)
    controls = acq.get("unchanged_controls", 0)

    classes = {
        "simple_retrieval": {
            "available": controls,
            "source": "unchanged infobox attributes -- the answer is the same in both revisions",
            "state": "SUFFICIENT" if controls >= MINIMUMS["simple_retrieval"] else "INSUFFICIENT",
        },
        "revision_sensitive": {
            "available": primary,
            "articles": articles,
            "source": ("changed infobox attributes retained under the frozen three-per-article "
                       "cap, selected by hash order fixed before any value was seen"),
            "state": (
                "SUFFICIENT"
                if primary >= MINIMUMS["revision_sensitive"]
                and articles >= MIN_ARTICLES_WITH_PRIMARY
                else "INSUFFICIENT"
            ),
        },
        "conflicting_evidence": {
            "available": None,
            "source": "requires two sources disagreeing on the same attribute",
            "state": "UNDETERMINED",
            "why": ("the acquisition records one article per title and does not pair articles "
                    "on a shared attribute, so real conflicts cannot be counted from this "
                    "receipt. PROTOCOL_V2 includes this class only if real conflicts exist."),
        },
        "multi_document": {
            "available": None,
            "source": "an answer requiring at least two source documents",
            "state": "UNDETERMINED",
            "why": ("the corpus is one article per title; whether any question genuinely "
                    "requires two of them is a property of the question set, which does not "
                    "exist yet"),
        },
        "provenance_sensitive": {
            "available": len(records),
            "source": "each eligible page carries an exact before/after revision id and hash",
            "state": ("SUFFICIENT" if len(records) >= MINIMUMS["provenance_sensitive"]
                      else "INSUFFICIENT"),
            "caveat": ("counts pages that can carry a provenance question, not questions built "
                       "and validated; the gold evidence location still has to be constructed"),
        },
    }

    primary_ok = classes["revision_sensitive"]["state"] == "SUFFICIENT"
    control_ok = classes["simple_retrieval"]["state"] == "SUFFICIENT"

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v7-endpoint-sufficiency.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "governing_protocol": "PROTOCOL_V2_2026-08-19.md section 1",
        "corpus": "corpus-v7",
        "corpus_root_sha256": integrity.get("corpus_root_sha256"),
        "integrity_gates_passed": integrity.get("gates_passed"),
        "frozen_minimums": MINIMUMS,
        "min_articles_with_primary": MIN_ARTICLES_WITH_PRIMARY,
        "classes": classes,
        "primary_endpoint_class_sufficient": primary_ok,
        "control_class_sufficient": control_ok,
        "what_changed_since_v2": (
            "v2 produced 0 revision-sensitive questions against a required 60, because the "
            "Family B corpora were consecutive revision pairs in which structured facts do "
            "not move. corpus-v7 uses snapshots 1,095+ days apart, which is the acquisition "
            "answer to that diagnosis rather than a looser parser."
        ),
        "endpoint_status": "NOT_RUN",
        "what_this_is_not": [
            "not a question set -- none has been built against corpus-v7",
            "not a leakage measurement -- section 3's overlap thresholds are unmeasured",
            "not a result -- the RAW / BASIC RAG / TAVONEL arms have not been run",
            "not a claim that the endpoint will succeed; sufficiency is a precondition",
        ],
        "next_gate": (
            "build the question set under PROTOCOL_V2 section 2's fixed templates, then measure "
            "section 3's leakage thresholds, and only then execute the three arms"
        ),
        "identity_module_modified": False,
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out = EXP / "receipts" / "v7-endpoint-sufficiency-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for name, info in classes.items():
        need = MINIMUMS[name]
        got = info["available"]
        print(f"  {info['state']:<13} {name:<22} need>={need:<4} have="
              f"{got if got is not None else '?'}")
    print(f"primary endpoint class sufficient: {primary_ok} "
          f"({classes['revision_sensitive']['articles']} articles, "
          f"need >= {MIN_ARTICLES_WITH_PRIMARY})")
    print(f"endpoint status: {receipt['endpoint_status']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
