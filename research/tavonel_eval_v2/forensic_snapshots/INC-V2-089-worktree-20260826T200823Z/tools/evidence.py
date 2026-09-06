"""Immutable receipt plumbing. INC-V2-005.

An evidence-producing run must not be able to destroy the evidence of an earlier
one. The forensic tool did exactly that: two runs, one receipt path, and the
first run's receipt is gone. The judgements happened to agree, but nobody can
show that now, because only one of the two receipts still exists.

So a receipt written through this module:

* lands on a **run-specific path** that names the run, never a bare stem;
* **refuses to overwrite**. If the path exists, the write raises. There is no
  force flag, because the only reason to want one is the failure this module
  exists to prevent;
* carries its own content hash, its run id, its timestamp, and the digests of
  the tool and the protocol that produced it, so a receipt can be traced to the
  code and the contract behind it without consulting anything outside itself.

``latest/<stem>.json`` is written as a convenience pointer. It is **not
evidence** and says so in its own body: it holds a path and a digest, never a
finding. A reader that wants a result reads the immutable receipt it names.

Receipts written before this module existed keep their paths. Rewriting them
would be a mutation of evidence in the name of preventing mutation of evidence.
They are listed in ``receipts/legacy-mutable-receipts.json`` instead.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import NS, canonical_sha, now, rel, sha_file

RECEIPTS = NS / "receipts"
POINTERS = RECEIPTS / "latest"

SCHEMA = "tavonel.v2.immutable_receipt_envelope.v1"
POINTER_SCHEMA = "tavonel.v2.receipt_pointer.v1"


class ReceiptExists(RuntimeError):
    """A run tried to write a receipt path that another run already holds."""


def _compact(stamp: str) -> str:
    return stamp.replace("-", "").replace(":", "").replace("+0000", "Z")[:15]


def new_run_id(tool: Path, protocol: Path | None = None) -> str:
    """A run id that names when it ran and what produced it.

    Not random: derived from the tool digest, the protocol digest, the wall
    clock and the process id. Two runs of the same tool on the same protocol in
    the same second from different processes still differ, and a run id can be
    checked against the receipt that carries it.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    seed = "|".join(
        [
            sha_file(tool),
            sha_file(protocol) if protocol is not None else "no-protocol",
            stamp,
            str(os.getpid()),
        ]
    )
    return stamp + "-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def receipt_path(stem: str, run_id: str) -> Path:
    return RECEIPTS / f"{stem}--{run_id}.json"


def write_immutable(
    stem: str,
    body: dict[str, Any],
    *,
    tool: Path,
    protocol: Path | None = None,
    run_id: str | None = None,
    pointer: bool = True,
) -> dict[str, str]:
    """Write one immutable receipt and return where it went.

    Raises ``ReceiptExists`` rather than overwriting. A caller that reaches this
    has a run id collision, which means either a genuine duplicate run or a bug
    in run id derivation; both want a stack trace, not a silent replacement.
    """
    if run_id is None:
        run_id = new_run_id(tool, protocol)

    target = receipt_path(stem, run_id)
    if target.exists():
        raise ReceiptExists(
            f"{rel(target)} already exists. Receipts are never overwritten; "
            "a re-run gets its own run id."
        )

    envelope = dict(body)
    envelope["provenance"] = {
        "schema": SCHEMA,
        "run_id": run_id,
        "generated_at": now(),
        "tool": rel(tool),
        "tool_sha256": sha_file(tool),
        "protocol": rel(protocol) if protocol is not None else None,
        "protocol_sha256": sha_file(protocol) if protocol is not None else None,
        "receipt_stem": stem,
        "immutable": True,
        "overwrite_refused_by": rel(Path(__file__).resolve()),
    }
    bare = {key: value for key, value in envelope.items() if key != "receipt_sha256"}
    envelope["receipt_sha256"] = canonical_sha(bare)

    target.parent.mkdir(parents=True, exist_ok=True)
    # exclusive create: if two processes race to the same run id, one of them
    # fails loudly instead of both believing they wrote the receipt
    with open(target, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")

    written = {
        "run_id": run_id,
        "receipt": rel(target),
        "receipt_sha256": envelope["receipt_sha256"],
        "receipt_file_sha256": sha_file(target),
    }

    if pointer:
        POINTERS.mkdir(parents=True, exist_ok=True)
        note = (
            "NOT EVIDENCE. A mutable convenience pointer to the most recent "
            "immutable receipt for this stem. It carries no finding. Cite the "
            "file it names, never this one."
        )
        (POINTERS / f"{stem}.json").write_text(
            json.dumps(
                {
                    "schema": POINTER_SCHEMA,
                    "is_evidence": False,
                    "note": note,
                    "stem": stem,
                    "points_to": written["receipt"],
                    "points_to_file_sha256": written["receipt_file_sha256"],
                    "run_id": run_id,
                    "updated_at": now(),
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        written["pointer"] = rel(POINTERS / f"{stem}.json")

    return written


def runs_of(stem: str) -> list[str]:
    """Every immutable receipt written for this stem, oldest run id first."""
    return sorted(rel(path) for path in RECEIPTS.glob(f"{stem}--*.json"))
