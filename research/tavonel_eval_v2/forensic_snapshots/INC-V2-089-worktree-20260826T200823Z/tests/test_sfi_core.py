"""The IR contract and the core extractor. Lane 1, owned by the orchestrator.

These tests exist to stop the new states from decaying back into the old one.
`MODELED` was a claim the grammar made from a table and nobody checked; the
whole repair is that `REPRESENTED_IN_COMPILED_STATE` is checkable and checked.
A test suite that lets an extractor assert REPRESENTED without a representation,
or lets a fail-closed state be reported as complete, would return the programme
to exactly where SFH1 found it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("source_fact_ir", "canonicalization"):
    sys.path.insert(0, str(NS / _sub))

import core_extractor  # noqa: E402
import ir  # noqa: E402
from canonical_document import canonical_document  # noqa: E402

LONG = (
    "This paragraph is padded out past the canonicaliser's one hundred and "
    "twenty character minimum so that it survives block assembly and becomes a "
    "unit of its own rather than being folded away."
)


def document_for(raw: bytes) -> dict:
    return canonical_document(
        source_family="git",
        source_id="fixture",
        version_id="1",
        payload=raw,
        source_digest="sha256:0",
        known_at=None,
        valid_from=None,
        licence="mit",
    )


def witness() -> ir.Witness:
    return ir.Witness(construct="test", byte_start=0, byte_end=4, excerpt="", unit_path=("a",))


# ---------------------------------------------------------------------------
# the four states


def test_the_four_states_are_exactly_the_ruling_s_four():
    assert set(ir.STATES) == {
        "REPRESENTED_IN_COMPILED_STATE",
        "RECOGNIZED_BUT_UNREPRESENTED",
        "IGNORED_BY_PREDECLARED_POLICY",
        "UNRESOLVED_SOURCE_FACT",
    }


def test_only_the_declined_state_is_fail_open():
    """A declined loss is a declared limitation. Every other loss is a defect."""
    assert set(ir.FAIL_CLOSED) == {ir.UNREPRESENTED, ir.UNRESOLVED}
    assert ir.IGNORED not in ir.FAIL_CLOSED
    assert ir.REPRESENTED not in ir.FAIL_CLOSED


def test_represented_without_a_representation_is_refused():
    """The whole defect, in one assertion: recognition is not representation."""
    with pytest.raises(ValueError, match="no representation"):
        ir.SourceFact(kind=ir.CONTENT_TEXT, witness=witness(), state=ir.REPRESENTED)


def test_an_unrepresented_fact_may_not_smuggle_a_representation():
    with pytest.raises(ValueError, match="representation on a"):
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.UNREPRESENTED,
            representation={"text": "x"},
            reason="r",
        )


def test_a_declined_fact_must_name_the_policy_that_declined_it():
    with pytest.raises(ValueError, match="predeclared policy"):
        ir.SourceFact(kind=ir.CONTENT_TEXT, witness=witness(), state=ir.IGNORED)


def test_a_fail_closed_fact_must_say_why():
    for state in sorted(ir.FAIL_CLOSED):
        with pytest.raises(ValueError, match="no reason"):
            ir.SourceFact(kind=ir.CONTENT_TEXT, witness=witness(), state=state)


def test_a_policy_reference_cannot_dress_up_a_loss_as_declined():
    """Citing a policy on an UNRESOLVED fact would make a defect read as a
    limitation, which is the single most valuable confusion to prevent."""
    with pytest.raises(ValueError, match="policy reference on a"):
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.UNRESOLVED,
            reason="malformed",
            policy_ref="POLICY-CORE-001",
        )


# ---------------------------------------------------------------------------
# identity


def test_identity_is_witness_derived_not_value_derived():
    """A changed fact must be the SAME fact with a new value.

    If identity moved with the value there would be no such thing as a change —
    only a disappearance and an arrival — and nothing downstream could be told
    which artifact to rebuild.
    """
    first = ir.SourceFact(
        kind=ir.REFERENCE_TARGET,
        witness=witness(),
        state=ir.REPRESENTED,
        representation={"target": "/a"},
    )
    second = ir.SourceFact(
        kind=ir.REFERENCE_TARGET,
        witness=witness(),
        state=ir.REPRESENTED,
        representation={"target": "/b"},
    )
    assert first.fact_id == second.fact_id
    assert first.representation != second.representation


def test_identity_separates_kinds_at_one_site():
    site = witness()
    text = ir.SourceFact(
        kind=ir.CONTENT_TEXT, witness=site, state=ir.REPRESENTED, representation={"t": 1}
    )
    link = ir.SourceFact(
        kind=ir.REFERENCE_TARGET, witness=site, state=ir.REPRESENTED, representation={"t": 1}
    )
    assert text.fact_id != link.fact_id


def test_canonical_json_is_insensitive_to_key_order():
    assert ir.digest({"a": 1, "b": 2}) == ir.digest({"b": 2, "a": 1})


# ---------------------------------------------------------------------------
# channels and kinds


def test_every_kind_has_a_channel_and_an_owner():
    for kind in ir.KINDS:
        assert kind in ir.KIND_CHANNEL
        assert kind in ir.KIND_OWNER
        assert ir.KIND_CHANNEL[kind] in ir.CHANNELS


def test_the_ruling_s_facets_all_have_first_class_kinds():
    """Reference target, language, accessibility/applicability, effective time,
    authority, canonical locator and provenance spans — each named by the
    ruling, each a kind rather than a note in someone's text."""
    for kind in (
        ir.REFERENCE_TARGET,
        ir.INCLUDE_TARGET,
        ir.LANGUAGE,
        ir.ACCESSIBILITY,
        ir.APPLICABILITY,
        ir.EFFECTIVE_TIME,
        ir.AUTHORITY,
        ir.LOCATOR,
        ir.PROVENANCE_SPAN,
    ):
        assert kind in ir.KINDS


def test_reference_kinds_do_not_travel_the_semantic_channel():
    """A reference-target change must not be judged by a text diff. That
    conflation is INC-V2-006 and three of the four confirmed stale escapes."""
    for kind in (ir.REFERENCE_TARGET, ir.REFERENCE_DEFINITION, ir.INCLUDE_TARGET, ir.LOCATOR):
        assert ir.KIND_CHANNEL[kind] == ir.REFERENTIAL


# ---------------------------------------------------------------------------
# the registry


def test_the_registry_refuses_two_producers_for_one_kind():
    class Rival:
        kinds = (ir.CONTENT_TEXT,)

        def extract(self, *, raw, document):
            return []

    with pytest.raises(ValueError, match="already produced by"):
        ir.register(Rival())


def test_unclaimed_kinds_are_reportable_rather_than_assumed_absent():
    unclaimed = ir.unclaimed_kinds()
    assert isinstance(unclaimed, tuple)
    for kind in ir.registered_kinds():
        assert kind not in unclaimed


def test_the_core_kinds_are_claimed_by_the_core():
    for kind in core_extractor.CoreExtractor.kinds:
        assert ir.KIND_OWNER[kind] == "core"


# ---------------------------------------------------------------------------
# fail-closed behaviour


def test_a_fail_closed_fact_blocks_the_source_faithful_assertion():
    facts = [
        ir.SourceFact(
            kind=ir.LANGUAGE, witness=witness(), state=ir.UNRESOLVED, reason="ambiguous tag"
        )
    ]
    with pytest.raises(ir.NotSourceFaithful, match="fail-closed"):
        ir.assert_source_faithful(facts)


def test_a_declined_fact_does_not_block_it():
    facts = [
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.IGNORED,
            policy_ref="POLICY-CORE-001",
        )
    ]
    ir.assert_source_faithful(facts)


def test_a_represented_fact_with_no_fingerprint_blocks_it():
    """Link 3 absent means the chain is absent, whatever the state says."""
    facts = [
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.REPRESENTED,
            representation={"text": "x"},
        )
    ]
    with pytest.raises(ir.NotSourceFaithful, match="chain link absent"):
        ir.assert_source_faithful(
            facts, fingerprint=lambda fact: "", dependencies=lambda fact: ("k",)
        )


def test_a_represented_fact_with_no_dependency_path_blocks_it():
    facts = [
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.REPRESENTED,
            representation={"text": "x"},
        )
    ]
    with pytest.raises(ir.NotSourceFaithful, match="dependency_path"):
        ir.assert_source_faithful(
            facts, fingerprint=lambda fact: "sha256:x", dependencies=lambda fact: ()
        )


def test_the_full_chain_passes():
    facts = [
        ir.SourceFact(
            kind=ir.CONTENT_TEXT,
            witness=witness(),
            state=ir.REPRESENTED,
            representation={"text": "x"},
        )
    ]
    ir.assert_source_faithful(
        facts, fingerprint=lambda fact: "sha256:x", dependencies=lambda fact: ("section:x",)
    )


def test_the_gate_is_an_exception_and_not_a_boolean():
    """A fail-closed condition that returns False into an `if` nobody wrote is
    not fail-closed."""
    assert issubclass(ir.NotSourceFaithful, Exception)


def test_counting_survives_what_the_gate_refuses():
    """An unresolved fact that stops the run cannot be counted, and a fact that
    cannot be counted is indistinguishable from one never seen."""
    facts = [
        ir.SourceFact(
            kind=ir.LANGUAGE, witness=witness(), state=ir.UNRESOLVED, reason="ambiguous"
        )
    ]
    assert ir.tally(facts)[ir.UNRESOLVED] == 1


# ---------------------------------------------------------------------------
# the core extractor


def test_the_core_extractor_emits_three_facts_per_unit():
    raw = ("# Title\n\n" + LONG + "\n\n## Note\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    assert len(document["units"]) >= 2
    assert len(facts) == 3 * len(document["units"])


def test_every_core_witness_verifies_against_the_raw_bytes():
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document_for(raw))
    for fact in facts:
        assert fact.witness.verify(raw), fact.kind


def test_a_unit_the_state_does_not_carry_is_not_called_represented():
    """The check the old instrument never made, forced by removing the digest
    the compiled state would have written."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    for unit in document["units"]:
        unit["text_sha256"] = None
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    content = [fact for fact in facts if fact.kind == ir.CONTENT_TEXT]
    assert content
    assert all(fact.state == ir.UNREPRESENTED for fact in content)
    assert all(fact.reason for fact in content)


def test_a_unit_absent_from_the_order_is_not_called_represented():
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    document["structure"]["order"] = []
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    structural = [fact for fact in facts if fact.kind == ir.STRUCTURE]
    assert structural
    assert all(fact.state == ir.UNREPRESENTED for fact in structural)


def test_an_unlocatable_unit_produces_an_unrepresented_span_not_a_guess():
    """A provenance span that is wrong is worse than one that is absent, because
    the absent one is visible."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    for unit in document["units"]:
        unit["text"] = "text that appears nowhere in the source at all, invented"
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    spans = [fact for fact in facts if fact.kind == ir.PROVENANCE_SPAN]
    assert spans
    assert all(fact.state == ir.UNREPRESENTED for fact in spans)
    assert all(fact.representation is None for fact in spans)


def test_witness_paths_are_document_qualified():
    """An unqualified path anchors a fact to the wrong artifact, or to none, and
    does it silently — it still looks like a path and still compares."""
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    assert facts
    for fact in facts:
        assert fact.witness.unit_path[0] == document["source_id"]


def test_no_unit_disappears_from_the_fact_list():
    """A unit that vanishes from the facts is the silent drop this design exists
    to prevent, so even an unlocatable one is emitted in a fail-closed state."""
    raw = ("# Title\n\n" + LONG + "\n\n## Two\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    paths = {fact.witness.unit_path for fact in facts}
    assert paths == {
        ir.unit_path_for(document["source_id"], unit["explicit_path"])
        for unit in document["units"]
    }


def test_every_declined_case_names_a_policy_in_the_published_table():
    raw = ("# Title\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    document["units"].append(
        {"explicit_path": ["Empty"], "heading": "Empty", "ordinal": 99, "text": "  ",
         "text_sha256": None}
    )
    facts = core_extractor.EXTRACTOR.extract(raw=raw, document=document)
    declined = [fact for fact in facts if fact.state == ir.IGNORED]
    assert declined
    for fact in declined:
        assert fact.policy_ref in core_extractor.POLICIES


def test_extract_all_is_deterministic():
    raw = ("# Title\n\n" + LONG + "\n\n## Two\n\n" + LONG + "\n").encode("utf-8")
    document = document_for(raw)
    first = [fact.fact_id for fact in ir.extract_all(raw=raw, document=document)]
    second = [fact.fact_id for fact in ir.extract_all(raw=raw, document=document)]
    assert first == second
    assert first
