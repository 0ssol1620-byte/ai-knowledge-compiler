"""Blueprint §9.3 compatibility signals over §9.4's candidate tiers.

The layer this module implements answers *which element is which*, separately
from *what changed inside it*. CURRENT has no such separation: a normalised-text
mismatch is a `MODIFIED_CLAIM` on the spot (`semantic_diff.py:422`), so a moved
row and an edited row arrive downstream wearing the same label.

Every signal here can say it has no value, with a `MissingReason`, and none is
ever filled with a zero. That is not politeness towards §N4.4 -- it is what
makes the signals safe to hand to `akc_cir.identity`, whose renormalisation and
critical-signal abstention only work if absence is distinguishable from
disagreement.

**Identity is not one of the signals.** §9.3 lists six and the sixth is
"existing stable ID evidence", which is precisely what `source_continuity` and
`explicit_identifier` already are in the core scorer. Supplying it again would
count the same evidence twice under two names and inflate the score of exactly
the pairs the core was already confident about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from akc_cir.identity import MissingReason, normalize_text_for_identity

from .assignment import max_weight_assignment
from .element_model import DocumentElement, ElementIndex, ElementType

__all__ = [
    "ALIGNMENT_SIGNAL_NAMES",
    "AlignmentContext",
    "CandidateTier",
    "SignalValue",
    "classify_tier",
    "compatibility",
    "type_compatibility",
]

#: The five signals this layer adds. Ordered for stable reporting.
ALIGNMENT_SIGNAL_NAMES = (
    "align_type",
    "align_spatial",
    "align_structural",
    "align_content",
    "align_context",
)

#: A signal's value, or the reason it has none.
SignalValue = tuple[float | None, MissingReason | None]


class CandidateTier(StrEnum):
    """§9.4 steps 1-3. Which tier a pair reached, and therefore what counts.

    The tier is not a score. It records *why* the pair is a candidate at all,
    and one consequence follows from it: at `EXACT_CONTENT` the two elements
    say the same thing, so where they sit and who sits next to them cannot be
    evidence that they are different elements. A pure layout move is the case
    that makes this concrete -- the element is identical and everything
    positional about it changed, and a scorer that lets position vote is a
    scorer that reports a move as a difference.
    """

    EXACT_CONTENT = "T1_EXACT_CONTENT"
    SAME_NEIGHBOURHOOD = "T2_SAME_NEIGHBOURHOOD"
    TYPE_COMPATIBLE = "T3_TYPE_COMPATIBLE"
    INCOMPATIBLE = "T4_INCOMPATIBLE"


#: Cross-type pairs that can still be one element continuing. Symmetric; only
#: the prose family is listed, because a table row that became a figure is not
#: a continuation of anything, it is a removal and an addition.
_COMPATIBLE_PAIRS: dict[frozenset[ElementType], float] = {
    frozenset({ElementType.TEXT, ElementType.FOOTNOTE}): 0.5,
    frozenset({ElementType.TEXT, ElementType.CAPTION}): 0.5,
    frozenset({ElementType.TEXT, ElementType.HEADING}): 0.5,
}


def type_compatibility(left: ElementType, right: ElementType) -> float:
    if left is right:
        return 1.0
    return _COMPATIBLE_PAIRS.get(frozenset({left, right}), 0.0)


def _tokens(text: str) -> set[str]:
    return set(normalize_text_for_identity(text).split())


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def classify_tier(
    before: DocumentElement,
    after: DocumentElement,
    *,
    before_index: ElementIndex,
    after_index: ElementIndex,
) -> CandidateTier:
    """Which of §9.4's candidate tiers this pair reached.

    `EXACT_CONTENT` additionally requires the hash to be unique on both sides.
    Two identical rows in one table would otherwise make the tier a coin flip,
    and a tier that suppresses the positional signals must not fire on a pair
    where position is the only thing that could tell the two apart.
    """
    if before.content_hash == after.content_hash and (
        before_index.is_unique_content(before.logical_id)
        and after_index.is_unique_content(after.logical_id)
    ):
        return CandidateTier.EXACT_CONTENT
    if type_compatibility(before.element_type, after.element_type) <= 0.0:
        return CandidateTier.INCOMPATIBLE
    if before.structural_path and before.structural_path == after.structural_path:
        return CandidateTier.SAME_NEIGHBOURHOOD
    return CandidateTier.TYPE_COMPATIBLE


def _spatial(before: DocumentElement, after: DocumentElement) -> SignalValue:
    left = before.centre1000
    right = after.centre1000
    if left is None or right is None:
        # A parser that emits no box has not failed; some formats have none.
        return None, MissingReason.NOT_APPLICABLE
    page_gap = abs(before.page_index - after.page_index)
    page_term = max(0.0, 1.0 - 0.34 * page_gap)
    distance = ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
    # 1000x1000 per-mille page, so the diagonal is the largest distance two
    # centres can be apart and is what normalises the term to 0..1.
    position_term = max(0.0, 1.0 - distance / (1000.0 * 2**0.5))
    return 0.5 * page_term + 0.5 * position_term, None


def _structural_role(
    before: DocumentElement,
    after: DocumentElement,
    *,
    before_index: ElementIndex,
    after_index: ElementIndex,
) -> SignalValue:
    """Table-header and figure-caption binding, which the core path does not see.

    `structural_path` agreement is already a core signal at weight .20, so this
    signal deliberately does not repeat it. What it adds is the binding a path
    cannot express: the key that names a table row independently of its
    position, and the figure a caption is attached to.
    """
    if before.table_key and after.table_key:
        left = normalize_text_for_identity(before.table_key)
        right = normalize_text_for_identity(after.table_key)
        return (1.0 if left == right else 0.0), None

    if before.binds_to and after.binds_to:
        left_target = before_index.by_logical_id.get(before.binds_to)
        right_target = after_index.by_logical_id.get(after.binds_to)
        if left_target is None or right_target is None:
            # The binding names something the index does not hold. That is a
            # broken fixture or a partial extraction, not a disagreement.
            return None, MissingReason.ERROR
        same = (
            left_target.content_hash == right_target.content_hash
            and left_target.element_type is right_target.element_type
        )
        return (1.0 if same else 0.0), None

    return None, MissingReason.NOT_APPLICABLE


def _content(before: DocumentElement, after: DocumentElement) -> SignalValue:
    """Lexical agreement, with the numeric set weighed separately.

    Numbers get their own term because they are the part of a span where a
    single token flipping is a material change and lexical overlap barely
    moves. A row whose numbers are the same multiset in a different order
    scores 0.5 rather than 0.0 on that term: that is a move, and §9.5 asks for
    move and value-change to be distinguishable rather than both landing as a
    mismatch.

    FORMULA is compared on its canonical token sequence. That is a proxy for
    §9.5's parsed expression tree, not the tree itself -- there is no formula
    parser in this repository, and calling a token sequence a tree would be
    claiming a capability that does not exist.
    """
    both_figures = (
        before.element_type is ElementType.FIGURE
        and after.element_type is ElementType.FIGURE
    )
    if both_figures and not before.text and not after.text:
        # A figure with no caption, alt text or native data, and no visual
        # encoder in this experiment. There is nothing to compare.
        return None, MissingReason.MODEL_UNAVAILABLE

    lexical = _jaccard(_tokens(before.text), _tokens(after.text))
    left_numbers = before.numbers
    right_numbers = after.numbers
    if not left_numbers and not right_numbers:
        return lexical, None
    if left_numbers == right_numbers:
        numeric = 1.0
    elif sorted(left_numbers) == sorted(right_numbers):
        numeric = 0.5
    else:
        numeric = 0.0
    return 0.6 * lexical + 0.4 * numeric, None


@dataclass(frozen=True, slots=True)
class AlignmentContext:
    """A pre-pass alignment, so §9.3's context signal has something to read.

    "Preceding/following *aligned* elements" cannot be evaluated before an
    alignment exists, so this runs one first over type, structural role and
    content only. Spatial and context are excluded from the pre-pass on
    purpose: the first would let position decide the alignment that position is
    then scored against, and the second is what the pre-pass exists to produce.
    """

    pairs: dict[str, str]

    @staticmethod
    def build(before_index: ElementIndex, after_index: ElementIndex) -> AlignmentContext:
        before_elements = list(before_index.elements)
        after_elements = list(after_index.elements)
        if not before_elements or not after_elements:
            return AlignmentContext(pairs={})

        matrix: list[list[float]] = []
        for after_element in after_elements:
            row: list[float] = []
            for before_element in before_elements:
                tier = classify_tier(
                    before_element,
                    after_element,
                    before_index=before_index,
                    after_index=after_index,
                )
                if tier is CandidateTier.INCOMPATIBLE:
                    row.append(0.0)
                    continue
                type_score = type_compatibility(
                    before_element.element_type, after_element.element_type
                )
                content_score, _ = _content(before_element, after_element)
                role_score, _ = _structural_role(
                    before_element,
                    after_element,
                    before_index=before_index,
                    after_index=after_index,
                )
                terms = [type_score, content_score if content_score is not None else None]
                if role_score is not None:
                    terms.append(role_score)
                present = [term for term in terms if term is not None]
                row.append(sum(present) / len(present) if present else 0.0)
            matrix.append(row)

        assignment = max_weight_assignment(matrix)
        pairs: dict[str, str] = {}
        for after_position, before_position in assignment.items():
            if matrix[after_position][before_position] <= 0.0:
                continue
            pairs[after_elements[after_position].logical_id] = before_elements[
                before_position
            ].logical_id
        return AlignmentContext(pairs=pairs)


def _context(
    before: DocumentElement,
    after: DocumentElement,
    *,
    before_index: ElementIndex,
    after_index: ElementIndex,
    context: AlignmentContext,
) -> SignalValue:
    before_prev, before_next = before_index.neighbours(before.logical_id)
    after_prev, after_next = after_index.neighbours(after.logical_id)
    agreements: list[float] = []
    for before_side, after_side in ((before_prev, after_prev), (before_next, after_next)):
        if before_side is None or after_side is None:
            # An element at the edge of a version has no neighbour on that
            # side. That is where it sits, not a failure to compute anything.
            continue
        agreements.append(1.0 if context.pairs.get(after_side) == before_side else 0.0)
    if not agreements:
        return None, MissingReason.NOT_APPLICABLE
    return sum(agreements) / len(agreements), None


def compatibility(
    before: DocumentElement,
    after: DocumentElement,
    *,
    before_index: ElementIndex,
    after_index: ElementIndex,
    context: AlignmentContext,
    enabled: frozenset[str] = frozenset(ALIGNMENT_SIGNAL_NAMES),
) -> tuple[dict[str, float], dict[str, str], CandidateTier]:
    """§9.3's signals for one candidate pair, with the reasons for any absences.

    `enabled` is how the ablations are run. A suppressed signal is reported
    unavailable rather than scored zero, so an ablation measures the absence of
    a signal and not the presence of a disagreement nobody observed -- which is
    the same §N4.4 distinction the core scorer turns on.
    """
    tier = classify_tier(
        before, after, before_index=before_index, after_index=after_index
    )

    raw: dict[str, SignalValue] = {
        "align_type": (
            type_compatibility(before.element_type, after.element_type),
            None,
        ),
        "align_structural": _structural_role(
            before, after, before_index=before_index, after_index=after_index
        ),
        "align_content": _content(before, after),
    }

    if tier is CandidateTier.EXACT_CONTENT:
        # See `CandidateTier.EXACT_CONTENT`. The two elements say the same
        # thing; position and neighbourhood are what a move changes, so they
        # are not evidence about whether this is the same element.
        raw["align_spatial"] = (None, MissingReason.NOT_APPLICABLE)
        raw["align_context"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        raw["align_spatial"] = _spatial(before, after)
        raw["align_context"] = _context(
            before,
            after,
            before_index=before_index,
            after_index=after_index,
            context=context,
        )

    present: dict[str, float] = {}
    missing: dict[str, str] = {}
    for name in ALIGNMENT_SIGNAL_NAMES:
        value, reason = raw[name] if name in enabled else (None, MissingReason.NOT_APPLICABLE)
        if value is None:
            missing[name] = (reason or MissingReason.MODEL_UNAVAILABLE).value
        else:
            present[name] = value
    return present, missing, tier
