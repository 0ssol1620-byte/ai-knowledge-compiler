"""The expectation oracle for IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.

What a matched unit pair is *expected* to produce, derived from the declared
facet contract in `change_facets.py` and from nothing else.

The rule this module exists to hold is one line long:

    an expectation read off the thing under test is not an expectation.

The INC-V2-037 migration replaced one change predicate with another. Grading
the new predicate against the old one would say only that they disagree, which
is already known and which the founder's ruling forbids reading as ground truth
-- the old predicate is the defect under repair. Grading the new predicate
against itself would be a tautology. So the expectation is taken from the
unit pair's own fields, through the nine-facet partition, by code that has
never seen either predicate's answer.

**Nothing here imports `akc_cir`.** Not the diff, not the resolver, not the
fold. `IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.expectation_oracle` lists the
forbidden imports and the forbidden attribute reads, and INVARIANT_3 walks this
module's AST at closure time to check that the list still holds. A textual grep
would pass on an aliased import; the AST walk does not.

**What this module does NOT decide.** It does not decide whether production is
right. It states what production owes for each facet, and the closure runner
compares that obligation against what production actually emitted. Keeping the
two apart is the whole point: this module can be read on its own and checked
against the facet contract, without knowing what the answer came out as.
"""

from __future__ import annotations

from typing import Any

import change_facets as facets

SCHEMA = "tavonel.v2.identity_change_migration_closure.expectation_oracle.v1"

#: What production owes for one (facet, verdict) observation.
#:
#: `REQUIRE_TYPED_CHANGE` and `REQUIRE_FAIL_CLOSED` are separate names for a
#: reason. The first says the facet moved and a typed record must exist for it.
#: The second says the facet could not be compared and production must still
#: refuse to call it unchanged -- the fail-closed rule. Collapsing them into
#: one name would lose the distinction between "we saw a change" and "we could
#: not see", and losing that distinction is the INC-V2-037 defect class one
#: layer up.
REQUIRE_TYPED_CHANGE = "require_typed_change"
REQUIRE_FAIL_CLOSED = "require_fail_closed"
UNRESOLVED_NO_PRODUCTION_CHANNEL = "unresolved_no_production_channel"
IGNORED_BY_PREDECLARED_POLICY = "ignored_by_predeclared_policy"
NO_OBLIGATION = "no_obligation"

OBLIGATIONS: tuple[str, ...] = (
    REQUIRE_TYPED_CHANGE,
    REQUIRE_FAIL_CLOSED,
    UNRESOLVED_NO_PRODUCTION_CHANNEL,
    IGNORED_BY_PREDECLARED_POLICY,
    NO_OBLIGATION,
)

#: The only obligation that permits production to emit nothing at all. Named as
#: a set of one rather than tested inline, so a reader can see that the
#: permissive case is a closed list and that `unresolved` is not in it.
OBLIGATIONS_SATISFIED_BY_SILENCE: frozenset[str] = frozenset(
    {NO_OBLIGATION, IGNORED_BY_PREDECLARED_POLICY, UNRESOLVED_NO_PRODUCTION_CHANNEL}
)


class ContractBroken(RuntimeError):
    """A facet or verdict outside the declared vocabulary reached the oracle.

    Raised rather than defaulted. A default here would be the defect this whole
    closure is built to catch: an unknown mapped quietly onto a known.
    """


def obligation_for(facet: str, verdict: str, *, has_production_channel: bool) -> str:
    """What production owes for one facet observation. Total, and never lenient.

    `unchanged` is the ONLY verdict that discharges the obligation with
    silence. `unresolved` never does: with a production channel it becomes
    `REQUIRE_FAIL_CLOSED`, and without one it becomes
    `UNRESOLVED_NO_PRODUCTION_CHANNEL`, which is recorded as an unresolved
    observation and is never recorded as `unchanged`.
    """
    if facet not in facets.FACETS:
        raise ContractBroken(f"not a declared facet: {facet!r}")
    if verdict not in facets.VERDICTS:
        raise ContractBroken(f"not a declared verdict: {verdict!r}")

    if verdict == facets.IGNORED_BY_PREDECLARED_POLICY:
        return IGNORED_BY_PREDECLARED_POLICY
    if verdict == facets.UNCHANGED:
        return NO_OBLIGATION
    if not has_production_channel:
        # Both a CHANGED and an UNRESOLVED verdict land here when the unit
        # representation carries no data for the facet at all. Reporting either
        # as `no_obligation` would say the system is fine on a facet nothing
        # can see.
        return UNRESOLVED_NO_PRODUCTION_CHANNEL
    if verdict == facets.UNRESOLVED:
        return REQUIRE_FAIL_CLOSED
    return REQUIRE_TYPED_CHANGE


def facet_obligations(
    before: Any,
    after: Any,
    *,
    channels: dict[str, bool],
    ignored: frozenset[str] = frozenset(),
) -> dict[str, dict[str, str]]:
    """Per-facet verdict and obligation for one matched unit pair.

    `before` and `after` are duck-typed against `change_facets.UnitLike`. This
    signature deliberately accepts no diff, no change record and no predicate
    flag: there is no parameter through which production's answer could enter,
    which is what INVARIANT_3(b) checks.

    `channels` maps every declared facet to whether production has a channel
    for it. It comes from the frozen protocol, not from a default in code, so
    a channel cannot be quietly declared present by editing this module.
    """
    missing = set(facets.FACETS) - set(channels)
    if missing:
        raise ContractBroken(f"no channel declaration for: {sorted(missing)}")

    verdicts = facets.change_facets(before, after, ignored_facets=ignored)
    resolved: dict[str, dict[str, str]] = {}
    for facet in facets.FACETS:
        verdict = verdicts[facet]
        resolved[facet] = {
            "verdict": verdict,
            "obligation": obligation_for(
                facet, verdict, has_production_channel=bool(channels[facet])
            ),
        }
    return resolved


def unresolved_facets(resolved: dict[str, dict[str, str]]) -> tuple[str, ...]:
    """Facets this pair could not be compared on, in the partition's order."""
    return tuple(
        facet
        for facet in facets.FACETS
        if resolved[facet]["verdict"] == facets.UNRESOLVED
    )


def changed_facets(resolved: dict[str, dict[str, str]]) -> tuple[str, ...]:
    """Facets that moved, in the partition's order."""
    return tuple(
        facet for facet in facets.FACETS if resolved[facet]["verdict"] == facets.CHANGED
    )
