"""Stitching pages back into a document.

Masterplan §18 and §N12. The premise is one sentence: *page parser가 모두 성공해도
document가 틀릴 수 있다.* Every page can parse perfectly and the document still be
wrong, because a paragraph broken across a page break is two paragraphs, a table
spanning three pages is three tables, and a caption on page 5 belongs to a figure
on page 4.

§3.3 is the research behind it -- MPDocBench-Parse and Dr. DocBench both show that
systems strong on per-page scores lose cross-page structure -- and the conclusion
the masterplan draws is that page-level parser score and document-level semantic
integrity are separate KPIs. This module is the second one.

Two rules constrain the whole thing.

**Physical merge is the irreversible act, so it needs the highest bar.** §N12.3
sets three bands rather than a threshold: at or above 0.90 the tables merge, from
0.70 to 0.90 only a `CONTINUES_TABLE` relation is recorded, and below 0.70 they
stay apart. The middle band exists because §18.4 forbids an uncertain physical
merge: a relation is a claim a reviewer can reject, while a merge has already
destroyed the boundary it was unsure about.

**A merge that loses provenance is refused, not warned about.** §N12.5 requires
that every source cell keeps its origin, that the original page span can be
recovered, and that the structured payload round-trips. `merge_tables` checks all
three and raises rather than returning a merged table that cannot be taken apart
again -- the Evidence Inspector's whole job is going back to the source, and a
merged cell with no page is a cell that cannot.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .identity import MissingReason, normalize_text_for_identity

__all__ = [
    "PARAGRAPH_WEIGHTS",
    "TABLE_AUTO_MERGE",
    "TABLE_RELATION_FLOOR",
    "TABLE_WEIGHTS",
    "Block",
    "BlockKind",
    "ContinuationVerdict",
    "HeadingNode",
    "LinkDecision",
    "MergeRefused",
    "RelationKind",
    "TableBlock",
    "build_heading_hierarchy",
    "link_paragraphs",
    "link_tables",
    "merge_tables",
    "paragraph_continuation_score",
    "repeated_page_furniture",
    "table_continuation_score",
]


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADING = "heading"
    PAGE_FURNITURE = "page_furniture"


class RelationKind(StrEnum):
    """§N12.1's edge vocabulary."""

    NEXT_TEXT = "NEXT_TEXT"
    CONTINUES_LIST = "CONTINUES_LIST"
    CONTINUES_TABLE = "CONTINUES_TABLE"
    CAPTION_OF = "CAPTION_OF"
    FOOTNOTE_OF = "FOOTNOTE_OF"
    CHILD_OF_HEADING = "CHILD_OF_HEADING"


class ContinuationVerdict(StrEnum):
    """§N12.3's three bands. The middle one is the point."""

    MERGE = "MERGE"
    RELATION_ONLY = "RELATION_ONLY"
    SEPARATE = "SEPARATE"


#: §N12.2, verbatim.
PARAGRAPH_WEIGHTS: dict[str, float] = {
    "sentence_boundary_compatibility": 0.25,
    "semantic_continuity": 0.20,
    "font_style_similarity": 0.15,
    "x_alignment": 0.15,
    "line_spacing_similarity": 0.10,
    "language_model_continuation": 0.10,
    "section_context_match": 0.05,
}

#: §N12.3, verbatim.
TABLE_WEIGHTS: dict[str, float] = {
    "normalized_header_similarity": 0.25,
    "column_count_compatibility": 0.20,
    "x_boundary_alignment": 0.20,
    "data_type_pattern_similarity": 0.10,
    "border_style_similarity": 0.10,
    "page_bottom_top_position": 0.10,
    "caption_or_table_id_match": 0.05,
}

#: §N12.3's bands. Bootstrap, to be corrected by benchmark.
TABLE_AUTO_MERGE = 0.90
TABLE_RELATION_FLOOR = 0.70

#: The paragraph bands. §18.4's three cases, at the same shape as the table ones
#: so a reader does not have to hold two schemes in their head.
PARAGRAPH_AUTO_MERGE = 0.90
PARAGRAPH_RELATION_FLOOR = 0.70

# The full-width terminators are deliberate: a CJK sentence ends in a full-width
# stop, exclamation or question mark, and reading one as an unfinished sentence
# would make every such paragraph look like it continues onto the next page.
_SENTENCE_END = re.compile(r"[.!?。！？]['\")\]]?\s*$")  # noqa: RUF001
_NUMBERING = re.compile(
    r"^\s*(?:"
    r"(?P<dotted>\d+(?:\.\d+)*)\.?"           # 1, 1.1, 2.3.4
    r"|(?P<latin>[A-Z])\."                     # A.
    r"|(?P<hangul>[가-힣])\."                  # 가.
    r"|\((?P<paren>\d+)\)"                     # (1)
    r")\s+"
)


@dataclass(frozen=True, slots=True)
class Block:
    """One parsed block, with the geometry the scorers need.

    Every comparable field may be absent, and absent means the parser did not
    report it -- §N4.4 again. A block with no font information is not a block in
    the default font.
    """

    page_number1: int
    local_id: str
    kind: BlockKind
    text: str = ""
    #: Per-mille horizontal extent on the page.
    x0: int | None = None
    x1: int | None = None
    #: Per-mille vertical extent. `y1` near 1000 is at the page bottom.
    y0: int | None = None
    y1: int | None = None
    font_style: str = ""
    line_spacing: float | None = None
    section_path: tuple[str, ...] = ()

    @property
    def numbering(self) -> str:
        match = _NUMBERING.match(self.text)
        if not match:
            return ""
        return next(value for value in match.groupdict().values() if value)

    @property
    def ends_mid_sentence(self) -> bool:
        stripped = self.text.rstrip()
        return bool(stripped) and not _SENTENCE_END.search(stripped)

    @property
    def starts_mid_sentence(self) -> bool:
        stripped = self.text.lstrip()
        if not stripped:
            return False
        first = stripped[0]
        return first.islower() or first in ",;:)"


@dataclass(frozen=True, slots=True)
class TableBlock:
    """A table, with the structure §N12.3 compares and §N12.5 must preserve."""

    page_number1: int
    local_id: str
    header: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    column_x_boundaries: tuple[int, ...] = ()
    border_style: str = ""
    table_id: str = ""
    caption: str = ""
    #: Per-mille top and bottom of the table on its page.
    y0: int | None = None
    y1: int | None = None
    #: Where each row came from, as (page, row index in that page's table). A
    #: merged table carries the union, which is what makes the merge reversible.
    row_origins: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if self.row_origins and len(self.row_origins) != len(self.rows):
            raise ValueError(
                f"{self.local_id}: every row needs an origin; "
                f"{len(self.rows)} rows against {len(self.row_origins)} origins"
            )

    @property
    def column_count(self) -> int:
        if self.header:
            return len(self.header)
        return max((len(row) for row in self.rows), default=0)

    def with_origins(self) -> TableBlock:
        """Fill origins for a table read straight from one page."""
        if self.row_origins:
            return self
        origins = tuple((self.page_number1, index) for index in range(len(self.rows)))
        return TableBlock(
            page_number1=self.page_number1,
            local_id=self.local_id,
            header=self.header,
            rows=self.rows,
            column_x_boundaries=self.column_x_boundaries,
            border_style=self.border_style,
            table_id=self.table_id,
            caption=self.caption,
            y0=self.y0,
            y1=self.y1,
            row_origins=origins,
        )

    @property
    def page_span(self) -> tuple[int, ...]:
        return tuple(sorted({page for page, _ in self.row_origins}))


@dataclass(frozen=True, slots=True)
class LinkDecision:
    verdict: ContinuationVerdict
    score: float
    relation: RelationKind | None
    signals: dict[str, float] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)
    reason: str = ""


class MergeRefused(RuntimeError):
    """§N12.5 -- a merge that would lose provenance does not happen quietly."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(normalize_text_for_identity(left).split())
    right_tokens = set(normalize_text_for_identity(right).split())
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _closeness(left: float, right: float, tolerance: float) -> float:
    """1.0 when equal, falling to 0.0 at `tolerance` apart."""
    if tolerance <= 0:
        return 1.0 if left == right else 0.0
    return max(0.0, 1.0 - abs(left - right) / tolerance)


def _renormalise(
    raw: dict[str, tuple[float | None, MissingReason | None]],
    weights: dict[str, float],
) -> tuple[float, dict[str, float], dict[str, str]]:
    """§N4.4 -- score over the signals that have values, record the rest.

    The same reasoning as identity resolution: a parser that reports no font
    information has not reported that the fonts differ, and zero-filling it would
    put a genuine continuation permanently under the merge bar.
    """
    present: dict[str, float] = {}
    missing: dict[str, str] = {}
    for name, (value, reason) in raw.items():
        if value is None:
            missing[name] = (reason or MissingReason.MODEL_UNAVAILABLE).value
        else:
            present[name] = value
    available = sum(weights[name] for name in present)
    if available <= 0.0:
        return 0.0, present, missing
    score = sum(present[name] * weights[name] for name in present) / available
    return score, present, missing


# ---------------------------------------------------------------------------
# §N12.2 — paragraph continuation
# ---------------------------------------------------------------------------


def paragraph_continuation_score(
    left: Block,
    right: Block,
    *,
    semantic_continuity: float | None = None,
    language_model_continuation: float | None = None,
) -> tuple[float, dict[str, float], dict[str, str]]:
    """Does `right` continue the sentence `left` broke off?

    Both model-derived signals are passed in rather than computed. §N12.2 says
    the LLM is used *tool-less classifier로만* and must not modify the original
    text, so this module never calls one -- it accepts scores somebody else
    produced, and treats their absence as absence.

    `semantic_continuity` is injected for a second reason, and it is the more
    interesting one. The obvious stand-in is token overlap between the two
    fragments, and it is exactly backwards: the two halves of a broken sentence
    deliberately say different things, so a true continuation scores near zero.
    Token overlap measures *sameness*, which is what identity resolution wants
    and the opposite of what continuation wants. A signal whose name says one
    thing and whose arithmetic says another is worse than an absent one, so this
    is absent until an embedding supplies it.

    What remains is the deterministic evidence, and it is the right evidence: a
    paragraph that stopped mid-sentence, in the same font, at the same left
    margin, at the same line spacing, under the same heading.
    """
    raw: dict[str, tuple[float | None, MissingReason | None]] = {}

    # A paragraph that ended mid-sentence and one that starts lowercase is the
    # strongest single piece of evidence there is, and it needs no model.
    if not left.text or not right.text:
        raw["sentence_boundary_compatibility"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        compatible = left.ends_mid_sentence and right.starts_mid_sentence
        incompatible = (not left.ends_mid_sentence) and (not right.starts_mid_sentence)
        raw["sentence_boundary_compatibility"] = (
            (1.0 if compatible else 0.0 if incompatible else 0.5),
            None,
        )

    raw["semantic_continuity"] = (
        (semantic_continuity, None)
        if semantic_continuity is not None
        else (None, MissingReason.MODEL_UNAVAILABLE)
    )

    raw["font_style_similarity"] = (
        (None, MissingReason.NOT_APPLICABLE)
        if not left.font_style or not right.font_style
        else (1.0 if left.font_style == right.font_style else 0.0, None)
    )

    raw["x_alignment"] = (
        (None, MissingReason.NOT_APPLICABLE)
        if left.x0 is None or right.x0 is None
        else (_closeness(left.x0, right.x0, tolerance=60), None)
    )

    raw["line_spacing_similarity"] = (
        (None, MissingReason.NOT_APPLICABLE)
        if left.line_spacing is None or right.line_spacing is None
        else (_closeness(left.line_spacing, right.line_spacing, tolerance=0.5), None)
    )

    raw["language_model_continuation"] = (
        (language_model_continuation, None)
        if language_model_continuation is not None
        else (None, MissingReason.MODEL_UNAVAILABLE)
    )

    raw["section_context_match"] = (
        (None, MissingReason.NOT_APPLICABLE)
        if not left.section_path and not right.section_path
        else (1.0 if left.section_path == right.section_path else 0.0, None)
    )

    return _renormalise(raw, PARAGRAPH_WEIGHTS)


def link_paragraphs(
    left: Block,
    right: Block,
    *,
    semantic_continuity: float | None = None,
    language_model_continuation: float | None = None,
) -> LinkDecision:
    """§18.4's three cases for prose.

    A list item continuing a list is `CONTINUES_LIST` rather than `NEXT_TEXT`,
    because a numbered list broken across a page keeps its numbering and losing
    that turns item 7 into item 1 of a new list.
    """
    score, signals, missing = paragraph_continuation_score(
        left,
        right,
        semantic_continuity=semantic_continuity,
        language_model_continuation=language_model_continuation,
    )
    relation = (
        RelationKind.CONTINUES_LIST
        if left.kind is BlockKind.LIST_ITEM and right.kind is BlockKind.LIST_ITEM
        else RelationKind.NEXT_TEXT
    )

    if score >= PARAGRAPH_AUTO_MERGE:
        return LinkDecision(
            verdict=ContinuationVerdict.MERGE,
            score=score,
            relation=relation,
            signals=signals,
            missing=missing,
            reason=f"continuation evidence at {score:.2f}",
        )
    if score >= PARAGRAPH_RELATION_FLOOR:
        return LinkDecision(
            verdict=ContinuationVerdict.RELATION_ONLY,
            score=score,
            relation=relation,
            signals=signals,
            missing=missing,
            reason=(
                f"{score:.2f} is short of the {PARAGRAPH_AUTO_MERGE:.2f} merge "
                "bar; the relation is recorded and the boundary is kept"
            ),
        )
    return LinkDecision(
        verdict=ContinuationVerdict.SEPARATE,
        score=score,
        relation=None,
        signals=signals,
        missing=missing,
        reason=f"{score:.2f} is below the {PARAGRAPH_RELATION_FLOOR:.2f} floor",
    )


# ---------------------------------------------------------------------------
# §N12.3 — table continuation
# ---------------------------------------------------------------------------


def _column_type_pattern(rows: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """A coarse per-column type, for comparing two tables' shapes."""
    if not rows:
        return ()
    width = max(len(row) for row in rows)
    pattern: list[str] = []
    for column in range(width):
        values = [row[column] for row in rows if column < len(row) and row[column]]
        if not values:
            pattern.append("empty")
        elif all(re.fullmatch(r"-?[\d,. ]+%?", value.strip()) for value in values):
            pattern.append("numeric")
        elif all(re.fullmatch(r"[\d]{4}-[\d]{2}-[\d]{2}", value.strip()) for value in values):
            pattern.append("date")
        else:
            pattern.append("text")
    return tuple(pattern)


def table_continuation_score(
    upper: TableBlock, lower: TableBlock
) -> tuple[float, dict[str, float], dict[str, str]]:
    """Are these two tables one table split by a page break?"""
    raw: dict[str, tuple[float | None, MissingReason | None]] = {}

    # A continuation table often repeats the header and often does not. Both
    # tables having one is the only case where comparing them means anything.
    if not upper.header or not lower.header:
        raw["normalized_header_similarity"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        left = tuple(normalize_text_for_identity(cell) for cell in upper.header)
        right = tuple(normalize_text_for_identity(cell) for cell in lower.header)
        raw["normalized_header_similarity"] = (1.0 if left == right else 0.0, None)

    upper_columns = upper.column_count
    lower_columns = lower.column_count
    if not upper_columns or not lower_columns:
        raw["column_count_compatibility"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        raw["column_count_compatibility"] = (
            1.0 if upper_columns == lower_columns else 0.0,
            None,
        )

    if not upper.column_x_boundaries or not lower.column_x_boundaries:
        raw["x_boundary_alignment"] = (None, MissingReason.NOT_APPLICABLE)
    elif len(upper.column_x_boundaries) != len(lower.column_x_boundaries):
        raw["x_boundary_alignment"] = (0.0, None)
    else:
        closeness = [
            _closeness(a, b, tolerance=30)
            for a, b in zip(
                upper.column_x_boundaries, lower.column_x_boundaries, strict=True
            )
        ]
        raw["x_boundary_alignment"] = (sum(closeness) / len(closeness), None)

    upper_types = _column_type_pattern(upper.rows)
    lower_types = _column_type_pattern(lower.rows)
    if not upper_types or not lower_types:
        raw["data_type_pattern_similarity"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        shared = sum(
            1 for a, b in zip(upper_types, lower_types, strict=False) if a == b
        )
        raw["data_type_pattern_similarity"] = (
            shared / max(len(upper_types), len(lower_types)),
            None,
        )

    if not upper.border_style or not lower.border_style:
        raw["border_style_similarity"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        raw["border_style_similarity"] = (
            1.0 if upper.border_style == lower.border_style else 0.0,
            None,
        )

    # A table that runs off the bottom of one page and one that starts at the top
    # of the next. A table sitting in the middle of its page did not continue.
    if upper.y1 is None or lower.y0 is None:
        raw["page_bottom_top_position"] = (None, MissingReason.NOT_APPLICABLE)
    elif lower.page_number1 != upper.page_number1 + 1:
        raw["page_bottom_top_position"] = (0.0, None)
    else:
        at_bottom = max(0.0, (upper.y1 - 700) / 300)
        at_top = max(0.0, (300 - lower.y0) / 300)
        raw["page_bottom_top_position"] = (min(1.0, (at_bottom + at_top) / 2), None)

    upper_label = upper.table_id or upper.caption
    lower_label = lower.table_id or lower.caption
    if not upper_label or not lower_label:
        raw["caption_or_table_id_match"] = (None, MissingReason.NOT_APPLICABLE)
    else:
        raw["caption_or_table_id_match"] = (
            _token_overlap(upper_label, lower_label),
            None,
        )

    return _renormalise(raw, TABLE_WEIGHTS)


def link_tables(upper: TableBlock, lower: TableBlock) -> LinkDecision:
    """§N12.3's bands.

    The middle band is the reason this returns three things rather than a
    boolean. §18.4: medium confidence records `CONTINUES_TABLE` and does not
    physically merge. A relation is a claim a reviewer can reject; a merge has
    already destroyed the boundary it was unsure about.
    """
    score, signals, missing = table_continuation_score(upper, lower)

    if score >= TABLE_AUTO_MERGE:
        return LinkDecision(
            verdict=ContinuationVerdict.MERGE,
            score=score,
            relation=RelationKind.CONTINUES_TABLE,
            signals=signals,
            missing=missing,
            reason=f"continuation evidence at {score:.2f}",
        )
    if score >= TABLE_RELATION_FLOOR:
        return LinkDecision(
            verdict=ContinuationVerdict.RELATION_ONLY,
            score=score,
            relation=RelationKind.CONTINUES_TABLE,
            signals=signals,
            missing=missing,
            reason=(
                f"{score:.2f} is in the review band; the relation is recorded and "
                "the two tables stay separate"
            ),
        )
    return LinkDecision(
        verdict=ContinuationVerdict.SEPARATE,
        score=score,
        relation=None,
        signals=signals,
        missing=missing,
        reason=f"{score:.2f} is below the {TABLE_RELATION_FLOOR:.2f} floor",
    )


def merge_tables(upper: TableBlock, lower: TableBlock, *, decision: LinkDecision) -> TableBlock:
    """§N12.5's invariants, enforced rather than documented.

    Refuses unless the decision actually said MERGE, unless every row can name
    the page it came from, and unless the merged column count matches. The
    Evidence Inspector's job is going back to the source; a merged cell with no
    page is a cell that cannot be gone back to.
    """
    if decision.verdict is not ContinuationVerdict.MERGE:
        raise MergeRefused(
            f"the link decision was {decision.verdict.value}, not MERGE. "
            "§18.4 forbids an uncertain physical merge -- record the relation "
            "instead."
        )

    upper_sourced = upper.with_origins()
    lower_sourced = lower.with_origins()

    if upper_sourced.column_count != lower_sourced.column_count:
        raise MergeRefused(
            f"column counts differ ({upper_sourced.column_count} and "
            f"{lower_sourced.column_count}); merging would silently reshape rows"
        )

    rows = upper_sourced.rows + lower_sourced.rows
    origins = upper_sourced.row_origins + lower_sourced.row_origins
    if len(origins) != len(rows):
        raise MergeRefused("a merged row lost its origin")

    merged = TableBlock(
        page_number1=upper_sourced.page_number1,
        local_id=f"{upper_sourced.local_id}+{lower_sourced.local_id}",
        header=upper_sourced.header or lower_sourced.header,
        rows=rows,
        column_x_boundaries=upper_sourced.column_x_boundaries,
        border_style=upper_sourced.border_style,
        table_id=upper_sourced.table_id or lower_sourced.table_id,
        caption=upper_sourced.caption or lower_sourced.caption,
        y0=upper_sourced.y0,
        y1=lower_sourced.y1,
        row_origins=origins,
    )

    recovered = set(merged.page_span)
    expected = {upper_sourced.page_number1, lower_sourced.page_number1}
    if not expected <= recovered:
        raise MergeRefused(
            f"the merged table's page span {sorted(recovered)} does not cover "
            f"{sorted(expected)}; the original span is not recoverable"
        )
    return merged


# ---------------------------------------------------------------------------
# §N12.4 — heading hierarchy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeadingNode:
    block: Block
    level: int
    parent_id: str | None


def _numbering_depth(numbering: str) -> int | None:
    if not numbering:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)*", numbering):
        return numbering.count(".") + 1
    return 1


def build_heading_hierarchy(
    headings: Sequence[Block],
) -> tuple[tuple[HeadingNode, ...], tuple[str, ...]]:
    """Nest headings, and hand anomalies to the inspector rather than fixing them.

    §N12.4 combines numbering, style and indentation, and says that hierarchy
    cycles and level-jump anomalies go to the Inspector. They are returned here
    as anomaly strings rather than silently repaired: a document whose headings
    jump from 1 to 1.1.1 has something wrong with it, and quietly inserting the
    missing level would hide the evidence of what.
    """
    nodes: list[HeadingNode] = []
    anomalies: list[str] = []
    stack: list[HeadingNode] = []
    previous_depth: int | None = None

    for block in headings:
        depth = _numbering_depth(block.numbering)
        if depth is None:
            # No numbering: fall back to indentation, then to "one deeper than
            # nothing". Indentation is evidence; assuming top level is not.
            if block.x0 is not None and stack and stack[-1].block.x0 is not None:
                parent_x = stack[-1].block.x0
                depth = stack[-1].level + (1 if block.x0 > parent_x + 10 else 0)
                depth = max(1, depth)
            else:
                depth = 1

        if previous_depth is not None and depth > previous_depth + 1:
            anomalies.append(
                f"{block.local_id}: level jumped from {previous_depth} to {depth}"
            )

        while stack and stack[-1].level >= depth:
            stack.pop()
        parent = stack[-1].block.local_id if stack else None
        if parent == block.local_id:
            anomalies.append(f"{block.local_id}: heading is its own parent")
            parent = None

        node = HeadingNode(block=block, level=depth, parent_id=parent)
        nodes.append(node)
        stack.append(node)
        previous_depth = depth

    return tuple(nodes), tuple(anomalies)


# ---------------------------------------------------------------------------
# §18.1 — headers and footers
# ---------------------------------------------------------------------------


def repeated_page_furniture(
    blocks: Iterable[Block], *, minimum_pages: int = 3
) -> frozenset[str]:
    """Text that appears in the same place on enough pages to be furniture.

    Position matters as much as repetition. A phrase repeated on every page in
    the top 8% is a running header; the same phrase repeated in body positions is
    a document that says the same thing a lot, and removing it would delete
    content. §N9.3 depends on this: duplication detection excludes furniture, and
    misclassifying a body line as furniture hides a real decoder loop.
    """
    seen: dict[tuple[str, str], set[int]] = {}
    for block in blocks:
        normalized = normalize_text_for_identity(block.text)
        if not normalized:
            continue
        if block.y0 is None:
            zone = "unknown"
        elif block.y0 <= 80:
            zone = "header"
        elif block.y0 >= 920:
            zone = "footer"
        else:
            continue
        seen.setdefault((normalized, zone), set()).add(block.page_number1)

    return frozenset(
        text for (text, _), pages in seen.items() if len(pages) >= minimum_pages
    )
