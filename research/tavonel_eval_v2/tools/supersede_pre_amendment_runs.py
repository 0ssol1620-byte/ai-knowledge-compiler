#!/usr/bin/env python3
"""Mark the pre-amendment executions superseded and partial. Never edit them.

Founder ruling, 2026-08-23: "The pre-amendment execution must remain immutable
and explicitly superseded/partial."

Both halves matter and they pull in opposite directions. The receipts stay
exactly as written — editing an old receipt to say it is superseded is a
mutation of evidence in the name of describing evidence, which is INC-V2-005
with better manners. So the supersession is a NEW immutable receipt that names
the old ones by digest and says what they are.

Three kinds of pre-amendment execution exist here:

* **smoke receipts** — real receipts, real outcome metrics, 8 and 6 lineages.
  They are the exposure that costs both studies their held-out status.
* **the interrupted full run** — started, stopped by hand, wrote no cohort
  receipt at all. It is a partial execution and never was a result.
* **the first protocol freezes** — frozen after their runs had already started,
  so they never carried the "frozen before its data" property either.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

RECEIPTS = NS / "receipts"

SUPERSEDED = "SUPERSEDED_PRE_AMENDMENT_EXECUTION"
PARTIAL = "PARTIAL_EXECUTION_NO_RESULT_WRITTEN"
FREEZE_LATE = "FREEZE_AFTER_EXECUTION_BEGAN"


def pin(relative: str, state: str, why: str, superseded_by: str | None) -> dict[str, Any]:
    path = NS / relative
    body = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {
        "path": rel(path) if path.exists() else relative,
        "exists": path.exists(),
        "file_sha256": sha_file(path) if path.exists() else None,
        "generated_at": body.get("provenance", {}).get("generated_at"),
        "state": state,
        "why": why,
        "superseded_by": superseded_by,
        "edited": False,
        "edit_forbidden_because": (
            "editing a receipt to record that it is superseded is a mutation of "
            "evidence in the name of describing evidence"
        ),
    }


SMOKE_WHY = (
    "an execution on real lineages that produced and exposed outcome-derived "
    "metrics before the protocol was frozen or amended. It is the exposure that "
    "costs the study its held-out status; it is not a result and never was."
)

FINAL_SFH1 = "receipts/sfh1-source-faithfulness--20260823T031017Z-329258f9ec8a.json"
FINAL_OI2 = "receipts/oracle-independence-v2--20260823T033320Z-248859f8c1ee.json"


def body() -> dict[str, Any]:
    return {
        "schema": "tavonel.v2.pre_amendment_supersession.v1",
        "authorised_by": "founder ruling, 2026-08-23",
        "rule": (
            "the pre-amendment execution remains immutable and is explicitly superseded and partial"
        ),
        "executions": [
            pin(
                "receipts/sfh1-source-faithfulness--20260823T020607Z-4d87a644df4d.json",
                SUPERSEDED,
                SMOKE_WHY + " 8 lineages considered, 3 scored.",
                FINAL_SFH1,
            ),
            pin(
                "receipts/oracle-independence-v2--20260823T021301Z-f8d3eaca6dd1.json",
                SUPERSEDED,
                SMOKE_WHY + " 6 lineages considered, 2 judged.",
                FINAL_OI2,
            ),
        ],
        "interrupted_run": {
            "study": "SOURCE_FAITHFULNESS_HELDOUT_V1",
            "state": PARTIAL,
            "started_at": "2026-08-23T02:07:06+00:00",
            "stopped_at": "approximately 2026-08-23T02:34+00:00",
            "stopped_by": "operator, after a timing probe showed the span scan was superlinear",
            "cohort_receipt_written": False,
            "why": (
                "stopped by hand and wrote no receipt of any kind. Only its "
                "per-family admitted counts were ever visible, in a progress log. "
                "It is a partial execution, not a result, and nothing cites it."
            ),
            "what_was_visible": (
                "one progress line: considered 96, admitted 46, per-family counts. "
                "That is an acquisition-yield figure rather than a classification "
                "outcome, and it is recorded here anyway because the ruling's test "
                "is one-sided and this tool does not get to decide what counted."
            ),
        },
        "late_freezes": [
            pin(
                "receipts/sfh1-protocol-freeze--20260823T022251Z-cb1523508572.json",
                FREEZE_LATE,
                "frozen at 02:22:51, after the smoke run at 02:06:07 and after the "
                "full run began at 02:07:06. It never carried the property its "
                "protocol claims for itself.",
                "receipts/sfh1-protocol-freeze--20260823T024116Z-91689ae88d7b.json",
            ),
            pin(
                "receipts/oracle-v2-protocol-freeze--20260823T022252Z-2c122136037f.json",
                FREEZE_LATE,
                "frozen at 02:22:52, after the smoke run at 02:13:01.",
                "receipts/oracle-v2-protocol-freeze--20260823T024147Z-7dd609ba17c6.json",
            ),
        ],
        "consequence": {
            "SOURCE_FAITHFULNESS_HELDOUT_V1": "development_diagnostic",
            "ORACLE_INDEPENDENCE_V2": "development_diagnostic",
            "note": (
                "the ruling ordered the SFH1 downgrade. ORACLE_INDEPENDENCE_V2 "
                "fails the identical test on identical evidence, and applying the "
                "test to one study and not the other would leave a stronger claim "
                "standing on weaker evidence."
            ),
        },
        "not_affected": [
            "VALUE_BEARING_COHORT_V1",
            "VALUE_BEARING_COHORT_V2",
            "STOP-V2-005",
        ],
        "results_preserved": (
            "neither final result is repaired, re-scored or re-run. What changes "
            "is the split each may be reported under, not a single number in "
            "either."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    written = write_immutable(
        "pre-amendment-supersession", body(), tool=Path(__file__).resolve(), protocol=None
    )
    print(json.dumps(written, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
