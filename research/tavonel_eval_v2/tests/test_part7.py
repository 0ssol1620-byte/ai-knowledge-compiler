"""Unit-level counterparts to MARKUP_SEMANTICS_V1.

INC-V2-010 happened because a list of attributes was called "presentation" and
nobody checked the claim. These tests check it, one construct at a time, and
pin the three properties that make the policy honest rather than merely
different from the old one:

* an ignore carries an argument, not a category name;
* an unknown construct is surfaced, never assumed decorative;
* the policy digest moves when a classification moves and not when the file is
  merely reformatted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "tools"))

from markup_controls import (  # noqa: E402
    CONTROLS,
    NEGATIVE_DIRECTION_CONTROL,
    POSITIVE_DIRECTION_CONTROLS,
    THIRD_STATE_CONTROL,
    by_name,
)
from markup_policy import (  # noqa: E402
    ACCESSIBILITY,
    ATTRIBUTES,
    CONTENT_LEXICAL,
    EXTERNAL_DEPENDENCY,
    FACETS,
    IGNORED,
    METADATA,
    MODELED,
    POLICY,
    REFERENCE_LOCATOR,
    STRUCTURAL,
    TAGS,
    UNMODELED,
    UNRESOLVED,
)
from markup_semantics import (  # noqa: E402
    BLOCKS_COMPLETENESS,
    blocks_completeness,
    classify_attribute,
    classify_character_reference,
    classify_syntax_residue,
    classify_tag,
    classify_text,
    policy_digest,
    schema_digest,
    summary,
)


def _classify(control: dict) -> dict:
    kind = control["kind"]
    if kind == "attribute":
        return classify_attribute(control["construct"])
    if kind == "tag":
        return classify_tag(control["construct"])
    return classify_character_reference(control["construct"])


# --- the eight adversarial controls ------------------------------------------


@pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c["name"])
def test_every_markup_control_returns_its_expected_state_and_facet(control: dict) -> None:
    got = _classify(control)
    assert got["state"] == control["expect_state"], (control["name"], control["guards"])
    assert got["facet"] == control["expect_facet"], (control["name"], got)


def test_all_three_directions_hold_together() -> None:
    """A policy calling everything meaningful passes six of eight and is useless."""
    assert all(_classify(by_name(n))["state"] == MODELED for n in POSITIVE_DIRECTION_CONTROLS)
    assert _classify(by_name(THIRD_STATE_CONTROL))["state"] == UNRESOLVED
    assert _classify(by_name(NEGATIVE_DIRECTION_CONTROL))["state"] == IGNORED


def test_every_control_is_a_pair_that_differs_in_one_construct() -> None:
    """The claim is about change, and only a pair can show change."""
    for control in CONTROLS:
        assert control["before"] != control["after"], control["name"]
        assert control["differs_in"]


def test_the_structural_control_has_identical_visible_tokens() -> None:
    """Nesting changes meaning with no visible token moving at all."""
    control = by_name("nesting_changes_structure_same_tokens")
    import re  # noqa: PLC0415

    strip = lambda s: re.findall(r"[A-Za-z0-9]+", re.sub(r"<[^>]+>", " ", s))  # noqa: E731
    assert strip(control["before"]) == strip(control["after"])
    assert control["before"] != control["after"]


# --- what INC-V2-010 reclassified --------------------------------------------


@pytest.mark.parametrize(
    "attribute,facet",
    [
        ("colspan", STRUCTURAL),
        ("rowspan", STRUCTURAL),
        ("scope", STRUCTURAL),
        ("headers", STRUCTURAL),
        ("role", ACCESSIBILITY),
        ("alt", ACCESSIBILITY),
        ("title", ACCESSIBILITY),
        ("aria-label", ACCESSIBILITY),
        ("aria-hidden", ACCESSIBILITY),
        ("lang", METADATA),
        ("dir", METADATA),
        ("media", METADATA),
        ("content", METADATA),
        ("http-equiv", METADATA),
        ("rel", REFERENCE_LOCATOR),
        ("target", REFERENCE_LOCATOR),
    ],
)
def test_the_wrongly_ignored_attributes_are_now_modelled(attribute: str, facet: str) -> None:
    got = classify_attribute(attribute)
    assert got["state"] == MODELED, attribute
    assert got["facet"] == facet, (attribute, got["facet"])


def test_colspan_and_rowspan_are_control_facts_not_retrieval_units() -> None:
    """Nobody asks about a colspan; an answer can still be wrong because of one."""
    for name in ("colspan", "rowspan"):
        assert classify_attribute(name)["control_fact"] is True


def test_class_and_style_are_unresolved_not_ignored() -> None:
    for name in ("class", "style"):
        got = classify_attribute(name)
        assert got["state"] == UNRESOLVED, name
        assert got["facet"] == EXTERNAL_DEPENDENCY


def test_character_references_are_lexical_content() -> None:
    got = classify_character_reference("&#160;")
    assert got["state"] == MODELED
    assert got["facet"] == CONTENT_LEXICAL


@pytest.mark.parametrize("tag", ["table", "tr", "td", "th", "ul", "ol", "li", "h2", "p"])
def test_structural_tags_are_not_blanket_ignored(tag: str) -> None:
    got = classify_tag(tag)
    assert got["state"] == MODELED, tag
    assert got["facet"] == STRUCTURAL


def test_only_the_delimiters_are_residue() -> None:
    assert classify_syntax_residue("</")["state"] == IGNORED
    assert classify_tag("table")["state"] == MODELED


# --- the honesty properties --------------------------------------------------


def test_every_ignored_entry_carries_a_meaning_and_an_argument() -> None:
    for source, label in ((ATTRIBUTES, "attribute"), (TAGS, "tag")):
        for name, entry in source.items():
            if entry["state"] != IGNORED:
                continue
            assert entry.get("means"), (label, name, "no statement of what it means")
            assert entry.get("why"), (label, name, "no no-facet argument")
            assert "presentation attribute" != entry["why"].strip().lower()


def test_an_undeclared_construct_is_unmodeled_never_ignored() -> None:
    for name in ("binding", "targetref", "whatever-this-is"):
        assert classify_attribute(name)["state"] == UNMODELED, name
    for name in ("policyref", "madeuptag"):
        assert classify_tag(name)["state"] == UNMODELED, name


def test_resolution_is_total() -> None:
    valid = {MODELED, IGNORED, UNRESOLVED, UNMODELED}
    for name in list(ATTRIBUTES) + ["nothing-like-this"]:
        assert classify_attribute(name)["state"] in valid
    for name in list(TAGS) + ["nothing-like-this"]:
        assert classify_tag(name)["state"] in valid


def test_unresolved_blocks_completeness_exactly_as_unmodeled_does() -> None:
    assert set(BLOCKS_COMPLETENESS) == {UNMODELED, UNRESOLVED}
    assert blocks_completeness(UNRESOLVED)
    assert blocks_completeness(UNMODELED)
    assert not blocks_completeness(MODELED)
    assert not blocks_completeness(IGNORED)


def test_whitespace_between_elements_is_ignorable_but_preserved_whitespace_is_not() -> None:
    assert classify_text("   ")["state"] == IGNORED
    assert classify_text("   ", preserved=True)["state"] == MODELED


def test_every_modelled_entry_names_a_declared_facet() -> None:
    for source in (ATTRIBUTES, TAGS):
        for name, entry in source.items():
            if entry["state"] in {MODELED, UNRESOLVED}:
                assert entry["facet"] in FACETS, (name, entry["facet"])


# --- sealing -----------------------------------------------------------------


def test_the_policy_digest_is_over_the_mapping_not_the_file() -> None:
    """Reformatting must not move it; reclassifying must."""
    before = policy_digest()
    assert before == policy_digest(), "the digest is not stable across calls"

    original = ATTRIBUTES["colspan"]
    try:
        ATTRIBUTES["colspan"] = {**original, "state": IGNORED, "facet": None}
        POLICY["attributes"] = ATTRIBUTES
        assert policy_digest() != before, "a reclassification must move the digest"
    finally:
        ATTRIBUTES["colspan"] = original
        POLICY["attributes"] = ATTRIBUTES
    assert policy_digest() == before


def test_the_policy_digest_and_the_code_digest_are_different_things() -> None:
    import hashlib  # noqa: PLC0415

    code = "sha256:" + hashlib.sha256(
        (NS / "canonicalization" / "markup_semantics.py").read_bytes()
    ).hexdigest()
    assert policy_digest() != code
    assert schema_digest() != code


def test_the_sealed_run_recorded_a_composite_identity_with_four_parts() -> None:
    receipts = sorted((NS / "receipts").glob("markup-semantics-v1--*.json"))
    assert receipts
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    parts = body["instrument_identity"]["parts"]
    assert {"source_map_code", "witness_code", "markup_semantics_code", "markup_policy", "schema"} <= set(parts)
    assert body["instrument_identity"]["composite"].startswith("sha256:")


def test_the_sealed_run_passed_and_spent_nothing() -> None:
    receipts = sorted((NS / "receipts").glob("markup-semantics-v1--*.json"))
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert body["verdict"] == "PASS"
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
    assert body["gpu_authorised_by_this_result"] is False


def test_the_sealed_run_does_not_rescore_its_predecessors() -> None:
    receipts = sorted((NS / "receipts").glob("markup-semantics-v1--*.json"))
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    predecessors = body["predecessors_read_only"]
    assert "not re-scored" in predecessors["SOURCE_LOCALITY_V2"]
    assert "SUPERSEDED_BEFORE_EXECUTION" in predecessors["P4f"]
    assert body["programme_status"].startswith("PARTIAL")


def test_p4f_was_preserved_unmodified_and_p4g_supersedes_it() -> None:
    p4f = (NS / "protocols" / "P4f_cohort_expansion.yaml").read_text(encoding="utf-8")
    p4g = (NS / "protocols" / "P4g_cohort_expansion.yaml").read_text(encoding="utf-8")
    assert "G_P4F_INSTRUMENT_UNCHANGED" in p4f, "P4f keeps the gate that INC-V2-011 names"
    assert "supersedes: P4f_cohort_expansion" in p4g
    assert "G_P4G_COMPOSITE_IDENTITY" in p4g
    assert "hard_minimum_eligible_Q1: 190" in p4g, "the floor is not lowered"


def test_the_declared_consumer_is_named_so_the_arguments_are_falsifiable() -> None:
    consumer = POLICY["consumer_semantics"]
    assert consumer["reads"] and consumer["does_not_read"]
    assert consumer["cannot_decide_locally"]


def test_the_policy_summary_counts_agree_with_the_declarations() -> None:
    stats = summary()
    assert stats["declared_attributes"] == len(ATTRIBUTES)
    assert stats["declared_tags"] == len(TAGS)
    assert stats["by_state"][MODELED] > stats["by_state"][IGNORED]
    assert stats["ignored_entries_all_carry_a_reason"] is True
