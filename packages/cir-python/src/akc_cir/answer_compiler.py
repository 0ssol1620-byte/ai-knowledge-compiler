"""Compiling a question into an answer that states what it rests on.

Masterplan §22.3. An answer is not a sentence -- it is a *claim set* bound to
the world state it was compiled against, carrying every evidence occurrence it
rests on and an outcome from a closed set. The closed set is the honesty
mechanism: CURRENT, STALE, CONFLICT, UNRESOLVED, NOT_AUTHORIZED. There is no
value for "probably fine", so there is nothing to smuggle a guess through.

The compiler is deliberately boring. It classifies what the question is *about*
(``classify_intent``), audits whether the draft claims were extracted against
the world state that is still ACTIVE (freshness), refuses answers the asker may
not see (fail-closed authorization), and hands what survives to §N17's
``resolve_authority``. Every refusal is a result, not an exception: STALE and
UNRESOLVED are findings about the corpus and belong in the answer record.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .authority import (
    ClaimContext,
    ResolutionRule,
    ResolutionStatus,
    ScopedClaim,
    SourceStatus,
    resolve_authority,
)
from .world_state import WorldState, WorldStateRegistry, WorldStateStatus

__all__ = [
    "AnswerOutcome",
    "CompiledAnswer",
    "DraftClaim",
    "EvidenceOccurrence",
    "QueryIntent",
    "audit_freshness",
    "classify_intent",
    "compile_answer",
]


class QueryIntent(StrEnum):
    """What kind of question is being asked. §22.3's ten intents.

    The intent decides which machinery answers: temporal intents route to the
    bitemporal timeline, authority and applicability to the §N17 resolver,
    impact to the dependency graph. Classification is lexical and
    deterministic on purpose -- the same question must compile the same way
    twice, or replay (§19) cannot trust its own input.
    """

    #: What holds right now.
    CURRENT = "current"
    #: What was *valid* at a stated moment (reality axis).
    AS_OF_VALID = "as_of_valid"
    #: What the system *knew* at a stated moment (knowledge axis).
    AS_KNOWN = "as_known"
    #: Which claim governs when several could.
    AUTHORITY = "authority"
    #: Whether a claim covers this subject at all.
    APPLICABILITY = "applicability"
    #: Whether sources disagree.
    CONFLICT = "conflict"
    #: How a value evolved.
    HISTORY = "history"
    #: Where a statement comes from.
    PROVENANCE = "provenance"
    #: What changing one thing touches.
    IMPACT = "impact"
    #: Everything else: find material rather than answer from it.
    SEARCH = "search"


#: Lexical rules, most specific first. The first rule whose keyword occurs wins;
#: ties are impossible because the scan is sequential. Korean and English share
#: one table so a mixed-language corpus classifies identically.
_INTENT_RULES: tuple[tuple[QueryIntent, tuple[str, ...]], ...] = (
    (
        QueryIntent.PROVENANCE,
        (
            "출처",
            "근거",
            "어느 문서",
            "어떤 문서",
            "provenance",
            "which document",
            "what document",
            "where did this come",
            "citation",
            "sourced from",
        ),
    ),
    (
        QueryIntent.HISTORY,
        (
            "연혁",
            "변천",
            "이력",
            "history",
            "over time",
            "used to be",
            "how has",
            "evolution",
        ),
    ),
    (
        QueryIntent.IMPACT,
        (
            "영향",
            "파급",
            "impact",
            "affect",
            "affected",
            "consequence",
            "downstream",
        ),
    ),
    (
        QueryIntent.AS_KNOWN,
        (
            "알고 있었",
            "시점에 알",
            "as known",
            "did we know",
            "believed at",
        ),
    ),
    (
        QueryIntent.AS_OF_VALID,
        (
            "as of",
            "기준일",
            "기준으로",
            "시점 기준",
            "유효했던",
            "유효한지",
            "valid at",
            "valid on",
            "was valid",
        ),
    ),
    (
        QueryIntent.APPLICABILITY,
        (
            "적용",
            "해당",
            "apply",
            "applies",
            "applicable",
            "covers",
            "in scope",
            "out of scope",
        ),
    ),
    (
        QueryIntent.AUTHORITY,
        (
            "권한",
            "우선",
            "authority",
            "authoritative",
            "who decides",
            "governs",
            "governing",
            "prevail",
            "precedence",
            "outrank",
            "final say",
        ),
    ),
    (
        QueryIntent.CONFLICT,
        (
            "충돌",
            "모순",
            "상충",
            "conflict",
            "contradict",
            "disagree",
            "inconsistent",
            "discrepancy",
        ),
    ),
    (
        QueryIntent.CURRENT,
        (
            "현재",
            "최신",
            "지금",
            "current",
            "currently",
            "today",
            "latest",
            "up to date",
        ),
    ),
)


def classify_intent(query: str) -> QueryIntent:
    """Classify a question lexically. Anything unrecognized is SEARCH.

    SEARCH is the fallback rather than an error because a question the rules
    cannot name still deserves retrieval -- what it must never receive is a
    mislabeled temporal or authority answer compiled by the wrong machinery.
    """
    normalized = query.casefold()
    for intent, keywords in _INTENT_RULES:
        if any(keyword in normalized for keyword in keywords):
            return intent
    return QueryIntent.SEARCH


class AnswerOutcome(StrEnum):
    """§22.3's closed outcome set. There is no sixth value to smuggle a guess.

    CURRENT is the only outcome that presents content as an answer. The other
    four are findings about the corpus or the asker, and each one names why the
    content was withheld -- which makes them results, not failures.
    """

    #: Fresh claims resolved cleanly under §N17.
    CURRENT = "CURRENT"
    #: A draft claim was not extracted against the ACTIVE world state.
    STALE = "STALE"
    #: Equal-standing claims disagree; §N17.4 requires review, not a pick.
    CONFLICT = "CONFLICT"
    #: Nothing applicable exists. An empty answer beats an invented one.
    UNRESOLVED = "UNRESOLVED"
    #: Every candidate is invisible to this asker. Nothing is disclosed.
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


@dataclass(frozen=True, slots=True)
class EvidenceOccurrence:
    """One citation inside a compiled answer.

    `source_status` rides along from §N17 because a claim whose backing source
    was since withdrawn does not deserve the same footing as one that still
    stands, and the answer record is where an auditor checks that.
    """

    claim_id: str
    evidence_id: str
    source_status: SourceStatus


@dataclass(frozen=True, slots=True)
class DraftClaim:
    """A candidate statement awaiting compilation, with its extraction state.

    `world_state_id` records which published world the claim was extracted
    against. It is what the freshness auditor reads: a claim cannot know on its
    own that the world moved under it.
    """

    claim: ScopedClaim
    world_state_id: str


@dataclass(frozen=True, slots=True)
class CompiledAnswer:
    """§22.3's compiled answer.

    The first four fields are the contract: *what* the answer claims
    (`claim_ids`), *which world* it was compiled against (`world_state_id`),
    *what it rests on* (`evidence_occurrences`), and *whether it may be served*
    (`outcome`). An answer whose outcome is anything but CURRENT names its
    claims only when naming them is itself the finding (STALE, CONFLICT); a
    refused answer carries no claim ids at all.
    """

    claim_ids: tuple[str, ...]
    world_state_id: str
    evidence_occurrences: tuple[EvidenceOccurrence, ...]
    outcome: AnswerOutcome
    intent: QueryIntent = QueryIntent.SEARCH
    reason: str = ""


def audit_freshness(
    drafts: Sequence[DraftClaim],
    active: WorldState,
) -> tuple[str, ...]:
    """Claim ids extracted against any world other than the ACTIVE one.

    §N22.2 publishes states atomically precisely so this check can be a simple
    pointer comparison. A mismatch means either the draft predates the current
    publish or someone rewrote its state id -- both read STALE, and neither is
    decided here.
    """
    active_id = active.world_state_id
    return tuple(
        draft.claim.claim_id
        for draft in drafts
        if draft.world_state_id != active_id
    )


def _occurrences(drafts: Sequence[DraftClaim]) -> tuple[EvidenceOccurrence, ...]:
    """Cite every evidence id in the given set, in draft order."""
    return tuple(
        EvidenceOccurrence(
            claim_id=draft.claim.claim_id,
            evidence_id=evidence_id,
            source_status=draft.claim.source_status,
        )
        for draft in drafts
        if (evidence_id := draft.claim.evidence_id) is not None
    )


def compile_answer(
    query: str,
    drafts: Sequence[DraftClaim],
    registry: WorldStateRegistry,
    context: ClaimContext,
    *,
    rules: Iterable[ResolutionRule] = (),
) -> CompiledAnswer:
    """Compile a question and its draft claims into a §22.3 answer.

    The gates run fail-closed and in order: authorization before freshness, so
    a claim the asker may not see reveals nothing -- not even that it went
    stale; freshness before resolution, so a superseded claim never gets the
    chance to win on merit. Whatever survives goes to §N17's resolver, and its
    verdict maps onto the closed outcome set.
    """
    intent = classify_intent(query)
    active = registry.current

    if not drafts:
        return CompiledAnswer(
            claim_ids=(),
            world_state_id=active.world_state_id if active else "",
            evidence_occurrences=(),
            outcome=AnswerOutcome.UNRESOLVED,
            intent=intent,
            reason="the draft set is empty",
        )
    if (
        active is None
        or active.status is not WorldStateStatus.ACTIVE
    ):
        return CompiledAnswer(
            claim_ids=(),
            world_state_id="",
            evidence_occurrences=(),
            outcome=AnswerOutcome.UNRESOLVED,
            intent=intent,
            reason="no ACTIVE world state is published",
        )

    visible = [draft for draft in drafts if draft.claim.visible_to(context)]
    if not visible:
        # §22.1: a claim requiring a permission the asker lacks is not a weak
        # candidate, it is no candidate. With none left, even the count of
        # stale ones would be a disclosure.
        return CompiledAnswer(
            claim_ids=(),
            world_state_id=active.world_state_id,
            evidence_occurrences=(),
            outcome=AnswerOutcome.NOT_AUTHORIZED,
            intent=intent,
            reason=(
                "every draft claim requires a permission this question's "
                "context does not hold"
            ),
        )

    stale_ids = audit_freshness(visible, active)
    if stale_ids:
        stale_set = set(stale_ids)
        stale_drafts = [d for d in visible if d.claim.claim_id in stale_set]
        fresh_ids = tuple(
            d.claim.claim_id for d in visible if d.claim.claim_id not in stale_set
        )
        foreign = ", ".join(sorted({d.world_state_id for d in stale_drafts}))
        note = (
            f"; fresh candidates were set aside: {', '.join(fresh_ids)}"
            if fresh_ids
            else ""
        )
        return CompiledAnswer(
            claim_ids=tuple(stale_ids),
            world_state_id=active.world_state_id,
            evidence_occurrences=_occurrences(stale_drafts),
            outcome=AnswerOutcome.STALE,
            intent=intent,
            reason=(
                f"{len(stale_ids)} claim(s) were extracted against {foreign}, "
                f"not the ACTIVE {active.world_state_id}{note}"
            ),
        )

    resolution = resolve_authority(
        [draft.claim for draft in visible], context, rules=rules
    )
    if resolution.status is ResolutionStatus.CONFLICTED:
        tied = [d for d in visible if d.claim in resolution.candidates]
        return CompiledAnswer(
            claim_ids=tuple(claim.claim_id for claim in resolution.candidates),
            world_state_id=active.world_state_id,
            evidence_occurrences=_occurrences(tied),
            outcome=AnswerOutcome.CONFLICT,
            intent=intent,
            reason=resolution.reason,
        )
    if resolution.status is ResolutionStatus.NO_CANDIDATE or resolution.claim is None:
        return CompiledAnswer(
            claim_ids=(),
            world_state_id=active.world_state_id,
            evidence_occurrences=(),
            outcome=AnswerOutcome.UNRESOLVED,
            intent=intent,
            reason=resolution.reason,
        )

    winner = resolution.claim
    winning_drafts = [d for d in visible if d.claim.claim_id == winner.claim_id]
    return CompiledAnswer(
        claim_ids=(winner.claim_id,),
        world_state_id=active.world_state_id,
        evidence_occurrences=_occurrences(winning_drafts),
        outcome=AnswerOutcome.CURRENT,
        intent=intent,
        reason=resolution.reason,
    )
