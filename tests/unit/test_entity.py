"""Entity resolution — §21 and §N16.

Invariant 10 sets the asymmetry these tests enforce: a false merge costs more than
a false split. Two customer records wrongly merged mixes two companies' contracts,
and unpicking it means knowing which fact came from which — exactly what the merge
destroyed.
"""

from __future__ import annotations

import pytest
from akc_cir.entity import (
    HIGH_RISK_TYPES,
    EntityMention,
    EntityRegistry,
    MergeVerdict,
    ResolutionTier,
    resolve_mention,
)


def _mention(mention_id: str, text: str, **kw) -> EntityMention:
    kw.setdefault("evidence_id", f"ev_{mention_id}")
    kw.setdefault("type_candidate", "machine")
    return EntityMention(mention_id=mention_id, text=text, **kw)


def _machine(**kw) -> EntityMention:
    base = {
        "text": "M-012",
        "type_candidate": "machine",
        "attributes": {"plant": "B", "line": "B"},
    }
    base.update(kw)
    return _mention(base.pop("mention_id", "m1"), **base)


# --------------------------------------------------------------------------
# Evidence is required
# --------------------------------------------------------------------------


def test_a_mention_without_evidence_is_refused() -> None:
    """A merge is a claim about two passages; one that cannot name them is not."""
    with pytest.raises(ValueError, match="a claim about nothing"):
        EntityMention(mention_id="m1", text="M-012", evidence_id="")


# --------------------------------------------------------------------------
# §N16.2 tier 1 — the system of record
# --------------------------------------------------------------------------


def test_a_matching_system_identifier_merges() -> None:
    incoming = _machine(external_ids={"asset_id": "Asset_7782"})
    existing = _machine(mention_id="m0", external_ids={"asset_id": "Asset_7782"})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.verdict is MergeVerdict.AUTO_MERGE
    assert decision.tier is ResolutionTier.SYSTEM_OF_RECORD
    assert decision.entity_id == "ent_1"


def test_one_identifier_matching_two_entities_goes_to_review() -> None:
    """The system of record disagreeing with itself is not something to guess past."""
    incoming = _machine(external_ids={"asset_id": "Asset_7782"})
    twin = _machine(mention_id="m0", external_ids={"asset_id": "Asset_7782"})

    decision = resolve_mention(incoming, [("ent_1", twin), ("ent_2", twin)])

    assert decision.verdict is MergeVerdict.REVIEW
    assert set(decision.candidates) == {"ent_1", "ent_2"}


def test_a_system_identifier_beats_a_name_that_looks_different() -> None:
    incoming = _machine(text="Press 12", external_ids={"asset_id": "Asset_7782"})
    existing = _machine(mention_id="m0", external_ids={"asset_id": "Asset_7782"})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.tier is ResolutionTier.SYSTEM_OF_RECORD


# --------------------------------------------------------------------------
# §N16.2 tier 2 and 3
# --------------------------------------------------------------------------


def test_an_approved_alias_merges() -> None:
    incoming = _machine(text="Press Twelve", attributes={})
    existing = _machine(mention_id="m0", attributes={})

    decision = resolve_mention(
        incoming, [("ent_1", existing)], aliases={"press twelve": "ent_1"}
    )

    assert decision.tier is ResolutionTier.APPROVED_ALIAS
    assert decision.verdict is MergeVerdict.AUTO_MERGE


def test_a_composite_key_merges_when_every_attribute_agrees() -> None:
    decision = resolve_mention(_machine(), [("ent_1", _machine(mention_id="m0"))])

    assert decision.tier is ResolutionTier.COMPOSITE_KEY
    assert decision.verdict is MergeVerdict.AUTO_MERGE


def test_one_attribute_is_not_a_composite_key() -> None:
    """`{plant: B}` matches every machine in plant B."""
    incoming = _machine(attributes={"plant": "B"})
    existing = _machine(mention_id="m0", attributes={"plant": "B"})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.tier is not ResolutionTier.COMPOSITE_KEY


def test_a_composite_key_with_a_different_name_does_not_merge_on_the_key_alone() -> None:
    incoming = _machine(text="M-012")
    existing = _machine(mention_id="m0", text="M-099")

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.tier is not ResolutionTier.COMPOSITE_KEY


# --------------------------------------------------------------------------
# §N16.2 tier 4 and 5
# --------------------------------------------------------------------------


def test_context_overlap_merges_an_ordinary_type() -> None:
    incoming = _machine(attributes={}, context_ids=frozenset({"c1", "c2", "c3"}))
    existing = _machine(
        mention_id="m0", attributes={}, text="Press 12",
        context_ids=frozenset({"c1", "c2", "c3"}),
    )

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.tier is ResolutionTier.CONTEXT_OVERLAP
    assert decision.verdict is MergeVerdict.AUTO_MERGE


def test_similar_names_merge_an_ordinary_type() -> None:
    incoming = _mention("m1", "Acme Corp Rolling Mill", attributes={})
    existing = _mention("m0", "Acme Corp Rolling Mill", attributes={})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.tier is ResolutionTier.NAME_SIMILARITY
    assert decision.verdict is MergeVerdict.AUTO_MERGE


def test_two_equally_similar_names_go_to_review() -> None:
    incoming = _mention("m1", "Acme Rolling Mill", attributes={})
    twin = _mention("m0", "Acme Rolling Mill", attributes={})

    decision = resolve_mention(incoming, [("ent_1", twin), ("ent_2", twin)])

    assert decision.verdict is MergeVerdict.REVIEW
    assert len(decision.candidates) == 2


def test_unrelated_names_start_a_new_entity() -> None:
    incoming = _mention("m1", "Acme Rolling Mill", attributes={})
    existing = _mention("m0", "Bolt Supplier Limited", attributes={})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.verdict is MergeVerdict.NEW_ENTITY
    assert decision.tier is None


# --------------------------------------------------------------------------
# §N16.3 — high-risk types
# --------------------------------------------------------------------------


def test_a_customer_does_not_auto_merge_on_a_resemblance() -> None:
    """Merging two customers mixes two companies' contracts."""
    incoming = _mention("m1", "Acme Corporation", type_candidate="customer", attributes={})
    existing = _mention("m0", "Acme Corporation", type_candidate="customer", attributes={})

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.verdict is MergeVerdict.REVIEW
    assert decision.entity_id is None
    assert "high-risk" in decision.reason


def test_a_customer_does_auto_merge_on_an_identifier() -> None:
    incoming = _mention(
        "m1", "Acme Corp", type_candidate="customer",
        external_ids={"crm_id": "C-4411"}, attributes={},
    )
    existing = _mention(
        "m0", "Acme Corporation", type_candidate="customer",
        external_ids={"crm_id": "C-4411"}, attributes={},
    )

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.verdict is MergeVerdict.AUTO_MERGE
    assert decision.tier is ResolutionTier.SYSTEM_OF_RECORD


def test_a_customer_does_not_auto_merge_on_context_either() -> None:
    incoming = _mention(
        "m1", "Acme", type_candidate="customer", attributes={},
        context_ids=frozenset({"c1", "c2"}),
    )
    existing = _mention(
        "m0", "Zenith", type_candidate="customer", attributes={},
        context_ids=frozenset({"c1", "c2"}),
    )

    decision = resolve_mention(incoming, [("ent_1", existing)])

    assert decision.verdict is MergeVerdict.REVIEW


def test_the_high_risk_types_are_the_ones_that_cost_money() -> None:
    assert {"person", "customer", "contract"} <= HIGH_RISK_TYPES
    assert "machine" not in HIGH_RISK_TYPES


# --------------------------------------------------------------------------
# §N16.2 tier 6 — the model proposes and does not execute
# --------------------------------------------------------------------------


def test_a_model_proposal_can_only_reach_review() -> None:
    incoming = _mention("m1", "Rolling Mill Three", attributes={})
    existing = _mention("m0", "Bolt Supplier Limited", attributes={})

    decision = resolve_mention(
        incoming, [("ent_1", existing)], model_proposals=["ent_1"]
    )

    assert decision.verdict is MergeVerdict.REVIEW
    assert decision.tier is ResolutionTier.MODEL_PROPOSAL
    assert "propose and not" in decision.reason


def test_no_configuration_lets_a_model_proposal_merge() -> None:
    incoming = _mention("m1", "Rolling Mill Three", attributes={})
    existing = _mention("m0", "Bolt Supplier Limited", attributes={})

    for threshold in (0.0, 0.5, 1.0):
        decision = resolve_mention(
            incoming,
            [("ent_1", existing)],
            model_proposals=["ent_1"],
            name_threshold=1.0,
            context_threshold=threshold,
        )
        assert decision.verdict is not MergeVerdict.AUTO_MERGE


def test_a_proposal_naming_an_unknown_entity_is_ignored() -> None:
    incoming = _mention("m1", "Rolling Mill Three", attributes={})
    existing = _mention("m0", "Bolt Supplier Limited", attributes={})

    decision = resolve_mention(
        incoming, [("ent_1", existing)], model_proposals=["ent_ghost"]
    )

    assert decision.verdict is MergeVerdict.NEW_ENTITY


# --------------------------------------------------------------------------
# The tier is carried, not collapsed
# --------------------------------------------------------------------------


def test_a_tier_one_match_and_a_tier_five_match_are_distinguishable() -> None:
    """Collapsing them into one boolean loses what a reviewer needs."""
    by_id = resolve_mention(
        _machine(external_ids={"asset_id": "A1"}),
        [("ent_1", _machine(mention_id="m0", external_ids={"asset_id": "A1"}))],
    )
    by_name = resolve_mention(
        _mention("m1", "Acme Rolling Mill", attributes={}),
        [("ent_1", _mention("m0", "Acme Rolling Mill", attributes={}))],
    )

    assert by_id.merged and by_name.merged
    assert by_id.tier < by_name.tier


# --------------------------------------------------------------------------
# §N16.4 — reversible
# --------------------------------------------------------------------------


def _registry() -> EntityRegistry:
    registry = EntityRegistry()
    registry.add("ent_1", "m1")
    registry.add("ent_1", "m2")
    registry.add("ent_2", "m3")
    return registry


def _auto_decision():
    return resolve_mention(_machine(), [("ent_2", _machine(mention_id="m0"))])


def test_a_merge_folds_the_members_together() -> None:
    registry = _registry()

    registry.merge(
        merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=_auto_decision()
    )

    assert registry.members("ent_1") == ("m1", "m2", "m3")
    assert registry.entity_ids == ("ent_1",)


def test_an_unmerge_restores_exactly_what_was_there() -> None:
    """Re-deriving it would run the resolver against a corpus that has changed."""
    registry = _registry()
    registry.merge(
        merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=_auto_decision()
    )

    registry.unmerge("mg_1")

    assert registry.members("ent_1") == ("m1", "m2")
    assert registry.members("ent_2") == ("m3",)


def test_the_merge_record_names_the_tier_that_produced_it() -> None:
    registry = _registry()

    record = registry.merge(
        merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=_auto_decision()
    )

    assert record.tier is ResolutionTier.COMPOSITE_KEY


def test_the_system_cannot_execute_a_merge_the_resolver_declined() -> None:
    registry = _registry()
    review = resolve_mention(
        _mention("m1", "Acme Corporation", type_candidate="customer", attributes={}),
        [("ent_2", _mention("m0", "Acme Corporation", type_candidate="customer", attributes={}))],
    )

    with pytest.raises(ValueError, match="named human reviewer"):
        registry.merge(
            merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=review
        )


def test_a_named_reviewer_may_execute_a_declined_merge() -> None:
    registry = _registry()
    review = resolve_mention(
        _mention("m1", "Acme Corporation", type_candidate="customer", attributes={}),
        [("ent_2", _mention("m0", "Acme Corporation", type_candidate="customer", attributes={}))],
    )

    record = registry.merge(
        merge_id="mg_1",
        into="ent_1",
        absorbed="ent_2",
        decision=review,
        decided_by="ops@acme",
    )

    assert record.decided_by == "ops@acme"


def test_an_entity_cannot_absorb_itself() -> None:
    with pytest.raises(ValueError, match="absorb itself"):
        _registry().merge(
            merge_id="mg_1", into="ent_1", absorbed="ent_1", decision=_auto_decision()
        )


def test_undoing_a_merge_that_never_happened_is_an_error() -> None:
    with pytest.raises(KeyError, match="no merge"):
        _registry().unmerge("mg_ghost")


# --------------------------------------------------------------------------
# §N43's blocker: false merge in the critical set
# --------------------------------------------------------------------------


def test_the_audit_flags_a_high_risk_merge_no_identifier_supported() -> None:
    """Defence in depth, and the test says so.

    The resolver cannot currently produce this combination -- a high-risk type at
    tier 4 or 5 comes back REVIEW, and the registry refuses a system merge of a
    declined decision. The audit exists for the case where a later code path, or a
    type reclassified as high-risk after the fact, produces one anyway. It is
    exercised here by merging on name similarity and then asking the audit under a
    type map that calls the entity a customer.
    """
    registry = _registry()
    by_name = resolve_mention(
        _mention("m1", "Acme Rolling Mill", attributes={}),
        [("ent_2", _mention("m0", "Acme Rolling Mill", attributes={}))],
    )
    registry.merge(merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=by_name)

    assert by_name.tier is ResolutionTier.NAME_SIMILARITY
    assert registry.high_risk_auto_merges({"ent_1": "customer"}) == ("mg_1",)


def test_an_identifier_backed_merge_is_not_flagged_by_the_audit() -> None:
    registry = _registry()
    decision = resolve_mention(
        _machine(external_ids={"asset_id": "A1"}),
        [("ent_2", _machine(mention_id="m0", external_ids={"asset_id": "A1"}))],
    )
    registry.merge(
        merge_id="mg_1", into="ent_1", absorbed="ent_2", decision=decision
    )

    assert registry.high_risk_auto_merges({"ent_1": "customer"}) == ()


def test_a_reviewer_approved_merge_is_not_flagged_as_an_automatic_one() -> None:
    registry = _registry()
    review = resolve_mention(
        _mention("m1", "Acme Corporation", type_candidate="customer", attributes={}),
        [
            (
                "ent_2",
                _mention(
                    "m0", "Acme Corporation", type_candidate="customer", attributes={}
                ),
            )
        ],
    )
    registry.merge(
        merge_id="mg_1",
        into="ent_1",
        absorbed="ent_2",
        decision=review,
        decided_by="ops@acme",
    )

    assert registry.high_risk_auto_merges({"ent_1": "customer"}) == ()
