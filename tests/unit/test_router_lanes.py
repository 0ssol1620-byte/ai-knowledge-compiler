"""WP-R5: the ten execution lanes, the tenant boundary, and the portfolio."""

from __future__ import annotations

import json

import pytest
from akc_router import EXTERNAL_ROUTES, ExecutionLane, Route
from akc_router.data_policy import SENDS_TENANT_CONTENT_OFFSITE
from akc_router.portfolio import (
    EXTERNAL_LANES,
    NON_MODEL_LANES,
    REQUIRED_EVIDENCE,
    ModelEvidence,
    Qualification,
    UnboundLaneError,
    build_portfolio,
    container_digest,
    evidence_from_runtime_manifest,
    portfolio_revision,
)
from akc_router.speculation import INITIAL_SPECULATION_POLICY

# A real Arena runtime manifest shape, trimmed. Values are the ones actually
# recorded for `ovisocr2` in research/model_arena_20260903/runtimes/, so the
# WP-R4 assertion below is about the real evidence gap and not a toy.
_OVIS_MANIFEST: dict[str, object] = {
    "model_key": "ovisocr2",
    "model_repo": "ATH-MaaS/OvisOCR2",
    "model_revision": "1fc9221b7823a371d6e97f92d527cc847e24e107",
    "official_runtime": "vllm",
    "runtime_version": "0.22.1",
    "base_image": (
        "docker.io/vllm/vllm-openai@sha256:"
        "e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05"
    ),
    "gpu_min_vram_gb": 24,
    "gpu_count_min": 1,
    "license": {
        "id": "Apache-2.0",
        "url": "https://huggingface.co/ATH-MaaS/OvisOCR2",
        "status": "approved",
    },
    "prompt_id": "ovisocr2_page_markdown_v1",
    "inference_config": {"max_tokens": 8192, "temperature": 0.0},
}


# --- lanes -------------------------------------------------------------------


def test_the_ten_program_roles_exist() -> None:
    assert {lane.value for lane in ExecutionLane} == {
        "native",
        "authority",
        "fast_visual",
        "peer_visual",
        "table_specialist",
        "formula_specialist",
        "chart_specialist",
        "degraded_scan_specialist",
        "external_adjudicator",
        "human_review",
    }


def test_the_speculation_table_uses_the_split_specialists() -> None:
    lanes = {
        lane
        for policy in INITIAL_SPECULATION_POLICY.values()
        for lane in policy.primary_lanes + policy.peer_lanes
    }
    assert ExecutionLane.CHART_SPECIALIST in lanes
    assert ExecutionLane.DEGRADED_SCAN_SPECIALIST in lanes
    # No always-all row: no §21 row sends a page to more than four lanes.
    for policy in INITIAL_SPECULATION_POLICY.values():
        assert len(policy.primary_lanes) + len(policy.peer_lanes) <= 4


def test_every_route_is_classified_for_the_tenant_boundary() -> None:
    """A new route cannot be added without deciding whether it egresses."""
    assert set(SENDS_TENANT_CONTENT_OFFSITE) == set(Route)


def test_external_routes_is_exactly_the_offsite_set() -> None:
    assert {
        route for route, offsite in SENDS_TENANT_CONTENT_OFFSITE.items() if offsite
    } == EXTERNAL_ROUTES
    assert Route.MISTRAL_FALLBACK in EXTERNAL_ROUTES
    # Pulling a public filing in is not sending tenant content out.
    assert Route.AUTHORITY_RECONSTRUCTION not in EXTERNAL_ROUTES


def test_an_external_lane_binds_only_an_external_route() -> None:
    portfolio = build_portfolio(
        {
            ExecutionLane.EXTERNAL_ADJUDICATOR: (Route.MISTRAL_FALLBACK, "adjudicator"),
            ExecutionLane.FAST_VISUAL: (Route.PADDLE_FAST, "paddle"),
        },
        {},
    )
    for binding in portfolio.bindings:
        offsite = binding.route in EXTERNAL_ROUTES
        assert offsite == (binding.lane in EXTERNAL_LANES)


# --- portfolio ---------------------------------------------------------------


def test_container_digest_rejects_a_tag() -> None:
    assert container_digest("vllm/vllm-openai:v0.19.0") is None
    assert container_digest(None) is None
    assert container_digest("repo@sha256:" + "z" * 64) is None
    assert container_digest("repo@sha256:" + "a" * 64) == "sha256:" + "a" * 64


def test_ovis_stays_candidate_until_the_measured_evidence_is_bound() -> None:
    """WP-R4. Everything the manifest holds is bound; the rest is missing."""
    evidence = evidence_from_runtime_manifest(_OVIS_MANIFEST)
    assert evidence.qualification is Qualification.CANDIDATE
    assert evidence.container_digest_observed == (
        "sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05"
    )
    assert evidence.weights_revision == "1fc9221b7823a371d6e97f92d527cc847e24e107"
    assert evidence.gpu_min_vram_gb == 24
    assert evidence.inference_args_sha256 is not None
    assert set(evidence.missing_evidence) == {
        "warm_latency_seconds",
        "cold_start_seconds",
        "throughput_pages_per_gpu_hour",
        "failure_modes",
        "page_class_evidence",
        "data_policy",
    }


def test_complete_evidence_qualifies() -> None:
    evidence = evidence_from_runtime_manifest(
        _OVIS_MANIFEST,
        warm_latency_seconds=3.1,
        cold_start_seconds=91.0,
        throughput_pages_per_gpu_hour=940.0,
        failure_modes=("tensor_shape_error_at_concurrency_3",),
        page_class_evidence=("old_scans",),
        data_policy="in_tenant_gpu_only",
    )
    assert evidence.missing_evidence == ()
    assert evidence.qualification is Qualification.QUALIFIED


def test_an_unapproved_licence_is_excluded_not_candidate() -> None:
    manifest = {**_OVIS_MANIFEST, "license": {"id": "Unknown", "status": "pending"}}
    assert evidence_from_runtime_manifest(manifest).qualification is Qualification.EXCLUDED


def test_a_founder_exclusion_beats_complete_evidence() -> None:
    evidence = evidence_from_runtime_manifest(
        _OVIS_MANIFEST,
        warm_latency_seconds=1.0,
        cold_start_seconds=1.0,
        throughput_pages_per_gpu_hour=1.0,
        failure_modes=("none_observed",),
        page_class_evidence=("tables",),
        data_policy="in_tenant_gpu_only",
        founder_excluded=True,
        exclusion_reason="founder decision 2026-09-03",
    )
    assert evidence.qualification is Qualification.EXCLUDED


def test_a_lane_with_no_evidence_is_candidate_and_refuses_to_route() -> None:
    portfolio = build_portfolio(
        {ExecutionLane.TABLE_SPECIALIST: (Route.PADDLE_VL, "never_measured")}, {}
    )
    binding = portfolio.binding(ExecutionLane.TABLE_SPECIALIST)
    assert binding is not None
    assert binding.qualification is Qualification.CANDIDATE
    assert binding.missing_evidence == REQUIRED_EVIDENCE
    with pytest.raises(UnboundLaneError):
        portfolio.route_for(ExecutionLane.TABLE_SPECIALIST)
    # And it can still be read deliberately, for a shadow run.
    assert portfolio.route_for(ExecutionLane.TABLE_SPECIALIST, promotable_only=False) is (
        Route.PADDLE_VL
    )


def test_an_unbound_lane_raises_rather_than_defaulting() -> None:
    portfolio = build_portfolio({}, {})
    with pytest.raises(UnboundLaneError):
        portfolio.route_for(ExecutionLane.CHART_SPECIALIST)


def test_lanes_served_without_a_model_qualify() -> None:
    portfolio = build_portfolio(
        {
            ExecutionLane.NATIVE: (Route.NATIVE, None),
            ExecutionLane.HUMAN_REVIEW: (Route.REGION_RECOVERY, None),
        },
        {},
    )
    assert {ExecutionLane.NATIVE, ExecutionLane.HUMAN_REVIEW} == NON_MODEL_LANES
    assert portfolio.promotable_lanes == NON_MODEL_LANES
    assert portfolio.route_for(ExecutionLane.NATIVE) is Route.NATIVE


def test_the_revision_moves_when_a_binding_changes() -> None:
    qualified = evidence_from_runtime_manifest(
        _OVIS_MANIFEST,
        warm_latency_seconds=3.1,
        cold_start_seconds=91.0,
        throughput_pages_per_gpu_hour=940.0,
        failure_modes=("none",),
        page_class_evidence=("old_scans",),
        data_policy="in_tenant_gpu_only",
    )
    proposals = {ExecutionLane.PEER_VISUAL: (Route.PADDLE_VL, "ovisocr2")}
    unqualified = build_portfolio(proposals, {"ovisocr2": ModelEvidence(model_key="ovisocr2")})
    promoted = build_portfolio(proposals, {"ovisocr2": qualified})
    assert unqualified.revision != promoted.revision
    assert promoted.revision == portfolio_revision(promoted.bindings)
    assert unqualified.revision.startswith("portfolio_")


def test_a_model_key_is_never_read_as_a_capability() -> None:
    """ "table" in a model key proves nothing; only receipts qualify it."""
    named = ModelEvidence(model_key="best_table_reader_ocr_pro")
    assert named.qualification is Qualification.EXCLUDED
    assert "licence_status" in named.missing_evidence


def test_evidence_from_an_empty_manifest_claims_nothing() -> None:
    evidence = evidence_from_runtime_manifest({"model_key": "empty"})
    assert evidence.container_digest_observed is None
    assert evidence.inference_args_sha256 is None
    assert set(evidence.missing_evidence) >= set(REQUIRED_EVIDENCE) - {"licence_status"}
    assert json.dumps(evidence.missing_evidence)  # serialisable for a report
