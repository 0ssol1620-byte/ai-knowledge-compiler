"""Enumerate the V2R4 universe from the fresh acquisition, and prove it disjoint.

AN ADAPTER over the V2R2 enumerator, for the reason the freeze ladder and the
fetcher are adapters: the traversal, the integrity rejection, the collision
handling and the two-pass disjointness subtraction must behave IDENTICALLY here,
and a second copy of them would be free to drift.

WHAT V2R4 ADDS: the 300 lineages V2R3 froze and V2R3R1 MEASURED become an
excluded set. Everything V2R3 excluded stays excluded -- this study is not
narrower than its predecessor anywhere.

WHY THOSE 300 ARE SPENT. V2R3R1 inherited them unscored by exact carry-forward
and then ran. Its instrument graded ONE invariant against a pass rule naming
eight (INC-V2-067), so the run establishes nothing about the other seven -- but
the one it graded, INVARIANT_6, is the one whose answer is now KNOWN for this
material. A cohort whose results are known cannot be a prospective confirmatory
denominator, and an adjudication of INCOMPLETE_INSTRUMENT_COVERAGE does not
un-spend it. Both universes name the same 300; the union is excluded.

THE SUBTRACTION IS TWO-PASS AND THAT MATTERS. V2R1 never exercised it, because
V2R1 had zero overlaps; the reporting-only version therefore survived to V2R2,
where 7 CFR 273 -- SFI1-spent and a VBC1 declared root -- had to be removed
rather than noted. Reporting an overlap leaves the row in the universe. Pass 1
identifies what must leave, the rows are excluded with EVERY set that named them,
and pass 2 re-proves disjointness over the survivors.

ONE WART, NAMED RATHER THAN HIDDEN. The base writes repo-root-relative payload
paths from a string LITERAL, not from its `CORPUS` global, so rebinding the
corpus does not reach it. The adapter therefore repoints those two fields per
row afterwards, and ASSERTS the expected prefix on every one of them -- a silent
miss would produce a universe whose rows point at another study's payloads,
which the digest verification would catch only if the bytes differed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import enumerate_v2r2_universe as base  # noqa: E402
import enumerate_v2r3_universe as parent  # noqa: E402
import sources_v2r4 as frame  # noqa: E402

CORPUS = NS / "artifacts" / "development" / "v2r4_corpus"
MANIFEST = CORPUS / "manifest.json"
OUT_DIR = NS / "artifacts" / "development" / "v2r4_universe"
OUT = OUT_DIR / "v2r4_universe_candidates.json"
SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r4_universe_enumeration.v1"

BASE_REL = "research/tavonel_eval_v2/artifacts/development/v2r2_corpus"
OUR_REL = "research/tavonel_eval_v2/artifacts/development/v2r4_corpus"

#: Both universes name the same 300 lineages. Both globs are read and unioned,
#: so which receipt a later reader considers authoritative cannot change what is
#: excluded here.
V2R3_UNIVERSE_GLOB = "identity-change-migration-closure-v2r3-universe--*.json"
V2R3R1_UNIVERSE_GLOB = "identity-change-migration-closure-v2r3r1-universe--*.json"

_OVERRIDE_TARGETS = (
    "frame",
    "CORPUS",
    "MANIFEST",
    "OUT_DIR",
    "OUT",
    "SCHEMA",
    "excluded_sets",
    "enumerate_universe",
    "_read_json",
)


def _verify_override_targets() -> None:
    missing = [name for name in _OVERRIDE_TARGETS if not hasattr(base, name)]
    if missing:
        raise RuntimeError(
            f"the V2R2 enumerator no longer defines {missing}. An override that "
            "lands on nothing is not an override. Fix the adapter rather than the "
            "base: V2R2's tooling is spent-run evidence."
        )


_verify_override_targets()


def v2r3_lineage_spent_set() -> dict[str, Any]:
    """The 300, read from BOTH frozen universe receipts by name.

    An explicit read of `pairs[].lineage_id`, not the permissive structural scan
    the quoted-anywhere sets use. The question here is not "did we mention this
    lineage somewhere"; it is "are these exactly the lineages that were
    measured", and for that the honest read is the declared one.

    NO VERDICT IS READ. Not the INVARIANT_6 outcome, not the violation count, not
    the adjudication. Lineage ids only. Reading the result to decide what to
    exclude would make this study's selection a function of its predecessor's
    outcome, which is the error one level up from reading a lineage's result.
    """
    receipts = sorted(
        [*(NS / "receipts").glob(V2R3_UNIVERSE_GLOB), *(NS / "receipts").glob(V2R3R1_UNIVERSE_GLOB)]
    )
    ids: set[str] = set()
    per_receipt: dict[str, int] = {}
    for path in receipts:
        body = json.loads(path.read_text(encoding="utf-8"))
        found = {str(row["lineage_id"]) for row in body.get("pairs", ())}
        per_receipt[path.name] = len(found)
        ids |= found
    if not ids:
        raise RuntimeError(
            "neither V2R3's nor V2R3R1's frozen universe receipt names any pairs, so "
            "the 300 spent lineages cannot be subtracted. A disjointness proof "
            "against an empty set proves nothing."
        )
    return {
        "id": "v2r3_and_v2r3r1_spent_300",
        "lineage_count": len(ids),
        "union_across_both_chains": True,
        "sources_present": [path.name for path in receipts],
        "per_receipt_pair_count": per_receipt,
        "sources_missing": [],
        "read_by": "explicit read of pairs[].lineage_id from the frozen receipts",
        "read_for": (
            "lineage ids only. No V2R3R1 verdict, invariant outcome, violation count "
            "or adjudication is read here. Selecting on a predecessor's result is "
            "the error one level up from reading a lineage's own result."
        ),
        "why_spent": (
            "V2R3 acquired and froze these 300 UNSCORED; V2R3R1 inherited them by "
            "exact carry-forward and MEASURED them. Their INVARIANT_6 outcome was "
            "read and reported, so a cohort whose results are known cannot be a "
            "prospective confirmatory denominator. The INC-V2-067 adjudication -- "
            "that the instrument graded one invariant of eight -- does not un-spend "
            "the material; it only means the other seven were never asked."
        ),
        "coverage": (
            "complete. Both chains' universe receipts are read and unioned, so which "
            "receipt is considered authoritative cannot change what is excluded."
        ),
        "_ids": ids,
    }


#: The parent adapter's list, captured AT IMPORT.
#:
#: `_bound()` rebinds `base.excluded_sets`, so reaching for `base.excluded_sets()`
#: from inside the replacement would call itself -- which is not a subtle
#: failure: the V2R3 adapter hit `RecursionError` after 996 frames the first time
#: it ran for real, and its lane test passed because it called the adapter from
#: OUTSIDE the binding scope, where the name still resolved to the base. A test
#: that exercises a wrapper outside the state the wrapper exists to create is not
#: exercising the wrapper.
#:
#: `parent.excluded_sets` is safe to call here for the same reason: it closes
#: over ITS OWN import-time capture of the base function, not over the live
#: attribute this adapter rebinds.
_PARENT_EXCLUDED_SETS = parent.excluded_sets


def excluded_sets() -> list[dict[str, Any]]:
    """Everything V2R3 excluded, plus the 300 V2R3R1 measured.

    Built on the parent's list rather than restated. Restating it would create a
    second declaration of what is spent, and the two would drift the first time
    one of them was edited -- which is the same defect as V2R2's hand-maintained
    quota and share.
    """
    return [*_PARENT_EXCLUDED_SETS(), v2r3_lineage_spent_set()]


def _bindings() -> dict[str, Any]:
    return {
        "frame": frame,
        "CORPUS": CORPUS,
        "MANIFEST": MANIFEST,
        "OUT_DIR": OUT_DIR,
        "OUT": OUT,
        "SCHEMA": SCHEMA,
        "excluded_sets": excluded_sets,
    }


@contextmanager
def _bound() -> Iterator[None]:
    """Point the shared enumerator at V2R4 for one call, then hand it back."""
    previous = {name: getattr(base, name) for name in _bindings()}
    for name, value in _bindings().items():
        setattr(base, name, value)
    try:
        wrong = [
            name for name, value in _bindings().items() if getattr(base, name, None) is not value
        ]
        if wrong:
            raise RuntimeError(
                f"the shared enumerator did not take this adapter's bindings: {wrong}"
            )
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def _repoint_payload_paths(body: dict[str, Any]) -> dict[str, Any]:
    """Repoint every payload path from the base's literal to this corpus.

    Asserted per field rather than replaced blindly. A row whose path did not
    carry the expected prefix would silently keep pointing into V2R2's corpus,
    and the digest verification downstream would only notice if the bytes there
    happened to differ.
    """
    rows = body.get("pairs", ())
    repointed = 0
    for row in rows:
        for side in ("before", "after"):
            entry = row.get(side) or {}
            for field in ("raw_path", "canonical_path"):
                value = entry.get(field)
                if value is None:
                    continue
                if not value.startswith(BASE_REL + "/"):
                    raise RuntimeError(
                        f"{row.get('lineage_id')}.{side}.{field} is {value!r}, which "
                        f"does not start with {BASE_REL!r}. The base enumerator's "
                        "path literal has moved and this repointing no longer knows "
                        "what it is rewriting."
                    )
                entry[field] = OUR_REL + value[len(BASE_REL) :]
                repointed += 1
    #: A repointing that found nothing to do over a NON-EMPTY universe is a
    #: miss, not a no-op. The V2R3 adapter's first version read `rows`, which the
    #: enumerator does not emit -- it emits `pairs` -- so the loop ran zero times,
    #: the per-path assertion never fired, and 300 pairs were written still
    #: pointing into V2R2's corpus while the tool reported success. A guard that
    #: iterates an empty collection proves nothing (INC-V2-044).
    if rows and not repointed:
        raise RuntimeError(
            f"{len(rows)} pairs were enumerated and not one payload path was "
            "repointed. The base enumerator's output shape has moved and this "
            "function is looking at the wrong key."
        )
    body["payload_paths_repointed"] = {
        "count": repointed,
        "from": BASE_REL,
        "to": OUR_REL,
        "why": (
            "the base enumerator writes repo-root-relative payload paths from a "
            "string literal rather than from its CORPUS global, so rebinding the "
            "corpus does not reach it. Every path is asserted to carry the expected "
            "prefix before it is rewritten."
        ),
    }
    return body


def enumerate_universe() -> dict[str, Any]:
    with _bound():
        return _repoint_payload_paths(base.enumerate_universe())


def main() -> int:
    body = enumerate_universe()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pairs = body.get("pair_count", len(body.get("pairs", ())))
    print(
        f"[enumerate] pairs {pairs} "
        f"repointed {body['payload_paths_repointed']['count']} paths "
        f"-> {OUT.relative_to(NS)}"
    )
    print(f"[enumerate] sufficiency {body['sufficiency']['state']} {body['by_family']}")
    print(f"[enumerate] disjointness_holds {body['disjointness_holds']}")
    return 0 if pairs else 1


if __name__ == "__main__":
    raise SystemExit(main())
