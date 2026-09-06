"""A superseded receipt must never be selected as authoritative evidence.

The Family B attribution correction is the case this guards. A sealed receipt
recorded that the structural channel was the root cause of `stale_left_behind =
2` on the confirmatory corpus. That was wrong -- the cause was the unresolved
incoming identity seed -- and rather than edit the sealed receipt, a superseding
one was written naming it.

Which leaves a live hazard: a generator that walks the receipts directory and
reads the older file on its own resurrects the retracted causal statement, with
a valid hash attached. The hash proves the bytes, not the claim.

So this asserts three things about the corpus of receipts itself, independent of
any particular generator:

    1. every `supersedes` pointer resolves to a receipt that exists
    2. the superseding receipt records the superseded one's sha256, so the
       retraction is bound to specific bytes rather than to a filename
    3. no receipt that has been superseded is reachable as authoritative
       evidence without its superseding receipt being reachable too

Point 3 is the one with teeth. It fails if someone adds a superseded receipt to
an evidence index while leaving the correction out.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_DIRS = [
    ROOT / "research/experiments/H1-B-REAL-REVISION-01/receipts",
    ROOT / "research/experiments/H1-C-TEMPORAL-AUTHORITY-01/receipts",
    ROOT / "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts",
]


def _receipts() -> list[Path]:
    return sorted(p for d in RECEIPT_DIRS if d.is_dir() for p in d.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _supersedes(payload: dict) -> dict | None:
    block = payload.get("supersedes")
    return block if isinstance(block, dict) else None


def test_at_least_one_superseding_receipt_exists() -> None:
    """Otherwise the checks below pass by finding nothing, which proves nothing."""
    found = [p for p in _receipts() if _supersedes(_load(p))]
    assert found, (
        "no receipt declares `supersedes`. Either the attribution correction was "
        "removed or this contract is no longer pointed at the right directory; "
        "both make the rest of this file vacuous"
    )


@pytest.mark.parametrize("path", _receipts(), ids=lambda p: p.name)
def test_a_supersedes_pointer_resolves_and_pins_bytes(path: Path) -> None:
    block = _supersedes(_load(path))
    if block is None:
        pytest.skip("does not supersede anything")

    target_name = block.get("receipt")
    assert target_name, f"{path.name} declares `supersedes` without naming a receipt"
    target = path.parent / target_name
    assert target.is_file(), (
        f"{path.name} supersedes {target_name}, which does not exist. A retraction "
        "pointing at nothing cannot be checked and will not be honoured"
    )

    declared = block.get("sha256")
    assert declared, (
        f"{path.name} supersedes {target_name} without pinning its sha256. Bound "
        "to a filename alone, the retraction silently stops applying the moment "
        "the superseded file is regenerated"
    )
    actual = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    assert declared == actual, (
        f"{path.name} retracts a version of {target_name} that is not the one on "
        f"disk.\n  declared: {declared}\n  actual:   {actual}\n"
        "The retraction no longer applies to these bytes, so the retracted claim "
        "is live again."
    )


def test_no_superseded_receipt_is_cited_without_its_correction() -> None:
    """An evidence index may cite the old receipt only alongside the new one.

    Citing the superseded receipt alone is how the retracted causal statement
    gets back into a manuscript: the file is real, its hash checks out, and
    nothing in it says it was withdrawn.
    """
    superseded: dict[str, str] = {}
    for path in _receipts():
        block = _supersedes(_load(path))
        if block and block.get("receipt"):
            superseded[block["receipt"]] = path.name

    if not superseded:
        pytest.skip("nothing is superseded")

    offenders: list[str] = []
    for index in ROOT.glob("docs/evidence/*.json"):
        text = index.read_text(encoding="utf-8")
        for old, correction in superseded.items():
            if old in text and correction not in text:
                offenders.append(f"{index.name} cites {old} without {correction}")

    assert not offenders, (
        "a superseded receipt is cited as evidence without its correction:\n  "
        + "\n  ".join(offenders)
    )
