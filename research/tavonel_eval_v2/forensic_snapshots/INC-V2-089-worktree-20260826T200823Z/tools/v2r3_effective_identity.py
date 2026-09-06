"""The three-layer identity model for V2R3, and the effective state machine.

Founder ruling sections 4 and 5. V2R1 and V2R2 each failed by collapsing a layer:

    V2R1  mistook a RAW SNAPSHOT ID for a resolved identity
    V2R2  mistook a RESOLVER DECISION for an effective disposition

Both are the same error at different heights, so V2R3 names all three layers and
never lets one stand in for another:

    LAYER 1  ResolverDecisionSurface            what the resolver decided locally
    LAYER 2  IndependentQuarantineSurface       what the contract makes unsafe
    LAYER 3  EffectiveIdentityDispositionSurface   what may actually be ASSERTED

QUARANTINE DOES NOT CHANGE THE RESOLVER RESULT. It changes what production is
allowed to assert from that result. A unit the resolver settled as NEW, whose
identity is entangled in an unsettled neighbourhood, is still historically a NEW
decision -- and is still forbidden to be reported as added.

THE EFFECTIVE STATE MACHINE, predeclared and frozen before any V2R3 outcome is
opened.

For an AFTER-side unit:

    A  resolver AMBIGUOUS                          -> EFFECTIVE_UNRESOLVED
    B  resolver NEW      and implicated quarantined -> EFFECTIVE_UNRESOLVED
    C  resolver NEW      and not quarantined        -> EFFECTIVE_NEW
    D  resolver MATCHED  and counterpart quarantined -> EFFECTIVE_UNRESOLVED
    E  resolver MATCHED  and not quarantined        -> EFFECTIVE_MATCHED

For a BEFORE-side unit not consumed by an EFFECTIVE match:

    F  quarantined     -> EFFECTIVE_UNRESOLVED
    G  not quarantined -> EFFECTIVE_REMOVED

Row B is the one V2R2 did not have. Its absence is not a detail: V2R2 required
`unit_added` there while the compatibility contract forbade it and V2R2's own
clause (e) required `identity_unresolved`, which no implementation can satisfy.
The obligations below are therefore derived from the EFFECTIVE disposition and
from nothing else, and `v2r3_state_table` proves mechanically that no reachable
state requires and forbids the same record.

"Consumed by an EFFECTIVE match" is deliberate. A MATCHED decision overridden to
unresolved by row D does not consume its counterpart, so that counterpart falls
through to the before-side rules and lands on F -- unresolved, because the same
quarantine that overrode the match covers it. Reading consumption off Layer 1
would leave it accounted by a correspondence that was never asserted.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalMatch,
    assign_one_to_one,
)
from akc_cir.semantic_diff import ChangeKind  # noqa: E402
from v2r3_quarantine_oracle import (  # noqa: E402
    QuarantineOracle,
    build_oracle_quarantine,
    decisions_to_oracle_inputs,
)


class Effective(StrEnum):
    """Layer 3. The only vocabulary the invariant is allowed to grade against."""

    UNRESOLVED = "EFFECTIVE_UNRESOLVED"
    NEW = "EFFECTIVE_NEW"
    MATCHED = "EFFECTIVE_MATCHED"
    REMOVED = "EFFECTIVE_REMOVED"


#: The identity-sensitive records. Facet events -- `evidence_moved`,
#: `temporal_changed`, `metadata_changed` -- are NOT here and never will be:
#: they are emitted only after a correspondence exists, so they are events ON an
#: identity rather than assertions about one. Founder ruling forbids letting one
#: discharge an accounting obligation.
IDENTITY_RECORDS: tuple[ChangeKind, ...] = (
    ChangeKind.UNIT_ADDED,
    ChangeKind.UNIT_REMOVED,
    ChangeKind.MODIFIED_CLAIM,
)
UNRESOLVED_RECORD = ChangeKind.IDENTITY_UNRESOLVED


class StateNotTotal(RuntimeError):
    """A unit reached zero effective dispositions, or more than one."""


@dataclass(frozen=True)
class EffectiveUnit:
    """One unit's journey through all three layers, kept whole.

    Layer 1 is retained rather than discarded once Layer 3 is computed. An
    adjudication that cannot see the resolver decision behind an effective
    disposition cannot tell an override from an agreement, and telling those
    apart is the entire content of the V2R2 finding.
    """

    logical_id: str
    side: str
    resolver_state: str
    quarantined: bool
    implicated_identity: str | None
    effective: Effective
    rule: str
    counterpart: str | None = None


@dataclass(frozen=True)
class EffectiveSurface:
    """Layer 3 over both sides of one revision pair."""

    after: tuple[EffectiveUnit, ...]
    before: tuple[EffectiveUnit, ...]
    matched_pairs: tuple[tuple[str, str], ...]
    quarantine: QuarantineOracle
    resolver_census: dict[str, int] = field(default_factory=dict)

    @property
    def units(self) -> tuple[EffectiveUnit, ...]:
        return self.after + self.before

    def of(self, effective: Effective) -> tuple[EffectiveUnit, ...]:
        return tuple(u for u in self.units if u.effective is effective)

    def as_dict(self) -> dict[str, Any]:
        census: dict[str, int] = {}
        for unit in self.units:
            census[unit.effective.value] = census.get(unit.effective.value, 0) + 1
        overrides = [
            u for u in self.units if u.quarantined and u.resolver_state in ("NEW", "MATCHED")
        ]
        return {
            "effective_census": census,
            "resolver_census": dict(self.resolver_census),
            "quarantine_members": len(self.quarantine.members),
            "matched_pairs": len(self.matched_pairs),
            "matched_with_differing_raw_ids": sum(1 for b, a in self.matched_pairs if b != a),
            #: The count that distinguishes "the quarantine did nothing" from
            #: "the quarantine did something". A V2R3 PASS over a cohort with
            #: zero overrides could not have exercised rows B or D at all.
            "quarantine_overrides": len(overrides),
            "quarantine_overrides_by_resolver_state": {
                state: sum(1 for u in overrides if u.resolver_state == state)
                for state in ("NEW", "MATCHED")
            },
        }


def classify_after(
    logical_id: str,
    resolver_state: str,
    implicated: str | None,
    counterpart: str | None,
    quarantine: QuarantineOracle,
) -> EffectiveUnit:
    """Rows A through E, in the frozen order."""
    if resolver_state == "AMBIGUOUS":
        return EffectiveUnit(
            logical_id, "after", resolver_state, True, implicated, Effective.UNRESOLVED, "A"
        )
    if resolver_state == "NEW":
        #: `implicated` is the identity the decision speaks about, which for a
        #: NEW decision is the incoming unit's own id -- `assign_one_to_one`
        #: seeds `logical_id` from it. Computed the same way production computes
        #: it, because row B must fire on exactly the units production's guard
        #: fires on, and a second definition of "implicated" would be a second
        #: thing to drift.
        target = implicated or logical_id
        if target in quarantine:
            return EffectiveUnit(
                logical_id, "after", resolver_state, True, target, Effective.UNRESOLVED, "B"
            )
        return EffectiveUnit(logical_id, "after", resolver_state, False, target, Effective.NEW, "C")
    if resolver_state == "MATCHED":
        target = counterpart or implicated or logical_id
        if target in quarantine or logical_id in quarantine:
            return EffectiveUnit(
                logical_id,
                "after",
                resolver_state,
                True,
                target,
                Effective.UNRESOLVED,
                "D",
                counterpart,
            )
        return EffectiveUnit(
            logical_id,
            "after",
            resolver_state,
            False,
            target,
            Effective.MATCHED,
            "E",
            counterpart,
        )
    raise StateNotTotal(  # pragma: no cover -- the resolver has three states
        f"{logical_id!r} carries resolver state {resolver_state!r}, which the frozen "
        "state machine does not cover. An unhandled state is an unaccounted unit."
    )


def classify_before(logical_id: str, quarantine: QuarantineOracle) -> EffectiveUnit:
    """Rows F and G, for a before-side unit no EFFECTIVE match consumed."""
    if logical_id in quarantine:
        return EffectiveUnit(
            logical_id, "before", "UNCONSUMED", True, logical_id, Effective.UNRESOLVED, "F"
        )
    return EffectiveUnit(
        logical_id, "before", "UNCONSUMED", False, logical_id, Effective.REMOVED, "G"
    )


def build_effective_surface(
    before_units: list[Any], after_units: list[Any], source: str
) -> EffectiveSurface:
    """All three layers for one revision pair, in order, exactly once."""
    # ---- LAYER 1 ---------------------------------------------------------
    decisions = assign_one_to_one(
        [unit.fingerprint(source_lineage=source) for unit in after_units],
        [unit.fingerprint(source_lineage=source) for unit in before_units],
        resolver=LogicalIdentityResolver(),
    )
    before_ids = frozenset(unit.logical_id for unit in before_units)

    census: dict[str, int] = {}
    for decision in decisions:
        census[decision.match.name] = census.get(decision.match.name, 0) + 1

    # ---- LAYER 2 ---------------------------------------------------------
    unsettled, definite = decisions_to_oracle_inputs(after_units, decisions, before_ids)
    quarantine = build_oracle_quarantine(
        unsettled_decisions=unsettled, definite_matches=definite, before_ids=before_ids
    )

    # ---- LAYER 3 ---------------------------------------------------------
    after_states: list[EffectiveUnit] = []
    matched_pairs: list[tuple[str, str]] = []
    for incoming, decision in zip(after_units, decisions, strict=True):
        state = decision.match.name
        counterpart = (
            decision.logical_id
            if decision.match is LogicalMatch.MATCHED and decision.logical_id in before_ids
            else None
        )
        if decision.match is LogicalMatch.MATCHED and counterpart is None:
            #: A settled decision naming a counterpart the before side does not
            #: carry cannot be an effective match. Production emits UNIT_ADDED
            #: here, so the honest classification is the resolver-NEW path --
            #: and it still passes through the quarantine overlay rather than
            #: being waved through.
            state = "NEW"
        unit = classify_after(
            incoming.logical_id,
            state,
            decision.logical_id,
            counterpart,
            quarantine,
        )
        after_states.append(unit)
        if unit.effective is Effective.MATCHED and unit.counterpart:
            matched_pairs.append((unit.counterpart, unit.logical_id))

    consumed = {b for b, _ in matched_pairs}
    before_states = [
        classify_before(logical_id, quarantine) for logical_id in sorted(before_ids - consumed)
    ]

    surface = EffectiveSurface(
        after=tuple(after_states),
        before=tuple(before_states),
        matched_pairs=tuple(matched_pairs),
        quarantine=quarantine,
        resolver_census=census,
    )
    verify_total(surface, before_ids, frozenset(u.logical_id for u in after_units))
    return surface


def verify_total(
    surface: EffectiveSurface, before_ids: frozenset[str], after_ids: frozenset[str]
) -> None:
    """Exactly one effective disposition per unit, both sides, no exceptions.

    Raises rather than returning a verdict. A partition that is not total is not
    a weaker measurement, it is a broken instrument, and the caller has nothing
    useful to do with one.
    """
    problems: list[str] = []

    seen_after = [u.logical_id for u in surface.after]
    if len(seen_after) != len(set(seen_after)):
        problems.append("an after-side unit received more than one effective disposition")
    if set(seen_after) != after_ids:
        problems.append(
            f"after-side coverage is not exact: "
            f"{sorted(after_ids - set(seen_after))[:4]} unclassified"
        )

    consumed = {b for b, _ in surface.matched_pairs}
    seen_before = [u.logical_id for u in surface.before]
    if len(seen_before) != len(set(seen_before)):
        problems.append("a before-side unit received more than one effective disposition")
    if consumed & set(seen_before):
        problems.append(
            "a before-side unit is both consumed by an effective match and "
            f"classified on its own: {sorted(consumed & set(seen_before))[:4]}"
        )
    if set(seen_before) | consumed != before_ids:
        missing = before_ids - (set(seen_before) | consumed)
        problems.append(f"before-side coverage is not exact: {sorted(missing)[:4]} unaccounted")

    if len(consumed) != len(surface.matched_pairs):
        problems.append("a before-side unit was consumed by more than one effective match")
    after_matched = [a for _, a in surface.matched_pairs]
    if len(after_matched) != len(set(after_matched)):
        problems.append("an after-side unit holds more than one effective match")

    if problems:
        raise StateNotTotal("; ".join(problems))
