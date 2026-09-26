"""``arena.reports.tavonel_data``: variant aggregation and the recovery join."""

from __future__ import annotations

from arena.reports.loaders import ModelRunSource, VariantSource
from arena.reports.tavonel_data import compute_variant_metrics, recovery_report_rows


def _replay_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "case_key": "case-0",
        "chosen_model_key": "paddleocr_vl_1_6",
        "final_model": "paddleocr_vl_1_6",
        "escalation_stage": 0,
        "recovery_required": False,
        "number_of_model_calls": 1,
        "unresolved": False,
    }
    base.update(overrides)
    return base


def _source(
    *,
    decisions: list[dict[str, object]] | None = None,
    replay: list[dict[str, object]] | None = None,
    cost: dict[str, object] | None = None,
) -> VariantSource:
    return VariantSource(
        route_decisions=decisions or [],
        route_frozen=None,
        replay_manifest=replay or [],
        replay_summary=None,
        cost=cost,
    )


def _run(receipts: list[dict[str, object]]) -> ModelRunSource:
    return ModelRunSource(
        receipts=receipts, run_summary=None, run_summary_reason=None, canary_receipt=None
    )


def test_compute_variant_metrics_empty_source_is_na() -> None:
    metrics = compute_variant_metrics("A_base", "A_base", _source())
    assert metrics.total_cases == 0
    assert metrics.escalation_rate.value is None
    assert metrics.cost_total_usd.value is None


def test_compute_variant_metrics_prefers_replay_manifest_over_decisions() -> None:
    rows = [
        _replay_row(case_key="case-0", escalation_stage=1, chosen_model_key="opus5_subscription"),
        _replay_row(case_key="case-1", recovery_required=True),
        _replay_row(case_key="case-2", unresolved=True, chosen_model_key=None),
    ]
    metrics = compute_variant_metrics("C_adaptive", "C_adaptive", _source(replay=rows))

    assert metrics.total_cases == 3
    assert metrics.escalation_rate.value == round(1 / 3, 6)
    assert metrics.recovery_needed_rate.value == round(1 / 3, 6)
    assert metrics.opus_usage_rate.value == round(1 / 3, 6)
    assert metrics.unresolved_rate.value == round(1 / 3, 6)


def test_compute_variant_metrics_falls_back_to_route_decisions_no_unresolved() -> None:
    decisions = [
        {
            "case_key": "case-0",
            "primary": "paddleocr_vl_1_6",
            "decision": "ACCEPT",
            "final_model": "paddleocr_vl_1_6",
            "escalation_stage": 0,
            "recovery_required": False,
            "number_of_model_calls": 1,
        }
    ]
    metrics = compute_variant_metrics("A_base", "A_base", _source(decisions=decisions))
    assert metrics.total_cases == 1
    # unresolved is only knowable from a replay manifest.
    assert metrics.unresolved_rate.value is None
    assert metrics.unresolved_rate.reason is not None


def test_compute_variant_metrics_reads_cost_totals() -> None:
    source = _source(
        replay=[_replay_row()],
        cost={
            "totals": {"total_usd": 1.5, "usd_per_1000_pages": 30.0},
            "all_models_full_run_usd_for_contrast_only": 5.0,
        },
    )
    metrics = compute_variant_metrics("C_adaptive", "C_adaptive", source)
    assert metrics.cost_total_usd.value == 1.5
    assert metrics.cost_per_1000_pages_usd.value == 30.0
    assert metrics.all_models_contrast_usd.value == 5.0
    assert metrics.cost_delta_vs_all_models_usd.value == round(1.5 - 5.0, 6)


def test_compute_variant_metrics_missing_cost_is_na() -> None:
    metrics = compute_variant_metrics("A_base", "A_base", _source(replay=[_replay_row()]))
    assert metrics.cost_total_usd.value is None
    assert metrics.cost_delta_vs_all_models_usd.value is None


def test_compute_variant_metrics_single_primary_model() -> None:
    rows = [_replay_row(case_key="c0", primary_model_key="paddleocr_vl_1_6")]
    metrics = compute_variant_metrics("A_base", "A_base", _source(replay=rows))
    assert metrics.primary_model_key.value == "paddleocr_vl_1_6"


def test_recovery_report_rows_marks_unexecuted_when_no_matching_receipt() -> None:
    plan = [
        {
            "recovery_job_id": "job-1",
            "model_key": "paddleocr_vl_1_6",
            "case_key": "case-0",
            "sample_id": "parsebench:case/0",
            "recovery_type": "higher_dpi",
            "round": 1,
        }
    ]
    rows = recovery_report_rows(plan, {})
    assert len(rows) == 1
    assert rows[0]["executed"] is False
    assert rows[0]["status"] is None
    assert rows[0]["reason"] == "not yet executed (planned only)"


def test_recovery_report_rows_matches_recovery_job_kind_receipt() -> None:
    plan = [
        {
            "recovery_job_id": "job-1",
            "model_key": "paddleocr_vl_1_6",
            "case_key": "case-0",
            "sample_id": "parsebench:case/0",
            "recovery_type": "higher_dpi",
            "round": 1,
        }
    ]
    runs = {
        "paddleocr_vl_1_6": _run(
            [
                {
                    "job_kind": "recovery",
                    "case_key": "case-0",
                    "status": "SUCCESS",
                    "error_class": None,
                },
                {
                    "job_kind": "inference",
                    "case_key": "case-0",
                    "status": "SUCCESS",
                    "error_class": None,
                },
            ]
        )
    }
    rows = recovery_report_rows(plan, runs)
    assert rows[0]["executed"] is True
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["reason"] is None


def test_recovery_report_rows_empty_plan_is_empty() -> None:
    assert recovery_report_rows([], {}) == []
