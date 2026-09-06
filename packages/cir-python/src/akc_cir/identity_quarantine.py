"""Which units an unsettled identity decision makes unsafe to classify.

INC-V2-047. `diff_documents` protected the units a resolver *named* as candidates
of an AMBIGUOUS decision, and nothing else:

    unsettled.update(decision.candidates)

That set is not the set the decision actually makes unsafe. A `logical_id` is a
pure function of source id and explicit path, so a restructured section produces
the SAME logical id on both sides carrying different text. The resolver scores
the incoming unit against a *different* before-side unit, lands in the review
band, and returns AMBIGUOUS naming that other unit. The before-side unit sharing
the incoming's own id is implicated by the same unsettled question and is named
by nobody — so it fell through to the removal loop and was reported
`UNIT_REMOVED`: a definite deletion asserted about a unit whose identity the
resolver had explicitly declined to settle.

The prospective closure `IDENTITY_CHANGE_MIGRATION_CLOSURE_V1` found nine such
cases across eight lineages, identically under the legacy and the migrated change
predicate — so this is not a migration regression. It is an older fail-closed
defect that the closure was rigorous enough to surface.

**The contract, stated once.** For each AMBIGUOUS or UNRESOLVED resolution, the
quarantine is the complete identity neighbourhood that decision makes unsafe:

    1. every candidate the decision declared;
    2. the candidate it selected, if it selected one;
    3. the exact logical-id counterpart of the incoming unit, when a before-side
       unit carries that id -- the member INC-V2-047 is about;
    4. transitively, any before-side unit that a *definite* decision matched to a
       member already quarantined by (1)-(3), because that match was decided
       against a unit whose own identity is unsettled.

A quarantined member may not receive a concrete identity-sensitive outcome:
no `UNIT_ADDED`, no `UNIT_REMOVED`, no `MODIFIED_CLAIM`. That is the half a
one-line `unsettled.add(...)` patch would have covered.

**It is not the whole requirement, and the other half is easy to get wrong.**
Suppressing the false `UNIT_REMOVED` is not a fix on its own: a unit that
vanishes from the diff entirely has had a false statement replaced by no
statement, which is the silent disappearance this programme keeps rediscovering
under other names. Every quarantined member must remain VISIBLE as explicitly
unresolved, so that a fail-closed endpoint (SFI3's E7) can observe it and score
it. This module decides membership; `semantic_diff` is responsible for emitting
the unresolved record, and `test_identity_quarantine.py` asserts both halves.

Nothing here changes identity normalisation, the matching algorithm, or the
facet-based change predicate. It reads decisions the resolver already made and
says which units they leave unsafe to speak about.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: Why a member is quarantined. Carried per member rather than as one blanket
#: reason: a reader auditing a diff needs to know which unsettled question
#: implicated this particular unit, and "it was in the quarantine" does not say.
DECLARED_CANDIDATE = "declared as a candidate of an unsettled identity decision"
SELECTED_CANDIDATE = "selected by a decision that was nonetheless unsettled"
LOGICAL_ID_COUNTERPART = (
    "shares the logical id of an incoming unit whose identity is unsettled; a "
    "restructured section yields the same id on both sides, so this unit is "
    "implicated by that question while being named by nobody (INC-V2-047)"
)
MATCHED_TO_A_QUARANTINED_UNIT = (
    "matched by a definite decision to a unit whose own identity is unsettled, "
    "so the match was decided against an unsafe counterpart"
)


@dataclass(frozen=True, slots=True)
class QuarantineMember:
    """One unit withheld from definite classification, and why."""

    logical_id: str
    reason: str
    #: The incoming unit whose unsettled decision implicated this one. Kept so a
    #: quarantine can be audited back to the decision that caused it rather than
    #: read as an unexplained absence.
    implicated_by: str


@dataclass(frozen=True, slots=True)
class IdentityQuarantine:
    """The complete set of units no definite identity outcome may be asserted about."""

    members: Mapping[str, QuarantineMember]

    def __contains__(self, logical_id: object) -> bool:
        return logical_id in self.members

    def __bool__(self) -> bool:
        return bool(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def member(self, logical_id: str) -> QuarantineMember:
        """The member record for `logical_id`, which MUST already be a member.

        `reason_for` and `implicated_by` answer `None` for a non-member, which
        is right for a caller that is asking whether a unit is quarantined. It
        is wrong for a caller that has *already* tested membership and is now
        building the unresolved record that states the uncertainty: there, a
        `None` coerced to a placeholder produces a well-formed-LOOKING record
        carrying an empty candidate, which a fail-closed consumer scanning for
        non-empty ids drops on the floor. That is silent disappearance wearing
        the costume of a statement.

        INC-V2-051: the call site in `semantic_diff` used `or ""` and
        `or "identity is unsettled"`. A probe over every quarantine path found
        the fallback was never once taken, because `QuarantineMember.reason`
        and `.implicated_by` are both non-optional. A guard whose failure is
        impossible is not a guard (INC-V2-036); it is a claim about an
        invariant, and the honest way to write that claim is to let the lookup
        fail loudly if the invariant ever breaks.
        """
        return self.members[logical_id]

    def reason_for(self, logical_id: str) -> str | None:
        member = self.members.get(logical_id)
        return member.reason if member else None

    def implicated_by(self, logical_id: str) -> str | None:
        member = self.members.get(logical_id)
        return member.implicated_by if member else None


def _add(
    members: dict[str, QuarantineMember], logical_id: str | None, reason: str, source: str
) -> None:
    """Record a member, keeping the FIRST reason recorded for it.

    First rather than last so the reason names the decision that originally made
    the unit unsafe, not whichever later pass happened to touch it again.
    """
    if not logical_id or logical_id in members:
        return
    members[logical_id] = QuarantineMember(
        logical_id=logical_id, reason=reason, implicated_by=source
    )


def build_quarantine(
    *,
    unsettled_decisions: Iterable[tuple[str, tuple[str, ...], str | None]],
    definite_matches: Iterable[tuple[str, str]] = (),
    before_ids: frozenset[str] | set[str] = frozenset(),
) -> IdentityQuarantine:
    """The units made unsafe by every unsettled decision in this diff.

    `unsettled_decisions` is `(incoming_logical_id, declared_candidates,
    selected_candidate_or_None)` per AMBIGUOUS/UNRESOLVED decision.
    `definite_matches` is `(incoming_logical_id, counterpart_logical_id)` for
    every decision that DID settle, used only for clause (4).
    `before_ids` is every logical id present on the before side, so clause (3)
    quarantines a counterpart only when one actually exists -- quarantining an
    id nothing carries would inflate the set without protecting anything.

    Clause (4) is applied to fixpoint. One pass would be enough for today's
    resolver, where a definite match names exactly one counterpart, but a
    quarantine that silently depended on that would be a guard whose correctness
    rests on a property nobody stated. The loop terminates because the member
    set only grows and is bounded by the units in the diff.
    """
    members: dict[str, QuarantineMember] = {}
    before = frozenset(before_ids)

    for incoming_id, candidates, selected in unsettled_decisions:
        for candidate in candidates:
            _add(members, candidate, DECLARED_CANDIDATE, incoming_id)
        _add(members, selected, SELECTED_CANDIDATE, incoming_id)
        #: Clause (3): the member INC-V2-047 is about.
        if incoming_id in before:
            _add(members, incoming_id, LOGICAL_ID_COUNTERPART, incoming_id)

    matches = tuple(definite_matches)
    while True:
        grew = False
        for incoming_id, counterpart in matches:
            if counterpart in members and incoming_id not in members:
                _add(members, incoming_id, MATCHED_TO_A_QUARANTINED_UNIT, counterpart)
                grew = True
        if not grew:
            break

    return IdentityQuarantine(members=dict(members))
