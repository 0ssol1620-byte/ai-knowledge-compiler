"""Sampling frame for SOURCE_FAITHFULNESS_HELDOUT_V1. Frozen before acquisition.

The frame is the VBC2 lineage list, which was itself frozen before any history
was read and checked disjoint from P4i, the VBC1 probe and the
MODEL_ENDPOINT_V1 survivors. Reusing it is legitimate here for one specific
reason and it is worth stating precisely: **no canonical document was ever built
from it.** VBC2 read property observations and nothing else. With respect to the
canonicaliser, the compiler and the coverage witness — the three things this
protocol measures — those 2,271 lineages are untouched.

The three lineages VBC2 admitted are excluded, because the VBC2 preflight did
build their canonical documents.

Order is ascending sha256 of the lineage id, computed before a single payload is
read. Not by yield, not by size, not by which family answers fastest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
FRAME = NS / "artifacts" / "development" / "vbc2_lineages.json"

PROTOCOL_ID = "SOURCE_FAITHFULNESS_HELDOUT_V1"

#: Held out from the frame. Their canonical documents exist already.
SPENT_LINEAGES = frozenset(
    {
        "git:denoland/docs:runtime/desktop/comparison.md",
        "git:backstage/backstage:docs/.well-known/skills/mui-to-bui-migration/SKILL.md",
        "wikipedia:en:Reykjanesbær",
    }
)

PRIMARY_TARGET = 320
FLOOR = 200

#: Grammar breadth, not yield. Three distinct scanners are exercised — markdown,
#: MediaWiki-rendered HTML and eCFR XML — and SEC HTML is the only long-form
#: filing grammar in the frame. A family that yields zero is reported as zero
#: and its quota is never redistributed.
FAMILY_QUOTA = {
    "git_docs": 120,
    "regulation_ecfr": 100,
    "encyclopedia_wikipedia": 70,
    "sec_edgar": 30,
}

FAMILIES_REQUIRED = 2

#: A revision larger than this is not classified. Declared on compute grounds:
#: the frozen span scanner is superlinear in payload size — 3.2 MB takes 16
#: seconds and 4.6 MB takes 44 — so an uncapped run stalls on a handful of
#: documents and never reaches the rest of the frame.
#:
#: The value is deliberately insensitive. Payload sizes in this frame are
#: bimodal: the 95th percentile is 0.49 MB and the next populated band starts
#: above 3 MB, so every cap between 1 MB and 3 MB excludes the same 4.2-4.6% of
#: revisions. A bound that cannot be moved usefully is a bound that was not
#: tuned, and the distribution is published with it so a reader can check that.
MAX_PAYLOAD_BYTES = 2_000_000
MAX_PAYLOAD_BASIS = "compute: the span scanner is superlinear in payload size"
MAX_PAYLOAD_NOT_BASIS = "observed classification outcome"

#: Inherited from VALUE_BEARING_COHORT_V2 unchanged, and for the reasons that
#: protocol declared: API availability, compute and reproducibility. STOP-V2-005
#: forbids refitting them to an observed result, and that prohibition binds here
#: even though a different quantity is being measured.
HISTORY = {
    "horizon_days": 1460,
    "acquisition_cutoff": "2026-08-23T00:00:00Z",
    "max_revisions_inspected_per_lineage": 12,
    "basis": "API availability, compute and reproducibility",
    "explicitly_not_basis": "observed classification outcome",
    "inherited_from": "VALUE_BEARING_COHORT_V2",
}

#: Why a lineage produced no scored pair. Every one is reported; none is a
#: reason to reach back into the frame for a replacement, because replacing a
#: silent lineage with a talkative one is selection by yield.
FAILURE_CODES = (
    "TOO_FEW_REVISIONS",
    "NO_RAW_DIFFERENCE",
    "PAYLOAD_UNAVAILABLE",
    "PAYLOAD_TOO_LARGE_TO_CLASSIFY",
    "LISTING_FAILED",
    "CANONICALISATION_EMPTY",
    "BEYOND_FAMILY_QUOTA",
)


def order_key(lineage_id: str) -> str:
    return hashlib.sha256(lineage_id.encode("utf-8")).hexdigest()


def frame() -> list[dict[str, Any]]:
    """Every candidate lineage, in frozen order, with spent ones removed."""
    body = json.loads(FRAME.read_text(encoding="utf-8"))
    rows = [
        lineage
        for lineage in body["lineages"]
        if lineage["lineage_id"] not in SPENT_LINEAGES
    ]
    return sorted(rows, key=lambda lineage: order_key(lineage["lineage_id"]))


def frame_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [row["lineage_id"] for row in rows], separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
