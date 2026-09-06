#!/usr/bin/env python3
"""Seal SFIR4 as a terminal operational stop. INC-V2-101.

This receipt exists so the stop is a recorded scientific outcome rather than an
absence. SFIR1, SFIR2 and SFIR3 each stopped and each has a failure authority;
SFIR4 is the fourth, and the only one that stopped for an operational reason
rather than a data one.

What it must NOT be read as saying: SFIR4 measured something. It did not. The
capacity census aborted before any quantity was computed, printed or written,
so `capacity_measured` is `incomplete` and `scientific_threshold_evaluated` is
`false`. A stop is not a FAIL of the criterion -- the criterion was never
applied -- and conflating the two would let a reader infer that the declared
frame is short of capacity, which nothing here establishes either way.

The receipt is deliberately unable to express a PASS. There is no verdict field
to flip.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from common import now, rel, sha_file, write_hashed  # noqa: E402

STEM = "sfir4-terminal-operational-stop"
SCHEMA = "tavonel.sfir4.terminal_operational_stop.v1"

#: The exact disposition, in the founder's own vocabulary. Held as literals so
#: the receipt cannot drift from the ruling that authorised it.
DISPOSITION: dict[str, Any] = {
    "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4",
    "state": "TERMINAL_OPERATIONAL_STOP",
    "cause": "frozen transport budget incompatible with observed Wikimedia rate behavior",
    "corpus_opened": False,
    "capacity_measured": "incomplete",
    "scientific_threshold_evaluated": False,
}

#: Read from the endpoint, not from any SFIR4 or SFIR5 result. Recorded because
#: it is the operational motivation for the successor and must be auditable as
#: such -- a successor justified by an unrecorded observation is a successor
#: justified by nothing.
OBSERVED_RATE_BEHAVIOUR: dict[str, Any] = {
    "endpoint": "en.wikipedia.org/w/api.php",
    "shape": "quota per ~60s window, not a per-request rate",
    "trials": [
        {"inter_request_delay_seconds": 0, "ok": 10, "throttled": 2},
        {"inter_request_delay_seconds": 2, "ok": 10, "throttled": 2},
        {"inter_request_delay_seconds": 5, "ok": 11, "throttled": 1},
        {"inter_request_delay_seconds": 7, "ok": 20, "throttled": 0, "window_seconds": 150},
    ],
    "retry_after_values_seen_seconds": [55, 54, 54, 53, 53, 52, 51, 51, 50, 50],
    "why_this_is_admissible_for_designing_a_successor": (
        "it measures the ENDPOINT, not SFIR4's or SFIR5's capacity result. No "
        "candidate was counted, no threshold evaluated, no cohort read. Using it "
        "to choose a pacing budget is therefore not choosing a parameter by "
        "looking at an outcome."
    ),
}

FROZEN_BOUNDS_THAT_WERE_NOT_EDITED: dict[str, Any] = {
    "maximum_retries_per_request": 5,
    "max_rate_limit_wait_seconds": 60,
    "max_total_rate_limit_wait_seconds": 180,
    "why_not_edited": (
        "the three earlier SFIR4 corrections were unconditional defects with one "
        "right answer whichever way the census came out. This is a tuning "
        "parameter, and a value chosen after watching a run fail is chosen partly "
        "by the failure. Editing it would have been the first correction in this "
        "study to fail the standard the paper's own section 2 sets."
    ),
}


def build(generated_at: str | None = None) -> dict[str, Any]:
    stamp = generated_at or now()
    census = NS / "receipts" / "sfir4-capacity-metadata-census.json"
    charter = NS / "receipts" / "sfir4-design-charter-freeze.json"
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": stamp,
        "disposition": dict(DISPOSITION),
        "observed_rate_behaviour": dict(OBSERVED_RATE_BEHAVIOUR),
        "frozen_bounds_that_were_not_edited": dict(FROZEN_BOUNDS_THAT_WERE_NOT_EDITED),
        "result_blind_at_stop": {
            "capacity_receipt_written": census.is_file(),
            "capacity_receipt_path": rel(census),
            "capacity_quantity_computed_printed_or_written": False,
            "how_verified": (
                "the destination path was checked for a receipt and the captured "
                "run output was searched for any capacity quantity; it holds a "
                "traceback and nothing else."
            ),
        },
        "aborts_before_this_one": [
            {"incident": "INC-V2-095", "cause": "eCFR metadata field renamed", "repaired": True},
            {
                "incident": "INC-V2-096",
                "cause": "reserved CFR title carries no edition date",
                "repaired": True,
            },
            {
                "incident": "INC-V2-098",
                "cause": "RemoteDisconnected matched no handler",
                "repaired": True,
            },
        ],
        "succeeded_by": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5",
        "what_this_receipt_does_not_say": (
            "that SFIR4 measured anything. The criterion was never applied, so this "
            "is not a FAIL of the capacity threshold and must not be read as "
            "evidence that the declared frame is short of capacity. Nothing here "
            "establishes that either way."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    if charter.is_file():
        body["charter_at_stop"] = {"path": rel(charter), "sha256": sha_file(charter)}
    return body


def main() -> int:
    body = build()
    written = write_hashed(NS / "receipts" / f"{STEM}.json", body)
    print(f"{STEM}: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
