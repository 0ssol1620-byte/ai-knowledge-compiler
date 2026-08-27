#!/usr/bin/env python3
"""SFI3_ROOT_RESERVATION_V1 -- the cross-study contract that lets V2R4 and SFI3
be separate without either one waiting on the other.

THE PROBLEM THIS SOLVES

V2R4's INVARIANT_8 briefly carried `from_sfi3_material`, meaning *every lineage
id in SFI3's frozen acquisition*. That receipt does not exist and must not,
because the serial order is

    V2R4 PASS -> SFI3 freeze/acquisition -> SFI3 PASS -> four-link -> GPU

so the requirement was circular: V2R4 waited on SFI3's acquisition and SFI3
waited on V2R4's PASS. Neither could start. INVARIANT_8 is a disjointness
invariant over material that is ALREADY spent, and a held-out cohort nobody has
acquired is not spent material.

THE REPAIR: RESERVE CONTAINERS, NOT COHORTS

This artifact is frozen BEFORE V2R4's rung 0 and reserves the SOURCE CONTAINERS
SFI3 is permitted to draw from later -- repositories, CFR title/parts, SEC roots
and Wikipedia category roots -- plus the PREDECLARED REPLACEMENT POOL a failed
root may later be recovered from. Then:

    reserve containers
        -> V2R4 chooses its own containers OUTSIDE the reservation
        -> V2R4 executes
        -> SFI3 draws only from INSIDE the reservation

Both studies bind the same receipt by path and sha256. No future artifact is
needed to prove the predecessor's separation, and no present artifact
constrains the successor's outcome.

IDENTITY METADATA ONLY -- WHAT THIS MODULE MAY READ

Four literal tuples in `sources_sfi3` and three candidate tuples in
`replace_sfi3_roots`. Nothing else. No root is expanded, no listing is fetched,
no revision is opened, no pair is constructed, no acquisition artifact is read.
The pattern is `enumerate_v2_universe.sfi3_root_containers`, which established
it; `tests/test_sfi3_root_reservation.py` walks this module's AST to hold it
there rather than trusting the docstring.

Reading SFI3's contents to prove V2R4's disjointness would spend SFI3's
prospective material to buy an argument for its predecessor -- the same trade
the Wikipedia family was excluded to avoid.

FAIL CLOSED ON UNDECIDABLE CONTAINERS

Wikipedia roots are CATEGORIES. Whether an arbitrary article belongs to one is
not decidable from metadata, and the only way to decide it would be to expand an
SFI3 category. So `encyclopedia_wikipedia` is UNDECIDABLE here, and a study that
declares roots in an undecidable family is REFUSED rather than assumed disjoint.
V2R4 already excludes the family for the same reason, which is why it passes --
not because the check is inert.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "acquisition"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import replace_sfi3_roots as replacement  # noqa: E402
import sources_sfi3  # noqa: E402
from common import now, rel  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.sfi3_root_reservation.v1"
STEM = "sfi3-root-reservation"
RESERVATION_ID = "SFI3_ROOT_RESERVATION_V1"

FRAME_MODULE = NS / "acquisition" / "sources_sfi3.py"
REPLACEMENT_MODULE = NS / "tools" / "replace_sfi3_roots.py"

FAMILY_GIT = "git_docs"
FAMILY_ECFR = "regulation_ecfr"
FAMILY_SEC = "sec_edgar"
FAMILY_WIKIPEDIA = "encyclopedia_wikipedia"

#: Families whose container membership a lineage id settles on its own, from the
#: id and the reserved identities alone.
DECIDABLE_FAMILIES: tuple[str, ...] = (FAMILY_GIT, FAMILY_ECFR, FAMILY_SEC)

#: Families where it does not. Membership here needs the container EXPANDED, and
#: expanding an SFI3 root to prove a predecessor's disjointness is exactly the
#: trade this contract exists to refuse.
UNDECIDABLE_FAMILIES: dict[str, str] = {
    FAMILY_WIKIPEDIA: (
        "SFI3's Wikipedia roots are CATEGORIES. Whether an article belongs to one "
        "is not decidable from metadata, and deciding it would mean expanding an "
        "SFI3 category -- spending another study's prospective material to buy a "
        "disjointness argument here. A study declaring roots in this family is "
        "refused rather than assumed disjoint."
    ),
}


class ReservationRefused(RuntimeError):
    """The reservation cannot be built, verified, or proved separate from."""


def _sha_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    """A canonical digest of a JSON-able value, for comparing two readings."""
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )


# ---------------------------------------------------------------------------
# what SFI3 declared -- read as identity, never expanded


def declared_roots() -> dict[str, list[Any]]:
    """SFI3's four declared root tuples, as sorted identity lists.

    `sources_sfi3.SEC_ROOTS` is empty BY DECLARATION rather than by omission,
    which is a stronger statement than an absent attribute: it means every
    sec_edgar lineage is provably disjoint from SFI3 by the empty set, and it
    means a later edit that populates it changes this reservation's digest.
    """
    return {
        FAMILY_GIT: sorted(f"{root['owner']}/{root['repo']}" for root in sources_sfi3.GIT_ROOTS),
        FAMILY_ECFR: sorted(f"{title}-{part}" for title, part, _ in sources_sfi3.ECFR_ROOTS),
        FAMILY_WIKIPEDIA: sorted(sources_sfi3.WIKIPEDIA_CATEGORY_ROOTS),
        FAMILY_SEC: sorted(f"{a}-{b}" for a, b in sources_sfi3.SEC_ROOTS),
    }


def replacement_pool() -> dict[str, list[Any]]:
    """The PREDECLARED pool a failed SFI3 root may later be recovered from.

    Reserving only the declared roots would leave a hole exactly the size of the
    replacement policy: eleven git roots and one Wikipedia category have already
    been replaced once, under a criterion frozen before any candidate was
    checked. A later replacement drawn from outside this pool would put SFI3 into
    a container V2R4 was never told to avoid.

    Read from `replace_sfi3_roots`'s own candidate tuples, so the pool this
    reserves and the pool the replacer may draw from are one declaration.
    """
    return {
        FAMILY_GIT: sorted(
            f"{root['owner']}/{root['repo']}" for root in replacement.GIT_CANDIDATE_ROOTS
        ),
        FAMILY_ECFR: sorted(
            f"{title}-{part}" for title, part, _ in replacement.ECFR_CANDIDATE_ROOTS
        ),
        FAMILY_WIKIPEDIA: sorted(replacement.WIKIPEDIA_CANDIDATE_ROOTS),
        FAMILY_SEC: [],
    }


def reserved(reservation: dict[str, Any] | None = None) -> dict[str, set[str]]:
    """Declared roots UNION replacement pool, per family, as one reserved set.

    The union is the reservation: a container SFI3 may use, whether it uses it
    first or only after a failure. V2R4 must stay out of all of it.
    """
    body = reservation or build()
    out: dict[str, set[str]] = {}
    for family in (FAMILY_GIT, FAMILY_ECFR, FAMILY_WIKIPEDIA, FAMILY_SEC):
        out[family] = set(body["declared_roots"].get(family) or []) | set(
            body["replacement_pool"].get(family) or []
        )
    return out


# ---------------------------------------------------------------------------
# building and verifying the artifact


def build() -> dict[str, Any]:
    """The reservation body, derived fresh from the two modules every time.

    Not cached and not read back from a previous receipt: `verify` compares a
    stored reservation against THIS derivation, and a build that returned the
    stored copy would make the comparison a tautology.
    """
    declared = declared_roots()
    pool = replacement_pool()

    #: Candidates that are ALREADY declared roots. Expected, not a defect: the
    #: replacement round of 2026-08-23 promoted eleven git candidates and one
    #: Wikipedia category into the declared set, and they are still legal
    #: candidates in the pool they came from. Recorded rather than refused --
    #: an earlier draft of this function treated the overlap as a contradiction
    #: and refused every real reservation, which is a check that had never been
    #: run against the state it was guarding.
    already_promoted = {
        family: sorted(set(declared[family]) & set(pool[family]))
        for family in declared
        if set(declared[family]) & set(pool[family])
    }

    #: What WOULD be a defect: a family with declared roots and no unused
    #: candidate left. A later availability failure there could only be
    #: recovered by widening the reservation, and there is no post-V2R4
    #: widening -- so the failure would be unrecoverable rather than merely
    #: inconvenient. Reported, not refused: it is a capacity fact about a
    #: future that may not happen, and refusing now would block V2R4 on it.
    exhausted = sorted(
        family
        for family in declared
        if declared[family] and not (set(pool[family]) - set(declared[family]))
    )

    return {
        "schema": SCHEMA,
        "reservation_id": RESERVATION_ID,
        "sfi3_protocol_id": sources_sfi3.PROTOCOL_ID,
        "frame_module": rel(FRAME_MODULE),
        "frame_module_sha256": _sha_file(FRAME_MODULE),
        "replacement_module": rel(REPLACEMENT_MODULE),
        "replacement_module_sha256": _sha_file(REPLACEMENT_MODULE),
        "declared_roots": declared,
        "replacement_pool": pool,
        "reserved_counts": {
            family: len(set(declared[family]) | set(pool[family])) for family in declared
        },
        "already_promoted_from_the_pool": already_promoted,
        "families_with_no_unused_candidate": exhausted,
        "what_exhausted_means": (
            "a family whose replacement pool holds nothing it has not already "
            "promoted. A later availability failure there cannot be recovered "
            "without widening the reservation, and there is no post-V2R4 "
            "widening. Reported here so that is a known state rather than a "
            "surprise at SFI3 acquisition."
        ),
        "decidable_families": list(DECIDABLE_FAMILIES),
        "undecidable_families": dict(UNDECIDABLE_FAMILIES),
        "read_for": (
            "root IDENTITY metadata only. No root is expanded, no listing is "
            "fetched, no revision is opened, no pair is constructed and no SFI3 "
            "acquisition artifact is read."
        ),
        "what_this_does_not_carry": (
            "no revision contents, no qualifying pair counts, no change outcomes, "
            "no source fact transitions and no payload. A reservation that carried "
            "any of them would be a preview of SFI3's result."
        ),
        "no_post_v2r4_widening": (
            "this set is frozen before V2R4 rung 0 and is never widened afterwards. "
            "A later SFI3 root failure is recovered from inside the pool above, by "
            "the criterion `replace_sfi3_roots` froze before any candidate was "
            "checked -- never by reserving something new."
        ),
        "why_it_is_not_an_invariant_8_population": (
            "INVARIANT_8 excludes material that is already spent. SFI3's cohort "
            "does not exist yet and must not until V2R4 has passed, so requiring "
            "it there made a circular gate. Separation is a CONTAINER contract "
            "settled in advance, not a cohort comparison settled afterwards."
        ),
        "content_digest": _digest({"declared": declared, "pool": pool}),
        "built": now(),
    }


def verify(reservation: dict[str, Any]) -> dict[str, Any]:
    """A stored reservation still describes what the modules declare NOW."""
    if reservation.get("schema") != SCHEMA:
        raise ReservationRefused(f"{reservation.get('schema')!r} is not an SFI3 root reservation")
    if reservation.get("reservation_id") != RESERVATION_ID:
        raise ReservationRefused(
            f"the reservation names {reservation.get('reservation_id')!r}, not {RESERVATION_ID}"
        )

    current = build()
    moved = [
        field
        for field in ("frame_module_sha256", "replacement_module_sha256", "content_digest")
        if reservation.get(field) != current[field]
    ]
    if moved:
        raise ReservationRefused(
            f"the reservation no longer describes what SFI3 declares: {moved} moved. "
            "A container set that changed after it was reserved cannot be the set "
            "the other study was told to avoid."
        )
    if reservation.get("sfi3_protocol_id") != current["sfi3_protocol_id"]:
        raise ReservationRefused(
            "the reservation reserves containers for a different SFI3 protocol"
        )
    return {
        "held": True,
        "reservation_id": RESERVATION_ID,
        "sfi3_protocol_id": current["sfi3_protocol_id"],
        "reserved_counts": current["reserved_counts"],
        "content_digest": current["content_digest"],
        "recomputed": "derived again from the two modules, not read back",
    }


def freeze(*, no_receipt: bool = False) -> dict[str, Any]:
    """Write the reservation immutably, or return the body without writing."""
    body = build()
    if no_receipt:
        return body
    body["provenance"] = write_immutable(STEM, body, tool=Path(__file__).resolve(), protocol=None)
    return body


def latest_reservation(receipts: Path | None = None) -> Path | None:
    """The newest reservation receipt on disk, or None.

    A convenience for tooling that has not been handed a path. It is NOT the
    binding: rung 0 binds ONE path and ONE sha256, and this function's result is
    never substituted for that -- see `require_separation`, which takes the
    reservation body its caller resolved.
    """
    directory = receipts or (NS / "receipts")
    found = sorted(directory.glob(f"{STEM}--*.json"))
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# the separation proof both studies run


def require_separation(
    *,
    reservation: dict[str, Any],
    families: dict[str, list[str]],
    study: str,
) -> dict[str, Any]:
    """`study`'s declared containers are outside SFI3's reservation.

    `families` maps family name -> that study's declared container identities, in
    the same spelling `declared_roots` uses. Every family is checked; a family
    whose membership is not decidable from identity alone REFUSES rather than
    being reported clean, because "we could not tell" and "they do not overlap"
    are different answers and only one of them is a proof.
    """
    verify(reservation)
    held = reserved(reservation)

    undecidable = sorted(set(families) & set(UNDECIDABLE_FAMILIES))
    if undecidable:
        raise ReservationRefused(
            f"{study} declares roots in {undecidable}, where reservation membership "
            "is not decidable from identity metadata: "
            + " ".join(UNDECIDABLE_FAMILIES[family] for family in undecidable)
            + " Exclude the family from the candidate frame, or fail closed. Do not "
            "open an SFI3 category to prove this."
        )

    unknown = sorted(set(families) - set(held))
    if unknown:
        raise ReservationRefused(
            f"{study} declares families {unknown} that the reservation says nothing "
            "about. A family nobody reserved against is not a family proved disjoint."
        )

    collisions = {
        family: sorted(set(declared) & held[family])
        for family, declared in families.items()
        if set(declared) & held[family]
    }
    if collisions:
        raise ReservationRefused(
            f"{study} declares containers reserved for SFI3: {collisions}. The "
            "reservation covers declared roots AND the predeclared replacement "
            "pool, so a container that is only a replacement candidate is still "
            "reserved -- SFI3 may land there after a failure."
        )
    return {
        "held": True,
        "study": study,
        "reservation_id": RESERVATION_ID,
        "content_digest": reservation["content_digest"],
        "families_checked": sorted(families),
        "containers_checked": {family: len(v) for family, v in families.items()},
        "reserved_counts": {family: len(held[family]) for family in sorted(held)},
        "decided_on": "container identity only; no root on either side was expanded",
    }


def require_within_reservation(
    *,
    reservation: dict[str, Any],
    families: dict[str, list[str]],
) -> dict[str, Any]:
    """The reverse direction: SFI3's own frozen roots are INSIDE the reservation.

    Run by SFI3's freeze machinery before it reads a fresh payload. Without it
    the reservation would constrain only V2R4, and SFI3 could quietly draw from a
    container it never reserved -- which is the same overlap seen from the other
    side.
    """
    verify(reservation)
    held = reserved(reservation)
    escaped = {
        family: sorted(set(declared) - held.get(family, set()))
        for family, declared in families.items()
        if set(declared) - held.get(family, set())
    }
    if escaped:
        raise ReservationRefused(
            f"SFI3's frozen roots leave the reservation: {escaped}. A replacement "
            "may only be drawn from the pool that was predeclared before V2R4 "
            "chose its own containers; there is no post-V2R4 widening."
        )
    return {
        "held": True,
        "reservation_id": RESERVATION_ID,
        "content_digest": reservation["content_digest"],
        "families_checked": sorted(families),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "freeze", "verify"))
    parser.add_argument(
        "--reservation",
        type=Path,
        default=None,
        help="an existing reservation receipt, for `verify`",
    )
    args = parser.parse_args(argv)

    try:
        if args.action == "build":
            body = build()
        elif args.action == "freeze":
            body = freeze()
        else:
            path = args.reservation or latest_reservation()
            if path is None:
                raise ReservationRefused("no reservation receipt was named or found")
            body = verify(json.loads(Path(path).read_text(encoding="utf-8")))
            body["reservation_receipt"] = str(path)
    except ReservationRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=1))
        return 4
    print(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
