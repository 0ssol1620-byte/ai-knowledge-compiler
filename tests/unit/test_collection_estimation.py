from __future__ import annotations

import pytest
from akc_router import (
    CollectionEstimateInput,
    DimensionUnit,
    GpuClass,
    GpuThermalState,
    PreflightObservation,
    Route,
    RoutePopulation,
    StaticDocumentFeatures,
    build_cluster_identity,
    build_zero_authority_learned_router_shadow,
    calibrate_estimate,
    estimate_collection,
    select_adaptive_samples,
)


def observation(page: int, difficulty: float, **overrides: object) -> PreflightObservation:
    values: dict[str, object] = {
        "page_id": f"page-{page}",
        "cluster_id": "cluster-a",
        "page_index0": page,
        "difficulty": difficulty,
        "native_quality": max(0.0, 1.0 - difficulty / 100),
        "table_density": 0.0,
        "image_density": 0.1,
        "numeric_density": 0.0,
        "width": 1000,
        "height": 1400,
    }
    values.update(overrides)
    return PreflightObservation.model_validate(values)


def test_adaptive_sampling_is_cluster_bound_and_selects_outliers() -> None:
    plans = select_adaptive_samples(
        [
            observation(0, 10),
            observation(1, 12),
            observation(2, 15, table_density=0.9),
            observation(3, 85, numeric_density=0.9),
            observation(4, 90, image_density=0.95),
        ]
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan.population == 5
    assert plan.expansion_limit in {5, 10, 20}
    assert "page-2" in plan.selected_page_ids
    assert "page-3" in plan.selected_page_ids or "page-4" in plan.selected_page_ids


def test_sampling_rejects_page_identity_reuse_across_clusters() -> None:
    duplicate = observation(0, 10)
    with pytest.raises(ValueError, match="globally unique"):
        select_adaptive_samples(
            [
                duplicate,
                duplicate.model_copy(update={"cluster_id": "cluster-b"}),
            ]
        )


def test_quantile_estimate_excludes_duplicates_and_reserves_above_p95() -> None:
    estimate = estimate_collection(
        CollectionEstimateInput(
            route_populations=(
                RoutePopulation(
                    route=Route.NATIVE,
                    pages=70,
                    sampled_pages=3,
                    recovery_probability=0.01,
                ),
                RoutePopulation(
                    route=Route.PADDLE_VL,
                    pages=30,
                    sampled_pages=5,
                    sample_runtime_seconds_p50=1.5,
                    sample_runtime_seconds_p95=4.0,
                    recovery_probability=0.1,
                ),
            ),
            duplicate_pages=10,
            knowledge_note_count=25,
            entity_relation_candidates=40,
            export_profile_count=3,
            queue_delay_p50_seconds=5,
            queue_delay_p95_seconds=20,
            gpu_state=GpuThermalState.COLD,
            gpu_class=GpuClass.L4,
            max_parallel_pages=8,
        )
    )
    assert estimate.billable_pages == 90
    assert estimate.credit_p50 < estimate.credit_p95 < estimate.reserve_ceiling
    assert estimate.duration_p50_seconds < estimate.duration_p95_seconds
    assert sum(estimate.route_mix.values()) == pytest.approx(1.0)
    assert estimate.route_mix[Route.PADDLE_VL.value] == pytest.approx(1 / 3)


def test_unresolved_and_quarantined_pages_are_unbillable() -> None:
    estimate = estimate_collection(
        CollectionEstimateInput(
            route_populations=(
                RoutePopulation(route=Route.NATIVE, pages=7, sampled_pages=3),
                RoutePopulation(route=Route.UNRESOLVED, pages=2, sampled_pages=2),
                RoutePopulation(route=Route.QUARANTINE, pages=1),
            ),
        )
    )
    assert estimate.billable_pages == 7
    assert estimate.unbillable_pages == 3
    assert Route.UNRESOLVED.value not in estimate.route_mix
    assert Route.QUARANTINE.value not in estimate.route_mix


def test_region_and_authority_recovery_are_estimated_as_billable_work() -> None:
    estimate = estimate_collection(
        CollectionEstimateInput(
            route_populations=(
                RoutePopulation(route=Route.REGION_RECOVERY, pages=2, sampled_pages=2),
                RoutePopulation(
                    route=Route.AUTHORITY_RECONSTRUCTION,
                    pages=1,
                    sampled_pages=1,
                ),
            ),
        )
    )
    assert estimate.billable_pages == 3
    assert estimate.credit_p50 > 0
    assert estimate.duration_p50_seconds > 0
    assert estimate.route_mix == {
        Route.AUTHORITY_RECONSTRUCTION.value: pytest.approx(1 / 3),
        Route.REGION_RECOVERY.value: pytest.approx(2 / 3),
    }


def test_static_cluster_identity_covers_all_template_signals_without_raw_path() -> None:
    features = StaticDocumentFeatures(
        file_type="application/pdf",
        page_count=100,
        native_text_presence=0.75,
        producer="Acme PDF",
        font_profile="fonts-v1",
        image_coverage=0.2,
        page_width=2480,
        page_height=3508,
        dimension_unit=DimensionUnit.PIXELS,
        resolution_dpi=300,
        table_line_candidates=14,
        column_count=2,
        numeric_density=0.45,
        language_script="Kore+Latn",
        layout_fingerprint="layout-v1",
        document_style_signature="style-v1",
        theme_master_signature="theme-v1",
        scan_device_signature="scanner-v1",
        folder_context_hash="a" * 64,
    )
    identity = build_cluster_identity(features)
    assert identity.startswith("cluster_")
    assert len(identity) == len("cluster_") + 64
    assert build_cluster_identity(features) == identity
    assert build_cluster_identity(
        features.model_copy(update={"layout_fingerprint": "layout-v2"})
    ) != identity
    assert build_cluster_identity(
        features.model_copy(update={"document_style_signature": "style-v2"})
    ) != identity


def test_sampling_receipt_names_every_measured_representative_and_outlier_role() -> None:
    rows = [observation(index, float(index * 7 + 10)) for index in range(8)]
    rows[1] = rows[1].model_copy(update={"table_density": 0.99})
    rows[2] = rows[2].model_copy(update={"image_density": 0.98})
    rows[3] = rows[3].model_copy(update={"numeric_density": 0.97})
    rows[4] = rows[4].model_copy(update={"native_quality": 0.01})
    rows[5] = rows[5].model_copy(update={"width": 5000, "height": 500})

    plan = select_adaptive_samples(rows)[0]

    reasons = {
        reason for page_reasons in plan.selection_reasons.values() for reason in page_reasons
    }
    assert {
        "MEDIAN_DIFFICULTY",
        "FIRST_PAGE",
        "LAST_PAGE",
        "HIGHEST_TABLE",
        "HIGHEST_IMAGE",
        "HIGHEST_NUMERIC",
        "LOWEST_NATIVE_QUALITY",
        "UNUSUAL_DIMENSION",
    } <= reasons
    assert plan.expansion_limit == 10


def test_predictor_consumes_stored_candidate_export_queue_gpu_and_probe_inputs() -> None:
    population = (RoutePopulation(route=Route.PADDLE_VL, pages=20, sampled_pages=5),)
    baseline = estimate_collection(CollectionEstimateInput(route_populations=population))
    enriched = estimate_collection(
        CollectionEstimateInput(
            route_populations=population,
            knowledge_note_count=9,
            entity_relation_candidates=14,
            export_profile_count=4,
            queue_delay_p50_seconds=7,
            queue_delay_p95_seconds=22,
            gpu_state=GpuThermalState.COLD,
            gpu_class=GpuClass.CPU_ONLY,
            sample_output_tokens=3_000,
            evidence_revision="test-evidence-v1",
            evidence_sha256="b" * 64,
            measured_signal_fields=(
                "knowledge_note_count",
                "entity_relation_candidates",
                "sample_output_tokens",
            ),
        )
    )
    assert enriched.credit_p50 > baseline.credit_p50
    assert enriched.duration_p50_seconds > baseline.duration_p50_seconds
    assert enriched.evidence_sha256 == "b" * 64
    assert enriched.measured_signal_fields == (
        "knowledge_note_count",
        "entity_relation_candidates",
        "sample_output_tokens",
    )


def test_learned_router_shadow_is_structurally_zero_authority() -> None:
    shadow = build_zero_authority_learned_router_shadow(
        champion_revision="rules-v1",
        challenger_revision="learned-v1",
        evidence_sha256="c" * 64,
        champion_route_mix={Route.NATIVE.value: 1.0},
        challenger_route_mix={Route.PADDLE_FAST.value: 1.0},
        calibration_observations=1_000,
    )
    assert shadow.authority == "zero"
    assert shadow.production_route_source == "deterministic_fallback"
    assert shadow.promotion_eligible is False
    assert shadow.calibration_status == "eligible_for_review"
    assert "ZERO_AUTHORITY" in shadow.reason_codes


def test_calibration_reports_coverage_without_mutating_the_estimate() -> None:
    estimate = estimate_collection(
        CollectionEstimateInput(
            route_populations=(RoutePopulation(route=Route.NATIVE, pages=10, sampled_pages=3),)
        )
    )
    calibration = calibrate_estimate(
        estimate,
        actual_credits=estimate.credit_p50,
        actual_duration_seconds=estimate.duration_p95_seconds + 1,
    )
    assert calibration.estimate_error_ratio == 0
    assert calibration.p95_credit_covered
    assert not calibration.p95_duration_covered
