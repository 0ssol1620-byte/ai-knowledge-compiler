"""Which of several true statements applies to this question.

Masterplan §22 and §N17. The opening rule is a prohibition: *단순 `latest wins`
금지.* Two claims can both be true -- a global warranty policy of three years and
a customer contract of five -- and picking the newer one is not resolution, it is
a coin flip with a timestamp.

The ordering is fixed by §N17.3 and the order is the design:

    permission_visible → temporal_valid → scope_match → explicit_override
    → authority_rank → specificity → source_status → recency

Recency is last, deliberately. So is authority rank, which is further down than
intuition suggests, and §22.3's worked example shows why: for a Customer A
question the contract beats the global policy *because its scope names Customer
A*, not because CONTRACTUAL outranks OFFICIAL. Scope is element three and
authority is element five. Getting that order backwards would let a
higher-authority document that does not apply to the asker override one that does.

When the tuple runs out -- equal on every element and still disagreeing -- the
answer is `CONFLICTED`, not an average, not a vote and not the newest. §22.4:
*AI에게 하나를 임의로 고르게 하지 않는다.* Two contradictory claims with equal
standing is a fact about the corpus, and the honest response is to say so and ask
for review.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum

__all__ = [
    "AuthorityClass",
    "ClaimContext",
    "Resolution",
    "ResolutionRule",
    "ResolutionStatus",
    "RuleOutcome",
    "ScopedClaim",
    "SourceStatus",
    "rank_claims",
    "resolve_authority",
]


class AuthorityClass(IntEnum):
    """Element five of the tuple. Ordered, and the order is arguable by design.

    A regulation sits above a contract because a contract cannot waive a legal
    obligation; a contract sits above internal policy because it binds the
    company externally. Both are defaults a tenant may override in the rule DSL,
    which is why they are data rather than logic.
    """

    DRAFT = 0
    INFORMAL = 1
    DEPARTMENTAL = 2
    OFFICIAL = 3
    CONTRACTUAL = 4
    REGULATORY = 5


class SourceStatus(IntEnum):
    """Element seven. A withdrawn document is not merely older."""

    WITHDRAWN = 0
    SUPERSEDED = 1
    AMENDED = 2
    ACTIVE = 3


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    CONFLICTED = "CONFLICTED"
    NO_CANDIDATE = "NO_CANDIDATE"


class RuleOutcome(StrEnum):
    PREFER = "PREFER"
    EXCLUDE = "EXCLUDE"


@dataclass(frozen=True, slots=True)
class ClaimContext:
    """§22.1 -- the question being asked, which is what "applies" is relative to.

    A claim is not applicable in the abstract. The same warranty clause applies
    to Customer A and does not apply to Customer B, and a resolver that does not
    take the asker into account cannot express that.
    """

    subject: str
    as_of: datetime
    object_id: str | None = None
    customer_id: str | None = None
    region: str | None = None
    contract_id: str | None = None
    #: Permissions the asker holds. A claim requiring one they lack is not
    #: ranked lower -- it is not a candidate at all.
    permissions: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ScopedClaim:
    """One statement, with everything the ranking tuple needs to place it."""

    claim_id: str
    subject: str
    value: str
    authority: AuthorityClass
    source_status: SourceStatus = SourceStatus.ACTIVE
    #: Scope dimensions this claim constrains. An empty scope applies to
    #: everything, which makes it general rather than authoritative.
    scope: dict[str, str] = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime | None = None
    required_permission: str | None = None
    evidence_id: str | None = None

    def visible_to(self, context: ClaimContext) -> bool:
        if self.required_permission is None:
            return True
        return self.required_permission in context.permissions

    def temporally_valid(self, moment: datetime) -> bool:
        begun = self.valid_from is None or moment >= self.valid_from
        not_ended = self.valid_to is None or moment < self.valid_to
        return begun and not_ended

    def scope_match(self, context: ClaimContext) -> int:
        """How well this claim's scope fits the question. -1 means it does not.

        A claim scoped to Customer B is not a weaker answer for a Customer A
        question, it is the wrong answer, and returning a low score rather than a
        disqualification would let it win when nothing better exists.
        """
        available = {
            "customer_id": context.customer_id,
            "region": context.region,
            "contract_id": context.contract_id,
            "object_id": context.object_id,
        }
        matched = 0
        for dimension, required in self.scope.items():
            actual = available.get(dimension)
            if actual is None or actual != required:
                return -1
            matched += 1
        return matched

    @property
    def specificity(self) -> int:
        """Element six. A claim that names more dimensions says more."""
        return len(self.scope)


@dataclass(frozen=True, slots=True)
class ResolutionRule:
    """§N17.2's rule contract, as a predicate with a precedence.

    `evidence_requirement` is EXPLICIT by default: a rule that changes which
    claim wins is a governance act, and one that fires on an inferred condition
    would let an inference override a contract.
    """

    rule_id: str
    subject_type: str
    when: Callable[[ScopedClaim, ClaimContext], bool]
    precedence: int = 0
    outcome: RuleOutcome = RuleOutcome.PREFER
    evidence_requirement: str = "EXPLICIT"
    approved_by: str = ""

    def applies_to(self, claim: ScopedClaim, context: ClaimContext) -> bool:
        if self.subject_type != claim.subject:
            return False
        if self.evidence_requirement == "EXPLICIT" and claim.evidence_id is None:
            return False
        return self.when(claim, context)


@dataclass(frozen=True, slots=True)
class Resolution:
    status: ResolutionStatus
    claim: ScopedClaim | None
    candidates: tuple[ScopedClaim, ...] = ()
    required_review: bool = False
    reason: str = ""
    #: Audit only. How many claims the asker was not permitted to see. Kept out
    #: of the answer body: a user-visible "3 results hidden" is itself a
    #: disclosure about documents they have no access to.
    permission_filtered: int = 0

    def as_record(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "claim_id": self.claim.claim_id if self.claim else None,
            "value": self.claim.value if self.claim else None,
            "candidates": [c.claim_id for c in self.candidates],
            "required_review": self.required_review,
            "reason": self.reason,
        }


def _rank_tuple(
    claim: ScopedClaim, context: ClaimContext, *, override: int
) -> tuple[int, ...]:
    """§N17.3, in order. Higher is better at every position.

    Returned as a plain tuple so the comparison is Python's lexicographic one:
    element two only matters when element one ties, which is exactly what
    "앞 요소가 우선한다" means and is easy to get wrong with a weighted sum.
    """
    return (
        1 if claim.visible_to(context) else 0,
        1 if claim.temporally_valid(context.as_of) else 0,
        claim.scope_match(context),
        override,
        int(claim.authority),
        claim.specificity,
        int(claim.source_status),
        int(claim.recorded_at.timestamp()) if claim.recorded_at else 0,
    )


def rank_claims(
    claims: Sequence[ScopedClaim],
    context: ClaimContext,
    *,
    rules: Iterable[ResolutionRule] = (),
) -> list[tuple[tuple[int, ...], ScopedClaim]]:
    """Rank the applicable claims, best first, with the tuple that placed them."""
    applicable = [
        claim
        for claim in claims
        if claim.visible_to(context)
        and claim.temporally_valid(context.as_of)
        and claim.scope_match(context) >= 0
    ]
    rule_list = list(rules)

    scored: list[tuple[tuple[int, ...], ScopedClaim]] = []
    for claim in applicable:
        override = 0
        for rule in rule_list:
            if not rule.applies_to(claim, context):
                continue
            if rule.outcome is RuleOutcome.EXCLUDE:
                override = -1
                break
            override = max(override, rule.precedence)
        if override < 0:
            continue
        scored.append((_rank_tuple(claim, context, override=override), claim))

    scored.sort(key=lambda pair: (pair[0], pair[1].claim_id), reverse=True)
    return scored


def resolve_authority(
    claims: Sequence[ScopedClaim],
    context: ClaimContext,
    *,
    rules: Iterable[ResolutionRule] = (),
) -> Resolution:
    """Answer the question, or say honestly that the corpus does not.

    §N17.4: when two claims tie on every element of the tuple and say different
    things, the status is CONFLICTED and review is required. Averaging them,
    voting between them or taking the newer one all produce a confident answer
    the evidence does not support, and a downstream agent cannot tell the
    difference.
    """
    hidden = sum(1 for claim in claims if not claim.visible_to(context))
    ranked = rank_claims(claims, context, rules=rules)

    if not ranked:
        return Resolution(
            status=ResolutionStatus.NO_CANDIDATE,
            claim=None,
            reason=(
                "no claim is visible, temporally valid and in scope for this "
                "question"
            ),
            permission_filtered=hidden,
        )

    best_tuple, best = ranked[0]
    tied = [claim for tup, claim in ranked if tup == best_tuple]

    if len({claim.value for claim in tied}) > 1:
        return Resolution(
            status=ResolutionStatus.CONFLICTED,
            claim=None,
            candidates=tuple(tied),
            required_review=True,
            reason=(
                f"{len(tied)} claims are equal on every ranking element and "
                "disagree; choosing between them would be a guess presented as "
                "an answer"
            ),
            permission_filtered=hidden,
        )

    return Resolution(
        status=ResolutionStatus.RESOLVED,
        claim=best,
        candidates=tuple(claim for _, claim in ranked),
        reason=_explain(best_tuple, best, ranked),
        permission_filtered=hidden,
    )


_ELEMENTS = (
    "permission_visible",
    "temporal_valid",
    "scope_match",
    "explicit_override",
    "authority_rank",
    "specificity",
    "source_status",
    "recency",
)


def _explain(
    best: tuple[int, ...], claim: ScopedClaim, ranked: Sequence[tuple[tuple[int, ...], ScopedClaim]]
) -> str:
    """Name the element that actually decided it.

    An operator reading "the contract won" needs to know whether it won on scope
    or on authority, because those are different claims about the corpus and one
    of them may be wrong.
    """
    if len(ranked) < 2:
        return f"{claim.claim_id} is the only applicable claim"
    runner_up = ranked[1][0]
    for index, name in enumerate(_ELEMENTS):
        if best[index] != runner_up[index]:
            return (
                f"{claim.claim_id} wins on {name} "
                f"({best[index]} against {runner_up[index]})"
            )
    return f"{claim.claim_id} ties on every element and agrees with the rest"
