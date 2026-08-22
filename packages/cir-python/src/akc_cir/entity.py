"""Deciding that two mentions are the same thing.

Masterplan §21 and §N16. The subtitle is the design: *evidence-first*. A resolver
that starts from name similarity will merge "Acme Corp" and "Acme Corporation"
correctly and "M-012" and "M-01 2" catastrophically, and it will do both with the
same confidence.

So the tiers are ordered by what kind of evidence they rest on, and the tier that
produced a match is carried on the result. §N16.2:

    1  a system-of-record identifier that matched exactly
    2  an approved alias table
    3  an exact composite key
    4  type plus relationship or context overlap
    5  name or semantic similarity
    6  an LLM proposal

A match at tier 1 and a match at tier 5 are different claims, and collapsing them
into one boolean loses the only thing a reviewer needs. Tier 6 has a hard rule:
*LLM은 candidate를 제안할 뿐 merge transaction을 실행하지 않는다.* It can raise a
pair for review and nothing else; there is no configuration that lets it merge.

Invariant 10 governs the thresholds: *false merge는 false split보다 비싸다.* Two
customer records wrongly merged mixes two companies' contracts, and unpicking it
afterwards means knowing which fact came from which -- which is exactly what the
merge destroyed. §N16.4 requires the merge be reversible, so `EntityRegistry`
keeps the pre-merge state rather than the ability to guess it back.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

__all__ = [
    "HIGH_RISK_TYPES",
    "EntityMention",
    "EntityRegistry",
    "MergeDecision",
    "MergeRecord",
    "MergeVerdict",
    "ResolutionTier",
    "resolve_mention",
]


class ResolutionTier(IntEnum):
    """§N16.2's hierarchy. Lower is stronger evidence."""

    SYSTEM_OF_RECORD = 1
    APPROVED_ALIAS = 2
    COMPOSITE_KEY = 3
    CONTEXT_OVERLAP = 4
    NAME_SIMILARITY = 5
    MODEL_PROPOSAL = 6


class MergeVerdict(StrEnum):
    AUTO_MERGE = "AUTO_MERGE"
    REVIEW = "REVIEW"
    NEW_ENTITY = "NEW_ENTITY"


#: §N16.3 -- types where a wrong merge does commercial or legal damage rather
#: than cosmetic damage, and which therefore never auto-merge below tier 3.
HIGH_RISK_TYPES = frozenset({"person", "customer", "contract", "supplier", "account"})

#: The tiers whose evidence is an identifier rather than a resemblance. Only
#: these can auto-merge a high-risk type.
_IDENTIFIER_TIERS = frozenset(
    {
        ResolutionTier.SYSTEM_OF_RECORD,
        ResolutionTier.APPROVED_ALIAS,
        ResolutionTier.COMPOSITE_KEY,
    }
)

_NON_ALNUM = re.compile(r"[^\w]+", re.UNICODE)


def normalize_mention(text: str) -> str:
    """Fold what should not distinguish two mentions of one thing.

    Deliberately weaker than it could be. Stripping every separator would make
    `M-012` and `M012` identical, which is usually right and is catastrophic when
    an asset scheme uses the separator to mean something. Case and surrounding
    punctuation only; anything more is an alias-table decision, not a string
    function's.
    """
    folded = unicodedata.normalize("NFKC", text).strip().casefold()
    return _NON_ALNUM.sub(" ", folded).strip()


@dataclass(frozen=True, slots=True)
class EntityMention:
    """§N16.1's mention. Evidence is required, not optional.

    A mention with no evidence id cannot be resolved by this module at all: the
    whole point of evidence-first is that a merge is a claim about two passages
    in two documents, and one that cannot name its passages is a claim about
    nothing.
    """

    mention_id: str
    text: str
    evidence_id: str
    type_candidate: str = ""
    attributes: Mapping[str, str] = field(default_factory=dict)
    external_ids: Mapping[str, str] = field(default_factory=dict)
    context_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError(
                f"{self.mention_id}: a mention needs an evidence id. A merge is a "
                "claim about two passages, and one that cannot name them is a "
                "claim about nothing."
            )

    @property
    def normalized(self) -> str:
        return normalize_mention(self.text)


@dataclass(frozen=True, slots=True)
class MergeDecision:
    verdict: MergeVerdict
    entity_id: str | None
    tier: ResolutionTier | None
    score: float
    reason: str
    candidates: tuple[str, ...] = ()

    @property
    def merged(self) -> bool:
        return self.verdict is MergeVerdict.AUTO_MERGE


@dataclass(frozen=True, slots=True)
class MergeRecord:
    """§N16.4 -- what a merge has to keep so it can be undone.

    Not "enough to reconstruct". The actual prior state: which mentions belonged
    to which entity before. Reconstructing it would mean re-running the resolver
    against a corpus that has since changed, and getting a different answer is
    the normal case rather than the exception.
    """

    merge_id: str
    entity_id: str
    absorbed_entity_id: str
    tier: ResolutionTier
    score: float
    previous_members: tuple[str, ...]
    absorbed_members: tuple[str, ...]
    decided_by: str = "system"


def _composite_key(mention: EntityMention) -> tuple[str, ...] | None:
    """A key made of the attributes, when there are enough to be a key.

    One attribute is not a composite key. `{plant: B}` matches every machine in
    plant B, and treating it as an identifier would merge the lot.
    """
    if len(mention.attributes) < 2:
        return None
    return tuple(
        f"{key}={normalize_mention(value)}"
        for key, value in sorted(mention.attributes.items())
    )


def _name_similarity(left: EntityMention, right: EntityMention) -> float:
    left_tokens = set(left.normalized.split())
    right_tokens = set(right.normalized.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _context_overlap(left: EntityMention, right: EntityMention) -> float:
    if not left.context_ids or not right.context_ids:
        return 0.0
    shared = left.context_ids & right.context_ids
    return len(shared) / len(left.context_ids | right.context_ids)


def resolve_mention(
    mention: EntityMention,
    candidates: Sequence[tuple[str, EntityMention]],
    *,
    aliases: Mapping[str, str] | None = None,
    name_threshold: float = 0.85,
    context_threshold: float = 0.60,
    model_proposals: Iterable[str] = (),
) -> MergeDecision:
    """Walk §N16.2's tiers in order and stop at the first that answers.

    Stopping at the first is what makes the tier meaningful. Combining tiers into
    a weighted score would let three weak resemblances outvote the absence of an
    identifier, and the result would carry a confident number with no way to see
    that no identifier was involved.

    `model_proposals` names entity ids an LLM suggested. They never merge --
    §N16.2 is explicit that the model proposes and does not execute -- so the
    strongest outcome available to tier 6 is REVIEW.
    """
    by_id = dict(candidates)
    high_risk = mention.type_candidate in HIGH_RISK_TYPES

    # Tier 1 -- a system of record said so.
    if mention.external_ids:
        matches = [
            entity_id
            for entity_id, other in candidates
            if any(
                other.external_ids.get(system) == value
                for system, value in mention.external_ids.items()
            )
        ]
        if len(matches) == 1:
            return MergeDecision(
                verdict=MergeVerdict.AUTO_MERGE,
                entity_id=matches[0],
                tier=ResolutionTier.SYSTEM_OF_RECORD,
                score=1.0,
                reason="an external system identifier matched exactly",
                candidates=(matches[0],),
            )
        if len(matches) > 1:
            return MergeDecision(
                verdict=MergeVerdict.REVIEW,
                entity_id=None,
                tier=ResolutionTier.SYSTEM_OF_RECORD,
                score=1.0,
                reason=(
                    "one external identifier matched several entities; the "
                    "system of record disagrees with itself"
                ),
                candidates=tuple(sorted(matches)),
            )

    # Tier 2 -- an alias a human approved.
    alias_target = (aliases or {}).get(mention.normalized)
    if alias_target and alias_target in by_id:
        return MergeDecision(
            verdict=MergeVerdict.AUTO_MERGE,
            entity_id=alias_target,
            tier=ResolutionTier.APPROVED_ALIAS,
            score=1.0,
            reason="an approved alias names this entity",
            candidates=(alias_target,),
        )

    # Tier 3 -- every attribute agrees, and there is more than one of them.
    key = _composite_key(mention)
    if key is not None:
        matches = [
            entity_id
            for entity_id, other in candidates
            if _composite_key(other) == key and other.normalized == mention.normalized
        ]
        if len(matches) == 1:
            return MergeDecision(
                verdict=MergeVerdict.AUTO_MERGE,
                entity_id=matches[0],
                tier=ResolutionTier.COMPOSITE_KEY,
                score=1.0,
                reason=f"composite key {'|'.join(key)} matched exactly",
                candidates=(matches[0],),
            )

    # Tier 4 -- same type, and the surrounding relationships overlap.
    contextual = sorted(
        (
            (_context_overlap(mention, other), entity_id)
            for entity_id, other in candidates
            if other.type_candidate == mention.type_candidate
        ),
        reverse=True,
    )
    # `> 0.0` as well as the threshold. A threshold of zero means "any overlap
    # counts", and zero overlap is not overlap -- without this, configuring the
    # threshold down merges two entities that share nothing.
    if contextual and contextual[0][0] > 0.0 and contextual[0][0] >= context_threshold:
        score, entity_id = contextual[0]
        return MergeDecision(
            verdict=MergeVerdict.REVIEW if high_risk else MergeVerdict.AUTO_MERGE,
            entity_id=None if high_risk else entity_id,
            tier=ResolutionTier.CONTEXT_OVERLAP,
            score=score,
            reason=(
                f"context overlap {score:.2f} with matching type"
                + (
                    f"; {mention.type_candidate} is high-risk and does not "
                    "auto-merge without an identifier"
                    if high_risk
                    else ""
                )
            ),
            candidates=(entity_id,),
        )

    # Tier 5 -- the names look alike. The weakest evidence that is still evidence.
    similar = sorted(
        ((_name_similarity(mention, other), entity_id) for entity_id, other in candidates),
        reverse=True,
    )
    if similar and similar[0][0] > 0.0 and similar[0][0] >= name_threshold:
        score, entity_id = similar[0]
        runner_up = similar[1][0] if len(similar) > 1 else 0.0
        if score - runner_up < 0.05 and len(similar) > 1:
            return MergeDecision(
                verdict=MergeVerdict.REVIEW,
                entity_id=None,
                tier=ResolutionTier.NAME_SIMILARITY,
                score=score,
                reason=(
                    f"two entities have equally similar names ({score:.2f} and "
                    f"{runner_up:.2f})"
                ),
                candidates=(entity_id, similar[1][1]),
            )
        return MergeDecision(
            verdict=MergeVerdict.REVIEW if high_risk else MergeVerdict.AUTO_MERGE,
            entity_id=None if high_risk else entity_id,
            tier=ResolutionTier.NAME_SIMILARITY,
            score=score,
            reason=(
                f"name similarity {score:.2f}"
                + (
                    f"; {mention.type_candidate} is high-risk and a resemblance "
                    "is not an identifier"
                    if high_risk
                    else ""
                )
            ),
            candidates=(entity_id,),
        )

    # Tier 6 -- a model thinks so. It may say so and nothing more.
    proposed = [entity_id for entity_id in model_proposals if entity_id in by_id]
    if proposed:
        return MergeDecision(
            verdict=MergeVerdict.REVIEW,
            entity_id=None,
            tier=ResolutionTier.MODEL_PROPOSAL,
            score=0.0,
            reason=(
                "a model proposed this match; §N16.2 lets it propose and not "
                "execute, so the strongest outcome available here is review"
            ),
            candidates=tuple(proposed),
        )

    return MergeDecision(
        verdict=MergeVerdict.NEW_ENTITY,
        entity_id=None,
        tier=None,
        score=0.0,
        reason="no tier produced a match",
    )


class EntityRegistry:
    """Entities and their mentions, with every merge reversible.

    §N16.4. `unmerge` restores the exact membership recorded at merge time rather
    than re-deriving it: re-running the resolver against a corpus that has since
    grown gives a different answer, and "different" is the normal case.
    """

    def __init__(self) -> None:
        self._members: dict[str, list[str]] = {}
        self._merges: list[MergeRecord] = []

    def add(self, entity_id: str, mention_id: str) -> None:
        self._members.setdefault(entity_id, []).append(mention_id)

    def members(self, entity_id: str) -> tuple[str, ...]:
        return tuple(self._members.get(entity_id, ()))

    @property
    def entity_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._members))

    @property
    def merges(self) -> tuple[MergeRecord, ...]:
        return tuple(self._merges)

    def merge(
        self,
        *,
        merge_id: str,
        into: str,
        absorbed: str,
        decision: MergeDecision,
        decided_by: str = "system",
    ) -> MergeRecord:
        """Fold one entity into another, keeping what it takes to undo it."""
        if decision.verdict is not MergeVerdict.AUTO_MERGE and decided_by == "system":
            raise ValueError(
                f"the decision was {decision.verdict.value}; a merge the resolver "
                "declined needs a named human reviewer, not the system"
            )
        if decision.tier is None:
            raise ValueError("a merge must record which tier produced it")
        if into == absorbed:
            raise ValueError("an entity cannot absorb itself")
        if into not in self._members or absorbed not in self._members:
            raise KeyError("both entities must exist before they can be merged")

        record = MergeRecord(
            merge_id=merge_id,
            entity_id=into,
            absorbed_entity_id=absorbed,
            tier=decision.tier,
            score=decision.score,
            previous_members=tuple(self._members[into]),
            absorbed_members=tuple(self._members[absorbed]),
            decided_by=decided_by,
        )
        self._members[into] = list(self._members[into]) + list(self._members[absorbed])
        del self._members[absorbed]
        self._merges.append(record)
        return record

    def unmerge(self, merge_id: str) -> None:
        """Put both entities back exactly as they were."""
        for index in range(len(self._merges) - 1, -1, -1):
            record = self._merges[index]
            if record.merge_id != merge_id:
                continue
            self._members[record.entity_id] = list(record.previous_members)
            self._members[record.absorbed_entity_id] = list(record.absorbed_members)
            del self._merges[index]
            return
        raise KeyError(f"no merge {merge_id} to undo")

    def high_risk_auto_merges(self, types: Mapping[str, str]) -> tuple[str, ...]:
        """Merges of a high-risk type that no identifier supported.

        The audit §N43 asks for -- *false merge in critical set* is the blocker
        condition, and this is what a reviewer runs to look for one.
        """
        return tuple(
            record.merge_id
            for record in self._merges
            if types.get(record.entity_id) in HIGH_RISK_TYPES
            and record.tier not in _IDENTIFIER_TIERS
            and record.decided_by == "system"
        )
