"""Two clocks: when a fact was true, and when we knew it.

Masterplan §13. The distinction is the product's central promise -- *when reality
changes, your AI should know exactly what changed* -- and it needs both axes to
answer the two questions that look identical and are not:

    what was the policy on 3 January?
    what did the AI believe the policy was on 3 January?

The first is valid time. The second is system time. A policy backdated to
January but recorded in March is correct under the first and absent under the
second, and an agent that answered a question in February was not wrong -- it
answered from what was recorded then. Collapsing the two axes makes it
impossible to tell a stale answer from a dishonest one.

§8.1 governs what may be stored: *문서에 없는 날짜를 확정값으로 저장 금지.* A
fact whose validity the document never stated carries `valid_from=None` and
`temporal_source=UNKNOWN`, and this module will not let an as-of query silently
treat unknown as "always true". That is what `TemporalPolicy` is for: the caller
decides how unknowns are handled, and the answer records which policy produced
it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
    "AsOfAnswer",
    "TemporalFact",
    "TemporalPolicy",
    "TemporalSource",
    "TemporalTimeline",
]


class TemporalSource(StrEnum):
    """Where a validity date came from. §8.1 forbids blurring these."""

    #: The document said so.
    EXPLICIT = "explicit"
    #: Derived from surrounding context, and marked as derived.
    INFERRED = "inferred"
    #: The document did not say, and nothing invented one.
    UNKNOWN = "unknown"


class TemporalPolicy(StrEnum):
    """How an as-of query treats a fact whose validity is unknown."""

    #: Leave it out. Safe for a compliance answer where an unsupported date is
    #: worse than a missing one.
    EXCLUDE_UNKNOWN = "exclude_unknown"
    #: Include it, and say in the answer that it was included on this basis.
    INCLUDE_UNKNOWN = "include_unknown"


@dataclass(frozen=True, slots=True)
class TemporalFact:
    """One assertion on both axes.

    `valid_from` / `valid_to` are reality. `recorded_at` / `superseded_at` are
    the system's knowledge of it. All four are optional in the same way the
    source may be silent, and none is ever invented to fill a gap.
    """

    logical_id: str
    value: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime | None = None
    superseded_at: datetime | None = None
    temporal_source: TemporalSource = TemporalSource.UNKNOWN
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError(f"{self.logical_id}: valid_to precedes valid_from")
        if self.recorded_at and self.superseded_at and self.superseded_at < self.recorded_at:
            raise ValueError(f"{self.logical_id}: superseded_at precedes recorded_at")
        if (
            self.temporal_source is TemporalSource.EXPLICIT
            and self.valid_from is None
            and self.valid_to is None
        ):
            raise ValueError(
                f"{self.logical_id}: temporal_source is explicit but no date was given. "
                "A fact the document dated must carry that date; a fact it did not "
                "is unknown, and §8.1 forbids storing an invented one as fact."
            )

    @property
    def validity_known(self) -> bool:
        return self.temporal_source is not TemporalSource.UNKNOWN and (
            self.valid_from is not None or self.valid_to is not None
        )

    def valid_at(self, moment: datetime) -> bool:
        """Was this true in reality at `moment`?"""
        begun = self.valid_from is None or moment >= self.valid_from
        not_ended = self.valid_to is None or moment < self.valid_to
        return begun and not_ended

    def known_at(self, moment: datetime) -> bool:
        """Had the system recorded this by `moment`, and not yet retracted it?"""
        recorded = self.recorded_at is None or moment >= self.recorded_at
        not_retracted = self.superseded_at is None or moment < self.superseded_at
        return recorded and not_retracted


@dataclass(frozen=True, slots=True)
class AsOfAnswer:
    """A temporal answer, carrying how it was reached.

    `included_unknown` is not a footnote. An answer that silently mixed facts
    with stated validity and facts with none is not auditable, and §35's rule
    that every rate carries its denominator has the same shape here.
    """

    facts: tuple[TemporalFact, ...]
    valid_at: datetime | None
    known_at: datetime | None
    policy: TemporalPolicy
    included_unknown: tuple[str, ...] = ()
    excluded_unknown: tuple[str, ...] = ()

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(fact.value for fact in self.facts)

    def describe(self) -> str:
        parts = []
        if self.valid_at:
            parts.append(f"valid at {self.valid_at.isoformat()}")
        if self.known_at:
            parts.append(f"as known at {self.known_at.isoformat()}")
        note = ""
        if self.included_unknown:
            note = (
                f"; {len(self.included_unknown)} fact(s) with no stated validity "
                "were included under include_unknown"
            )
        elif self.excluded_unknown:
            note = (
                f"; {len(self.excluded_unknown)} fact(s) with no stated validity "
                "were excluded"
            )
        return (", ".join(parts) or "no temporal bound") + note


class TemporalTimeline:
    """The bitemporal store for one workspace's facts."""

    def __init__(self, facts: Iterable[TemporalFact] = ()) -> None:
        self._facts: list[TemporalFact] = list(facts)

    def add(self, fact: TemporalFact) -> None:
        self._facts.append(fact)

    def __len__(self) -> int:
        return len(self._facts)

    def as_of(
        self,
        *,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
        logical_id: str | None = None,
        policy: TemporalPolicy = TemporalPolicy.EXCLUDE_UNKNOWN,
    ) -> AsOfAnswer:
        """§13.2's `knowledge.as_of`.

        `valid_at` asks what reality was. `known_at` asks what the system had
        recorded. Supplying both reconstructs what an agent would have retrieved
        at that moment, which is what §19's replay needs.
        """
        selected: list[TemporalFact] = []
        included_unknown: list[str] = []
        excluded_unknown: list[str] = []

        for fact in self._facts:
            if logical_id is not None and fact.logical_id != logical_id:
                continue
            if known_at is not None and not fact.known_at(known_at):
                continue
            if valid_at is not None:
                if not fact.validity_known:
                    if policy is TemporalPolicy.EXCLUDE_UNKNOWN:
                        excluded_unknown.append(fact.logical_id)
                        continue
                    included_unknown.append(fact.logical_id)
                elif not fact.valid_at(valid_at):
                    continue
            selected.append(fact)

        return AsOfAnswer(
            facts=tuple(selected),
            valid_at=valid_at,
            known_at=known_at,
            policy=policy,
            included_unknown=tuple(dict.fromkeys(included_unknown)),
            excluded_unknown=tuple(dict.fromkeys(excluded_unknown)),
        )

    def history(self, logical_id: str) -> tuple[TemporalFact, ...]:
        """§13.2's `entity.history`, ordered the way a reader expects.

        Facts without a recorded_at sort last rather than first: an undated
        record is not evidence that it came before everything else.
        """
        matching = [fact for fact in self._facts if fact.logical_id == logical_id]
        return tuple(
            sorted(
                matching,
                key=lambda fact: (
                    fact.recorded_at is None,
                    fact.recorded_at or datetime.max.replace(tzinfo=None),
                    fact.valid_from is None,
                    fact.valid_from or datetime.max.replace(tzinfo=None),
                ),
            )
        )

    def contradictions(self, logical_id: str | None = None) -> tuple[tuple[str, str, str], ...]:
        """Facts that claim different values for the same thing at the same time.

        §17.1 lists temporal contradiction as an integrity category, and this is
        what detects it: two facts for one logical id whose validity windows
        overlap and whose values differ. One of them is wrong, and a compile
        that emits both is emitting a contradiction.
        """
        found: list[tuple[str, str, str]] = []
        candidates = [
            fact
            for fact in self._facts
            if logical_id is None or fact.logical_id == logical_id
        ]
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                if left.logical_id != right.logical_id:
                    continue
                if left.value == right.value:
                    continue
                if left.superseded_at is not None or right.superseded_at is not None:
                    # A retracted fact does not contradict its replacement.
                    continue
                if _windows_overlap(left, right):
                    found.append((left.logical_id, left.value, right.value))
        return tuple(found)


def _windows_overlap(left: TemporalFact, right: TemporalFact) -> bool:
    """Do two validity windows share any instant?

    An open end is treated as open, and an entirely unknown window overlaps
    nothing: two facts that never stated when they applied are not evidence of a
    contradiction, only of missing dates.
    """
    if not left.validity_known or not right.validity_known:
        return False
    left_start = left.valid_from or _open_start(left)
    right_start = right.valid_from or _open_start(right)
    left_end = left.valid_to
    right_end = right.valid_to
    left_clears_right = left_end is None or right_start < left_end
    right_clears_left = right_end is None or left_start < right_end
    return left_clears_right and right_clears_left


def _open_start(fact: TemporalFact) -> datetime:
    """The earliest instant, in whatever timezone the fact uses."""
    tz = fact.valid_to.tzinfo if fact.valid_to else None
    return datetime.min.replace(tzinfo=tz)


def replay_context(
    timeline: TemporalTimeline,
    *,
    at: datetime,
    logical_ids: Sequence[str] | None = None,
) -> AsOfAnswer:
    """What the system would have served at `at`. §19's replay input.

    Both axes are pinned to the same moment: reality as it was, filtered to what
    had been recorded by then. §19 is explicit that this reconstructs the input
    context and never claims to reconstruct a model's reasoning.
    """
    answer = timeline.as_of(valid_at=at, known_at=at, policy=TemporalPolicy.EXCLUDE_UNKNOWN)
    if logical_ids is None:
        return answer
    wanted = set(logical_ids)
    return AsOfAnswer(
        facts=tuple(fact for fact in answer.facts if fact.logical_id in wanted),
        valid_at=answer.valid_at,
        known_at=answer.known_at,
        policy=answer.policy,
        included_unknown=answer.included_unknown,
        excluded_unknown=tuple(lid for lid in answer.excluded_unknown if lid in wanted),
    )
