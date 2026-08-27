"""Unit-level counterparts to the P4d gates and the envelope contract.

The envelope layer's whole safety argument is that it is *derived*. A gate
measured over a corpus can pass while the abstraction has quietly become a fact,
so these pin the five contract properties directly, plus the two rules the
implementation got wrong on its first run: measurement granularity, and what a
citation is.
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

from envelope import (  # noqa: E402
    AUTHORITATIVE,
    COVERS,
    DERIVED,
    build_envelopes,
    citation_for,
    envelope_fingerprint,
    invalidated_envelopes,
    is_enumeration_marker,
    normalise_citation,
)

FIELDS = {"title": "17 CFR 240.0-1", "doc_type": "Code of Federal Regulations section"}


def _section() -> list[dict[str, object]]:
    """A CFR-shaped section: a named heading with enumerated descendants."""
    return [
        {
            "explicit_path": ["§ 240.0-1 Definitions."],
            "heading": "§ 240.0-1 Definitions.",
            "text": "As used in the rules in this part, unless the context requires otherwise:",
            "text_sha256": "sha256:aaa",
        },
        {
            "explicit_path": ["§ 240.0-1 Definitions.", "(a)"],
            "heading": "(a)",
            "text": "The term Commission means the Securities and Exchange Commission.",
            "text_sha256": "sha256:bbb",
        },
        {
            "explicit_path": ["§ 240.0-1 Definitions.", "(a)", "(1)"],
            "heading": "(1)",
            "text": "The term section refers to a section of the Act.",
            "text_sha256": "sha256:ccc",
        },
        {
            "explicit_path": ["Reporting obligations"],
            "heading": "Reporting obligations",
            "text": "A registrant shall file the report within four business days.",
            "text_sha256": "sha256:ddd",
        },
    ]


# --- the marker rule ---------------------------------------------------------


@pytest.mark.parametrize("heading", ["(a)", "(3)", "(i)", "1.", "(iv)", "", "  "])
def test_enumeration_markers_are_recognised(heading: str) -> None:
    assert is_enumeration_marker(heading)


@pytest.mark.parametrize(
    "heading",
    ["Definitions.", "Reporting obligations", "§ 240.0-1 Definitions.", "Scope"],
)
def test_names_are_not_mistaken_for_markers(heading: str) -> None:
    """The doubt runs one way on purpose.

    Calling a name a marker would silently coarsen retrieval; calling a marker a
    name only leaves the P4c behaviour in place for that atom.
    """
    assert not is_enumeration_marker(heading)


# --- the five contract properties --------------------------------------------


def test_an_envelope_records_member_ids_and_is_never_authoritative() -> None:
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    assert envelopes
    for env in envelopes:
        assert env.member_ids
        assert env.authoritative is False
        assert env.kind == DERIVED


def test_enumerated_children_join_their_nearest_named_ancestor() -> None:
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    by_anchor = {e.anchor_path: e for e in envelopes}
    assert set(by_anchor) == {"§ 240.0-1 Definitions.", "Reporting obligations"}
    definitions = by_anchor["§ 240.0-1 Definitions."]
    assert len(definitions.member_ids) == 3, definitions.member_ids
    assert len(by_anchor["Reporting obligations"].member_ids) == 1


def test_every_dependency_edge_is_typed_and_points_at_a_canonical_atom() -> None:
    envelopes, _ = build_envelopes("doc", "current", _section(), FIELDS)
    edges = [edge for env in envelopes for edge in env.edges()]
    assert edges
    assert all(edge["edge"] == COVERS for edge in edges)
    assert all(edge["to_kind"] == AUTHORITATIVE for edge in edges)


def test_evidence_is_atoms_and_never_envelope_text() -> None:
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    records = [record for env in envelopes for record in env.evidence(atoms)]
    assert records
    for record in records:
        assert record["kind"] == AUTHORITATIVE
        assert record["envelope_is_evidence"] is False
        assert "text" not in record
        assert record["atom_id"] in atoms


def test_a_moved_member_invalidates_exactly_its_own_envelope() -> None:
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    by_anchor = {e.anchor_path: e for e in envelopes}
    moved = {by_anchor["§ 240.0-1 Definitions."].member_ids[1]}
    invalidated = invalidated_envelopes(envelopes, moved)
    assert invalidated == [by_anchor["§ 240.0-1 Definitions."].envelope_id]
    assert by_anchor["Reporting obligations"].envelope_id not in invalidated


def test_no_moved_atom_invalidates_nothing() -> None:
    envelopes, _ = build_envelopes("doc", "current", _section(), FIELDS)
    assert invalidated_envelopes(envelopes, set()) == []


def test_the_fingerprint_is_over_members_not_prose() -> None:
    """An envelope that hashed its own text could drift from its members."""
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    env = next(e for e in envelopes if len(e.member_ids) > 1)
    before = envelope_fingerprint(env, atoms)

    same_text_new_digest = dict(atoms)
    first = env.member_ids[0]
    same_text_new_digest[first] = {**atoms[first], "text_sha256": "sha256:changed"}
    assert envelope_fingerprint(env, same_text_new_digest) != before

    new_prose_same_digest = dict(atoms)
    new_prose_same_digest[first] = {**atoms[first], "text": "entirely different prose"}
    assert envelope_fingerprint(env, new_prose_same_digest) == before


def test_no_function_offers_the_reverse_dependency_direction() -> None:
    """Deciding an atom changed because envelope text changed is never done."""
    import envelope as module  # noqa: PLC0415

    exported = {name for name in dir(module) if not name.startswith("_")}
    assert not {"atoms_from_envelope_change", "invalidated_atoms"} & exported


# --- citation addressing -----------------------------------------------------


@pytest.mark.parametrize(
    "left,right",
    [
        ("§ 240.0-1(a)(3)", "240.0-1 (a)(3)"),
        ("§240.0-1(a)(3)", "§ 240.0-1 (A)(3)"),
    ],
)
def test_locators_that_name_the_same_address_normalise_together(
    left: str, right: str
) -> None:
    assert normalise_citation(left) == normalise_citation(right)


def test_different_addresses_do_not_collide() -> None:
    assert normalise_citation("§ 240.0-1(a)") != normalise_citation("§ 240.0-1(b)")


def test_a_citation_is_assembled_from_the_path_and_carries_no_body_text() -> None:
    envelopes, atoms = build_envelopes("doc", "current", _section(), FIELDS)
    definitions = next(e for e in envelopes if e.anchor_path.startswith("§"))
    atom = atoms[definitions.member_ids[1]]
    citation = citation_for(atom)
    assert "(a)" in citation
    assert "Commission" not in citation, "a locator names where to look, never what is there"


# --- P4d receipt-level checks ------------------------------------------------


def _latest_p4d() -> dict:
    receipts = sorted((NS / "receipts").glob("p4d-retrieval-granularity--*.json"))
    assert receipts, "P4d has no receipt"
    return json.loads(receipts[-1].read_text(encoding="utf-8"))


def test_p4d_ranks_over_logical_envelopes_not_indexed_rows() -> None:
    """INC-V2-009: an envelope must not tie against its own superseded revision."""
    body = _latest_p4d()
    assert body["P4d_Core_Semantic"]["measures"]["tie_rate"] == 0.0


def test_p4d_keeps_the_two_modes_apart() -> None:
    body = _latest_p4d()
    assert "verdict" not in body, "a combined verdict would merge two modes into one number"
    assert body["P4d_Core_Semantic"]["verdict"] == "FAIL"
    assert body["P4d_Citation"]["verdict"] == "PASS"
    assert body["P4d_Citation"]["never_mixed_into_mode_a"] is True


def test_p4d_does_not_claim_to_repair_p4c() -> None:
    body = _latest_p4d()
    assert body["p4c_core_state"].startswith("FAIL")
    assert body["gpu_authorised_by_this_result"] is False
    assert body["programme_status"].startswith("PARTIAL")


def test_p4d_reuses_the_p4b_ranking_rather_than_writing_it_a_fourth_time() -> None:
    tree = ast.parse((NS / "tools" / "run_p4d.py").read_text(encoding="utf-8"))
    reused = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "run_p4b"
        for alias in node.names
    }
    assert {"rank", "FieldedBm25"} <= reused, reused


def test_p4d_spent_nothing() -> None:
    body = _latest_p4d()
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0


def test_the_citation_families_are_declared_rather_than_inferred() -> None:
    """Read from source rather than imported: the oracle isolation probe another
    test module installs on ``sys.meta_path`` is global to the interpreter."""
    tree = ast.parse((NS / "tools" / "run_p4d.py").read_text(encoding="utf-8"))
    declared = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CITATION_FAMILIES"
            for target in node.targets
        )
    )
    families = ast.literal_eval(declared.args[0])
    assert families == {"regulation_ecfr"}
    body = _latest_p4d()
    assert body["P4d_Citation"]["declared_families"] == ["regulation_ecfr"]


def test_the_leakage_gate_was_not_relaxed_after_it_failed() -> None:
    """The predicate stands at zero, and the run reports the failure."""
    body = _latest_p4d()
    gate = body["P4d_Core_Semantic"]["gates"]["G_P4D_NO_LEAKAGE"]
    assert gate["threshold"] == 0
    assert gate["passed"] is False
    assert gate["value"] > 0
