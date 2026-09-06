#!/usr/bin/env python3
"""Integrity of the FROZEN INSTRUMENT chain, over the research tree's own receipts.

``verify_sealed_evidence.py`` exists and passes over its declared scope::

    docs/evidence/*.json | docs/ip/receipts/*.json |
    research/experiments/*/receipts/*.json | research/experiments/*/manifest.json

That scope does not contain ``research/tavonel_eval_v2/receipts/*.json``. Every
freeze this study performed -- protocol, universe, frame, domain, scorer,
exclusion, spent-identity, design-charter -- pins its instrument there, and no
verifier read those pins. A guard that cannot see the surface it protects is the
INC-V2-036 defect class: its failure was impossible, so its success meant
nothing. This module is that guard, aimed at the surface the other one skips.

Two binding classes, deliberately separated, because they carry different
consequences:

FROZEN
    A receipt whose stem marks it as a freeze or an attestation: the pinned
    bytes are the instrument a later measurement was declared to have run under.
    Drift here means a sealed result is no longer byte-reproducible from this
    worktree. It is a FAIL, and no claim that the change was only cosmetic
    converts it back -- the pin is over bytes, and the original bytes are what
    is gone.

ADVISORY
    A receipt that records a passing observation about the tree at a moment
    (suite evidence, hygiene passes, claim matrices). The tree is expected to
    move on afterwards. Drift here is reported and is not a failure.

Read-only by construction: the single file written is this script's own receipt.
It never rewrites a pin. Re-pinning a frozen attestation to current bytes would
convert an integrity finding into a silent overwrite of historical evidence,
which the project constitution lists under stop-the-line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    NS,
    ROOT,
    now,
    rel,
    sha_file,
    write_hashed,
)

SCHEMA = "tavonel.v2.frozen_instrument_integrity.v1"
STEM = "frozen-instrument-integrity"

#: A receipt stem containing any of these marks bytes that were declared frozen.
FROZEN_MARKERS: tuple[str, ...] = (
    "-attestation",
    "-freeze",
    "-authority",
    "-reservation",
    "-handoff",
    "-pin",
    "-seal",
)

#: Receipts that record a moment rather than freeze one. The tree is expected
#: to move on after these, so their drift is reported without failing.
ADVISORY_MARKERS: tuple[str, ...] = (
    "suite-evidence",
    "evidence-hygiene-pass",
    "claim-matrix",
    "-verification",
)

#: Extensions whose bytes are the instrument. A pin over a receipt or a data
#: artifact is checked by that receipt's own chain, not here.
SOURCE_SUFFIXES: frozenset[str] = frozenset({".py", ".yaml", ".yml", ".md", ".toml"})


class IntegrityRefused(RuntimeError):
    """Raised when the verifier cannot answer, as distinct from answering FAIL."""


def classify(stem: str) -> str:
    """FROZEN, ADVISORY or SKIP for a receipt filename stem."""
    if any(mark in stem for mark in ADVISORY_MARKERS):
        return "ADVISORY"
    if any(mark in stem for mark in FROZEN_MARKERS):
        return "FROZEN"
    return "SKIP"


def _resolve(path_text: str) -> Path | None:
    """Resolve a pinned path, which receipts write repo-relative or NS-relative."""
    for base in (ROOT, NS):
        candidate = base / path_text
        if candidate.is_file():
            return candidate
    return None


def bindings(body: Any) -> list[tuple[str, str]]:
    """Every (path, sha256) pair a receipt carries over a source file.

    Two shapes are in use across this tree and both are read:
    ``{"pinned_files": {path: sha}}`` and ``[{"path": ..., "sha256": ...}]``.
    """
    found: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            path_text = node.get("path")
            digest = node.get("sha256")
            if isinstance(path_text, str) and isinstance(digest, str):
                found.append((path_text, digest))
            for key, value in node.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, str)
                    and value.startswith("sha256:")
                    and Path(key).suffix in SOURCE_SUFFIXES
                ):
                    found.append((key, value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    return [
        (path_text, digest)
        for path_text, digest in found
        if Path(path_text).suffix in SOURCE_SUFFIXES
    ]


def verify(receipts: Path | None = None) -> dict[str, Any]:
    """Check every binding carried by the research tree's own receipts."""
    directory = receipts if receipts is not None else NS / "receipts"
    if not directory.is_dir():
        raise IntegrityRefused(f"no receipt directory at {directory}")

    frozen_drift: list[dict[str, str]] = []
    advisory_drift: list[dict[str, str]] = []
    absent: list[dict[str, str]] = []
    counts = {"FROZEN": 0, "ADVISORY": 0, "SKIP": 0}
    checked = matched = 0
    digests: dict[Path, str] = {}

    for receipt_path in sorted(directory.glob("*.json")):
        kind = classify(receipt_path.stem)
        counts[kind] += 1
        if kind == "SKIP":
            continue
        try:
            body = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrityRefused(f"{receipt_path.name} is unreadable: {exc}") from exc

        for path_text, expected in sorted(set(bindings(body))):
            resolved = _resolve(path_text)
            if resolved is None:
                absent.append({"receipt": receipt_path.name, "path": path_text, "class": kind})
                continue
            if resolved not in digests:
                digests[resolved] = sha_file(resolved)
            checked += 1
            if digests[resolved] == expected:
                matched += 1
                continue
            row = {
                "receipt": receipt_path.name,
                "path": rel(resolved),
                "expected": expected,
                "worktree": digests[resolved],
                "class": kind,
            }
            (frozen_drift if kind == "FROZEN" else advisory_drift).append(row)

    frozen_files = sorted({row["path"] for row in frozen_drift})
    frozen_receipts = sorted({row["receipt"] for row in frozen_drift})

    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "scope": ["research/tavonel_eval_v2/receipts/*.json"],
        "read_only": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "receipt_classes": counts,
        "totals": {
            "bindings_checked": checked,
            "bindings_match": matched,
            "bindings_frozen_drift": len(frozen_drift),
            "bindings_advisory_drift": len(advisory_drift),
            "bindings_unresolvable": len(absent),
            "frozen_files_drifted": len(frozen_files),
            "frozen_receipts_affected": len(frozen_receipts),
        },
        "frozen_drift": frozen_drift,
        "advisory_drift": advisory_drift,
        "unresolvable": absent,
        "frozen_files_drifted": frozen_files,
        "frozen_receipts_affected": frozen_receipts,
        "does_not_repin": (
            "This verifier never writes a pin. A frozen attestation whose bytes "
            "moved is reported, not repaired -- repairing it by writing the "
            "current digest would overwrite historical evidence."
        ),
        "verdict": "FAIL" if frozen_drift else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen-instrument integrity check.")
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help="seal the finding under receipts/ instead of printing it only",
    )
    args = parser.parse_args(argv)

    try:
        body = verify()
    except IntegrityRefused as exc:
        print(json.dumps({"verdict": "UNKNOWN", "why": str(exc)}))
        return 2

    if args.write_receipt:
        path = NS / "receipts" / f"{STEM}.json"
        write_hashed(path, body)
        summary = {
            "receipt": rel(path),
            "verdict": body["verdict"],
            "totals": body["totals"],
        }
    else:
        summary = {
            "verdict": body["verdict"],
            "totals": body["totals"],
            "frozen_receipts_affected": body["frozen_receipts_affected"],
        }
    print(json.dumps(summary, indent=1))
    return 0 if body["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
