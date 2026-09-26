"""Variants A-E as policies: identity, determinism and which page moves where."""

from __future__ import annotations

import dataclasses
import json

import pytest
from arena.tavonel import freeze, policies, signals, variants
from arena.tavonel.errors import PolicyError
from arena.tavonel.policies import (
    DECISION_ACCEPT,
    DECISION_ACCEPT_WITH_RECOVERY,
    DECISION_ESCALATE_OPUS,
    DECISION_ROUTE_SPECIALIST,
    CaseContext,
    PolicyParams,
    build_policy,
)
from conftest import PRIMARY, TABLE_SPECIALIST, TEXT_SPECIALIST, Campaign


def _contexts(campaign: Campaign) -> dict[str, CaseContext]:
    signals.build_signals(campaign.paths)
    contexts = freeze.build_contexts(campaign.paths, primary_model_key=PRIMARY)
    return {ctx.case_key: ctx for ctx in contexts}


# ------------------------------------------------------------------ identity


@pytest.mark.parametrize("variant", variants.VARIANT_IDS)
def test_every_variant_has_a_stable_identity(variant: str) -> None:
    first = build_policy(variant)
    second = build_policy(variant)
    assert first.policy_id == second.policy_id
    assert first.policy_sha256 == second.policy_sha256
    assert first.policy_sha256.startswith("sha256:")


def test_policy_ids_are_distinct_across_variants() -> None:
    ids = {build_policy(variant).policy_id for variant in variants.VARIANT_IDS}
    assert len(ids) == len(variants.VARIANT_IDS)


def test_changing_a_threshold_changes_the_policy_hash() -> None:
    base = build_policy(variants.VARIANT_C)
    tuned = build_policy(
        variants.VARIANT_C, PolicyParams().with_threshold("min_output_chars", 999.0)
    )
    assert base.policy_sha256 != tuned.policy_sha256
    assert base.policy_id == tuned.policy_id


def test_changing_a_model_slot_changes_the_policy_hash() -> None:
    base = build_policy(variants.VARIANT_C)
    swapped = build_policy(
        variants.VARIANT_C,
        dataclasses.replace(
            PolicyParams(),
            models=dataclasses.replace(policies.ModelSlots(), text_specialist="olmocr2"),
        ),
    )
    assert base.policy_sha256 != swapped.policy_sha256


def test_every_threshold_declares_itself_uncalibrated() -> None:
    parameters = build_policy(variants.VARIANT_D).parameters()
    assert parameters["thresholds"]
    for threshold in parameters["thresholds"]:
        assert threshold["calibrated"] is False
        assert threshold["rationale"]


def test_unknown_threshold_is_refused() -> None:
    with pytest.raises(PolicyError):
        PolicyParams().with_threshold("no_such_threshold", 1.0)


def test_unknown_variant_is_refused() -> None:
    with pytest.raises(PolicyError):
        build_policy("Z")


def test_variant_aliases_resolve() -> None:
    assert variants.normalize_variant("c") == variants.VARIANT_C
    assert variants.normalize_variant("oracle") == variants.VARIANT_E


# ------------------------------------------------------------------ triggers


@pytest.mark.parametrize(
    ("case_key", "attribute"),
    [
        ("case-empty", "empty_output"),
        ("case-truncated", "truncated"),
        ("case-repetition", "repetition"),
        ("case-table", "table_structure_broken"),
        ("case-formula", "formula_heavy"),
    ],
)
def test_each_page_trips_exactly_the_trigger_it_was_built_for(
    campaign: Campaign, case_key: str, attribute: str
) -> None:
    contexts = _contexts(campaign)
    triggers = policies.evaluate_triggers(contexts[case_key], PolicyParams())
    assert getattr(triggers, attribute) is True
    clean = policies.evaluate_triggers(contexts["case-clean"], PolicyParams())
    assert getattr(clean, attribute) is False


def test_a_blank_source_page_is_not_an_empty_output_failure(campaign: Campaign) -> None:
    manifest = campaign.paths.source_manifest
    rows = [
        json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line
    ]
    for row in rows:
        if row["case_key"] == "case-empty":
            row["preflight"]["near_white_ratio"] = 0.999
            row["preflight"]["is_probably_blank"] = True
    manifest.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )

    contexts = _contexts(campaign)
    triggers = policies.evaluate_triggers(contexts["case-empty"], PolicyParams())
    assert triggers.valid_blank_source is True
    assert triggers.empty_output is False
    assert "alternative_prompt" not in policies.recovery_types_for(triggers)


def test_the_disagreement_trigger_records_its_own_absence(campaign: Campaign) -> None:
    contexts = _contexts(campaign)
    triggers = policies.evaluate_triggers(contexts["case-clean"], PolicyParams())
    assert triggers.disagreement_available is False
    assert triggers.disagreement is False
    assert "no disagreement matrix row" in triggers.consulted[
        "peer_similarity_unavailable_reason"
    ]


def test_a_page_the_cheap_peer_disagrees_with_is_routed(campaign: Campaign) -> None:
    params = PolicyParams()
    peer = params.models.disagreement_peer
    context = dataclasses.replace(
        _contexts(campaign)["case-clean"],
        peer_similarity={peer: 0.10},
        peer_similarity_available=True,
    )
    triggers = policies.evaluate_triggers(context, params)
    assert triggers.disagreement_available is True
    assert triggers.disagreement is True

    decision = build_policy(variants.VARIANT_C, params).decide(context)
    assert decision.decision == DECISION_ROUTE_SPECIALIST
    assert decision.final_model == params.models.disagreement_target
    assert "peer_disagreement" in decision.escalation_reasons


def test_agreement_with_the_cheap_peer_does_not_route(campaign: Campaign) -> None:
    params = PolicyParams()
    context = dataclasses.replace(
        _contexts(campaign)["case-clean"],
        peer_similarity={params.models.disagreement_peer: 0.99},
        peer_similarity_available=True,
    )
    assert policies.evaluate_triggers(context, params).disagreement is False
    assert build_policy(variants.VARIANT_C, params).decide(context).decision == DECISION_ACCEPT


# ------------------------------------------------------------------ variants


def test_variant_a_accepts_every_page_from_the_primary(campaign: Campaign) -> None:
    contexts = _contexts(campaign)
    policy = build_policy(variants.VARIANT_A)
    for decision in policy.decide_all(list(contexts.values())):
        assert decision.decision == DECISION_ACCEPT
        assert decision.final_model == PRIMARY
        assert decision.number_of_model_calls == 1
        assert decision.recovery_required is False


def test_variant_b_keeps_the_output_and_only_plans_recovery(campaign: Campaign) -> None:
    contexts = _contexts(campaign)
    decisions = {
        decision.case_key: decision
        for decision in build_policy(variants.VARIANT_B).decide_all(list(contexts.values()))
    }
    for decision in decisions.values():
        assert decision.final_model == PRIMARY
        assert decision.number_of_model_calls == 1
    assert decisions["case-clean"].decision == DECISION_ACCEPT
    assert decisions["case-empty"].decision == DECISION_ACCEPT_WITH_RECOVERY
    assert "alternative_prompt" in decisions["case-empty"].recovery_types
    assert "higher_dpi" in decisions["case-empty"].recovery_types
    assert decisions["case-truncated"].recovery_types == ("overlap_tiling",)
    assert decisions["case-repetition"].recovery_types == ("safer_config",)
    assert decisions["case-table"].recovery_types == ("crop",)


def test_variant_c_routes_each_failure_to_its_specialist(campaign: Campaign) -> None:
    contexts = _contexts(campaign)
    decisions = {
        decision.case_key: decision
        for decision in build_policy(variants.VARIANT_C).decide_all(list(contexts.values()))
    }
    assert decisions["case-clean"].decision == DECISION_ACCEPT
    assert decisions["case-clean"].number_of_model_calls == 1
    for case_key in ("case-empty", "case-truncated", "case-repetition"):
        assert decisions[case_key].decision == DECISION_ROUTE_SPECIALIST
        assert decisions[case_key].final_model == TEXT_SPECIALIST
        assert decisions[case_key].number_of_model_calls == 2
    assert decisions["case-table"].final_model == TABLE_SPECIALIST


def test_variant_c_routes_a_formula_page_when_the_specialist_exists(
    campaign: Campaign,
) -> None:
    params = dataclasses.replace(
        PolicyParams(),
        models=dataclasses.replace(
            policies.ModelSlots(), formula_specialist=TABLE_SPECIALIST
        ),
    )
    contexts = _contexts(campaign)
    decision = build_policy(variants.VARIANT_C, params).decide(contexts["case-formula"])
    assert decision.decision == DECISION_ROUTE_SPECIALIST
    assert decision.final_model == TABLE_SPECIALIST
    assert "formula_heavy" in decision.escalation_reasons


def test_an_unavailable_specialist_is_recorded_not_silently_swapped(
    campaign: Campaign,
) -> None:
    contexts = _contexts(campaign)
    decision = build_policy(variants.VARIANT_C).decide(contexts["case-formula"])
    assert decision.decision == policies.DECISION_ACCEPT
    assert decision.final_model == PRIMARY
    assert "formula_heavy" in decision.escalation_reasons
    assert decision.notes and "no frozen output" in decision.notes[0]


def test_variant_c_is_deterministic_and_order_independent(campaign: Campaign) -> None:
    contexts = list(_contexts(campaign).values())
    policy = build_policy(variants.VARIANT_C)
    forward = {d.case_key: d.final_model for d in policy.decide_all(contexts)}
    backward = {d.case_key: d.final_model for d in policy.decide_all(list(reversed(contexts)))}
    assert forward == backward


def test_variant_d_escalates_only_within_its_cap(campaign_with_opus: Campaign) -> None:
    contexts = _contexts(campaign_with_opus)
    params = PolicyParams().with_threshold("escalation_fraction_cap", 0.5)
    decisions = {
        decision.case_key: decision
        for decision in build_policy(variants.VARIANT_D, params).decide_all(
            list(contexts.values())
        )
    }
    escalated = [
        case_key
        for case_key, decision in decisions.items()
        if decision.decision == DECISION_ESCALATE_OPUS
    ]
    assert len(escalated) == 3
    assert set(escalated) == {"case-empty", "case-repetition", "case-truncated"}
    for case_key in escalated:
        assert decisions[case_key].final_model == "opus5_subscription"
        assert decisions[case_key].escalation_stage == 2
        assert decisions[case_key].number_of_model_calls == 3


def test_variant_d_escalates_nothing_at_the_default_cap(campaign_with_opus: Campaign) -> None:
    contexts = _contexts(campaign_with_opus)
    decisions = build_policy(variants.VARIANT_D).decide_all(list(contexts.values()))
    assert all(decision.decision != DECISION_ESCALATE_OPUS for decision in decisions)
    assert all(decision.risk_score is not None for decision in decisions)


def test_variant_d_ranking_does_not_depend_on_input_order(
    campaign_with_opus: Campaign,
) -> None:
    contexts = list(_contexts(campaign_with_opus).values())
    params = PolicyParams().with_threshold("escalation_fraction_cap", 0.5)
    policy = build_policy(variants.VARIANT_D, params)
    forward = {d.case_key: d.decision for d in policy.decide_all(contexts)}
    backward = {d.case_key: d.decision for d in policy.decide_all(list(reversed(contexts)))}
    assert forward == backward


def test_risk_score_never_decides_acceptance_on_its_own(campaign: Campaign) -> None:
    contexts = _contexts(campaign)
    params = PolicyParams()
    clean = contexts["case-clean"]
    triggers = policies.evaluate_triggers(clean, params)
    assert policies.risk_score(triggers, clean, params) == 0.0
    assert build_policy(variants.VARIANT_C).decide(clean).decision == DECISION_ACCEPT
