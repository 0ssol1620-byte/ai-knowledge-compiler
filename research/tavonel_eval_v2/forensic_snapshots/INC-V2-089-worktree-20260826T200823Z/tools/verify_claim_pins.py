#!/usr/bin/env python3
"""Read-only re-verification of `paper/CLAIM_MATRIX.yaml` against
`paper/claim_receipt_pins.json`.

This tool never writes to either file. It re-runs the binding a reader is
meant to trust — every non-`PENDING` claim names a receipt that exists, that
receipt's current bytes still hash to the digest `claim_receipt_pins.json`
pinned for that claim id, and neither file names an evidence source that
cannot actually be re-checked from a fresh clone:

* a `receipts/latest/` mutable convenience pointer is never accepted as an
  evidence pin, regardless of whether its current bytes happen to hash-match
  right now — the whole reason it is a pointer rather than a receipt is that
  it can be repointed by a later run without either `CLAIM_MATRIX.yaml` or
  `claim_receipt_pins.json` changing, and every pointer's own body says so
  (`is_evidence: false`, and a `note` field naming itself not evidence — see
  `evidence.write_immutable`'s pointer schema). This tool asserts that
  self-declaration matches its own refusal rather than taking the refusal on
  faith;
* a claim citing a git-ignored path is refused — a citation that only
  resolves on the machine that produced it is not evidence a clone can check;
* a claim citing a path with no entry in `claim_receipt_pins.json` is
  refused — an unpinned path is an assertion, not a checked digest.

Mismatches are reported, never repaired. Fixing `CLAIM_MATRIX.yaml` or
`claim_receipt_pins.json` is the paper-closure workstream's call, not this
tool's — see the founder's routing instructions for this session.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
sys.path.insert(0, str(NS / "tools"))

from common import sha_file  # noqa: E402  -- "sha256:<hex>", matches the pin format

CLAIM_MATRIX_PATH = NS / "paper" / "CLAIM_MATRIX.yaml"
PINS_PATH = NS / "paper" / "claim_receipt_pins.json"

PENDING = "PENDING"
LATEST_POINTER_PREFIX = "receipts/latest/"

VERDICT_PASS = "PASS"  # noqa: S105 -- a status label, not a credential
VERDICT_REFUSED = "REFUSED"
VERDICT_PENDING_SKIPPED = "PENDING_SKIPPED"

VERDICTS: tuple[str, ...] = (VERDICT_PASS, VERDICT_REFUSED, VERDICT_PENDING_SKIPPED)


def _is_git_ignored(relative_path: str) -> bool | None:
    """True/False from `git check-ignore`, run from this namespace's root.

    `None` — never coerced to `False` — if git could not be asked at all. A
    check that could not run must not silently read as "not ignored"; the
    caller records that as its own violation.
    """
    try:
        # fixed argv, no shell, no user-controlled executable path — `git` is
        # resolved from PATH deliberately, the same pattern already used by
        # `tools/freeze_sfi3_protocol.py`'s own `subprocess.run` calls.
        result = subprocess.run(  # noqa: S603
            ["git", "check-ignore", "-q", relative_path],  # noqa: S607
            cwd=NS,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None  # >1 is a git usage error, not a yes/no answer


def _pointer_self_declaration(pointer_path: Path) -> dict[str, Any]:
    """What a `receipts/latest/...` file says about itself.

    This module refuses every `receipts/latest/` citation by path alone (see
    `check_claim`) — this function does not decide that refusal, it only
    checks that the pointer's own body backs it up, which is the audit trail
    the task asked for ("those pointers say so in their own note field").
    """
    try:
        body = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"readable": False, "error": f"{type(error).__name__}: {error}"}
    return {
        "readable": True,
        "is_evidence": body.get("is_evidence"),
        "note": body.get("note"),
        "points_to": body.get("points_to"),
        "self_declares_non_evidence": body.get("is_evidence") is False,
    }


def check_claim(claim: dict[str, Any], pins: dict[str, str]) -> dict[str, Any]:
    """Every check this task named, run against one claim row. Never repaired."""
    claim_id = claim.get("id", "<no id>")
    receipt_field = claim.get("receipt")
    result: dict[str, Any] = {
        "claim_id": claim_id,
        "receipt_field": receipt_field,
        "violations": [],
    }

    if receipt_field == PENDING:
        result["verdict"] = VERDICT_PENDING_SKIPPED
        return result

    if not receipt_field or not isinstance(receipt_field, str):
        result["violations"].append(
            "receipt field is missing or not a string; a non-PENDING claim must name a path"
        )
        result["verdict"] = VERDICT_REFUSED
        return result

    absolute = (NS / receipt_field).resolve()
    exists = absolute.is_file()
    result["exists"] = exists
    if not exists:
        result["violations"].append(f"receipt path does not exist: {receipt_field}")

    is_latest_pointer = receipt_field.startswith(LATEST_POINTER_PREFIX)
    result["is_latest_mutable_pointer"] = is_latest_pointer
    if is_latest_pointer:
        declaration = _pointer_self_declaration(absolute) if exists else {"readable": False}
        result["pointer_self_declaration"] = declaration
        note = declaration.get("note")
        result["violations"].append(
            "receipt cites a receipts/latest/ mutable convenience pointer, which is never "
            "accepted as an evidence pin regardless of whether it currently hash-matches"
            + (f" (the pointer's own note: {note!r})" if note else " (its note could not be read)")
        )

    ignored = _is_git_ignored(receipt_field)
    result["git_ignored"] = ignored
    if ignored:
        result["violations"].append(f"receipt path is git-ignored: {receipt_field}")
    elif ignored is None:
        result["violations"].append(
            f"git-ignore status of {receipt_field!r} could not be determined by `git "
            "check-ignore`; not treated as clean"
        )

    pin = pins.get(claim_id)
    result["pin_present"] = pin is not None
    if pin is None:
        result["violations"].append(f"no entry for {claim_id} in {PINS_PATH.name}")
    elif exists:
        actual = sha_file(absolute)
        result["pinned_sha256"] = pin
        result["actual_sha256"] = actual
        result["hash_matches"] = actual == pin
        if actual != pin:
            result["violations"].append(f"receipt bytes hash to {actual}, pinned digest is {pin}")

    result["verdict"] = VERDICT_REFUSED if result["violations"] else VERDICT_PASS
    return result


def run() -> dict[str, Any]:
    matrix = yaml.safe_load(CLAIM_MATRIX_PATH.read_text(encoding="utf-8"))
    pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    claims = matrix.get("claims", [])

    results = [check_claim(claim, pins) for claim in claims]
    by_verdict = {verdict: 0 for verdict in VERDICTS}
    refused: list[dict[str, Any]] = []
    for record in results:
        by_verdict[record["verdict"]] = by_verdict.get(record["verdict"], 0) + 1
        if record["verdict"] == VERDICT_REFUSED:
            refused.append(record)

    #: a pin naming a claim id that no longer exists in the matrix at all —
    #: not one of the task's named checks, but the same kind of dangling
    #: citation, so it is surfaced rather than silently ignored.
    claim_ids = {claim.get("id") for claim in claims}
    orphan_pins = sorted(set(pins) - claim_ids)

    return {
        "schema": "tavonel.v2.claim_pin_verification.v1",
        "claim_matrix": str(CLAIM_MATRIX_PATH.relative_to(NS)).replace("\\", "/"),
        "claim_matrix_sha256": sha_file(CLAIM_MATRIX_PATH),
        "pins_file": str(PINS_PATH.relative_to(NS)).replace("\\", "/"),
        "pins_file_sha256": sha_file(PINS_PATH),
        "total_claims": len(claims),
        "by_verdict": by_verdict,
        "refused": refused,
        "orphan_pins": orphan_pins,
        "overall": "CLEAN" if not refused and not orphan_pins else "MISMATCHES_FOUND",
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="omit the full per-claim result list, keep the refused list and counts",
    )
    args = parser.parse_args(argv)

    result = run()
    output = {k: v for k, v in result.items() if k != "results"} if args.summary_only else result
    print(json.dumps(output, indent=2))
    return 0 if result["overall"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
