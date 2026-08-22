"""Blueprint §9.5 — what changed *inside* an element, once alignment settled who it is.

CURRENT does none of this. Two aligned units whose normalised text differs at
all become one `MODIFIED_CLAIM` (`semantic_diff.py:422`), so a warranty term
going from two years to three, a `may` becoming a `must`, and a scan that
turned `m` into `rn` are the same label with the same downstream consequence.

This module takes changes the core already produced and says which of those it
is. It does not decide identity, does not emit changes of its own, and does not
write anything back into the diff -- it returns a parallel record the harness
reports beside the diff.

**The demotions are the risky half and are guarded accordingly.**
`RENDERING_ONLY` is the only refinement that says "this is not a meaning
change", and it can only be reached when the two sides' numbers are already
identical. Optical-confusable folding that is allowed to touch a digit could
turn a real numeric change into a rendering artefact, and that is a wrong
answer in the expensive direction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from akc_cir.identity import normalize_text_for_identity
from akc_cir.semantic_diff import ChangeKind, SemanticChange, SemanticDiff

from .element_model import ElementType, numeric_tokens

__all__ = [
    "CRITICAL_REFINEMENTS",
    "SEMANTIC_CHANGE_KINDS",
    "ChangeRefinement",
    "RefinedChange",
    "refine",
    "refine_pair",
]


class ChangeRefinement(StrEnum):
    """What a `MODIFIED_CLAIM` actually was."""

    MODALITY_CHANGE = "modality_change"
    EXCEPTION_SCOPE_CHANGE = "exception_scope_change"
    DATE_PERIOD_CHANGE = "date_period_change"
    NUMERIC_VALUE_CHANGE = "numeric_value_change"
    #: The same values in a different order -- a move inside the element.
    VALUE_ORDER_CHANGE = "value_order_change"
    #: The characters differ and what they say does not.
    RENDERING_ONLY = "rendering_only"
    #: A wording change that is none of the above. Reported as a meaning change
    #: because nothing here can prove it is not one.
    TEXT_EDIT = "text_edit"


#: Refinements that are a meaning change. `VALUE_ORDER_CHANGE` and
#: `RENDERING_ONLY` are the two that are not.
_SEMANTIC_REFINEMENTS = frozenset(
    {
        ChangeRefinement.MODALITY_CHANGE,
        ChangeRefinement.EXCEPTION_SCOPE_CHANGE,
        ChangeRefinement.DATE_PERIOD_CHANGE,
        ChangeRefinement.NUMERIC_VALUE_CHANGE,
        ChangeRefinement.TEXT_EDIT,
    }
)

#: §9.8's high-risk set: figures, modal verbs, exception clauses, effective
#: dates. Missing one of these is the failure the acceptance criterion is
#: written against.
CRITICAL_REFINEMENTS = frozenset(
    {
        ChangeRefinement.MODALITY_CHANGE,
        ChangeRefinement.EXCEPTION_SCOPE_CHANGE,
        ChangeRefinement.DATE_PERIOD_CHANGE,
        ChangeRefinement.NUMERIC_VALUE_CHANGE,
    }
)

#: Change kinds that assert a meaning change on their own, without refinement.
#: `EVIDENCE_MOVED` and `STRUCTURE_CHANGED` are deliberately absent: they say
#: the document was rearranged, which is what a layout change is.
#: `IDENTITY_UNRESOLVED` is absent because it is not a change at all
#: (`semantic_diff.py:195`), and it is counted separately.
SEMANTIC_CHANGE_KINDS = frozenset(
    {
        ChangeKind.UNIT_ADDED,
        ChangeKind.UNIT_REMOVED,
        ChangeKind.ENTITY_CHANGED,
        ChangeKind.RELATIONSHIP_ADDED,
        ChangeKind.RELATIONSHIP_REMOVED,
        ChangeKind.AUTHORITY_CHANGED,
    }
)

_MODALS = ("must", "shall", "may", "should", "will", "can", "cannot")
_EXCEPTION_MARKERS = (
    "except",
    "unless",
    "notwithstanding",
    "provided",
    "excluding",
    "save",
)
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ISO_DATE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")

#: Optical confusions, longest first so `rn` is folded before `n`. Applied only
#: to tokens that contain a letter, and only when the two sides already agree
#: on every number -- see the module docstring.
_CONFUSABLES: tuple[tuple[str, str], ...] = (
    ("rn", "m"),
    ("vv", "w"),
    ("cl", "d"),
    ("0", "o"),
    ("1", "l"),
    ("5", "s"),
    ("8", "b"),
)

#: Rendering markup a formula can gain or lose without the expression changing.
#: A token-sequence proxy for §9.5's parsed expression tree, and named as one.
_FORMULA_NOISE = re.compile(r"[\\,!;\s{}]+")


def _ocr_fold(normalized: str) -> str:
    folded: list[str] = []
    for token in normalized.split():
        if any(character.isalpha() for character in token):
            for source, target in _CONFUSABLES:
                token = token.replace(source, target)
        folded.append(token)
    return " ".join(folded)


def _formula_basis(text: str) -> str:
    return _FORMULA_NOISE.sub("", normalize_text_for_identity(text))


def _month_positions(tokens: list[str]) -> set[int]:
    """Where a month name sits, judged by whether a number sits beside it.

    `may` is both a month and a modal verb, and the two refinements it can fire
    are different answers to different questions. Neither reading is safe
    without a rule, so the rule is positional: `1 may 2026` is a date and
    `the buyer may inspect` is not. Both directions of that confusion have been
    seen here -- a `may` -> `must` promotion reporting a date change, and a
    month change reporting a modality change -- so the same set decides both.
    """
    positions: set[int] = set()
    for position, word in enumerate(tokens):
        if word not in _MONTHS:
            continue
        neighbours = (
            tokens[max(0, position - 1) : position] + tokens[position + 1 : position + 2]
        )
        if any(neighbour.isdigit() for neighbour in neighbours):
            positions.add(position)
    return positions


def _modal_counts(basis: str) -> dict[str, int]:
    tokens = basis.split()
    dates = _month_positions(tokens)
    counts = dict.fromkeys(_MODALS, 0)
    for position, word in enumerate(tokens):
        if word in counts and position not in dates:
            counts[word] += 1
    return counts


def _counts(basis: str, vocabulary: tuple[str, ...]) -> dict[str, int]:
    tokens = basis.split()
    return {word: tokens.count(word) for word in vocabulary}


def _date_tokens(basis: str) -> tuple[str, ...]:
    found = list(_ISO_DATE.findall(basis)) + list(_YEAR.findall(basis))
    tokens = basis.split()
    found.extend(tokens[position] for position in sorted(_month_positions(tokens)))
    return tuple(sorted(found))


@dataclass(frozen=True, slots=True)
class RefinedChange:
    """One core change, plus what type-specific reasoning made of it."""

    kind: ChangeKind
    logical_id: str | None
    refinement: ChangeRefinement | None
    fired: tuple[ChangeRefinement, ...] = ()

    @property
    def semantic(self) -> bool:
        if self.kind in SEMANTIC_CHANGE_KINDS:
            return True
        if self.kind is not ChangeKind.MODIFIED_CLAIM:
            return False
        return self.refinement in _SEMANTIC_REFINEMENTS

    @property
    def critical(self) -> bool:
        return any(item in CRITICAL_REFINEMENTS for item in self.fired)

    def as_record(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "logical_id": self.logical_id,
            "refinement": self.refinement.value if self.refinement else None,
            "fired": [item.value for item in self.fired],
            "semantic": self.semantic,
            "critical": self.critical,
        }


def refine_pair(
    before: str, after: str, *, element_type: ElementType = ElementType.TEXT
) -> tuple[ChangeRefinement, tuple[ChangeRefinement, ...]]:
    """Classify one before/after text pair. Returns the primary and all that fired.

    All of them are returned because a clause that changed its modal verb *and*
    its figure is two changes, and reporting only the first would understate the
    blast radius of the second.
    """
    if element_type is ElementType.FORMULA and _formula_basis(before) == _formula_basis(
        after
    ):
        return ChangeRefinement.RENDERING_ONLY, (ChangeRefinement.RENDERING_ONLY,)

    left_numbers = numeric_tokens(before)
    right_numbers = numeric_tokens(after)
    numbers_agree = left_numbers == right_numbers

    left_basis = normalize_text_for_identity(before)
    right_basis = normalize_text_for_identity(after)
    if numbers_agree:
        # The guard. Folding is only allowed where it cannot rewrite a number.
        left_basis = _ocr_fold(left_basis)
        right_basis = _ocr_fold(right_basis)

    if left_basis == right_basis:
        return ChangeRefinement.RENDERING_ONLY, (ChangeRefinement.RENDERING_ONLY,)

    fired: list[ChangeRefinement] = []
    if _modal_counts(left_basis) != _modal_counts(right_basis):
        fired.append(ChangeRefinement.MODALITY_CHANGE)
    if _counts(left_basis, _EXCEPTION_MARKERS) != _counts(right_basis, _EXCEPTION_MARKERS):
        fired.append(ChangeRefinement.EXCEPTION_SCOPE_CHANGE)
    if _date_tokens(left_basis) != _date_tokens(right_basis):
        fired.append(ChangeRefinement.DATE_PERIOD_CHANGE)
    if not numbers_agree:
        if sorted(left_numbers) == sorted(right_numbers):
            fired.append(ChangeRefinement.VALUE_ORDER_CHANGE)
        else:
            fired.append(ChangeRefinement.NUMERIC_VALUE_CHANGE)

    if not fired:
        fired.append(ChangeRefinement.TEXT_EDIT)
    elif fired == [ChangeRefinement.VALUE_ORDER_CHANGE] and set(left_basis.split()) != set(
        right_basis.split()
    ):
        # The numbers were only reordered, but the words around them were not.
        # A reorder alone is not a meaning change; this is not a reorder alone.
        fired.append(ChangeRefinement.TEXT_EDIT)

    # A reorder never outranks whatever fired beside it. Same values in a new
    # order is a move; same values in a new order *and* a changed modal verb is
    # a modality change that happens to have moved.
    primary = next(
        (item for item in fired if item is not ChangeRefinement.VALUE_ORDER_CHANGE),
        ChangeRefinement.VALUE_ORDER_CHANGE,
    )
    return primary, tuple(fired)


def refine(
    diff: SemanticDiff, *, element_types: dict[str, ElementType] | None = None
) -> tuple[RefinedChange, ...]:
    """Refine every `MODIFIED_CLAIM` in a diff, leaving the other kinds alone."""
    types = element_types or {}
    refined: list[RefinedChange] = []
    for change in diff.changes:
        refined.append(_refine_change(change, types))
    return tuple(refined)


def _refine_change(
    change: SemanticChange, types: dict[str, ElementType]
) -> RefinedChange:
    if change.kind is not ChangeKind.MODIFIED_CLAIM:
        return RefinedChange(kind=change.kind, logical_id=change.logical_id, refinement=None)
    element_type = types.get(change.logical_id or "", ElementType.TEXT)
    primary, fired = refine_pair(
        change.before or "", change.after or "", element_type=element_type
    )
    return RefinedChange(
        kind=change.kind,
        logical_id=change.logical_id,
        refinement=primary,
        fired=fired,
    )
