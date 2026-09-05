"""Counterfactual cost: what a variant actually routed, never the whole arena."""

from __future__ import annotations

import json

import pytest
from arena.tavonel import cost, freeze, jsonio, recovery_plan, replay, signals, variants
from arena.tavonel.errors import MissingInputError
from arena.tavonel.policies import PolicyParams
from conftest import PRIMARY, TABLE_SPECIALIST, TEXT_SPECIALIST, Campaign


def _run(campaign: Campaign, variant: str) -> dict:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variant)
    replay.replay_variant(campaign.paths, variant=variant)
    report = cost.variant_cost(campaign.paths, variant=variant)
    return json.loads(report.path.read_text(encoding="utf-8"))


def test_a_base_variant_prices_only_the_primary(campaign: Campaign) -> None:
    payload = _run(campaign, variants.VARIANT_A)
    assert set(payload["per_model"]) == {PRIMARY}
    assert payload["per_model"][PRIMARY]["pages_served"] == len(campaign.cases)
    assert payload["never_sum_all_models"] is True


def test_an_adaptive_variant_prices_exactly_the_models_it_routed_to(
    campaign: Campaign,
) -> None:
    payload = _run(campaign, variants.VARIANT_C)
    assert set(payload["per_model"]) == {PRIMARY, TEXT_SPECIALIST, TABLE_SPECIALIST}
    served = sum(entry["pages_served"] for entry in payload["per_model"].values())
    assert served == len(campaign.cases)
    assert payload["per_model"][TABLE_SPECIALIST]["pages_served"] == 1


def test_the_total_is_never_the_sum_of_all_models(campaign: Campaign) -> None:
    payload = _run(campaign, variants.VARIANT_C)
    total = payload["totals"]["total_usd"]
    contrast = payload["all_models_full_run_usd_for_contrast_only"]
    assert total is not None
    assert contrast is not None
    assert total < contrast


def test_routing_to_a_dearer_model_costs_more_than_the_base(campaign: Campaign) -> None:
    base = _run(campaign, variants.VARIANT_A)["totals"]["total_usd"]
    adaptive = _run(campaign, variants.VARIANT_C)["totals"]["total_usd"]
    assert adaptive > base


def test_inference_and_overhead_are_reported_separately(campaign: Campaign) -> None:
    payload = _run(campaign, variants.VARIANT_A)
    entry = payload["per_model"][PRIMARY]
    assert entry["inference_usd"] > 0
    assert entry["overhead_usd"] > 0
    assert entry["subtotal_usd"] == pytest.approx(
        entry["inference_usd"] + entry["overhead_usd"], abs=1e-9
    )
    assert entry["gpu_seconds"] == pytest.approx(len(campaign.cases) * 0.92, abs=1e-6)


def test_a_page_without_a_pod_rate_is_unpriced_not_free(campaign: Campaign) -> None:
    campaign.paths.cost_ledger.unlink()
    payload = _run(campaign, variants.VARIANT_A)
    entry = payload["per_model"][PRIMARY]
    assert entry["priced_pages"] == 0
    assert entry["unpriced_pages"] == len(campaign.cases)
    assert entry["subtotal_usd"] is None
    assert entry["overhead_usd"] is None
    assert entry["overhead_unavailable_reason"]
    assert payload["totals"]["total_usd"] is None
    assert payload["totals"]["usd_per_1000_pages"] is None
    assert payload["totals"]["unpriced_reasons"]


def test_a_subscription_page_is_priced_at_its_api_equivalent_never_zero(
    campaign_with_opus: Campaign,
) -> None:
    campaign = campaign_with_opus
    signals.build_signals(campaign.paths)
    params = PolicyParams().with_threshold("escalation_fraction_cap", 0.5)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_D, params=params)
    replay.replay_variant(campaign.paths, variant=variants.VARIANT_D)
    report = cost.variant_cost(campaign.paths, variant=variants.VARIANT_D)
    payload = json.loads(report.path.read_text(encoding="utf-8"))

    opus = payload["per_model"]["opus5_subscription"]
    assert opus["pages_served"] == 3
    assert opus["basis"] == ["api_equivalent_list_price"]
    assert opus["inference_usd"] == pytest.approx(3 * 0.021, abs=1e-9)
    assert opus["overhead_usd"] is None


def test_recovery_cost_is_null_with_a_reason_until_it_runs(campaign: Campaign) -> None:
    payload = _run(campaign, variants.VARIANT_B)
    assert payload["recovery"]["planned_jobs"] == 0
    assert payload["recovery"]["usd"] is None
    assert payload["recovery"]["reason"]


def test_recovery_jobs_are_counted_once_planned(campaign: Campaign) -> None:
    _run(campaign, variants.VARIANT_B)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    report = cost.variant_cost(campaign.paths, variant=variants.VARIANT_B)
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert payload["recovery"]["planned_jobs"] == 5
    assert payload["recovery"]["type_counts"]["overlap_tiling"] == 1
    assert payload["recovery"]["usd"] is None


def test_unresolved_pages_are_not_charged(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_C)
    campaign.paths.canonical_path(TEXT_SPECIALIST, "case-truncated").unlink()
    manifest = campaign.paths.frozen_manifest(TEXT_SPECIALIST)
    rows = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line)["case_key"] != "case-truncated"
    ]
    jsonio.write_jsonl_atomic(manifest, rows)
    replay.replay_variant(campaign.paths, variant=variants.VARIANT_C)
    report = cost.variant_cost(campaign.paths, variant=variants.VARIANT_C)
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    served = sum(entry["pages_served"] for entry in payload["per_model"].values())
    assert served == len(campaign.cases) - 1


def test_pricing_requires_the_replay_manifest(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)
    with pytest.raises(MissingInputError):
        cost.variant_cost(campaign.paths, variant=variants.VARIANT_A)
