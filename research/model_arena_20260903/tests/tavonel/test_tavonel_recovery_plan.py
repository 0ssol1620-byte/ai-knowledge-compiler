"""Recovery plan rows: contract 3.6 shape, stable ids, nothing executed."""

from __future__ import annotations

import json

import pytest
from arena.tavonel import freeze, jsonio, recovery_plan, signals, variants
from arena.tavonel.errors import MissingInputError
from arena.tavonel.policies import RECOVERY_TYPES
from conftest import PRIMARY, Campaign

REQUIRED_FIELDS = {
    "schema",
    "recovery_job_id",
    "base_inference_job_id",
    "case_key",
    "sample_id",
    "model_key",
    "recovery_type",
    "recovery_config",
    "recovery_config_sha256",
    "round",
    "trigger_signals",
    "planned_before_gt",
}


def _plan(campaign: Campaign, variant: str = variants.VARIANT_B) -> list[dict]:
    return [
        json.loads(line)
        for line in campaign.paths.variant_recovery_plan(variant)
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def _prepare(campaign: Campaign, variant: str = variants.VARIANT_B) -> None:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variant)


def test_rows_carry_exactly_the_contract_fields(campaign: Campaign) -> None:
    _prepare(campaign)
    report = recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    rows = _plan(campaign)
    assert rows and len(rows) == report.row_count
    for row in rows:
        assert set(row) == REQUIRED_FIELDS
        assert row["planned_before_gt"] is True
        assert row["recovery_type"] in RECOVERY_TYPES
        assert row["model_key"] == PRIMARY
        assert row["round"] == 1
        assert row["trigger_signals"]


def test_the_config_hash_matches_the_config_it_ships(campaign: Campaign) -> None:
    _prepare(campaign)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    for row in _plan(campaign):
        assert row["recovery_config_sha256"] == jsonio.prefixed(
            jsonio.json_sha256_hex(row["recovery_config"])
        )
        assert row["recovery_config"]["calibrated"] is False


def test_the_job_id_is_derived_from_the_run_it_recovers(campaign: Campaign) -> None:
    _prepare(campaign)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    for row in _plan(campaign):
        assert row["recovery_job_id"] == jsonio.json_sha256_hex(
            {
                "campaign_id": json.loads(
                    campaign.paths.receipt_path(PRIMARY, row["case_key"]).read_text(
                        encoding="utf-8"
                    )
                )["campaign_id"],
                "inference_job_id_of_base": row["base_inference_job_id"],
                "recovery_config_sha256": row["recovery_config_sha256"],
                "recovery_type": row["recovery_type"],
                "round": row["round"],
            }
        )


def test_replanning_is_stable_and_a_new_round_makes_new_ids(campaign: Campaign) -> None:
    _prepare(campaign)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    first = {row["recovery_job_id"] for row in _plan(campaign)}
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    assert {row["recovery_job_id"] for row in _plan(campaign)} == first
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B, round_number=2)
    second = {row["recovery_job_id"] for row in _plan(campaign)}
    assert second.isdisjoint(first)


def test_each_page_gets_the_recovery_its_signals_justify(campaign: Campaign) -> None:
    _prepare(campaign)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
    by_case: dict[str, set[str]] = {}
    for row in _plan(campaign):
        by_case.setdefault(row["case_key"], set()).add(row["recovery_type"])
    assert by_case["case-empty"] == {"alternative_prompt", "higher_dpi"}
    assert by_case["case-truncated"] == {"overlap_tiling"}
    assert by_case["case-repetition"] == {"safer_config"}
    assert by_case["case-table"] == {"crop"}
    assert "case-clean" not in by_case


def test_variant_a_plans_no_recovery_at_all(campaign: Campaign) -> None:
    _prepare(campaign, variants.VARIANT_A)
    report = recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_A)
    assert report.row_count == 0
    assert _plan(campaign, variants.VARIANT_A) == []


def test_the_merged_plan_is_the_deduplicated_union(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_A)
    freeze.freeze_routes(campaign.paths, variant=variants.VARIANT_B)
    recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_A)
    report = recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)

    merged = [
        json.loads(line)
        for line in campaign.paths.recovery_plan.read_text(encoding="utf-8").splitlines()
        if line
    ]
    ids = [row["recovery_job_id"] for row in merged]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids)) == report.merged_row_count == report.row_count


def test_a_run_without_an_inference_job_id_cannot_be_recovered(campaign: Campaign) -> None:
    _prepare(campaign)
    for case_key in campaign.cases:
        receipt_path = campaign.paths.receipt_path(PRIMARY, case_key)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        del receipt["inference_job_id"]
        jsonio.write_json_atomic(receipt_path, receipt)
        signals_path = campaign.paths.signals_path(PRIMARY, case_key)
        record = json.loads(signals_path.read_text(encoding="utf-8"))
        record["run"]["inference_job_id"] = None
        jsonio.write_json_atomic(signals_path, record)

    with pytest.raises(MissingInputError):
        recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)


def test_planning_requires_a_frozen_route_set(campaign: Campaign) -> None:
    signals.build_signals(campaign.paths)
    with pytest.raises(MissingInputError):
        recovery_plan.plan_recovery(campaign.paths, variant=variants.VARIANT_B)
