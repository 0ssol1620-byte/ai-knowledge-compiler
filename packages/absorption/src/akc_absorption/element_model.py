"""Blueprint §9.2 — the typed element model CURRENT does not have.

`akc_cir.semantic_diff.UnitSnapshot` carries text, a structural path, an anchor
and neighbours. It carries no element *type* and no box
(`semantic_diff.py:100`), so nothing downstream can tell a table row from a
caption, and nothing can ask where on the page either of them sat. This module
adds that layer beside `UnitSnapshot` rather than inside it: the two are joined
by `logical_id`, so a document can be described both ways without the core
dataclass changing shape.

Two fields the blueprint lists are deliberately absent. `visual_feature_ref`
and `semantic_embedding_ref` name providers this experiment does not run --
there is no embedding call and no visual encoder anywhere in EXP-0101 -- and
carrying them as empty strings would be exactly the §N4.4 zero-fill the
identity layer refuses. A later experiment that actually calls those providers
adds the fields with values in them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum

from akc_cir.identity import normalize_bbox1000, normalize_text_for_identity

__all__ = [
    "DocumentElement",
    "ElementIndex",
    "ElementType",
    "numeric_tokens",
]


class ElementType(StrEnum):
    """§9.2's vocabulary, verbatim."""

    TEXT = "TEXT"
    HEADING = "HEADING"
    TABLE = "TABLE"
    TABLE_ROW = "TABLE_ROW"
    TABLE_CELL = "TABLE_CELL"
    FORMULA = "FORMULA"
    FIGURE = "FIGURE"
    CAPTION = "CAPTION"
    FOOTNOTE = "FOOTNOTE"


#: A number, with an optional sign, thousands separators and a decimal part.
#: Percent and currency are read as part of the surrounding token rather than
#: the number, because "3%" and "3" differing is a unit change and the numeric
#: comparison should see both sides of it.
_NUMERIC = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def numeric_tokens(text: str) -> tuple[str, ...]:
    """Every number in a span, canonicalised, in order.

    Order is kept rather than folded to a set: a table row whose cells were
    reordered has the same numbers in a different order, and a row whose value
    changed does not. Collapsing to a set loses the distinction the whole
    type-specific reasoning step exists to make.
    """
    found: list[str] = []
    for match in _NUMERIC.finditer(text):
        raw = match.group(0).replace(",", "")
        if raw.startswith("+"):
            raw = raw[1:]
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        found.append(raw or "0")
    return tuple(found)


@dataclass(frozen=True, slots=True)
class DocumentElement:
    """One typed element of one version.

    `logical_id` is the join back to `UnitSnapshot`. It is not an assertion
    about identity across versions -- that is still `akc_cir.identity`'s call --
    it only says which unit within *this* version this element describes.
    """

    element_id: str
    version_id: str
    element_type: ElementType
    logical_id: str
    text: str
    structural_path: tuple[str, ...] = ()
    page_index: int = 0
    bbox1000: tuple[int, int, int, int] | None = None
    #: Reading-order position within the version. Used for neighbourhood, never
    #: for identity: an element that moved is still the same element.
    order_index: int = 0
    #: For a TABLE_ROW, the header-derived key that names the row independently
    #: of where it sits. Empty when the table has no usable header.
    table_key: str = ""
    #: A CAPTION's figure, a FOOTNOTE's anchor. §9.3's figure-caption relation.
    binds_to: str = ""
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not self.element_id or not self.version_id:
            raise ValueError("a document element needs an element id and a version id")
        if self.page_index < 0:
            raise ValueError("page_index is 0-based and cannot be negative")
        # Validated through the core helper so a box that would be rejected
        # when an evidence id is derived from it is rejected here too.
        normalize_bbox1000(self.bbox1000)

    @property
    def content_hash(self) -> str:
        """A digest over what the element *says*, not where it sits.

        Type is in the digest because the same words as a heading and as a
        caption are not the same element. Position is not, because §9.4's first
        candidate tier is exactly "these two have identical content", and a tier
        that changed when the element moved would never fire on a moved one.
        """
        payload = f"{self.element_type.value}\x1f{normalize_text_for_identity(self.text)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def numbers(self) -> tuple[str, ...]:
        return numeric_tokens(self.text)

    @property
    def centre1000(self) -> tuple[float, float] | None:
        if self.bbox1000 is None:
            return None
        x0, y0, x1, y1 = self.bbox1000
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


@dataclass(frozen=True, slots=True)
class ElementIndex:
    """The elements of one version, addressable the three ways alignment needs.

    Built once per version and reused across every candidate pair, because the
    alternative -- rebuilding the by-hash and by-order views inside the scoring
    loop -- makes the scorer quadratic in the document rather than in the
    candidate window.
    """

    version_id: str
    elements: tuple[DocumentElement, ...]
    by_logical_id: dict[str, DocumentElement] = field(default_factory=dict)
    by_content_hash: dict[str, tuple[str, ...]] = field(default_factory=dict)
    order: tuple[str, ...] = ()

    @staticmethod
    def of(version_id: str, elements: list[DocumentElement]) -> ElementIndex:
        ordered = tuple(sorted(elements, key=lambda item: (item.order_index, item.element_id)))
        by_logical: dict[str, DocumentElement] = {}
        for element in ordered:
            if element.logical_id in by_logical:
                raise ValueError(
                    f"two elements in {version_id} claim logical id {element.logical_id}; "
                    "the join back to UnitSnapshot would be ambiguous"
                )
            by_logical[element.logical_id] = element
        by_hash: dict[str, list[str]] = {}
        for element in ordered:
            by_hash.setdefault(element.content_hash, []).append(element.logical_id)
        return ElementIndex(
            version_id=version_id,
            elements=ordered,
            by_logical_id=by_logical,
            by_content_hash={key: tuple(value) for key, value in by_hash.items()},
            order=tuple(element.logical_id for element in ordered),
        )

    def neighbours(self, logical_id: str) -> tuple[str | None, str | None]:
        """The logical ids reading-order-adjacent to this one."""
        try:
            position = self.order.index(logical_id)
        except ValueError:
            return None, None
        before = self.order[position - 1] if position > 0 else None
        after = self.order[position + 1] if position + 1 < len(self.order) else None
        return before, after

    def is_unique_content(self, logical_id: str) -> bool:
        """Whether this element's content hash names it alone in its version.

        §9.4's first candidate tier only means anything when the hash picks out
        one element. Two identical rows in one table make an exact-content match
        a coin flip, and the tier must not fire on them.
        """
        element = self.by_logical_id.get(logical_id)
        if element is None:
            return False
        return len(self.by_content_hash.get(element.content_hash, ())) == 1
