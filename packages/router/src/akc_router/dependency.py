"""Dependency-aware DAG (program §8, blueprint §23).

Eight edge kinds, each built from *native structure the reader actually
reported*. Nothing here guesses from page proximity alone: two consecutive
pages that both contain tables are not a continued table unless the reader saw
a table run to the bottom of one and resume at the top of the next with a
matching column signature.

The important half is `unknown`. When the structure input for an edge kind is
`None` the reader could not tell, and that produces **no edge and a recorded
`dependency_unknown` signal** -- never an edge on a hunch and never a silent
absence, because a missing edge and an unknowable edge schedule identically but
mean completely different things.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from .execution_plan import DependencyEdge, DependencyKind


@dataclass(frozen=True, slots=True)
class UnitStructure:
    """Native structure for one unit. `None` means the reader could not tell.

    Fields come from the lane-A readers: PDF layout for tables, footnotes and
    figures; `python-pptx` for speaker notes; `openpyxl` for preserved formula
    precedents; the mail/XBRL families for the rest. A family with no reader
    leaves its fields `None` and every edge it would have carried is unknown.
    """

    unit_id: str
    page_index0: int
    # Continued table: does a table run to the bottom / resume at the top, and
    # what are its columns? All three must be known for an edge to exist.
    table_runs_to_bottom: bool | None = None
    table_resumes_at_top: bool | None = None
    table_column_signature: str | None = None
    # Footnotes: markers this unit *defines*, and markers it *references*.
    footnote_definitions: tuple[str, ...] | None = None
    footnote_references: tuple[str, ...] | None = None
    # Figures and callouts: ids this unit contains, and ids it refers to.
    figure_ids: tuple[str, ...] | None = None
    caption_references: tuple[str, ...] | None = None
    image_callout_references: tuple[str, ...] | None = None
    # Office and mail natives.
    slide_notes_for_unit_id: str | None = None
    formula_precedent_unit_ids: tuple[str, ...] | None = None
    attachment_of_unit_id: str | None = None
    xbrl_context_unit_id: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    edges: tuple[DependencyEdge, ...] = ()
    #: `(unit_id, kind)` pairs the reader could not decide. Recorded, not zeroed.
    unknown: tuple[tuple[str, DependencyKind], ...] = ()
    signals: tuple[str, ...] = field(default_factory=tuple)

    def edges_into(self, unit_id: str) -> tuple[DependencyEdge, ...]:
        return tuple(edge for edge in self.edges if edge.to_unit_id == unit_id)


def build_dependency_edges(structures: Sequence[UnitStructure]) -> DependencyGraph:
    """Build the §23 edges. Deterministic, and ordered by kind then unit."""
    by_id = {item.unit_id: item for item in structures}
    ordered = sorted(structures, key=lambda item: (item.page_index0, item.unit_id))
    edges: list[DependencyEdge] = []
    unknown: list[tuple[str, DependencyKind]] = []

    _continued_tables(ordered, edges, unknown)
    _footnotes(ordered, edges, unknown)
    _figure_captions(ordered, edges, unknown)
    _image_callouts(ordered, edges, unknown)
    _named_parent(
        ordered,
        by_id,
        edges,
        unknown,
        attribute="slide_notes_for_unit_id",
        kind=DependencyKind.SLIDE_NOTES,
    )
    _named_parent(
        ordered,
        by_id,
        edges,
        unknown,
        attribute="attachment_of_unit_id",
        kind=DependencyKind.EMAIL_ATTACHMENT,
    )
    _named_parent(
        ordered,
        by_id,
        edges,
        unknown,
        attribute="xbrl_context_unit_id",
        kind=DependencyKind.XBRL_CONTEXT,
    )
    _sheet_formulas(ordered, by_id, edges, unknown)

    deduped = tuple(
        dict.fromkeys(
            sorted(edges, key=lambda edge: (edge.kind.value, edge.from_unit_id, edge.to_unit_id))
        )
    )
    unknown_pairs = tuple(dict.fromkeys(unknown))
    return DependencyGraph(
        edges=deduped,
        unknown=unknown_pairs,
        signals=tuple(
            f"dependency_unknown:{kind.value}:{unit_id}" for unit_id, kind in unknown_pairs
        ),
    )


def _continued_tables(
    ordered: Sequence[UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
) -> None:
    """A table continues only when both sides agree, columns included."""
    for previous, current in pairwise(ordered):
        if previous.table_runs_to_bottom is None or current.table_resumes_at_top is None:
            unknown.append((current.unit_id, DependencyKind.CONTINUED_TABLE))
            continue
        if not (previous.table_runs_to_bottom and current.table_resumes_at_top):
            continue
        if previous.table_column_signature is None or current.table_column_signature is None:
            # Both edges look plausible and neither is checkable. Say so.
            unknown.append((current.unit_id, DependencyKind.CONTINUED_TABLE))
            continue
        if previous.table_column_signature != current.table_column_signature:
            continue
        edges.append(
            DependencyEdge(
                from_unit_id=previous.unit_id,
                to_unit_id=current.unit_id,
                kind=DependencyKind.CONTINUED_TABLE,
            )
        )


def _footnotes(
    ordered: Sequence[UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
) -> None:
    """The unit that *defines* a marker must land before the one that cites it."""
    definitions: dict[str, str] = {}
    for item in ordered:
        if item.footnote_definitions is None:
            unknown.append((item.unit_id, DependencyKind.FOOTNOTE))
            continue
        for marker in item.footnote_definitions:
            definitions.setdefault(marker, item.unit_id)
    for item in ordered:
        if item.footnote_references is None:
            unknown.append((item.unit_id, DependencyKind.FOOTNOTE))
            continue
        for marker in item.footnote_references:
            source = definitions.get(marker)
            if source is None or source == item.unit_id:
                continue
            edges.append(
                DependencyEdge(
                    from_unit_id=source,
                    to_unit_id=item.unit_id,
                    kind=DependencyKind.FOOTNOTE,
                )
            )


def _figure_captions(
    ordered: Sequence[UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
) -> None:
    owners = _figure_owners(ordered, unknown, DependencyKind.FIGURE_CAPTION)
    for item in ordered:
        if item.caption_references is None:
            unknown.append((item.unit_id, DependencyKind.FIGURE_CAPTION))
            continue
        _link(item, item.caption_references, owners, DependencyKind.FIGURE_CAPTION, edges)


def _image_callouts(
    ordered: Sequence[UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
) -> None:
    owners = _figure_owners(ordered, unknown, DependencyKind.IMAGE_CALLOUT)
    for item in ordered:
        if item.image_callout_references is None:
            unknown.append((item.unit_id, DependencyKind.IMAGE_CALLOUT))
            continue
        _link(item, item.image_callout_references, owners, DependencyKind.IMAGE_CALLOUT, edges)


def _figure_owners(
    ordered: Sequence[UnitStructure],
    unknown: list[tuple[str, DependencyKind]],
    kind: DependencyKind,
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for item in ordered:
        if item.figure_ids is None:
            unknown.append((item.unit_id, kind))
            continue
        for figure_id in item.figure_ids:
            owners.setdefault(figure_id, item.unit_id)
    return owners


def _link(
    item: UnitStructure,
    references: Iterable[str],
    owners: dict[str, str],
    kind: DependencyKind,
    edges: list[DependencyEdge],
) -> None:
    for reference in references:
        owner = owners.get(reference)
        if owner is None or owner == item.unit_id:
            continue
        edges.append(DependencyEdge(from_unit_id=owner, to_unit_id=item.unit_id, kind=kind))


def _named_parent(
    ordered: Sequence[UnitStructure],
    by_id: dict[str, UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
    *,
    attribute: str,
    kind: DependencyKind,
) -> None:
    """One edge kind that is just "this unit belongs to that one"."""
    for item in ordered:
        parent = getattr(item, attribute)
        if parent is None:
            continue
        if parent not in by_id or parent == item.unit_id:
            unknown.append((item.unit_id, kind))
            continue
        edges.append(DependencyEdge(from_unit_id=parent, to_unit_id=item.unit_id, kind=kind))


def _sheet_formulas(
    ordered: Sequence[UnitStructure],
    by_id: dict[str, UnitStructure],
    edges: list[DependencyEdge],
    unknown: list[tuple[str, DependencyKind]],
) -> None:
    for item in ordered:
        if item.formula_precedent_unit_ids is None:
            unknown.append((item.unit_id, DependencyKind.SHEET_FORMULA))
            continue
        for precedent in item.formula_precedent_unit_ids:
            if precedent not in by_id or precedent == item.unit_id:
                unknown.append((item.unit_id, DependencyKind.SHEET_FORMULA))
                continue
            edges.append(
                DependencyEdge(
                    from_unit_id=precedent,
                    to_unit_id=item.unit_id,
                    kind=DependencyKind.SHEET_FORMULA,
                )
            )


__all__ = ["DependencyGraph", "UnitStructure", "build_dependency_edges"]
