"""The authoritative identity-disposition surface for V2R2.

ONE resolver invocation, ONE partition, consumed by INVARIANT_6 clauses (c), (d)
and (e) alike. V2R1 failed as an instrument because each clause reconstructed its
own partial view of identity and clause (d) reconstructed the wrong one: it
equated `before_ids & after_ids` -- raw revision-local snapshot ids -- with
resolver-established cross-revision identity.

Those are different things and the architecture says so out loud.
`selective_build.snapshots` derives a snapshot logical id from
`source_id + explicit_path`, so an incoming unit's id changes when its path
changes. `LogicalIdentityResolver` exists precisely to bridge that: on MATCHED it
returns the BEFORE-side stable logical id while the incoming snapshot keeps its
own. `matched_pairs()` has documented this since V1 and reproduces
`assign_one_to_one` for exactly this reason.

So the rule this module enforces on itself:

    IDENTITY DISPOSITION comes from the resolver.
    A FACET EVENT is never an identity disposition.

`MODIFIED_CLAIM`, `EVIDENCE_MOVED`, `TEMPORAL_CHANGED` and the rest are emitted
only AFTER a correspondence has been established. They are events ON a match.
Counting one as evidence that a unit was accounted for is how V2R1's diagnosis
went wrong in its second draft, and it is why `EVIDENCE_MOVED` is deliberately
absent from every set below.

THE PARTITION IS MECHANICALLY EXHAUSTIVE. `verify_exhaustive()` proves every
before-side and after-side id lands in exactly one disposition, and the surface
refuses to be built if that fails -- a partition that is merely believed total is
the defect this module replaces.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)


class SurfaceNotExhaustive(RuntimeError):
    """The identity partition does not cover the population exactly once."""


@dataclass(frozen=True)
class Correspondence:
    """One resolver-established match across a revision boundary.

    The two ids MAY DIFFER, and that is the whole point. `before_logical_id` is
    the enduring identity the resolver selected; `after_snapshot_logical_id` is
    the incoming unit's revision-local id, which changes whenever its path does.
    """

    before_logical_id: str
    after_snapshot_logical_id: str


@dataclass(frozen=True)
class ResolverSurface:
    """The complete identity disposition of one revision pair."""

    matched: tuple[Correspondence, ...]
    new_after_ids: frozenset[str]
    ambiguous_after_ids: frozenset[str]
    ambiguous_candidate_before_ids: frozenset[str]
    unmatched_before_ids: frozenset[str]
    before_ids: frozenset[str]
    after_ids: frozenset[str]
    #: Every id an unsettled decision implicates: declared candidates, plus the
    #: before-side unit sharing the incoming's own id (the INC-V2-047 member).
    quarantine_members: frozenset[str] = field(default=frozenset())

    @property
    def matched_before_ids(self) -> frozenset[str]:
        return frozenset(c.before_logical_id for c in self.matched)

    @property
    def matched_after_ids(self) -> frozenset[str]:
        return frozenset(c.after_snapshot_logical_id for c in self.matched)

    def as_dict(self) -> dict[str, Any]:
        return {
            "matched": [
                {
                    "before_logical_id": c.before_logical_id,
                    "after_snapshot_logical_id": c.after_snapshot_logical_id,
                    "ids_differ": c.before_logical_id != c.after_snapshot_logical_id,
                }
                for c in self.matched
            ],
            "matched_count": len(self.matched),
            "matched_with_differing_ids": sum(
                1 for c in self.matched if c.before_logical_id != c.after_snapshot_logical_id
            ),
            "new_after_ids": sorted(self.new_after_ids),
            "ambiguous_after_ids": sorted(self.ambiguous_after_ids),
            "ambiguous_candidate_before_ids": sorted(self.ambiguous_candidate_before_ids),
            "unmatched_before_ids": sorted(self.unmatched_before_ids),
            "quarantine_members": sorted(self.quarantine_members),
            "before_population": len(self.before_ids),
            "after_population": len(self.after_ids),
        }


def build_surface(before_units: list[Any], after_units: list[Any], source: str) -> ResolverSurface:
    """Run the authoritative resolver ONCE and partition both sides.

    Uses the same `assign_one_to_one` + `LogicalIdentityResolver` production
    uses, invoked independently by the scorer -- not read back out of the diff.
    Reading dispositions off the diff would ask the diff to grade itself.
    """
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=source) for unit in after_units],
        [unit.fingerprint(source_lineage=source) for unit in before_units],
        resolver=LogicalIdentityResolver(),
    )

    before_ids = frozenset(unit.logical_id for unit in before_units)
    after_ids = frozenset(unit.logical_id for unit in after_units)

    matched: list[Correspondence] = []
    new_after: set[str] = set()
    ambiguous_after: set[str] = set()
    ambiguous_candidates: set[str] = set()
    quarantine: set[str] = set()

    for incoming, decision in zip(after_units, decisions, strict=True):
        if decision.match is LogicalMatch.AMBIGUOUS:
            ambiguous_after.add(incoming.logical_id)
            for candidate in decision.candidates or ():
                if candidate:
                    ambiguous_candidates.add(candidate)
                    quarantine.add(candidate)
            #: The INC-V2-047 member: a before-side unit carrying the incoming's
            #: own id is implicated by the same unsettled question and is named
            #: by nobody.
            if incoming.logical_id in before_ids:
                quarantine.add(incoming.logical_id)
            continue
        if decision.match is LogicalMatch.NEW:
            new_after.add(incoming.logical_id)
            continue
        counterpart = decision.logical_id
        if counterpart and counterpart in before_ids:
            matched.append(
                Correspondence(
                    before_logical_id=counterpart,
                    after_snapshot_logical_id=incoming.logical_id,
                )
            )
        else:
            #: A settled decision naming a counterpart that is not on the before
            #: side is not a match this surface can account for. Treated as NEW
            #: rather than silently dropped, because a disposition that vanishes
            #: is the failure mode this module exists to prevent.
            new_after.add(incoming.logical_id)

    consumed_before = frozenset(c.before_logical_id for c in matched)
    unmatched_before = before_ids - consumed_before

    surface = ResolverSurface(
        matched=tuple(matched),
        new_after_ids=frozenset(new_after),
        ambiguous_after_ids=frozenset(ambiguous_after),
        ambiguous_candidate_before_ids=frozenset(ambiguous_candidates),
        unmatched_before_ids=unmatched_before,
        before_ids=before_ids,
        after_ids=after_ids,
        quarantine_members=frozenset(quarantine),
    )
    verify_exhaustive(surface)
    return surface


def verify_exhaustive(surface: ResolverSurface) -> None:
    """Every id lands in exactly one disposition, and no unit is consumed twice.

    Raises rather than returning a verdict. An identity partition that is not
    total is not a weaker measurement, it is a broken instrument, and the caller
    has nothing useful to do with it.
    """
    problems: list[str] = []

    #: One-to-one conservation. `assign_one_to_one` is supposed to guarantee it;
    #: a guard that trusts the name of the function it is checking is not a
    #: guard.
    before_consumed = [c.before_logical_id for c in surface.matched]
    if len(before_consumed) != len(set(before_consumed)):
        problems.append("a before-side unit was consumed by more than one MATCHED decision")
    after_assigned = [c.after_snapshot_logical_id for c in surface.matched]
    if len(after_assigned) != len(set(after_assigned)):
        problems.append("an after-side unit was assigned more than one MATCHED decision")

    after_dispositions = (
        surface.matched_after_ids,
        surface.new_after_ids,
        surface.ambiguous_after_ids,
    )
    for index, first in enumerate(after_dispositions):
        for second in after_dispositions[index + 1 :]:
            overlap = first & second
            if overlap:
                problems.append(
                    f"after-side ids hold two dispositions at once: {sorted(overlap)[:4]}"
                )

    covered_after = surface.matched_after_ids | surface.new_after_ids | surface.ambiguous_after_ids
    missing_after = surface.after_ids - covered_after
    if missing_after:
        problems.append(f"after-side ids with no disposition: {sorted(missing_after)[:4]}")

    covered_before = surface.matched_before_ids | surface.unmatched_before_ids
    missing_before = surface.before_ids - covered_before
    if missing_before:
        problems.append(f"before-side ids with no disposition: {sorted(missing_before)[:4]}")
    both = surface.matched_before_ids & surface.unmatched_before_ids
    if both:
        problems.append(f"before-side ids both matched and unmatched: {sorted(both)[:4]}")

    if problems:
        raise SurfaceNotExhaustive("; ".join(problems))
