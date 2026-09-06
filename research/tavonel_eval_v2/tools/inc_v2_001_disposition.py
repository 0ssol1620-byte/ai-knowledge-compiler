#!/usr/bin/env python3
"""INC-V2-001 disposition, under the founder rulings of 2026-08-21.

Four drifted bindings and two receipt self-hashes, disposed of one way each.

1. The one binding whose pinned bytes survive is **restored**, not superseded.
   The current bytes are snapshotted inside this namespace first, with their
   digest recorded, so restoring destroys nothing: what is on disk now is
   preserved as forensic material before the pinned bytes go back.

2. The three bindings whose pinned bytes exist nowhere are placed in
   **permanent historical evidence quarantine**. No claim is made that any of
   them was recovered, and none may be cited in support of anything.

3. Two of those three have generators. Regeneration is permitted, but a
   regenerated file is a **new artifact** with a new id and a new receipt. It is
   never the artifact the old receipt pinned, and this tool does not regenerate
   anything.

4. The two receipts whose declared self-hash does not recompute stay at
   ``UNVERIFIED_SELF_HASH / EVIDENCE_QUARANTINE`` until someone demonstrates the
   canonicalisation recipe they were sealed under. Guessing an encoding until
   one reproduces the digest would manufacture the provenance rather than
   establish it.

The incident is not closed. This appends a restoration event to it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, git_head, rel, sha_bytes, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

SNAPSHOTS = NS / "forensic_snapshots" / "INC-V2-001"

RESTORE = {
    "path": "research/experiments/EXP-0101/receipts/committed-bytes-verification.json",
    "pinned_by": "research/experiments/EXP-0101/receipts/receipts.json",
    "pinned_sha256": ("sha256:287003fa2da00f1d81970b5c7b4c8a286a84a00e281957dc7f3dfe19c67bb28f"),
    "blob": "e305521066691b34219297c96d9968c7d51c73cf",
}

QUARANTINE = [
    {
        "path": "docs/audit/HOSTILE_REVIEW_2026-08-19.md",
        "pinned_by": "docs/ip/receipts/submission-package-index-2026-08-19.json",
        "pinned_sha256": (
            "sha256:93420f8b05de5d7c4f64ddd1f0015fdf748b9934ae75c7edcd39117af18c4071"
        ),
        "has_generator": False,
    },
    {
        "path": "docs/repro/TEST_SCOPE_STATUS.json",
        "pinned_by": "docs/ip/receipts/submission-package-index-2026-08-19.json",
        "pinned_sha256": (
            "sha256:0c12365dcf854a239a655cba995d04e33ae1009a8b8d1a2a04b936b6270a39ed"
        ),
        "has_generator": True,
    },
    {
        "path": (
            "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/"
            "question-set-v8-dev-2026-08-19.json"
        ),
        "pinned_by": (
            "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/"
            "v8-development-arm-run-2026-08-19.json"
        ),
        "pinned_sha256": (
            "sha256:1d0f2a775ea244b1a03cb954b60c4dd3fc14ce432c3b8997f3f1072bea4fa09c"
        ),
        "has_generator": True,
    },
]

SELF_HASH = [
    "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json",
    "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-holdout.json",
]


def blob_bytes(object_id: str) -> bytes:
    out = subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return out.stdout


def restore(apply: bool) -> dict[str, object]:
    target = ROOT / RESTORE["path"]
    before = target.read_bytes()
    before_sha = sha_bytes(before)

    pinned = blob_bytes(str(RESTORE["blob"]))
    pinned_sha = sha_bytes(pinned)
    if pinned_sha != RESTORE["pinned_sha256"]:
        raise SystemExit(
            "the blob does not hash to the pinned digest; refusing to restore. "
            f"blob={pinned_sha} pinned={RESTORE['pinned_sha256']}"
        )

    # Snapshot first, always, even on a dry run. Restoring is what destroys the
    # current bytes, so the copy has to exist before the write, not after it.
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    snapshot = SNAPSHOTS / (Path(RESTORE["path"]).name + ".pre-restoration")
    if snapshot.exists() and snapshot.read_bytes() != before:
        raise SystemExit(
            f"{rel(snapshot)} exists and holds different bytes; refusing to "
            "overwrite a forensic snapshot"
        )
    snapshot.write_bytes(before)

    restored = False
    after_sha = before_sha
    if apply and before_sha != pinned_sha:
        target.write_bytes(pinned)
        after_sha = sha_file(target)
        restored = True

    return {
        "path": RESTORE["path"],
        "pinned_by": RESTORE["pinned_by"],
        "source": "git_object_database:" + str(RESTORE["blob"]),
        "pinned_sha256": RESTORE["pinned_sha256"],
        "sha256_before_restoration": before_sha,
        "sha256_after_restoration": after_sha,
        "binding_verifies_after_restoration": after_sha == RESTORE["pinned_sha256"],
        "restored": restored,
        "already_matched": before_sha == pinned_sha,
        "forensic_snapshot": rel(snapshot),
        "forensic_snapshot_sha256": sha_bytes(before),
        "superseding_receipt_written": False,
        "what_the_drift_was": (
            "the file was regenerated against a later commit. The pinned bytes "
            "attest 25 of 25 receipts at commit 82ca6c4; the bytes found on disk "
            "attest 27 of 27 at commit e804a47. Both report GREEN. The later "
            "attestation is the more complete one, which is why the bytes it "
            "occupied are preserved as a forensic snapshot rather than discarded "
            "— but it is not what receipts.json pinned, so it cannot stand under "
            "that binding."
        ),
        "not_claimed": (
            "that the later attestation was wrong, or that restoring these bytes "
            "re-establishes anything beyond this one binding"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="snapshot and verify, but do not write the restored bytes",
    )
    args = parser.parse_args()

    restoration = restore(apply=not args.dry_run)

    body = {
        "schema": "tavonel.v2.inc_v2_001_disposition.v1",
        "mode": "dry-run" if args.dry_run else "apply",
        "incident": "INC-V2-001",
        "incident_state": "OPEN — restoration event appended, incident not closed",
        "authority": "founder rulings, 2026-08-21",
        "git_head": git_head(),
        "forensic_input": "research/tavonel_eval_v2/receipts/latest/"
        "inc-v2-001-provenance-forensic.json (pointer, not evidence)",
        "restoration": restoration,
        "permanent_historical_quarantine": {
            "state": "EVIDENCE_QUARANTINE — permanent",
            "rule": (
                "the pinned bytes exist in no source on this machine. These "
                "bindings cannot be re-established, and no future artifact may be "
                "presented as the evidence the old receipt described."
            ),
            "regeneration_rule": (
                "old unrecoverable artifact != regenerated artifact. A generator "
                "may be re-run, but its output takes a new artifact id, a new "
                "version and a new receipt, and inherits nothing from the old "
                "binding."
            ),
            "nothing_regenerated_here": True,
            "artifacts": QUARANTINE,
        },
        "self_hash_disposition": {
            "state": "UNVERIFIED_SELF_HASH / EVIDENCE_QUARANTINE",
            "rule": (
                "held until the canonicalisation recipe these receipts were "
                "sealed under is demonstrated. An encoding chosen because it "
                "happens to reproduce the digest would manufacture the "
                "provenance, not establish it."
            ),
            "no_encoding_guessed": True,
            "artifacts": SELF_HASH,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable("inc-v2-001-disposition", body, tool=Path(__file__).resolve())
    print(
        "restored="
        + str(restoration["restored"])
        + " binding_verifies="
        + str(restoration["binding_verifies_after_restoration"])
        + " -> "
        + written["receipt"]
    )
    if args.dry_run:
        return 0
    return 0 if restoration["binding_verifies_after_restoration"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
