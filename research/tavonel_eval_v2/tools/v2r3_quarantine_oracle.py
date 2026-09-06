"""An INDEPENDENT identity-quarantine oracle, written from the contract.

Founder ruling section 6. This module implements clause 1 of
`docs/COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md` from the contract TEXT, and it
must never import production's implementation of the same rule:

    akc_cir.identity_quarantine   FORBIDDEN
    akc_cir.semantic_diff         FORBIDDEN

Using production's `build_quarantine` as the expected side of a measurement
would compare production to itself, and a comparison that can only agree is not
a measurement (INC-V2-044). `tests/test_v2r3_oracle_independence.py` proves the
forbidden imports are absent by walking this file's AST, so the guarantee is
mechanical rather than a promise in a docstring.

WHAT IS ALLOWED, and why the line is drawn here. `assign_one_to_one` and
`LogicalIdentityResolver` may be used to OBTAIN resolver decisions, because the
property under test is the integration of those decisions with the quarantine
and the diff -- not a second proof of the resolver algorithm. Re-implementing
the resolver would be measuring a different thing and measuring it worse.

CLAUSE 1, VERBATIM FROM THE CONTRACT:

    Quarantine the whole neighbourhood, not the named part of it. For each
    AMBIGUOUS/UNRESOLVED decision: every declared candidate; the selected
    candidate if any; the exact logical-id counterpart when a before-side unit
    carries that id; and transitively any before-side unit a *definite* decision
    matched to an already-quarantined member.

Four sub-clauses, implemented separately below and each labelled with the reason
it is a member, so a parity disagreement with production can be attributed to a
sub-clause rather than to the set as a whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Membership reasons. Local literals -- deliberately NOT imported from
#: production's module, which defines its own equivalents. Two independent
#: spellings that happen to agree are evidence; one spelling shared by both
#: sides is a tautology waiting to be discovered.
DECLARED_CANDIDATE = "declared_candidate_of_an_unsettled_decision"
SELECTED_CANDIDATE = "selected_candidate_of_an_unsettled_decision"
LOGICAL_ID_COUNTERPART = "before_side_unit_sharing_the_unsettled_incoming_id"
MATCHED_TO_A_QUARANTINED_UNIT = "definitely_matched_to_an_already_quarantined_member"


@dataclass(frozen=True)
class OracleMember:
    logical_id: str
    reason: str
    implicated_by: str


@dataclass(frozen=True)
class QuarantineOracle:
    """Every identity the contract makes unsafe to speak definitely about."""

    members: dict[str, OracleMember]

    def __contains__(self, logical_id: object) -> bool:
        return logical_id in self.members

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self.members)

    def reason_for(self, logical_id: str) -> str:
        return self.members[logical_id].reason

    def as_dict(self) -> dict[str, Any]:
        return {
            "member_count": len(self.members),
            "by_reason": {
                reason: sorted(m.logical_id for m in self.members.values() if m.reason == reason)
                for reason in (
                    DECLARED_CANDIDATE,
                    SELECTED_CANDIDATE,
                    LOGICAL_ID_COUNTERPART,
                    MATCHED_TO_A_QUARANTINED_UNIT,
                )
            },
        }


def _add(
    members: dict[str, OracleMember], logical_id: str | None, reason: str, implicated_by: str
) -> bool:
    """First reason wins, and an empty id is never a member.

    An empty logical id names nothing. Admitting one would inflate the set with
    a member no record could ever make visible, and clause 3 of the contract
    would then be unsatisfiable for it -- the same shape as the defect this
    whole study keeps finding, arriving from the expected side for once.
    """
    if not logical_id or logical_id in members:
        return False
    members[logical_id] = OracleMember(
        logical_id=logical_id, reason=reason, implicated_by=implicated_by
    )
    return True


def build_oracle_quarantine(
    *,
    unsettled_decisions: list[tuple[str, tuple[str, ...], str | None]],
    definite_matches: list[tuple[str, str]],
    before_ids: frozenset[str] | set[str],
) -> QuarantineOracle:
    """Clause 1 of the compatibility contract, derived independently.

    `unsettled_decisions` is `(incoming_logical_id, declared_candidates,
    selected_candidate_or_None)` for every AMBIGUOUS/UNRESOLVED decision.
    `definite_matches` is `(incoming_logical_id, counterpart_logical_id)` for
    every decision that settled. `before_ids` is every logical id present on the
    before side.
    """
    members: dict[str, OracleMember] = {}
    before = frozenset(before_ids)

    for incoming_id, candidates, selected in unsettled_decisions:
        # 1a. every declared candidate
        for candidate in candidates:
            _add(members, candidate, DECLARED_CANDIDATE, incoming_id)
        # 1b. the selected candidate if any
        _add(members, selected, SELECTED_CANDIDATE, incoming_id)
        # 1c. the exact logical-id counterpart, when a before-side unit carries
        #     that id. This is the member INC-V2-047 is about: named by nobody,
        #     and before the repair it escaped as `unit_removed`.
        if incoming_id in before:
            _add(members, incoming_id, LOGICAL_ID_COUNTERPART, incoming_id)

    # 1d. transitive closure, to FIXPOINT.
    #
    # One pass would be enough for today's resolver, where a definite match
    # names exactly one counterpart. A quarantine whose correctness silently
    # rested on that property would be a guard nobody had stated the
    # precondition for. The loop terminates because the member set only grows
    # and is bounded by the units in the diff.
    while True:
        grew = False
        for incoming_id, counterpart in definite_matches:
            if counterpart in members and incoming_id not in members:
                grew |= _add(members, incoming_id, MATCHED_TO_A_QUARANTINED_UNIT, counterpart)
        if not grew:
            break

    return QuarantineOracle(members=members)


def decisions_to_oracle_inputs(
    after_units: list[Any], decisions: list[Any], before_ids: frozenset[str] | set[str]
) -> tuple[list[tuple[str, tuple[str, ...], str | None]], list[tuple[str, str]]]:
    """Split resolver decisions into the two lists the oracle consumes.

    Kept here rather than at the call sites so every consumer partitions the
    decisions the same way. Two call sites that each decided for themselves what
    counts as `unsettled` is precisely how V2R2's clauses came to disagree.

    AMBIGUOUS is the unsettled kind. Everything that named a counterpart is a
    definite match. A decision that settled without naming one contributes to
    neither list: it implicates nothing and matched nothing.
    """
    #: Imported lazily and by name so this module's top level stays free of any
    #: production dependency the AST guard would have to make an exception for.
    from akc_cir.identity import LogicalMatch

    unsettled: list[tuple[str, tuple[str, ...], str | None]] = []
    definite: list[tuple[str, str]] = []
    for incoming, decision in zip(after_units, decisions, strict=True):
        if decision.match is LogicalMatch.AMBIGUOUS:
            unsettled.append(
                (incoming.logical_id, tuple(decision.candidates or ()), decision.logical_id)
            )
        elif decision.logical_id:
            definite.append((incoming.logical_id, decision.logical_id))
    return unsettled, definite
