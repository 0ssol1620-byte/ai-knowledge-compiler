"""Enumerate the V2R3 universe from the fresh acquisition, and prove it disjoint.

AN ADAPTER over the V2R2 enumerator, for the reason the freeze ladder and the
fetcher are adapters: the traversal, the integrity rejection, the collision
handling and the two-pass disjointness subtraction must behave IDENTICALLY here,
and a second copy of them would be free to drift.

WHAT V2R3 ADDS: V2R2's own 270 spent lineages become an excluded set. Everything
V2R2 excluded stays excluded -- this study is not narrower than its predecessor
anywhere.

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
import sources_v2r3 as frame  # noqa: E402

CORPUS = NS / "artifacts" / "development" / "v2r3_corpus"
MANIFEST = CORPUS / "manifest.json"
OUT_DIR = NS / "artifacts" / "development" / "v2r3_universe"
OUT = OUT_DIR / "v2r3_universe_candidates.json"
SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r3_universe_enumeration.v1"

BASE_REL = "research/tavonel_eval_v2/artifacts/development/v2r2_corpus"
OUR_REL = "research/tavonel_eval_v2/artifacts/development/v2r3_corpus"

V2R2_UNIVERSE_GLOB = "identity-change-migration-closure-v2r2-universe--*.json"

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


def v2r2_spent_set() -> dict[str, Any]:
    """V2R2's 270, read from its frozen universe receipt by name.

    An explicit read of `pairs[].lineage_id`, not the permissive structural scan
    the quoted-anywhere sets use. The question here is not "did we mention this
    lineage somewhere"; it is "are these exactly the lineages that were
    measured", and for that the honest read is the declared one.

    The UNION across every V2R2 universe receipt, superseded ones included. A
    superseded universe was never measured, so its extra lineages are not spent
    in the strict sense -- excluding them anyway costs candidates and removes any
    argument about which receipt was the real one. The measured cohort is
    reported separately so the two counts can never be confused.
    """
    receipts = sorted((NS / "receipts").glob(V2R2_UNIVERSE_GLOB))
    ids: set[str] = set()
    for path in receipts:
        body = json.loads(path.read_text(encoding="utf-8"))
        ids |= {str(row["lineage_id"]) for row in body.get("pairs", ())}
    measured: set[str] = set()
    if receipts:
        measured = {
            str(row["lineage_id"])
            for row in json.loads(receipts[-1].read_text(encoding="utf-8")).get("pairs", ())
        }
    if not ids:
        raise RuntimeError(
            "V2R2's frozen universe receipt is absent or names no pairs, so the 270 "
            "spent lineages cannot be subtracted. A disjointness proof against an "
            "empty set proves nothing."
        )
    return {
        "id": "v2r2_spent",
        "lineage_count": len(ids),
        "measured_lineages": len(measured),
        "union_includes_superseded_receipts": True,
        "sources_present": [path.name for path in receipts],
        "sources_missing": [],
        "read_by": "explicit read of pairs[].lineage_id from the frozen receipt",
        "read_for": (
            "lineage ids only. No V2R2 verdict, count or violated case is read. The "
            "run was adjudicated INVALID_INSTRUMENT_CONTRACT, and that adjudication "
            "is neither re-opened nor re-interpreted here."
        ),
        "why_spent": (
            "V2R2 executed exactly once and its outcomes were read. An invalid "
            "instrument does not un-spend the material: a cohort whose results are "
            "known cannot be a prospective confirmatory denominator."
        ),
        "the_three_violating_lineages": (
            "ecfr:47:20:20.19, ecfr:7:3560:3560.105 and ecfr:7:3560:3560.102 are "
            "DEVELOPMENT / FORENSIC regression cases only and may never certify this "
            "closure."
        ),
        "coverage": (
            "complete. The union spans every V2R2 universe receipt; the measured "
            "cohort is the last one and is counted separately."
        ),
        "_ids": ids,
    }


#: The base's own implementation, captured AT IMPORT.
#:
#: `_bound()` rebinds `base.excluded_sets` to the function below, so reaching for
#: `base.excluded_sets()` from inside it calls itself -- which is not a subtle
#: failure: the first real enumeration run hit `RecursionError` after 996
#: frames. The lane test passed because it called the adapter from OUTSIDE the
#: binding scope, where the name still resolved to the base. A test that
#: exercises a wrapper outside the state the wrapper exists to create is not
#: exercising the wrapper.
_BASE_EXCLUDED_SETS = base.excluded_sets


def excluded_sets() -> list[dict[str, Any]]:
    """Everything V2R2 excluded, plus V2R2 itself.

    Built on the base's list rather than restated. Restating it would create a
    second declaration of what is spent, and the two would drift the first time
    one of them was edited -- which is the same defect as V2R2's hand-maintained
    quota and share.
    """
    return [*_BASE_EXCLUDED_SETS(), v2r2_spent_set()]


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
    """Point the shared enumerator at V2R3 for one call, then hand it back."""
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
    #: miss, not a no-op. The first version of this function read `rows`, which
    #: the enumerator does not emit -- it emits `pairs` -- so the loop ran zero
    #: times, the per-path assertion never fired, and 300 pairs were written
    #: still pointing into V2R2's corpus while the tool reported success.
    #: A guard that iterates an empty collection proves nothing (INC-V2-044).
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
