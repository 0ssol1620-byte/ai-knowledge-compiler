"""A contract is amended, and only what the amendment reached is rebuilt.

The scenario is one clause changing in a four-clause contract:

    Payment is due within 30 days of invoice.
    Payment is due within 45 days of invoice.

Everything else -- governing law, registered address, signatories -- is byte
identical. What has to hold is not "the two builds agree": that is what 43 pairs
already showed while 26 of them were missing source coverage. What has to hold is
that the clause keeps its identity, that the amendment is *not* erased by the
normalisation that keeps that identity, that the artifacts reading the clause
are the ones rebuilt, that the ones that do not read it are carried forward, and
that a source fact the compiled state failed to represent stops the whole thing.

Two of these tests are mutants. `test_legacy_predicate_erases_a_normalised_edit`
turns the pre-INC-V2-037 gate back on and asserts the change disappears, and
`test_assert_fingerprints_separated_catches_a_folded_fingerprint` feeds the
identity fold to the change fingerprint and asserts the guard fires. Without
them the passing tests above prove only that the current code agrees with
itself.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from akc_cir.dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.revision_compile import (
    CANDIDATE_BLOCKING_CHANGE_STATES,
    FAIL_CLOSED_SOURCE_FACT_STATES,
    FINGERPRINT_INPUTS,
    SCHEMA,
    ChangeState,
    IdentityContinuity,
    PriorWorld,
    RevisionDisposition,
    SourceFact,
    SourceFactState,
    audit_source_facts,
    change_fingerprint,
    compile_revision,
    identity_fingerprint,
)
from akc_cir.semantic_diff import (
    ChangeChannel,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

SOURCE = "src_" + "c" * 32
V1_SHA = "sha256:" + "1" * 64
V2_SHA = "sha256:" + "2" * 64

PAYMENT_V1 = "Payment is due within 30 days of invoice."
PAYMENT_V2 = "Payment is due within 45 days of invoice."
LAW = "This agreement is governed by the laws of the Republic of Korea."
ADDRESS = "Registered office: 12 Sejong-daero, Jung-gu, Seoul."
SIGNATORIES = "Signed by the authorised representatives of both parties."

PAYMENT = "ku_payment"
LAW_ID = "ku_law"
ADDRESS_ID = "ku_address"
SIGNATORIES_ID = "ku_signatories"


def _unit(logical_id: str, section: str, anchor: str, text: str, page: int) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=logical_id,
        text=text,
        document_path=("Contract", section),
        anchor=anchor,
        explicit_identifier=anchor,
        evidence_id=f"ev_{logical_id}_{page}",
        page_number1=page,
    )


def _units(payment_text: str) -> list[UnitSnapshot]:
    return [
        _unit(PAYMENT, "4. Payment", "4.1", payment_text, 2),
        _unit(LAW_ID, "9. Governing law", "9.1", LAW, 4),
        _unit(ADDRESS_ID, "1. Parties", "1.2", ADDRESS, 1),
        _unit(SIGNATORIES_ID, "10. Signatures", "10.1", SIGNATORIES, 5),
    ]


def _shape(units: list[UnitSnapshot]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
        unit_order=tuple(unit.logical_id for unit in units),
    )


#: artifact id -> the logical units its bytes are a function of.
READS: dict[str, tuple[str, ...]] = {
    "claim:payment": (PAYMENT,),
    "claim:law": (LAW_ID,),
    "claim:address": (ADDRESS_ID,),
    "claim:signatories": (SIGNATORIES_ID,),
    "summary:contract": (PAYMENT, LAW_ID),
    "retrieval:payment": (PAYMENT,),
    "graph:relations": (PAYMENT, LAW_ID, ADDRESS_ID, SIGNATORIES_ID),
}
ARTIFACTS = tuple(sorted(READS))


def _graph() -> DependencyGraph:
    edges = []
    for artifact, reads in READS.items():
        for unit in reads:
            edges.append(
                DependencyEdge(
                    source_id=artifact,
                    target_id=unit,
                    edge_type=EdgeType.DERIVED_FROM,
                    channels=frozenset({DependencyChannel.SEMANTIC}),
                )
            )
    return DependencyGraph(edges)


def _selective_builder(units: list[UnitSnapshot]):
    """The compiler under test. Reads the AFTER revision, one artifact at a time."""
    by_id = {unit.logical_id: unit for unit in units}

    def build(artifact_id: str) -> str:
        payload = {
            "artifact": artifact_id,
            "reads": [
                {"logical_id": item, "text": by_id[item].text}
                for item in READS[artifact_id]
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    return build


def _oracle(units: list[UnitSnapshot]):
    """A full rebuild written separately, and deliberately not by calling `build`.

    It walks the inventory rather than being handed an artifact, and assembles
    the same specification from its own loop. It is not a second *algorithm* --
    the spec is one spec -- but it is a second traversal, so a selective path
    that silently skips an artifact is caught rather than agreed with.
    """

    def full() -> dict[str, str]:
        by_id = {unit.logical_id: unit for unit in units}
        out: dict[str, str] = {}
        for artifact in sorted(READS):
            reads = []
            for item in READS[artifact]:
                reads.append({"logical_id": item, "text": by_id[item].text})
            body = json.dumps(
                {"artifact": artifact, "reads": reads},
                sort_keys=True,
                separators=(",", ":"),
            )
            out[artifact] = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        return out

    return full


def _prior_world(units: list[UnitSnapshot]) -> PriorWorld:
    return PriorWorld(
        world_state_id="world-v1",
        manifest_digest="sha256:" + "a" * 64,
        artifact_digests=_oracle(units)(),
        source_sha256=V1_SHA,
        units=units,
        shape=_shape(units),
    )


def _compile(payment_text: str = PAYMENT_V2, **kwargs):
    before = _units(PAYMENT_V1)
    after = _units(payment_text)
    return compile_revision(
        source_id=SOURCE,
        previous=_prior_world(before),
        after_units=after,
        after_shape=_shape(after),
        after_sha256=V2_SHA,
        graph=_graph(),
        artifacts=ARTIFACTS,
        build=_selective_builder(after),
        full_rebuild=_oracle(after),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# I is not E


def test_fingerprint_inputs_are_disjoint():
    assert not set(FINGERPRINT_INPUTS["identity"]) & set(FINGERPRINT_INPUTS["change"])
    assert "normalized_text" in FINGERPRINT_INPUTS["identity"]
    assert "raw_text" in FINGERPRINT_INPUTS["change"]


def test_identity_survives_the_amendment_and_the_amendment_survives_identity():
    before = _unit(PAYMENT, "4. Payment", "4.1", PAYMENT_V1, 2)
    after = _unit(PAYMENT, "4. Payment", "4.1", PAYMENT_V2, 2)
    # Different clause text, so identity has to work for this to be one clause.
    assert identity_fingerprint(before) != identity_fingerprint(after)
    # And the change is visible, which is the half that gets lost.
    assert change_fingerprint(before) != change_fingerprint(after)


def test_a_case_and_punctuation_edit_keeps_identity_and_is_still_a_change():
    """The case the separation exists for.

    `normalize_text_for_identity` folds these two together, which is right: it is
    the same clause, re-typeset. If that same fold decided change equivalence,
    the edit would vanish -- and a fold that erases punctuation will erase a
    decimal point on the day it meets one.
    """
    before = _unit(PAYMENT, "4. Payment", "4.1", "Payment is due within 30 days.", 2)
    after = _unit(PAYMENT, "4. Payment", "4.1", "PAYMENT IS DUE WITHIN 30 DAYS!", 2)
    assert identity_fingerprint(before) == identity_fingerprint(after)
    assert change_fingerprint(before) != change_fingerprint(after)


def test_assert_fingerprints_separated_catches_a_folded_fingerprint(monkeypatch):
    """Mutant. Feed the identity fold to the change fingerprint; the guard fires.

    Without this the test above proves only that two functions currently differ,
    not that anything notices when they stop.
    """
    import akc_cir.revision_compile as module

    monkeypatch.setattr(module, "change_fingerprint", module.identity_fingerprint)
    before = _unit(PAYMENT, "4. Payment", "4.1", "Payment is due within 30 days.", 2)
    after = _unit(PAYMENT, "4. Payment", "4.1", "PAYMENT IS DUE WITHIN 30 DAYS!", 2)
    with pytest.raises(AssertionError, match="leaked into change equivalence"):
        module.assert_fingerprints_separated(before, after)


def test_legacy_predicate_erases_a_normalised_edit():
    """Mutant on the diff itself, using the switch Core already keeps for it.

    `legacy_identity_change_predicate=True` restores the pre-INC-V2-037 gate, in
    which a matched pair was reported MODIFIED_CLAIM only when its identity folds
    differed. Under it, a case-and-punctuation edit produces no claim change at
    all. That is the defect, reproduced, so the default's behaviour above is a
    result rather than an assumption.
    """
    before = [_unit(PAYMENT, "4. Payment", "4.1", "Payment is due within 30 days.", 2)]
    after = [_unit(PAYMENT, "4. Payment", "4.1", "PAYMENT IS DUE WITHIN 30 DAYS!", 2)]
    common = {
        "before_sha256": V1_SHA,
        "after_sha256": V2_SHA,
        "level": DiffLevel.SEMANTIC,
        "before_shape": _shape(before),
        "after_shape": _shape(after),
        "before_units": before,
        "after_units": after,
        "source": SOURCE,
    }
    legacy = diff_documents(**common, legacy_identity_change_predicate=True)
    current = diff_documents(**common)
    legacy_semantic = legacy.changed_logical_ids_for(ChangeChannel.SEMANTIC)
    current_semantic = current.changed_logical_ids_for(ChangeChannel.SEMANTIC)
    assert legacy_semantic == ()
    assert current_semantic == (PAYMENT,)


def test_the_amended_clause_is_continued_and_semantic():
    result = _compile()
    payment = next(u for u in result.units if u.logical_unit_id == PAYMENT)
    assert payment.continuity is IdentityContinuity.CONTINUED
    assert payment.change_state is ChangeState.SEMANTIC
    assert payment.continued_and_changed
    assert payment.previous_logical_unit_id == PAYMENT


def test_untouched_clauses_are_continued_and_unchanged():
    result = _compile()
    for logical_id in (LAW_ID, ADDRESS_ID, SIGNATORIES_ID):
        record = next(u for u in result.units if u.logical_unit_id == logical_id)
        assert record.continuity is IdentityContinuity.CONTINUED
        assert record.change_state is ChangeState.UNCHANGED


# ---------------------------------------------------------------------------
# impact, selective rebuild, equivalence


def test_only_what_reads_the_amended_clause_is_rebuilt():
    result = _compile()
    assert set(result.rebuilt_artifact_ids) == {
        "claim:payment",
        "summary:contract",
        "retrieval:payment",
        "graph:relations",
    }
    assert set(result.carried_forward_artifact_ids) == {
        "claim:law",
        "claim:address",
        "claim:signatories",
    }


def test_work_avoided_is_positive_and_is_total_minus_rebuilt():
    result = _compile()
    assert result.total_artifacts == len(ARTIFACTS)
    assert result.work_avoided_artifacts > 0
    assert result.work_avoided_artifacts == result.total_artifacts - len(
        result.rebuilt_artifact_ids
    )


def test_the_selective_state_equals_the_independent_full_rebuild():
    result = _compile()
    assert result.equivalence == "passed"
    assert result.equivalence_divergent_artifact_ids == ()


def test_no_stale_value_is_carried_forward():
    """stale = 0, measured rather than asserted.

    Every carried-forward artifact is compared against the oracle's value for the
    AFTER revision. A carried value that differs is a stale escape.
    """
    after = _units(PAYMENT_V2)
    oracle = _oracle(after)()
    result = _compile()
    stale = [
        artifact
        for artifact in result.carried_forward_artifact_ids
        if result.state[artifact] != oracle[artifact]
    ]
    assert stale == []


def test_false_invalidation_is_measured_not_hidden():
    """A rebuild that produced what was already there is recorded.

    Rebuilding everything would make stale=0 trivially true; this is the number
    that stops that from looking like success.
    """
    result = _compile()
    assert result.unnecessary_rebuild_artifact_ids == ()


def test_an_identical_revision_rebuilds_nothing():
    before = _units(PAYMENT_V1)
    after = _units(PAYMENT_V1)
    result = compile_revision(
        source_id=SOURCE,
        previous=_prior_world(before),
        after_units=after,
        after_shape=_shape(after),
        after_sha256=V1_SHA,
        graph=_graph(),
        artifacts=ARTIFACTS,
        build=_selective_builder(after),
        full_rebuild=_oracle(after),
    )
    assert result.rebuilt_artifact_ids == ()
    assert len(result.carried_forward_artifact_ids) == len(ARTIFACTS)
    assert result.equivalence == "passed"


def test_an_artifact_with_no_plan_and_no_prior_value_is_quarantined():
    """Not invented, not silently empty.

    A new artifact the plan did not name and the prior world never held has no
    honest value, so it is withheld and the world cannot be promoted.
    """
    before = _units(PAYMENT_V1)
    after = _units(PAYMENT_V2)
    inventory = (*ARTIFACTS, "claim:orphan")
    prior = _prior_world(before)

    def build(artifact_id: str) -> str:
        return _selective_builder(after)(artifact_id)

    result = compile_revision(
        source_id=SOURCE,
        previous=prior,
        after_units=after,
        after_shape=_shape(after),
        after_sha256=V2_SHA,
        graph=_graph(),
        artifacts=inventory,
        build=build,
    )
    assert "claim:orphan" in result.quarantined_artifact_ids
    assert result.state["claim:orphan"].startswith("MISSING_")
    assert result.disposition is RevisionDisposition.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# source facts


def _represented(count: int) -> list[SourceFact]:
    return [
        SourceFact(
            fact_id=f"sf-{index}",
            kind="CONTENT_TEXT",
            state=SourceFactState.REPRESENTED,
        )
        for index in range(count)
    ]


def test_a_fully_represented_revision_is_promotable():
    result = _compile(source_facts=_represented(4))
    assert result.source_facts.source_faithful
    assert result.source_facts.coverage == 1.0
    assert result.review_reasons == ()
    assert result.disposition is RevisionDisposition.PROMOTABLE


def test_a_recognised_but_unrepresented_fact_blocks_promotion():
    facts = [
        *_represented(3),
        SourceFact(
            fact_id="sf-math",
            kind="UNSUPPORTED_CONSTRUCT",
            state=SourceFactState.UNREPRESENTED,
            reason="no canonical representation for an expression tree",
        ),
    ]
    result = _compile(source_facts=facts)
    assert not result.source_facts.source_faithful
    assert result.disposition is RevisionDisposition.REVIEW_REQUIRED
    assert any("fail closed" in reason for reason in result.review_reasons)


def test_an_unresolved_fact_blocks_promotion():
    facts = [
        *_represented(3),
        SourceFact(
            fact_id="sf-ambiguous",
            kind="CANONICAL_SOURCE_LOCATOR",
            state=SourceFactState.UNRESOLVED,
            reason="locator resolves to two regions",
        ),
    ]
    result = _compile(source_facts=facts)
    assert not result.source_facts.source_faithful
    assert result.disposition is RevisionDisposition.REVIEW_REQUIRED


def test_a_predeclared_ignore_is_the_only_state_that_fails_open():
    facts = [
        *_represented(3),
        SourceFact(
            fact_id="sf-styling",
            kind="ACCESSIBILITY",
            state=SourceFactState.IGNORED,
            policy_id="policy.accessibility.out-of-scope.v1",
        ),
    ]
    result = _compile(source_facts=facts)
    assert result.source_facts.source_faithful
    assert result.disposition is RevisionDisposition.PROMOTABLE
    assert result.source_facts.ignored_policies == (
        "policy.accessibility.out-of-scope.v1",
    )


def test_ignore_without_a_predeclared_policy_is_refused():
    with pytest.raises(ValueError, match="policy id"):
        audit_source_facts(
            [
                SourceFact(
                    fact_id="sf-1", kind="LANGUAGE", state=SourceFactState.IGNORED
                )
            ]
        )


def test_a_fail_closed_state_without_a_reason_is_refused():
    for state in FAIL_CLOSED_SOURCE_FACT_STATES:
        with pytest.raises(ValueError, match="needs a reason"):
            audit_source_facts(
                [SourceFact(fact_id="sf-1", kind="STRUCTURE", state=state)]
            )


def test_coverage_excludes_predeclared_ignores_from_its_denominator():
    """A broad IGNORE policy must not be able to raise coverage."""
    audit = audit_source_facts(
        [
            *_represented(1),
            SourceFact(
                fact_id="i1",
                kind="LANGUAGE",
                state=SourceFactState.IGNORED,
                policy_id="p.v1",
            ),
            SourceFact(
                fact_id="i2",
                kind="LANGUAGE",
                state=SourceFactState.IGNORED,
                policy_id="p.v1",
            ),
        ]
    )
    assert audit.total == 3
    assert audit.coverage == 1.0


# ---------------------------------------------------------------------------
# contract surface


def test_every_change_channel_the_diff_can_emit_is_routed():
    import akc_cir.revision_compile as module

    assert set(module._CHANNEL_STATE) == set(ChangeChannel)
    for state in module._CHANNEL_STATE.values():
        assert state in module._STATE_RANK


def test_an_untyped_unit_change_cannot_be_promotable():
    assert ChangeState.UNRESOLVED in CANDIDATE_BLOCKING_CHANGE_STATES


def test_the_result_carries_the_prior_world_binding():
    result = _compile(source_facts=_represented(4))
    record = result.as_record()
    assert record["schema"] == SCHEMA
    assert record["previousWorldStateId"] == "world-v1"
    assert record["previousManifestDigest"] == "sha256:" + "a" * 64
    assert record["recompilation"]["workAvoidedArtifacts"] == 3
    assert record["recompilation"]["totalArtifacts"] == 7
    assert record["equivalence"] == "passed"
    assert record["disposition"] == "promotable"
    assert record["sourceFacts"]["source_faithful"] is True


def test_the_record_separates_identity_from_change_per_unit():
    record = _compile(source_facts=_represented(4)).as_record()
    payment = next(
        unit
        for unit in record["identity"]["units"]
        if unit["logicalUnitId"] == PAYMENT
    )
    assert payment["identityContinuity"] == "continued"
    assert payment["changeState"] == "semantic"
    assert payment["identityFingerprint"] != payment["changeFingerprint"]
