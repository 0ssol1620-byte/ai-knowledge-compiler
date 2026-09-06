#!/usr/bin/env python3
"""Reclassify the two INC-V2-037 ladder receipts, without touching either.

The founder's ruling on INC-V2-042:

    the existing benchmark and canary receipts are RETROSPECTIVE MIGRATION
    SAFETY REGRESSION, not prospective ladder qualification. Do not delete or
    rewrite them. Record the reclassification in a NEW append-only artifact and
    in the incident ledger.

So this tool writes a new immutable receipt that *points at* the two originals
by file digest and says what they are. It opens them read-only, changes nothing,
and would rather fail than write. Editing an evidence artifact to correct the
standing of that artifact is the shape INC-V2-005 exists to prevent: the record
of what was believed, and when, is itself the evidence.

The measurements in those receipts are not disputed and are not re-run here.
What is reclassified is their STANDING. A benchmark that ran after the switch it
was supposed to authorise cannot make the legacy path authoritative again for
the window in which it was not, and it was measured by a party who already knew
which direction was convenient. That is worth having and it is not qualification.

Usage::

    python tools/reclassify_identity_change_ladder.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, rel, sha_file
from evidence import runs_of, write_immutable

STEM = "identity-change-ladder-reclassification"
SCHEMA = "tavonel.v2.identity_change_ladder_reclassification.v1"

RECEIPTS = NS / "receipts"

RECLASSIFIED = (
    "identity-change-benchmark--20260824T092056Z-eb6269afcbd0.json",
    "identity-change-canary--20260824T092141Z-36fa48664af6.json",
)

#: The receipts written PROSPECTIVELY, in ladder order, that this artifact
#: points a reader to instead. Named by stem rather than by filename so that a
#: reader follows the immutable receipt this repository actually holds.
PROSPECTIVE_STEMS = (
    "identity-change-migration-closure-protocol-freeze",
    "identity-change-migration-closure-universe",
    "identity-change-migration-closure",
)


class Refused(RuntimeError):
    """Something this tool must cite is not on disk."""


def cite(name: str) -> dict[str, Any]:
    """Read one receipt read-only and cite it by digest."""
    path = RECEIPTS / name
    if not path.is_file():
        raise Refused(f"a receipt this artifact must cite is missing: {name}")
    body = json.loads(path.read_text(encoding="utf-8"))
    provenance = body.get("provenance", {})
    return {
        "receipt": rel(path),
        "receipt_file_sha256": sha_file(path),
        "run_id": provenance.get("run_id"),
        "generated_at": provenance.get("generated_at"),
        "declared_immutable_by_its_own_envelope": provenance.get("immutable"),
        "opened": "read-only",
        "modified": False,
    }


def cite_stem(stem: str) -> dict[str, Any]:
    runs = runs_of(stem)
    if not runs:
        raise Refused(f"no receipt exists for stem {stem!r}")
    return {"stem": stem, **cite(Path(runs[-1]).name)}


def build() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "what_this_is": (
            "an append-only reclassification of two existing immutable receipts. "
            "It changes their STANDING, not their content, and it modifies "
            "neither."
        ),
        "ruling": {
            "source": "founder ruling on INC-V2-042, 2026-08-25",
            "keep_production_implementation": True,
            "preserve_legacy_reference_path": True,
            "legacy_flag": "akc_cir.semantic_diff.diff_documents("
            "legacy_identity_change_predicate=True)",
            "reclassified_to": "RETROSPECTIVE_MIGRATION_SAFETY_REGRESSION",
            "reclassified_from": "PROSPECTIVE_LADDER_QUALIFICATION",
            "receipts_are_immutable": True,
            "receipts_deleted_or_rewritten": False,
        },
        "reclassified": [cite(name) for name in RECLASSIFIED],
        "why": (
            "the Protected Core ladder ran out of order (INC-V2-042). The "
            "production switch shipped before the benchmark and the canary, "
            "which were produced retroactively in a later session by the same "
            "agent that wrote the gate grading them. The measurements are not "
            "disputed and are not re-run. A benchmark taken after the switch it "
            "was meant to authorise is a different instrument from one taken "
            "before it, and the favourable direction it came out in is exactly "
            "the condition under which a retroactive check is least trustworthy "
            "and most tempting to accept."
        ),
        "how_the_numbers_in_them_may_be_read": {
            "over_fire_1_10_percent": (
                "DESCRIPTIVE ONLY. It is not an acceptance threshold, was never "
                "declared as one before the result existed, and no criterion "
                "anywhere in the prospective closure is derived from it."
            ),
            "over_fires_are_not_false_positives": (
                "legacy disagreement is not ground truth: the legacy predicate "
                "is the defect under repair. Calling an over-fire a false "
                "positive would need an independent oracle saying the unit's "
                "compiled-relevant state did not move. None exists."
            ),
            "under_fire_zero_and_identity_records_agree": (
                "these remain the most load-bearing lines in the two receipts, "
                "and the prospective closure re-establishes the identity half "
                "independently on a disjoint cohort as INVARIANT_1."
            ),
        },
        "what_replaces_them_as_prospective_evidence": {
            "protocol": rel(NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"),
            "protocol_sha256": sha_file(
                NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"
            ),
            "receipts_in_ladder_order": [cite_stem(stem) for stem in PROSPECTIVE_STEMS],
            "note": (
                "the closure was frozen before its universe, and its universe "
                "before its measurement, each enforced as a refusal rather than "
                "as a convention."
            ),
        },
        "what_this_artifact_does_not_do": [
            "it does not re-run, re-score, correct or amend either receipt",
            "it does not move the SFI2 verdict, which stands as executed",
            "it does not make the retroactive evidence prospective",
            "it does not authorise GPU spend or a public claim",
        ],
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable receipt")
    args = parser.parse_args()

    try:
        body = build()
    except Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4

    before = {name: sha_file(RECEIPTS / name) for name in RECLASSIFIED}
    if args.write:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
    after = {name: sha_file(RECEIPTS / name) for name in RECLASSIFIED}
    if before != after:  # pragma: no cover -- nothing here opens them for writing
        raise SystemExit("a reclassified receipt changed on disk; refusing to continue")

    print(json.dumps({k: v for k, v in body.items() if k != "why"}, indent=1))
    print("reclassified receipts unchanged:", before == after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
