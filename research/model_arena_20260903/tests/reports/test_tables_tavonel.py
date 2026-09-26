"""``arena.reports.tables_tavonel``: routes, ablation, recovery, Opus, disagreement, Pareto."""

from __future__ import annotations

from arena.reports.loaders import CampaignSources, ModelRunSource, ScoreSource, VariantSource
from arena.reports.tables_tavonel import (
    build_model_disagreement,
    build_opus_subscription_report,
    build_pareto_frontier,
    build_recovery_report,
    build_tavonel_ablation,
    build_tavonel_routes,
)
from arena.reports.variant_ids import VARIANT_IDS, is_oracle


def _sources(**overrides: object) -> CampaignSources:
    base: dict[str, object] = {"root_exists": True}
    base.update(overrides)
    return CampaignSources(**base)  # type: ignore[arg-type]


def _replay_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "case_key": "case-0",
        "chosen_model_key": "paddleocr_vl_1_6",
        "final_model": "paddleocr_vl_1_6",
        "escalation_stage": 0,
        "recovery_required": False,
        "number_of_model_calls": 1,
        "unresolved": False,
    }
    row.update(overrides)
    return row


def test_build_tavonel_routes_covers_every_variant_id() -> None:
    spec = build_tavonel_routes(_sources())
    variants_seen = {row["variant"].value for row in spec.rows}
    assert variants_seen == set(VARIANT_IDS)


def test_build_tavonel_routes_missing_variant_is_na_with_reason() -> None:
    spec = build_tavonel_routes(_sources())
    for row in spec.rows:
        # a variant with no route decisions/replay output gets only a reason
        # cell -- every other column is simply absent, which renders as n/a.
        assert "escalation_pct" not in row
        assert row["reason"].value is None  # na_reason


def test_build_tavonel_routes_computes_rates_from_replay_manifest() -> None:
    variant = "C_adaptive"
    source = VariantSource(
        route_decisions=[],
        route_frozen=None,
        replay_manifest=[
            _replay_row(case_key="c0", escalation_stage=1, chosen_model_key="opus5_subscription"),
            _replay_row(case_key="c1"),
        ],
        replay_summary=None,
        cost={"totals": {"total_usd": 1.0, "usd_per_1000_pages": 500.0}},
    )
    sources = _sources(variants={variant: source})
    spec = build_tavonel_routes(sources)
    row = next(r for r in spec.rows if r["variant"].value == variant)
    assert row["escalation_pct"].value == 0.5
    assert row["opus_usage_pct"].value == 0.5
    assert row["completion"].value == 1.0  # nothing unresolved
    assert row["cost_usd_per_1000_pages"].value == 500.0


def test_build_tavonel_ablation_oracle_row_present_and_labelled() -> None:
    spec = build_tavonel_ablation(_sources())
    oracle_rows = [row for row in spec.rows if row["variant"].value == "E_oracle"]
    assert oracle_rows
    assert is_oracle("E_oracle")


def test_build_tavonel_ablation_quality_delta_needs_both_scores() -> None:
    variant = "A_base"
    source = VariantSource(
        route_decisions=[],
        route_frozen=None,
        replay_manifest=[_replay_row(primary_model_key="paddleocr_vl_1_6")],
        replay_summary=None,
        cost=None,
    )
    sources = _sources(
        variants={variant: source},
        scores={
            ("paddleocr_vl_1_6", "parsebench"): ScoreSource(
                summary={"overall": 0.7}, summary_reason=None, per_case=None, per_case_reason=None
            ),
            (variant, "parsebench"): ScoreSource(
                summary={"overall": 0.9}, summary_reason=None, per_case=None, per_case_reason=None
            ),
        },
    )
    spec = build_tavonel_ablation(sources)
    row = next(
        r
        for r in spec.rows
        if r["variant"].value == variant and r["benchmark"].value == "ParseBench"
    )
    assert row["before_score"].value == 0.7
    assert row["after_score"].value == 0.9
    assert row["quality_delta"].value == round(0.9 - 0.7, 6)


def test_build_recovery_report_empty_is_na() -> None:
    spec = build_recovery_report(_sources())
    assert spec.rows[0]["reason"].value is None


def test_build_recovery_report_passthrough() -> None:
    sources = _sources(
        recovery_plan=[
            {
                "recovery_job_id": "job-1",
                "model_key": "paddleocr_vl_1_6",
                "case_key": "case-0",
                "sample_id": "s0",
                "recovery_type": "higher_dpi",
                "round": 1,
            }
        ]
    )
    spec = build_recovery_report(sources)
    assert spec.rows[0]["recovery_job_id"].value == "job-1"
    assert spec.rows[0]["executed"].value is False


def test_build_opus_subscription_report_never_zero_per_page() -> None:
    sources = _sources(
        opus_receipts=[
            {
                "schema": "tavonel.arena.opus-canary-receipt.v1",
                "counts": {"attempted": 10, "success": 10, "failed": 0},
                "api_equivalent_list_price_usd_total": 0.5,
                "subscription_included_usage": True,
                "actual_marginal_api_cost": "N/A",
            }
        ]
    )
    spec = build_opus_subscription_report(sources)
    row = spec.rows[0]
    assert row["api_equivalent_list_price_usd_total"].value == 0.5
    assert row["api_equivalent_list_price_usd_per_page"].value == 0.05
    assert row["api_equivalent_list_price_usd_total"].value != 0
    assert row["subscription_included_usage"].value is True


def test_build_opus_subscription_report_missing_is_na() -> None:
    spec = build_opus_subscription_report(_sources())
    assert spec.rows[0]["reason"].value is None


def test_build_model_disagreement_passthrough() -> None:
    sources = _sources(
        disagreement_pairs=[
            {
                "model_a": "a",
                "model_b": "b",
                "case_key": "c0",
                "sample_id": "s0",
                "benchmark": "parsebench",
                "metrics": {"text_similarity": 0.9, "one_empty_one_nonempty": False},
            }
        ]
    )
    spec = build_model_disagreement(sources)
    assert spec.rows[0]["text_similarity"].value == 0.9


def test_build_model_disagreement_empty_is_na() -> None:
    spec = build_model_disagreement(_sources())
    assert spec.rows[0]["reason"].value is None


def test_build_pareto_frontier_one_frontier_per_benchmark_and_correct_dominance() -> None:
    sources = _sources(
        scores={
            ("model_a", "parsebench"): ScoreSource(
                summary={"overall": 0.9}, summary_reason=None, per_case=None, per_case_reason=None
            ),
            ("model_b", "parsebench"): ScoreSource(
                summary={"overall": 0.5}, summary_reason=None, per_case=None, per_case_reason=None
            ),
        },
        runs={
            "model_a": ModelRunSource(
                receipts=[{"status": "SUCCESS", "api_equivalent_list_price_usd": 0.01}],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            ),
            "model_b": ModelRunSource(
                receipts=[{"status": "SUCCESS", "api_equivalent_list_price_usd": 0.02}],
                run_summary=None,
                run_summary_reason=None,
                canary_receipt=None,
            ),
        },
    )
    benchmarks = ("parsebench", "omnidoc", "olmocr")
    spec = build_pareto_frontier(sources, ("model_a", "model_b"), benchmarks)
    parsebench_rows = {
        row["system"].value: row for row in spec.rows if row["benchmark"].value == "ParseBench"
    }
    assert parsebench_rows["model_a"]["pareto_non_dominated"].value is True
    assert parsebench_rows["model_b"]["pareto_non_dominated"].value is False
    # the other two benchmarks have no scored model at all -> both skipped, na
    omnidoc_rows = [row for row in spec.rows if row["benchmark"].value == "OmniDoc"]
    assert all(row["x_value"].value is None for row in omnidoc_rows)


def test_build_pareto_frontier_skips_models_with_no_quality_or_cost() -> None:
    spec = build_pareto_frontier(_sources(), ("model_a",), ("parsebench",))
    row = spec.rows[0]
    assert row["system"].value == "model_a"
    assert row["pareto_non_dominated"].value is None
    assert row["reason"].value is not None
