"""The prior-art baseline arm — `tech_xversion_diff`, clean-room.

**Register grade: YELLOW, `CLEAN_ROOM_ONLY`.** What is reproduced here is the
requirement level the contract states and nothing else: typed elements,
spatial/structural/content compatibility, a constrained one-to-one assignment,
and per-type difference reasoning. No source of that project was read, copied,
translated or ported. The provenance record for that claim is
`research/experiments/EXP-0101/receipts/clean-room-provenance.json`.

What this arm deliberately does **not** have is the part the blueprint marks as
TAVONEL's own: availability-aware renormalisation, critical-signal abstention,
and the review band that keeps an unsettled pair unsettled. The baseline
accepts or rejects each pair on one threshold. That is the comparison the
experiment is for -- a baseline given TAVONEL's abstention would not be the
baseline, and one denied the tiered candidate generation the method itself
specifies would be a straw man.
"""

from __future__ import annotations

from dataclasses import dataclass

from .alignment import (
    AlignmentContext,
    CandidateTier,
    classify_tier,
    compatibility,
)
from .assignment import max_weight_assignment
from .element_model import ElementIndex
from .type_reasoning import ChangeRefinement, refine_pair

__all__ = [
    "BASELINE_ACCEPT_THRESHOLD",
    "BaselineDiff",
    "BaselinePairChange",
    "baseline_diff",
]

#: The one threshold this arm has. **Uncalibrated**, frozen before the run and
#: not swept against the fixture, for the same reason the challenger's share is
#: not: a number tuned on the set the arms are scored on cannot be reported.
BASELINE_ACCEPT_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class BaselinePairChange:
    """One aligned pair and what per-type reasoning made of it."""

    before_logical_id: str
    after_logical_id: str
    score: float
    tier: CandidateTier
    refinement: ChangeRefinement | None
    fired: tuple[ChangeRefinement, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineDiff:
    pairs: tuple[BaselinePairChange, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def aligned_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple((pair.before_logical_id, pair.after_logical_id) for pair in self.pairs)

    @property
    def changed_logical_ids(self) -> tuple[str, ...]:
        """What a downstream traversal would start from.

        Includes removals, because a clause that disappeared invalidates what
        depended on it, and the elements whose refinement is a meaning change.
        Excludes additions on the after side -- they have no before-side id to
        propagate from.
        """
        changed: list[str] = []
        for pair in self.pairs:
            if pair.refinement is not None and pair.refinement not in _NON_SEMANTIC:
                changed.append(pair.before_logical_id)
        changed.extend(self.removed)
        return tuple(dict.fromkeys(changed))


_NON_SEMANTIC = frozenset(
    {ChangeRefinement.RENDERING_ONLY, ChangeRefinement.VALUE_ORDER_CHANGE}
)


def baseline_diff(
    before_index: ElementIndex,
    after_index: ElementIndex,
    *,
    accept_threshold: float = BASELINE_ACCEPT_THRESHOLD,
) -> BaselineDiff:
    """Align first, then diff inside each aligned pair.

    The compatibility matrix reuses the same signal implementations the
    challenger supplies to the core scorer. That is on purpose: if the two arms
    computed spatial agreement differently, the comparison would be measuring
    two implementations of a signal rather than two ways of using it.
    """
    before_elements = list(before_index.elements)
    after_elements = list(after_index.elements)
    if not before_elements or not after_elements:
        return BaselineDiff(
            pairs=(),
            added=tuple(element.logical_id for element in after_elements),
            removed=tuple(element.logical_id for element in before_elements),
        )

    context = AlignmentContext.build(before_index, after_index)

    matrix: list[list[float]] = []
    tiers: list[list[CandidateTier]] = []
    for after_element in after_elements:
        row: list[float] = []
        tier_row: list[CandidateTier] = []
        for before_element in before_elements:
            tier = classify_tier(
                before_element,
                after_element,
                before_index=before_index,
                after_index=after_index,
            )
            tier_row.append(tier)
            if tier is CandidateTier.INCOMPATIBLE:
                row.append(0.0)
                continue
            present, _missing, _tier = compatibility(
                before_element,
                after_element,
                before_index=before_index,
                after_index=after_index,
                context=context,
            )
            # Equal weight over the signals that have values. The baseline has
            # no weighting scheme of its own to reproduce.
            row.append(sum(present.values()) / len(present) if present else 0.0)
        matrix.append(row)
        tiers.append(tier_row)

    assignment = max_weight_assignment(matrix)

    pairs: list[BaselinePairChange] = []
    matched_before: set[str] = set()
    added: list[str] = []
    for after_position, after_element in enumerate(after_elements):
        before_position = assignment.get(after_position)
        if before_position is None or matrix[after_position][before_position] < accept_threshold:
            added.append(after_element.logical_id)
            continue
        before_element = before_elements[before_position]
        matched_before.add(before_element.logical_id)
        refinement: ChangeRefinement | None = None
        fired: tuple[ChangeRefinement, ...] = ()
        if before_element.content_hash != after_element.content_hash:
            refinement, fired = refine_pair(
                before_element.text,
                after_element.text,
                element_type=after_element.element_type,
            )
        pairs.append(
            BaselinePairChange(
                before_logical_id=before_element.logical_id,
                after_logical_id=after_element.logical_id,
                score=matrix[after_position][before_position],
                tier=tiers[after_position][before_position],
                refinement=refinement,
                fired=fired,
            )
        )

    removed = [
        element.logical_id
        for element in before_elements
        if element.logical_id not in matched_before
    ]
    return BaselineDiff(pairs=tuple(pairs), added=tuple(added), removed=tuple(removed))
