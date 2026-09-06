"""Unit-level counterparts to the P4e gates and the IntentView contract.

P4e's central claim is that a forbidden intent source is *unreachable*, not
filtered. A corpus-level gate reporting zero forbidden contributions is
consistent with a builder that simply did not reach for one this time, so these
tests attack the structure directly: they try to smuggle a forbidden field in
through construction, assignment, iteration and attribute access, and require a
refusal from each.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "retrieval"))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "acquisition"))

from intent_view import (  # noqa: E402
    ANCHOR,
    DOC_TYPE,
    FORBIDDEN_INTENT_SOURCES,
    IDENTITY,
    INTENT_CHANGED,
    PARENT,
    PERMITTED_INTENT_SOURCES,
    TITLE,
    ForbiddenIntentSource,
    IntentView,
    build_query,
    revision_neutral_fields,
)

PERMITTED = {
    TITLE: "uv documentation",
    IDENTITY: "astral-sh/uv",
    DOC_TYPE: "documentation",
    ANCHOR: "Dependency fields",
    PARENT: "Managing dependencies",
}


def _view() -> IntentView:
    return IntentView("test", **PERMITTED)


# --- the view refuses, at construction ---------------------------------------


@pytest.mark.parametrize("forbidden", FORBIDDEN_INTENT_SOURCES)
def test_a_forbidden_field_is_refused_at_construction(forbidden: str) -> None:
    """Refusing at construction, not at read.

    A view that accepted the field and then declined to return it would still
    have put the value in the builder's process memory.
    """
    with pytest.raises(ForbiddenIntentSource):
        IntentView("ctrl", **PERMITTED, **{forbidden: "whatever this is"})


def test_an_incomplete_view_is_refused() -> None:
    partial = {k: v for k, v in PERMITTED.items() if k != TITLE}
    with pytest.raises(ForbiddenIntentSource):
        IntentView("ctrl", **partial)


def test_a_view_with_no_parent_heading_is_fine() -> None:
    """Only the parent is optional; a top-level section genuinely has none."""
    view = IntentView("test", **{**PERMITTED, PARENT: None})
    assert view.read(PARENT) is None


# --- and every other way in is closed ----------------------------------------


def test_attributes_cannot_be_added_after_construction() -> None:
    view = _view()
    with pytest.raises(ForbiddenIntentSource):
        view.atom_body = "the resolver reads dependency-groups"


def test_unknown_attributes_are_not_readable() -> None:
    view = _view()
    with pytest.raises(ForbiddenIntentSource):
        _ = view.atom_body


def test_a_view_is_not_iterable() -> None:
    view = _view()
    with pytest.raises(ForbiddenIntentSource):
        list(view)


def test_reading_a_non_permitted_source_is_refused() -> None:
    view = _view()
    with pytest.raises(ForbiddenIntentSource):
        view.read("answer_span")


def test_the_slots_declaration_is_what_closes_the_last_door() -> None:
    """Without __slots__ the constructor's whitelist stops being the whole story.

    ``hasattr`` is not the probe here: unknown attribute access raises
    ForbiddenIntentSource rather than AttributeError, which is deliberate and
    stronger — the object is hostile to introspection on purpose — but it means
    hasattr propagates instead of returning False.
    """
    assert set(IntentView.__slots__) == {"_fields", "_reads", "_view_id"}
    with pytest.raises(ForbiddenIntentSource):
        _ = IntentView("test", **PERMITTED).__dict__


# --- provenance --------------------------------------------------------------


def test_every_read_is_recorded_with_its_source() -> None:
    view = _view()
    build_query(view)
    sources = {record["source"] for record in view.reads}
    assert sources <= set(PERMITTED_INTENT_SOURCES)
    assert sources, "the builder read nothing, which cannot be right"


def test_provenance_covers_every_substantive_field_and_nothing_else() -> None:
    view = _view()
    query = build_query(view)
    provenance = view.provenance()
    assert provenance
    for record in provenance:
        assert record["permitted"] is True
        assert record["provenance"] in PERMITTED_INTENT_SOURCES
        assert str(record["value"]) in query


def test_a_field_never_read_produces_no_provenance_record() -> None:
    """Absence is a failure at the gate, so it must not be manufactured here."""
    view = _view()
    view.read(ANCHOR)
    assert [record["field"] for record in view.provenance()] == [ANCHOR]


# --- the builder -------------------------------------------------------------


def test_the_builder_takes_exactly_one_restricted_argument() -> None:
    tree = ast.parse((NS / "retrieval" / "intent_view.py").read_text(encoding="utf-8"))
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_query"
    )
    assert len(builder.args.args) == 1
    assert not builder.args.kwonlyargs and builder.args.vararg is None


def test_the_builder_names_no_forbidden_source() -> None:
    tree = ast.parse((NS / "retrieval" / "intent_view.py").read_text(encoding="utf-8"))
    builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_query"
    )
    names = {n.id for n in ast.walk(builder) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(builder) if isinstance(n, ast.Attribute)
    }
    assert not names & set(FORBIDDEN_INTENT_SOURCES)


# --- revision neutrality -----------------------------------------------------


def test_identical_permitted_fields_produce_a_view() -> None:
    fields, differing = revision_neutral_fields(PERMITTED, dict(PERMITTED))
    assert differing == []
    assert fields == PERMITTED


@pytest.mark.parametrize("field", [TITLE, IDENTITY, DOC_TYPE, ANCHOR, PARENT])
def test_a_field_that_moved_between_revisions_blocks_the_question(field: str) -> None:
    after = {**PERMITTED, field: "something else"}
    fields, differing = revision_neutral_fields(PERMITTED, after)
    assert fields is None
    assert differing == [field]


def test_the_current_revision_value_is_never_silently_chosen() -> None:
    """Taking the current value would answer the question under test."""
    after = {**PERMITTED, ANCHOR: "Dependency fields and groups"}
    fields, _ = revision_neutral_fields(PERMITTED, after)
    assert fields is None, "no view may be built from a field that moved"


# --- P4e receipt-level checks ------------------------------------------------


def _latest_p4e() -> dict:
    receipts = sorted((NS / "receipts").glob("p4e-provenance-retrieval--*.json"))
    assert receipts, "P4e has no receipt"
    return json.loads(receipts[-1].read_text(encoding="utf-8"))


def test_p4e_recorded_zero_forbidden_contribution() -> None:
    body = _latest_p4e()
    gate = body["gates"]["G_P4E_NO_FORBIDDEN_CONTRIBUTION"]
    assert gate["threshold"] == 0
    assert gate["value"] == 0
    assert gate["passed"]


def test_p4e_negative_controls_were_actually_rejected() -> None:
    controls = _latest_p4e()["gates"]["G_P4E_CONTROLS_REJECTED"]["controls"]
    assert controls["ctrl_body_token_injected"]["rejected"] is True
    assert controls["ctrl_body_token_injected"]["by"] == "ForbiddenIntentSource"
    assert controls["ctrl_current_only_heading"]["rejected"] is True
    assert controls["ctrl_current_only_heading"]["by"] == INTENT_CHANGED


def test_p4e_reports_lexical_overlap_as_a_diagnostic_and_never_gates_it() -> None:
    body = _latest_p4e()
    assert body["lexical_overlap_diagnostic"]["status"] == "DIAGNOSTIC_ONLY"
    assert not any("OVERLAP" in name or "LEAKAGE" in name for name in body["gates"])


def test_p4e_cleared_the_q1_bar_without_moving_it() -> None:
    gate = _latest_p4e()["gates"]["G_P4E_Q1_SCALE"]
    assert gate["threshold"] == 100, "the bar P4d failed at 67 is unchanged"
    assert gate["value"] >= 100


def test_p4e_does_not_claim_to_repair_its_predecessors() -> None:
    body = _latest_p4e()
    assert body["predecessors_read_only"]["P4c_core"] == "FAIL"
    assert body["predecessors_read_only"]["P4d_core_semantic"] == "FAIL"
    assert body["programme_status"].startswith("PARTIAL")
    assert body["gpu_authorised_by_this_result"] is False


def test_p4e_keeps_the_two_endpoints_apart() -> None:
    endpoints = _latest_p4e()["endpoints"]
    assert endpoints["source_faithful_end_to_end"].startswith("NOT_ESTABLISHED")
    assert endpoints["never_combined"] is True


def test_every_scored_question_carries_a_source_coverage_status() -> None:
    body = _latest_p4e()
    scored = [row for row in body["rows"] if row.get("state") == "SCORED"]
    assert scored
    for row in scored:
        assert row["source_coverage"]["status"] in {
            "QUESTION_LOCAL_COVERAGE_COMPLETE",
            "QUESTION_LOCAL_COVERAGE_INCOMPLETE",
        }


def test_the_confirmatory_candidate_pool_is_reported_not_inflated() -> None:
    """The number that blocks the model study must be stated, not smoothed."""
    coverage = _latest_p4e()["source_coverage"]
    assert coverage["gpu_confirmatory_candidates"] == coverage[
        "question_local_coverage_complete"
    ]
    assert "26 of 26" in coverage["document_revisions_still_incomplete"]


def test_p4e_spent_nothing() -> None:
    body = _latest_p4e()
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0


def test_the_spacing_rule_cannot_see_a_result() -> None:
    tree = ast.parse((NS / "acquisition" / "sources_p4e.py").read_text(encoding="utf-8"))
    spacing = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "REVISION_SPACING" for t in node.targets
        )
    )
    declared = ast.literal_eval(spacing)
    assert declared["frozen_before_any_retrieval_result"] is True

    # the prohibition itself names what it forbids, so check the rule clauses
    # rather than the whole object
    clauses = json.dumps(
        {k: v for k, v in declared.items() if isinstance(v, dict)}
    ).lower()
    assert "score" not in clauses
    assert "bm25" not in clauses
    assert "q1" not in clauses
    assert "any retrieval score" in json.dumps(declared["never_conditioned_on"]).lower()
