"""Carry the parent's frozen, unscored universe forward EXACTLY, or refuse.

WHAT MAKES THIS LEGITIMATE AT ALL. V2R3's 300 pairs were acquired under a frozen
rung 0, enumerated, frozen as a universe, and then never scored: the instrument
crashed before grading and the founder ruling of 2026-08-26 established
NONE_ESTABLISHED outcome disclosure. Material nobody has seen an outcome from is
still a prospective denominator. Material somebody HAS seen an outcome from is
not, whatever is done to it afterwards.

SO THE ONE THING THAT MUST NOT EXIST HERE IS SELECTION FREEDOM. The eligibility
argument is "no outcome was observed AND nothing could have been chosen", and
the second half is this module's job. There is:

    no candidate search      the parent's frozen universe IS the candidate set
    no oversampling          300 in, 300 out
    no subset choice         there is no filter, not even a trivially-true one
    no repair of one row     a bad row aborts the whole carry-forward
    no re-fetch              the network is never touched; see `why_no_refetch`

A FILTER THAT IS CURRENTLY A NO-OP IS STILL A SELECTION FUNCTION. It is one edit
from not being one, and nothing downstream could tell the difference. So the
rows are copied whole and compared whole, and the eight declared deltas are
DERIVED from that comparison rather than checked one at a time -- eight
individually-passing field checks can still miss a ninth field nobody listed.

ALL OR NOTHING, and that is not a slogan. If a payload digest no longer matches
disk, the correct move is NOT to re-fetch that document or drop that pair: both
are selection, and both would make the survivors a set chosen after the fact.
The correct move is to abandon carry-forward and acquire a fresh cohort. This
module therefore raises on the first defect and offers no repair path.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

PARENT_UNIVERSE_GLOB = "identity-change-migration-closure-v2r3-universe--*.json"
PARENT_PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"

#: The parent's realised composition, declared here so a change is a refusal
#: rather than a recomputation that agrees with whatever it just read.
EXPECTED_PAIRS = 300
EXPECTED_FAMILIES: dict[str, int] = {"git_docs": 133, "regulation_ecfr": 104, "sec_edgar": 63}

#: The deltas the founder ruling requires to be zero. Derived from a whole-row
#: comparison, never measured independently of it.
DECLARED_DELTAS = (
    "added_pairs",
    "removed_pairs",
    "replaced_pairs",
    "reordered_pairs",
    "changed_raw_digests",
    "changed_canonical_digests",
    "changed_family_labels",
    "changed_revision_ids",
)


class CarryForwardRefused(RuntimeError):
    """The inherited set is not exactly the parent's. Acquire fresh material."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def parent_universe_receipt(receipts: Path | None = None) -> Path:
    """The parent's LAST frozen universe receipt, by name.

    Read explicitly rather than by structural scan. The question is not "is there
    a V2R3 universe somewhere" but "which set of 300 was actually frozen", and a
    permissive read could answer with a superseded one.
    """
    found = sorted((receipts or NS / "receipts").glob(PARENT_UNIVERSE_GLOB))
    if not found:
        raise CarryForwardRefused(
            "the parent's frozen universe receipt is absent, so there is nothing to "
            "carry forward and no set to prove equality against."
        )
    return found[-1]


def load_parent(receipts: Path | None = None) -> dict[str, Any]:
    path = parent_universe_receipt(receipts)
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("protocol_id") != PARENT_PROTOCOL_ID:
        raise CarryForwardRefused(
            f"{path.name} declares protocol {body.get('protocol_id')!r}, not "
            f"{PARENT_PROTOCOL_ID!r}. This is not the parent's universe."
        )
    rows = body.get("pairs")
    if not isinstance(rows, list) or not rows:
        raise CarryForwardRefused(f"{path.name} names no pairs")
    if len(rows) != EXPECTED_PAIRS:
        raise CarryForwardRefused(
            f"{path.name} holds {len(rows)} pairs, not the declared {EXPECTED_PAIRS}. "
            "The set being inherited is not the set the ruling adjudicated."
        )
    families: dict[str, int] = {}
    for row in rows:
        families[row["family"]] = families.get(row["family"], 0) + 1
    if families != EXPECTED_FAMILIES:
        raise CarryForwardRefused(
            f"{path.name} composition is {families}, not the declared {EXPECTED_FAMILIES}."
        )
    return body


#: The parent's CANDIDATE manifest -- the input its rung 3 consumed, not the
#: output rung 3 produced. Located by the digest the parent's frozen universe
#: receipt recorded for it, never by path alone: a path can be repointed and a
#: file can be replaced, and the question here is "is this the manifest that
#: produced the frozen 300", which only the digest answers.
PARENT_MANIFEST = (
    NS / "artifacts" / "development" / "v2r3_universe" / "v2r3_universe_candidates.json"
)

#: Fields a CANDIDATE row shares with the FROZEN row derived from it. The frozen
#: shape is not the candidate shape -- rung 3 consumes `raw_sha256_recorded`,
#: re-hashes the file, and emits `raw_sha256` plus a verification flag -- so
#: whole-row equality between the two is not the right question. The right
#: question is whether every field that SURVIVES the transform is unchanged, and
#: that is this table.
CANDIDATE_TO_FROZEN = (
    ("family", "family"),
    ("before_version", "before_version"),
    ("after_version", "after_version"),
)
CANDIDATE_SIDE_TO_FROZEN = (
    ("raw_path", "raw_path"),
    ("canonical_path", "canonical_path"),
    ("raw_sha256_recorded", "raw_sha256"),
    ("canonical_sha256_recorded", "canonical_sha256"),
)


def load_parent_manifest(parent: dict[str, Any]) -> dict[str, Any]:
    """The parent's candidate manifest, pinned by the digest its receipt recorded."""
    recorded = (parent.get("manifest") or {}).get("sha256")
    if not recorded:
        raise CarryForwardRefused(
            "the parent's frozen universe receipt records no manifest digest, so the "
            "manifest that produced its 300 rows cannot be identified. A manifest "
            "found by path alone is a file with the right name, not the right file."
        )
    if not PARENT_MANIFEST.is_file():
        raise CarryForwardRefused(f"the parent's candidate manifest is absent: {PARENT_MANIFEST}")
    actual = _sha_file(PARENT_MANIFEST)
    if actual != recorded:
        raise CarryForwardRefused(
            "the parent's candidate manifest has changed since its universe froze.\n"
            f"  recorded: {recorded}\n  current:  {actual}\n"
            "Do not regenerate it. The manifest that produced the frozen 300 is the "
            "only legal input; a regenerated one is a new enumeration."
        )
    body = json.loads(PARENT_MANIFEST.read_text(encoding="utf-8"))
    rows = body.get("pairs")
    if not isinstance(rows, list) or len(rows) != EXPECTED_PAIRS:
        raise CarryForwardRefused(
            f"the parent's candidate manifest holds {len(rows or ())} rows, not {EXPECTED_PAIRS}."
        )
    return body


def compare_candidates_to_frozen(
    candidate_rows: list[dict[str, Any]], frozen_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Every field that survives rung 3's transform is unchanged.

    This is the 0a question: is the manifest about to be consumed the one that
    produced the parent's frozen 300? It is deliberately NOT whole-row equality,
    because the two shapes differ by construction -- and pretending otherwise
    would make the check either impossible or silently narrowed to nothing.

    THE TWO ORDERS ARE NOT THE SAME ORDER, and that is not a defect to look past.
    The candidate manifest is in acquisition order; rung 3 sorts its output by
    `(lineage_id, before_version, after_version)`. Comparing them positionally
    reports 300 mismatches and no missing lineages, which is what the first
    version of this function did. Ignoring order instead would be worse -- it
    would accept a reordering, which the ruling names as a delta that must be
    zero. So the rows are matched BY LINEAGE ID, and the orders are tied together
    separately: sorting the candidates by rung 3's key must reproduce the frozen
    order exactly.
    """
    candidate_ids = _lineages(candidate_rows)
    frozen_ids = _lineages(frozen_rows)
    for name, ids in (("candidate manifest", candidate_ids), ("frozen universe", frozen_ids)):
        if len(set(ids)) != len(ids):
            duplicates = sorted({one for one in ids if ids.count(one) > 1})
            raise CarryForwardRefused(
                f"the parent's {name} names a lineage more than once: {duplicates[:5]}. "
                "Matching by id would then be ambiguous."
            )
    if set(candidate_ids) != set(frozen_ids):
        added = sorted(set(candidate_ids) - set(frozen_ids))
        removed = sorted(set(frozen_ids) - set(candidate_ids))
        raise CarryForwardRefused(
            "the parent's candidate manifest and its frozen universe do not name the "
            f"same lineages.\n  in the manifest only: {added[:5]}\n"
            f"  in the frozen set only: {removed[:5]}"
        )

    #: The frozen order is rung 3's sort of the candidate rows. Asserted, so a
    #: reordering cannot hide behind an id-keyed comparison.
    sort_key = ("lineage_id", "before_version", "after_version")
    resorted = [
        str(row["lineage_id"])
        for row in sorted(candidate_rows, key=lambda item: tuple(str(item[k]) for k in sort_key))
    ]
    if resorted != frozen_ids:
        first = next(
            (i for i, (a, b) in enumerate(zip(resorted, frozen_ids, strict=True)) if a != b),
            None,
        )
        raise CarryForwardRefused(
            "sorting the parent's candidate rows by rung 3's key does not reproduce "
            f"the frozen order; they first differ at position {first}. The set may be "
            "the same, but the ORDER has moved, and reordered_pairs must be 0."
        )

    by_id = {str(row["lineage_id"]): row for row in candidate_rows}
    drift: list[str] = []
    compared = 0
    for frozen in frozen_rows:
        candidate = by_id[str(frozen["lineage_id"])]
        for here, there in CANDIDATE_TO_FROZEN:
            compared += 1
            if candidate.get(here) != frozen.get(there):
                drift.append(
                    f"{candidate['lineage_id']}.{here}: {candidate.get(here)!r} vs "
                    f"{frozen.get(there)!r}"
                )
        for side in ("before", "after"):
            one = candidate.get(side) or {}
            other = frozen.get(side) or {}
            for here, there in CANDIDATE_SIDE_TO_FROZEN:
                compared += 1
                if one.get(here) != other.get(there):
                    drift.append(
                        f"{candidate['lineage_id']}.{side}.{here}: {one.get(here)!r} vs "
                        f"{other.get(there)!r}"
                    )
    if drift:
        raise CarryForwardRefused(
            "the parent's candidate manifest no longer corresponds to its frozen "
            f"universe: {drift[:6]}{' ...' if len(drift) > 6 else ''}"
        )
    expected = len(frozen_rows) * (len(CANDIDATE_TO_FROZEN) + 2 * len(CANDIDATE_SIDE_TO_FROZEN))
    if compared != expected:
        raise CarryForwardRefused(
            f"{compared} field comparisons were made where {expected} were expected. "
            "A correspondence check that skipped fields proves nothing about them."
        )
    return {
        "held": True,
        "pairs": len(frozen_rows),
        "fields_compared": compared,
        "lineage_id_sets_identical": True,
        "frozen_order_is_the_candidate_rows_sorted_by_rung_3_key": True,
        "row_fields": [here for here, _ in CANDIDATE_TO_FROZEN],
        "side_fields": {here: there for here, there in CANDIDATE_SIDE_TO_FROZEN},
        "why_not_whole_row_equality": (
            "rung 3 transforms a candidate row into a frozen row: it consumes "
            "`raw_sha256_recorded`, re-hashes the file, and emits `raw_sha256` beside "
            "a verification flag. The shapes differ by construction, so the honest "
            "question is whether every surviving field is unchanged."
        ),
    }


def carry_rows(parent: dict[str, Any]) -> list[dict[str, Any]]:
    """Every row, in order, unchanged.

    Deliberately not a comprehension with a condition. There is no condition, and
    a `for row in rows if <always true>` would be a selection function waiting to
    become one.
    """
    return json.loads(json.dumps(parent["pairs"]))


# ---------------------------------------------------------------------------
# the payloads still on disk are the ones the parent froze


def verify_payload_digests(rows: list[dict[str, Any]], root: Path | None = None) -> dict[str, Any]:
    """Recompute every raw and canonical digest from disk. No network.

    The frozen receipt records what the bytes hashed to when they were acquired.
    Trusting that record here would make the carry-forward a claim about a file
    rather than about the material: the whole point of not re-fetching is that
    the bytes on disk ARE the experiment, so they are the thing that gets hashed.
    """
    root = root or ROOT
    checked = 0
    missing: list[str] = []
    mismatched: list[str] = []
    for row in rows:
        for side in ("before", "after"):
            entry = row.get(side) or {}
            for field, digest_field in (
                ("raw_path", "raw_sha256"),
                ("canonical_path", "canonical_sha256"),
            ):
                relative = entry.get(field)
                recorded = entry.get(digest_field)
                if relative is None or recorded is None:
                    raise CarryForwardRefused(
                        f"{row.get('lineage_id')}.{side} declares no {field}/"
                        f"{digest_field}. A payload with no pinned digest cannot be "
                        "carried forward, because there is nothing to re-prove."
                    )
                path = root / relative
                if not path.is_file():
                    missing.append(f"{row.get('lineage_id')}.{side}.{field} -> {relative}")
                    continue
                checked += 1
                actual = _sha_file(path)
                if actual != recorded:
                    mismatched.append(
                        f"{row.get('lineage_id')}.{side}.{field}: frozen {recorded} "
                        f"current {actual}"
                    )
    if missing or mismatched:
        raise CarryForwardRefused(
            "the inherited payloads are not the ones the parent froze.\n"
            f"  missing:     {missing[:5]}{' ...' if len(missing) > 5 else ''}\n"
            f"  mismatched:  {mismatched[:5]}{' ...' if len(mismatched) > 5 else ''}\n"
            "Do NOT re-fetch and do NOT drop the affected pairs -- both are "
            "selection. Abandon carry-forward and acquire a fresh cohort."
        )
    if checked != len(rows) * 4:
        raise CarryForwardRefused(
            f"{checked} payload digests were recomputed over {len(rows)} pairs; "
            f"{len(rows) * 4} were expected. A verification that skipped rows "
            "silently proves nothing about them (INC-V2-044)."
        )
    return {
        "held": True,
        "payloads_rehashed": checked,
        "pairs": len(rows),
        "network": "none",
        "how": (
            "every raw and canonical file named by every row was re-hashed from disk "
            "and compared to the digest the parent's frozen receipt pinned. Nothing "
            "was re-fetched, and the recorded digest was never trusted in place of "
            "the file."
        ),
    }


# ---------------------------------------------------------------------------
# exact-set equality


def _lineages(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["lineage_id"]) for row in rows]


def compare(
    parent_rows: list[dict[str, Any]], successor_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Whole-row equality, with the declared deltas derived from it."""
    parent_ids = _lineages(parent_rows)
    successor_ids = _lineages(successor_rows)
    parent_set, successor_set = set(parent_ids), set(successor_ids)

    added = sorted(successor_set - parent_set)
    removed = sorted(parent_set - successor_set)
    shared = parent_set & successor_set

    parent_by_id = {str(row["lineage_id"]): row for row in parent_rows}
    successor_by_id = {str(row["lineage_id"]): row for row in successor_rows}

    replaced = sorted(key for key in shared if parent_by_id[key] != successor_by_id[key])
    reordered = (
        0
        if parent_ids == successor_ids
        else sum(1 for one, other in zip(parent_ids, successor_ids, strict=False) if one != other)
    )
    if len(parent_ids) != len(successor_ids) and reordered == 0:
        reordered = abs(len(parent_ids) - len(successor_ids))

    def _field_delta(getter: Any) -> int:
        return sum(1 for key in shared if getter(parent_by_id[key]) != getter(successor_by_id[key]))

    deltas = {
        "added_pairs": len(added),
        "removed_pairs": len(removed),
        "replaced_pairs": len(replaced),
        "reordered_pairs": reordered,
        "changed_raw_digests": _field_delta(
            lambda row: (row["before"]["raw_sha256"], row["after"]["raw_sha256"])
        ),
        "changed_canonical_digests": _field_delta(
            lambda row: (row["before"]["canonical_sha256"], row["after"]["canonical_sha256"])
        ),
        "changed_family_labels": _field_delta(lambda row: row["family"]),
        "changed_revision_ids": _field_delta(
            lambda row: (row.get("before_version"), row.get("after_version"))
        ),
    }
    missing_delta = sorted(set(DECLARED_DELTAS) - set(deltas))
    if missing_delta:
        raise CarryForwardRefused(
            f"the comparison does not compute the declared deltas {missing_delta}"
        )

    nonzero = {name: value for name, value in deltas.items() if value}
    if nonzero:
        raise CarryForwardRefused(
            f"exact carry-forward FAILED: {nonzero}.\n"
            f"  added:    {added[:5]}\n"
            f"  removed:  {removed[:5]}\n"
            f"  replaced: {replaced[:5]}\n"
            "Do not repair individual rows and continue. The 300 pairs are eligible "
            "only because there is zero selection freedom; repairing one row creates "
            "it. Use a fresh cohort instead."
        )

    #: `replaced_pairs` IS the whole-row check -- it compares the row dicts
    #: whole, so a change to any field, declared or not, lands there. This
    #: assertion therefore cannot fire while the deltas are all zero, and a
    #: guard whose failure is impossible is not a guard (INC-V2-036). It stays as
    #: an equality STATEMENT rather than a second check, and the reasoning is
    #: written here so a future reader does not add the redundant check back
    #: believing the declared list is field-by-field. It is not: seven of the
    #: eight deltas exist to NAME what changed, and the eighth catches
    #: everything including what nobody named.
    assert parent_rows == successor_rows, (
        "replaced_pairs is 0 but the row lists differ, which is unreachable unless "
        "the comparison itself has been changed"
    )

    families: dict[str, int] = {}
    for row in successor_rows:
        families[row["family"]] = families.get(row["family"], 0) + 1
    if families != EXPECTED_FAMILIES:
        raise CarryForwardRefused(f"composition {families} != declared {EXPECTED_FAMILIES}")

    return {
        "held": True,
        "pair_count": len(successor_rows),
        "by_family": dict(sorted(families.items())),
        **deltas,
        "ordered_lineage_ids_identical": True,
        "whole_row_equality": True,
        "how": (
            "the rows were compared whole and in order; the eight declared deltas are "
            "derived from that comparison rather than measured beside it, and "
            "whole-row equality is asserted separately so a field outside the "
            "declared set cannot pass unnoticed."
        ),
        "no_selection_function": (
            "the parent's frozen universe is the complete candidate set. Nothing is "
            "searched, sampled, filtered or subset -- not even by a condition that "
            "is currently always true."
        ),
    }


def prove_exact_carry_forward(receipts: Path | None = None) -> dict[str, Any]:
    parent = load_parent(receipts)
    rows = carry_rows(parent)
    payloads = verify_payload_digests(rows)
    equality = compare(parent["pairs"], rows)
    manifest = load_parent_manifest(parent)
    correspondence = compare_candidates_to_frozen(manifest["pairs"], parent["pairs"])
    receipt = parent_universe_receipt(receipts)
    return {
        "held": True,
        "mode": "EXACT_SET",
        "parent_protocol_id": PARENT_PROTOCOL_ID,
        "parent_universe_receipt": receipt.name,
        "parent_universe_receipt_file_sha256": _sha_file(receipt),
        "parent_universe_sha256": parent.get("universe_sha256"),
        "parent_universe_run_id": (parent.get("provenance") or {}).get("run_id"),
        "parent_manifest_sha256": (parent.get("manifest") or {}).get("sha256"),
        "equality": equality,
        "candidate_correspondence": correspondence,
        "payload_verification": payloads,
        "network": "none",
        "reacquisition": "none",
        "all_or_nothing": (
            "any defect raises and offers no repair path. Repairing a row, dropping a "
            "row or re-fetching a payload would each create the selection freedom the "
            "eligibility argument depends on not existing."
        ),
    }


def main() -> int:
    try:
        body = prove_exact_carry_forward()
    except CarryForwardRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    print(json.dumps(body, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
