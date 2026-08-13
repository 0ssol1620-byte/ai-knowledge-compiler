"""The diff decides what the rest of the system goes looking for.

Dependency traversal walks out from `changed_logical_ids`, impact marks
artifacts stale from that set, and selective recompile rebuilds exactly it. A
diff that names the wrong unit sends all three after the wrong thing, so these
tests are mostly about what it refuses to claim.
"""

from __future__ import annotations

import pytest
from akc_cir.identity import LogicalIdentityResolver
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


def _unit(
    logical_id: str,
    text: str,
    *,
    path: tuple[str, ...] = ("Warranty", "Coverage"),
    anchor: str = "4.2 Exceptions",
    neighbours: tuple[str, ...] = ("4.1 Scope", "4.3 Claims"),
    evidence: str | None = "ev_one",
    page: int | None = 17,
    entities: frozenset[str] = frozenset(),
    relationships: frozenset[tuple[str, str, str]] = frozenset(),
    authority: str | None = None,
) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=logical_id,
        text=text,
        document_path=path,
        anchor=anchor,
        neighbour_anchors=neighbours,
        evidence_id=evidence,
        page_number1=page,
        entities=entities,
        relationships=relationships,
        authority=authority,
    )


TWO_YEARS = "The warranty covers parts and labour for two years from delivery."
THREE_YEARS = "The warranty covers parts and labour for three years from delivery."


# --------------------------------------------------------------------------
# L0 — the cheap question, and its authority over the levels below
# --------------------------------------------------------------------------


def test_identical_bytes_are_not_a_change() -> None:
    diff = diff_documents(before_sha256=A, after_sha256=A)
    assert diff.content_changed is False
    assert [c.kind for c in diff.changes] == [ChangeKind.CONTENT_UNCHANGED]
    assert diff.changed_logical_ids == ()


def test_identical_bytes_cannot_produce_a_semantic_change(caplog) -> None:
    """A level below L0 must never disagree with it."""
    diff = diff_documents(
        before_sha256=A,
        after_sha256=A,
        level=DiffLevel.GRAPH,
        before_shape=DocumentShape(block_count=10),
        after_shape=DocumentShape(block_count=999),
        before_units=[_unit("ku_a", TWO_YEARS)],
        after_units=[_unit("ku_a", THREE_YEARS)],
    )
    assert diff.content_changed is False
    assert [c.kind for c in diff.changes] == [ChangeKind.CONTENT_UNCHANGED]


def test_changed_bytes_at_l0_say_only_that() -> None:
    diff = diff_documents(before_sha256=A, after_sha256=B)
    assert diff.content_changed is True
    assert diff.changes == ()


# --------------------------------------------------------------------------
# L1 — shape, and only shape
# --------------------------------------------------------------------------


def test_structural_diff_needs_both_shapes() -> None:
    with pytest.raises(ValueError, match="need a DocumentShape"):
        diff_documents(before_sha256=A, after_sha256=B, level=DiffLevel.STRUCTURAL)


def test_a_changed_heading_tree_is_structural() -> None:
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.STRUCTURAL,
        before_shape=DocumentShape(heading_path_set=frozenset({("Warranty",)})),
        after_shape=DocumentShape(
            heading_path_set=frozenset({("Warranty",), ("Shipping",)})
        ),
    )
    kinds = [c.kind for c in diff.changes]
    assert ChangeKind.STRUCTURE_CHANGED in kinds
    assert "1 added" in diff.changes[0].detail


def test_rewritten_words_with_the_same_shape_are_not_a_structural_change() -> None:
    """L1 asks about shape. Different words under the same skeleton is L3's business."""
    shape = DocumentShape(
        heading_path_set=frozenset({("Warranty",)}), block_count=12
    )
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.STRUCTURAL,
        before_shape=shape,
        after_shape=shape,
    )
    assert diff.changes == ()


def test_a_changed_table_shape_is_reported() -> None:
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.STRUCTURAL,
        before_shape=DocumentShape(table_shapes=((3, 4),)),
        after_shape=DocumentShape(table_shapes=((3, 5),)),
    )
    assert any("table shape" in c.detail for c in diff.changes)


# --------------------------------------------------------------------------
# L3 — the case the product exists for
# --------------------------------------------------------------------------


def _semantic(before_units, after_units, level=DiffLevel.SEMANTIC, resolver=None):
    return diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=level,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=before_units,
        after_units=after_units,
        resolver=resolver,
    )


def test_two_years_becoming_three_is_one_modified_claim() -> None:
    diff = _semantic([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)])

    modified = [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM]
    assert len(modified) == 1
    assert modified[0].logical_id == "ku_warranty"
    assert "two years" in modified[0].before
    assert "three years" in modified[0].after
    assert diff.changed_logical_ids == ("ku_warranty",)


def test_a_unit_that_did_not_change_produces_no_change() -> None:
    diff = _semantic([_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", TWO_YEARS)])
    assert [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM] == []


def test_reformatting_is_not_a_claim_change() -> None:
    """Whitespace and casing are folded; the clause did not change."""
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS)],
        [
            _unit(
                "ku_warranty",
                "  THE WARRANTY covers parts and labour for two years from delivery.  ",
            )
        ],
    )
    assert [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM] == []


def test_a_new_clause_is_added_not_modified() -> None:
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS)],
        [
            _unit("ku_warranty", TWO_YEARS),
            _unit(
                "ku_shipping",
                "Shipments are tendered to the earliest carrier.",
                path=("Shipping",),
                anchor="9.1 Carriers",
                neighbours=(),
            ),
        ],
    )
    added = [c for c in diff.changes if c.kind is ChangeKind.UNIT_ADDED]
    assert [c.logical_id for c in added] == ["ku_shipping"]


def test_a_deleted_clause_is_removed() -> None:
    diff = _semantic(
        [
            _unit("ku_warranty", TWO_YEARS),
            _unit(
                "ku_shipping",
                "Shipments are tendered to the earliest carrier.",
                path=("Shipping",),
                anchor="9.1 Carriers",
                neighbours=(),
            ),
        ],
        [_unit("ku_warranty", TWO_YEARS)],
    )
    removed = [c for c in diff.changes if c.kind is ChangeKind.UNIT_REMOVED]
    assert [c.logical_id for c in removed] == ["ku_shipping"]


# --------------------------------------------------------------------------
# The rule the module exists to hold
# --------------------------------------------------------------------------


def test_an_unsettled_identity_is_not_reported_as_a_modification() -> None:
    """Calling it modified asserts a continuity nobody established."""
    diff = _semantic(
        [_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        [_unit("ku_incoming", THREE_YEARS)],
    )

    kinds = {c.kind for c in diff.changes}
    assert ChangeKind.IDENTITY_UNRESOLVED in kinds
    assert ChangeKind.MODIFIED_CLAIM not in kinds


def test_an_unsettled_identity_is_not_a_remove_plus_add_either() -> None:
    """That spelling destroys a history that may well be real."""
    diff = _semantic(
        [_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        [_unit("ku_incoming", THREE_YEARS)],
    )
    unresolved = diff.unresolved
    assert len(unresolved) == 1
    assert unresolved[0].candidates == ("ku_left", "ku_right")
    assert unresolved[0].logical_id is None


def test_an_unsettled_identity_never_reaches_the_dependency_traversal() -> None:
    """Marking artifacts stale from an identity nobody settled spreads a guess."""
    diff = _semantic(
        [_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        [_unit("ku_incoming", THREE_YEARS)],
    )
    assert all(lid not in ("ku_left", "ku_right") for lid in diff.changed_logical_ids)


def test_the_unresolved_change_explains_itself() -> None:
    diff = _semantic(
        [_unit("ku_left", TWO_YEARS), _unit("ku_right", TWO_YEARS)],
        [_unit("ku_incoming", THREE_YEARS)],
    )
    assert diff.unresolved[0].detail


# --------------------------------------------------------------------------
# L2 — evidence moved is not evidence changed
# --------------------------------------------------------------------------


def test_a_clause_that_moved_pages_is_reported_as_moved_not_modified() -> None:
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS, evidence="ev_one", page=17)],
        [_unit("ku_warranty", TWO_YEARS, evidence="ev_two", page=18)],
    )
    moved = [c for c in diff.changes if c.kind is ChangeKind.EVIDENCE_MOVED]
    assert len(moved) == 1
    assert "17 -> 18" in moved[0].detail
    assert [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM] == []


def test_evidence_level_alone_reports_added_and_removed_anchors() -> None:
    diff = diff_documents(
        before_sha256=A,
        after_sha256=B,
        level=DiffLevel.EVIDENCE,
        before_shape=DocumentShape(),
        after_shape=DocumentShape(),
        before_units=[_unit("ku_a", TWO_YEARS, evidence="ev_one")],
        after_units=[_unit("ku_a", TWO_YEARS, evidence="ev_two")],
    )
    kinds = {c.kind for c in diff.changes}
    assert kinds == {ChangeKind.EVIDENCE_ADDED, ChangeKind.EVIDENCE_REMOVED}


# --------------------------------------------------------------------------
# L4 — graph
# --------------------------------------------------------------------------


def test_authority_change_is_reported_at_graph_level() -> None:
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS, authority="informal")],
        [_unit("ku_warranty", TWO_YEARS, authority="contractual")],
        level=DiffLevel.GRAPH,
    )
    authority = [c for c in diff.changes if c.kind is ChangeKind.AUTHORITY_CHANGED]
    assert len(authority) == 1
    assert authority[0].before == "informal"
    assert authority[0].after == "contractual"


def test_a_new_relationship_is_reported_at_graph_level() -> None:
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS)],
        [
            _unit(
                "ku_warranty",
                TWO_YEARS,
                relationships=frozenset({("product", "covered_by", "warranty")}),
            )
        ],
        level=DiffLevel.GRAPH,
    )
    added = [c for c in diff.changes if c.kind is ChangeKind.RELATIONSHIP_ADDED]
    assert len(added) == 1
    assert added[0].after == "product covered_by warranty"


def test_graph_changes_do_not_appear_below_graph_level() -> None:
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS, authority="informal")],
        [_unit("ku_warranty", TWO_YEARS, authority="contractual")],
        level=DiffLevel.SEMANTIC,
    )
    assert [c for c in diff.changes if c.kind is ChangeKind.AUTHORITY_CHANGED] == []


# --------------------------------------------------------------------------
# Reproducibility — impact analysis that cannot be re-derived cannot be audited
# --------------------------------------------------------------------------


def test_the_same_pair_of_versions_gives_the_same_change_id() -> None:
    before = [_unit("ku_warranty", TWO_YEARS)]
    after = [_unit("ku_warranty", THREE_YEARS)]
    assert _semantic(before, after).change_id == _semantic(before, after).change_id


def test_a_different_change_gives_a_different_change_id() -> None:
    before = [_unit("ku_warranty", TWO_YEARS)]
    assert _semantic(before, [_unit("ku_warranty", THREE_YEARS)]).change_id != (
        _semantic(before, [_unit("ku_warranty", "The warranty is void.")]).change_id
    )


def test_the_record_form_round_trips_the_masterplan_shape() -> None:
    """§12's example record: change_id, changes[], kind, logical_id, before, after."""
    record = _semantic(
        [_unit("ku_warranty", TWO_YEARS)], [_unit("ku_warranty", THREE_YEARS)]
    ).as_record()

    assert record["change_id"].startswith("chg_")
    assert record["level"] == "L3"
    modified = [c for c in record["changes"] if c["kind"] == "modified_claim"]
    assert modified and modified[0]["logical_id"] == "ku_warranty"


def test_a_stricter_resolver_can_be_supplied() -> None:
    strict = LogicalIdentityResolver(merge_threshold=0.99, new_threshold=0.98)
    diff = _semantic(
        [_unit("ku_warranty", TWO_YEARS)],
        [_unit("ku_warranty", THREE_YEARS)],
        resolver=strict,
    )
    assert [c for c in diff.changes if c.kind is ChangeKind.MODIFIED_CLAIM] == []
