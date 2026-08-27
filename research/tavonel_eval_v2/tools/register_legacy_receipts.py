#!/usr/bin/env python3
"""Pin the receipts that were written before INC-V2-005 existed.

Those receipts sit on mutable paths and cannot be moved: relocating evidence to
prevent evidence from being relocated is the same act it is meant to prevent,
and the founder ruling preserves the P0/P0b/P2/P3/P4 results unmodified.

What can be done is to record, once, what bytes each of them holds now. From
this point a later overwrite is detectable even on a mutable path. That is
weaker than immutability — it catches the change afterwards rather than refusing
it — and this register says so rather than implying the gap is closed.

The register itself is written through the immutable path, so it cannot be
quietly replaced either.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file  # noqa: E402
from evidence import RECEIPTS, write_immutable  # noqa: E402


def main() -> int:
    entries = []
    for path in sorted(RECEIPTS.glob("*.json")):
        if "--" in path.name:  # already an immutable receipt
            continue
        entries.append({"path": rel(path), "file_sha256": sha_file(path)})

    body = {
        "schema": "tavonel.v2.legacy_receipt_register.v1",
        "incident": "INC-V2-005",
        "what_this_is": (
            "the file digest of every receipt written on a mutable path before "
            "immutable receipt plumbing existed"
        ),
        "what_this_is_not": (
            "immutability. These paths remain writable. This register makes a "
            "later overwrite detectable after the fact; it does not prevent one, "
            "and it cannot recover a receipt already lost that way."
        ),
        "known_loss": (
            "receipts/inc-v2-001-provenance-forensic.json was overwritten by a "
            "second run of the same tool before this register existed. The first "
            "run's receipt is unrecoverable and no claim of two-run byte "
            "reproducibility is made from it."
        ),
        "legacy_receipt_count": len(entries),
        "legacy_receipts": entries,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(
        "legacy-mutable-receipt-register",
        body,
        tool=Path(__file__).resolve(),
    )
    print("registered " + str(len(entries)) + " legacy receipts -> " + written["receipt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
