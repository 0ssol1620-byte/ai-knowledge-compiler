"""INVARIANT_6 for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.

Every clause reads ONE `EffectiveSurface`, and every obligation comes from
`v2r3_state_table.OBLIGATIONS` keyed by the EFFECTIVE disposition. That single
sentence is the repair.

    V1    graded against nothing like this at all
    V2R1  clause (d) equated raw snapshot-id equality with resolved identity
    V2R2  clause (d) read a resolver-local NEW as a final disposition while
          clause (e) read the quarantine -- so the two disagreed about the same
          unit and the instrument required and forbade `unit_added` at once

Here (c), (d) and (e) cannot disagree, because none of them decides anything.
The surface decides; they read. A disagreement between clauses is no longer
expressible rather than merely unlikely, and `v2r3_state_table.check_contract`
proves before any freeze that no reachable state carries contradictory
obligations.

WHAT SILENCE MEANS, per disposition -- the question both predecessors answered
with one fixed rule and got wrong in opposite directions:

    EFFECTIVE_MATCHED     silence is LEGITIMATE. Production publishes no matched
                          surface, so an unchanged matched unit emits nothing.
    EFFECTIVE_NEW         silence is a VIOLATION. A unit that genuinely begins
                          must be visible as added.
    EFFECTIVE_REMOVED     silence is a VIOLATION.
    EFFECTIVE_UNRESOLVED  silence is a VIOLATION. Withholding a definite outcome
                          without stating the uncertainty replaces a false
                          statement with no statement, and a fail-closed
                          endpoint cannot score an absence.

NAMED means a NON-EMPTY logical id. An unresolved record implicating a unit it
declines to identify names nothing, and a clause that accepted one could be
satisfied by silence wearing the shape of a statement.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.semantic_diff import ChangeKind  # noqa: E402
from v2r3_effective_identity import (  # noqa: E402
    UNRESOLVED_RECORD,
    Effective,
    EffectiveSurface,
)
from v2r3_state_table import compose, obligations_for  # noqa: E402


class DiffView:
    """What production said about each logical id, indexed two ways.

    `subject` is what a record asserts ABOUT an id. `candidate` is an id named
    INSIDE another id's unresolved record. The distinction is load-bearing:
    contract clause 4 says a declared candidate is already visible through the
    incoming unit's record and must not be given a second one of its own, so
    visibility must accept the candidate form -- while a DEFINITE outcome only
    ever arrives in subject position and is graded there.
    """

    def __init__(self, diff: Any) -> None:
        self.subject: dict[str, set[ChangeKind]] = defaultdict(set)
        self.candidate: dict[str, set[ChangeKind]] = defaultdict(set)
        for change in diff.changes:
            if change.logical_id:
                self.subject[change.logical_id].add(change.kind)
            for candidate in change.candidates or ():
                if candidate:
                    self.candidate[candidate].add(change.kind)

    def asserts(self, logical_id: str, kind: ChangeKind) -> bool:
        return kind in self.subject.get(logical_id, ())

    def visibly_unresolved(self, logical_id: str) -> bool:
        return UNRESOLVED_RECORD in self.subject.get(
            logical_id, ()
        ) or UNRESOLVED_RECORD in self.candidate.get(logical_id, ())


def _contributions(
    surface: EffectiveSurface,
) -> dict[str, list[tuple[Any, Any, Any]]]:
    """Every obligation held against each logical id, with the unit that holds it.

    A logical id is unique PER SIDE and not across sides, so one id can carry
    two real units: an unmatched before-side unit that ended and an unmatched
    after-side unit that began at the same path. Both are correctly reported --
    `unit_removed` for one, `unit_added` for the other -- and an accounting that
    indexes by id alone reads each record as a violation of the other unit.

    Found on the spent V2R2 corpus by writing exactly that accounting. It is the
    same family as V2R1's and V2R2's failures, one layer lower: an identity
    model that cannot tell two things apart.
    """
    contributions: dict[str, list[tuple[Any, Any, Any]]] = defaultdict(list)
    for unit in surface.units:
        rules = obligations_for(unit.effective, unit.side)
        contributions[unit.logical_id].append(
            (unit, frozenset(rules["required"]), frozenset(rules["forbidden"]))
        )
        if unit.effective is Effective.MATCHED and unit.counterpart:
            #: The before-side half of a correspondence is CONSUMED, so it gets
            #: no unit of its own -- but it is still spoken about, and a
            #: spurious `unit_removed` on it is exactly the assertion an
            #: effective match forbids. Contributed explicitly rather than left
            #: ungraded.
            before_rules = obligations_for(unit.effective, "before")
            contributions[unit.counterpart].append(
                (unit, frozenset(before_rules["required"]), frozenset(before_rules["forbidden"]))
            )
    return contributions


def check_effective_accounting(
    diff: Any, surface: EffectiveSurface
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(d). Every effective disposition's obligation, discharged.

    Obligations are COMPOSED per logical id before grading -- required by union,
    forbidden by unanimous intersection minus required -- so the composition is
    satisfiable by construction. V2R2 died of a contract that was not.

    Returns (violations, observations). `observations` counts the effective
    dispositions actually examined, so a reader can tell a clause that held from
    a clause that had nothing to hold over: a criterion nothing could have
    violated has not been met, it has been avoided (INC-V2-044).
    """
    view = DiffView(diff)
    violations: list[dict[str, Any]] = []

    for logical_id, entries in sorted(_contributions(surface).items()):
        #: Contributions from the SAME unit are unioned before composing, and
        #: only then are DIFFERENT units composed with the union/intersection
        #: rule. The distinction is not cosmetic. A matched correspondence whose
        #: before and after ids happen to be EQUAL contributes twice for one
        #: unit -- `unit_added` forbidden on the after side, `unit_removed`
        #: forbidden on the before side -- and intersecting those two would
        #: cancel both prohibitions and let a matched unit be reported added.
        #: Control 1 caught exactly that.
        #:
        #: One unit speaking twice is one obligation; two units sharing an id
        #: are two obligations that must agree before either binds.
        by_holder: dict[int, tuple[Any, set[ChangeKind], set[ChangeKind]]] = {}
        for unit, req, forb in entries:
            key = id(unit)
            if key not in by_holder:
                by_holder[key] = (unit, set(), set())
            by_holder[key][1].update(req)
            by_holder[key][2].update(forb)
        required, forbidden = compose(
            [(frozenset(req), frozenset(forb)) for _u, req, forb in by_holder.values()]
        )
        holders = [unit for unit, _r, _f in by_holder.values()]

        def described(units: list[Any] = holders) -> dict[str, Any]:
            return {
                "held_by": [
                    {
                        "side": u.side,
                        "resolver_state": u.resolver_state,
                        "quarantined": u.quarantined,
                        "effective": u.effective.value,
                        "rule": u.rule,
                    }
                    for u in units
                ]
            }

        for kind in sorted(required, key=lambda k: k.value):
            satisfied = (
                view.visibly_unresolved(logical_id)
                if kind is UNRESOLVED_RECORD
                else view.asserts(logical_id, kind)
            )
            if not satisfied:
                violations.append(
                    {
                        "logical_id": logical_id,
                        "clause": "d",
                        "missing_record": kind.value,
                        "why": (
                            f"the composed obligation for this identity REQUIRES a "
                            f"{kind.value} record and production emitted none. "
                            "Silence is a violation here"
                        ),
                        **described(),
                    }
                )

        for kind in sorted(forbidden, key=lambda k: k.value):
            if view.asserts(logical_id, kind):
                violations.append(
                    {
                        "logical_id": logical_id,
                        "clause": "d",
                        "forbidden_record": kind.value,
                        "why": (
                            f"the composed obligation for this identity FORBIDS "
                            f"{kind.value} and production asserted it"
                        ),
                        **described(),
                    }
                )

    return violations, len(surface.units)


def check_quarantine_channel(
    diff: Any, surface: EffectiveSurface, *, declared_record: str
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(e). Every unsettled identity is VISIBLE, not merely withheld.

    Reads the SAME surface (d) reads. `declared_record` is checked against the
    live enum rather than trusted as a string: a protocol declaring a kind
    production never emits would make this clause vacuous, which is this study's
    most-repeated defect.
    """
    violations: list[dict[str, Any]] = []
    if declared_record not in {kind.value for kind in ChangeKind}:
        violations.append(
            {
                "clause": "e",
                "why": (
                    f"the protocol declares record kind {declared_record!r}, which is "
                    "not a member of production's ChangeKind. A clause written over a "
                    "record nothing emits cannot be violated"
                ),
            }
        )
        return violations, 0

    view = DiffView(diff)
    unresolved = surface.of(Effective.UNRESOLVED)
    for unit in unresolved:
        if view.visibly_unresolved(unit.logical_id):
            continue
        violations.append(
            {
                "logical_id": unit.logical_id,
                "clause": "e",
                "side": unit.side,
                "effective": unit.effective.value,
                "rule": unit.rule,
                "why": (
                    "an identity whose effective disposition is unresolved is not "
                    f"named by any {declared_record} record, as subject or as a "
                    "non-empty candidate. Withholding the definite outcome without "
                    "stating the uncertainty is SILENT SUPPRESSION"
                ),
            }
        )
    return violations, len(unresolved)


def check_unresolved_not_reproduced(
    surface: EffectiveSurface, reproduced_ids: frozenset[str] | set[str]
) -> tuple[list[dict[str, Any]], int]:
    """INVARIANT_6(c). An unsettled identity may not enter matched-facet reproduction.

    The population is the effective one, so (c) and (d) can never disagree about
    who was unsettled. In V2R2 they were computed separately and did.

    This grades the SCORER's own reproduction step, not production's -- which is
    the point. Reproducing facets across a correspondence the effective model
    declined to assert would smuggle the assertion back in through the oracle.
    """
    unsettled = {u.logical_id for u in surface.of(Effective.UNRESOLVED)}
    overlap = sorted(unsettled & frozenset(reproduced_ids))
    return (
        [
            {
                "logical_id": logical_id,
                "clause": "c",
                "why": (
                    "an identity with an EFFECTIVE_UNRESOLVED disposition entered "
                    "matched-facet reproduction, which asserts the correspondence "
                    "the effective model declined to make"
                ),
            }
            for logical_id in overlap
        ],
        len(unsettled),
    )
