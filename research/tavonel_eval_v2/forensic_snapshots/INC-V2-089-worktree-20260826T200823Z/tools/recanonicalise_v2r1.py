"""Re-derive V2R1 canonical documents from the STORED RAW BYTES. No network.

Why this exists, stated plainly. The first eCFR canonicalisation in
`fetch_v2r1_corpus` invented its own unit shape -- `heading_path`, no `heading`,
no `text_sha256` -- which `selective_build.snapshots` cannot read. All 106 eCFR
pairs in the frozen universe were therefore unmeasurable, and would have failed
as a block for a reason that has nothing to do with the migration. That is the
same trap INC-V2-053 records against INVARIANT_6(d), arriving from a different
direction.

WHAT THIS MAY AND MAY NOT CHANGE, and why the distinction is the whole point.

Canonicalisation is a DETERMINISTIC TRANSFORM of bytes that are already frozen.
Re-running it cannot change which lineages are in the universe, because
selection is pinned by lineage id and raw digest, and this tool refetches
nothing -- it reads the `.raw` files acquisition already wrote. So it verifies,
for every side it touches, that the recomputed raw digest still equals the one
acquisition recorded, and REFUSES if any of them moved. If the raw bytes are
identical and the lineage set is identical, then nothing about selection has
moved and only the derived representation has.

It also refuses outright once a measurement receipt exists. Re-deriving
canonical documents after an outcome has been read would be exactly the
post-hoc reshaping the freeze exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "acquisition"),
    str(NS / "canonicalization"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import fetch_v2r1_corpus as fx  # noqa: E402
import selective_build as engine  # noqa: E402

CORPUS = NS / "artifacts" / "development" / "v2r1_corpus"
MANIFEST = CORPUS / "manifest.json"
MEASUREMENT_GLOB = "identity-change-migration-closure-v2r1--*.json"


class RecanonicaliseRefused(RuntimeError):
    """A precondition for re-deriving canonical documents is not met."""


def main() -> int:
    spent = sorted((NS / "receipts").glob(MEASUREMENT_GLOB))
    if spent:
        raise RecanonicaliseRefused(
            "V2R1 has already been measured. Re-deriving canonical documents after "
            f"an outcome has been read is post-hoc reshaping.\n  {spent[-1].name}"
        )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rewritten = 0
    unchanged = 0
    checked = 0

    for row in manifest["admitted"]:
        candidate = {
            "family": row["family"],
            "lineage_id": row["lineage_id"],
            "licence": row["licence"],
            "before": {"version": row["before"]["version"], "known_at": None},
            "after": {"version": row["after"]["version"], "known_at": None},
        }
        for side in ("before", "after"):
            entry = row[side]
            raw_path = CORPUS / entry["raw_path"]
            payload = raw_path.read_bytes()
            checked += 1

            #: Selection is pinned by the raw bytes. If they moved, this is not a
            #: re-derivation, and the tool has no business continuing.
            recomputed = "sha256:" + hashlib.sha256(payload).hexdigest()
            if recomputed != entry["raw_sha256_recorded"]:
                raise RecanonicaliseRefused(
                    f"{row['lineage_id']} {side}: raw bytes no longer match the recorded "
                    "digest. Canonicalisation may be re-derived; selection may not."
                )

            document = fx.canonicalise(candidate, side, payload)
            canonical_bytes = json.dumps(document, sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            )
            canonical_path = CORPUS / entry["canonical_path"]
            if canonical_path.read_bytes() == canonical_bytes:
                unchanged += 1
                continue

            canonical_path.write_bytes(canonical_bytes)
            entry["canonical_sha256_recorded"] = (
                "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
            )
            rewritten += 1

    #: Prove the point of the exercise: every side is now readable by the code
    #: production actually uses. A rewrite that left them unreadable would be a
    #: second defect wearing the first one's clothes.
    unreadable: list[str] = []
    for row in manifest["admitted"]:
        for side in ("before", "after"):
            document = json.loads(
                (CORPUS / row[side]["canonical_path"]).read_text(encoding="utf-8")
            )
            try:
                units, _ = engine.snapshots(document)
            except Exception as error:  # noqa: BLE001
                unreadable.append(f"{row['lineage_id']} {side}: {type(error).__name__} {error}")
                continue
            if len(units) < 3:
                unreadable.append(f"{row['lineage_id']} {side}: fewer than 3 snapshots")

    MANIFEST.write_text(
        json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )

    print(f"sides checked   : {checked}")
    print(f"rewritten       : {rewritten}")
    print(f"already correct : {unchanged}")
    print(f"unreadable now  : {len(unreadable)}")
    for line in unreadable[:10]:
        print(f"  {line}")
    return 1 if unreadable else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecanonicaliseRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        raise SystemExit(4) from None
