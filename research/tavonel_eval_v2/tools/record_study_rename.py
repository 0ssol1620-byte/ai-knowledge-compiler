#!/usr/bin/env python3
"""Rename the Workstream B result, without touching the frozen protocol.

Founder ruling, 2026-08-23:

    Rename the Workstream B result from "independent oracle verification" to
    independent implementation differential study wherever necessary. The shared
    specification means independent verification was not achieved.

"Wherever necessary" cannot mean the protocol file. `ORACLE_INDEPENDENCE_V2.yaml`
is frozen and byte-pinned by its own freeze receipt, and editing a frozen
protocol to improve its wording is exactly the move every gate in this namespace
exists to refuse. The protocol says what it said when it was frozen, including
the parts whose framing the result did not earn.

So the rename lands where a name is actually asserted — the claim matrix, the
draft, the consolidated report — and this receipt is the record binding the old
name to the new one, naming the surfaces that carry each and the reason the
frozen text is not among them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, now, rel, sha_file
from evidence import write_immutable

WAS = "independent oracle verification"
IS = "independent implementation differential study"

PROTOCOL = NS / "protocols" / "ORACLE_INDEPENDENCE_V2.yaml"
FREEZE = NS / "receipts" / "oracle-v2-protocol-freeze--20260823T024147Z-7dd609ba17c6.json"
RESULT = NS / "receipts" / "oracle-independence-v2--20260823T033320Z-248859f8c1ee.json"


def surface(relative: str, carries: str, why: str) -> dict[str, Any]:
    path = NS / relative
    return {
        "path": relative,
        "exists": path.exists(),
        "sha256": sha_file(path) if path.exists() else None,
        "carries": carries,
        "why": why,
    }


def body() -> dict[str, Any]:
    return {
        "schema": "tavonel.v2.study_rename.v1",
        "authorised_by": "founder ruling, 2026-08-23",
        "study": "ORACLE_INDEPENDENCE_V2",
        "name_was": WAS,
        "name_is": IS,
        "because": (
            "the two implementations share a specification, and that "
            "specification was written by reading the engine. A defect living in "
            "the specification is common-mode and this design cannot see it. "
            "Independent verification was not achieved and the earlier working "
            "title claimed it."
        ),
        "what_would_be_required_instead": (
            "an independently checkable reference semantics for the supported "
            "source grammar, defined before either implementation. Labelling a "
            "second implementation an oracle does not produce one."
        ),
        "generated_at": now(),
        "renamed_surfaces": [
            surface(
                "paper/CLAIM_MATRIX.yaml",
                IS,
                "C-17 carries study_name, name_was and name_changed_because",
            ),
            surface(
                "paper/TAVONEL_PAPER_DRAFT_INTERNAL.md",
                IS,
                "section 5.2 heading and body; the four divergences are "
                "oracle-relative until section 5.3 confirms them on the "
                "production path",
            ),
            surface(
                "V2_CONSOLIDATED_REPORT_2026-08-21.md",
                IS,
                "the Workstream B section and its summary line",
            ),
        ],
        "not_renamed": [
            {
                "path": rel(PROTOCOL),
                "sha256": sha_file(PROTOCOL),
                "carries": "the frozen wording, including the word 'oracle' throughout",
                "why": (
                    f"frozen and byte-pinned by {FREEZE.name}. A frozen protocol "
                    "is not edited to improve its framing; that is the mutation "
                    "every gate here exists to refuse. Its own header already "
                    "records that independence was not achieved and that the "
                    "shared specification is why."
                ),
                "pinned_by": rel(FREEZE),
                "pinned_sha256": sha_file(FREEZE),
            },
            {
                "path": rel(RESULT),
                "sha256": sha_file(RESULT),
                "carries": "the executed result, exactly as executed",
                "why": (
                    "a result receipt is immutable. The rename is a change of "
                    "name, not of number, and no number in it moves."
                ),
            },
        ],
        "vocabulary": {
            "oracle-relative divergence": (
                "a disagreement between the production path and the second "
                "implementation. Says where to look; says nothing on its own "
                "about whether the production path left anything stale."
            ),
            "confirmed selective stale escape": (
                "established against the production clean full rebuild alone, "
                "in forensic-stale-escape. Four named cases, not a rate."
            ),
        },
        "forbidden_after_this_record": [
            WAS,
            "independent oracle",
            "independently verified",
            "oracle-verified",
        ],
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    written = write_immutable("study-rename", body(), tool=Path(__file__).resolve(), protocol=None)
    print(json.dumps(written, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
