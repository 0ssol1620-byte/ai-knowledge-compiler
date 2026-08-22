from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.builder_pod import (
    BuilderPodError,
    BuilderPodSpec,
    RunPodBuilderClient,
)


def _spec() -> BuilderPodSpec:
    return BuilderPodSpec(
        name="folynta-builder-ovis-20260804",
        image_name="vllm/vllm-openai@sha256:" + "a" * 64,
        gpu_type="NVIDIA A40",
        public_key="ssh-ed25519 AAAATEST test",
        allocation_id="builder-ovis-20260804",
        maximum_hourly_rate_usd=Decimal("0.50"),
        maximum_runtime_hours=Decimal("8"),
    )


def test_budget_reserves_worst_case_before_dispatch_and_never_exceeds_cap() -> None:
    budget = AuthorizedSpendBudget(campaign_id="campaign", hard_cap_usd="400")
    reservation = budget.reserve(allocation_id="builder", maximum_cost_usd="4")
    assert reservation.maximum_cost_usd == Decimal("4.000000")
    assert budget.report()["remaining_usd"] == "396.000000"
    with pytest.raises(ContractError, match="hard cap"):
        budget.reserve(allocation_id="overflow", maximum_cost_usd="397")
    budget.settle(allocation_id="builder", actual_cost_usd="1.23")
    assert budget.report()["settled_usd"] == "1.230000"


def test_budget_rejects_duplicate_and_over_reservation_settlement() -> None:
    budget = AuthorizedSpendBudget(campaign_id="campaign", hard_cap_usd="5")
    budget.reserve(allocation_id="one", maximum_cost_usd="2")
    with pytest.raises(ContractError, match="unique"):
        budget.reserve(allocation_id="one", maximum_cost_usd="1")
    with pytest.raises(ContractError, match="exceeded its authorized reservation"):
        budget.settle(allocation_id="one", actual_cost_usd="2.01")


def test_builder_spec_is_explicitly_not_a_qualified_runtime() -> None:
    spec = _spec()
    identity = spec.redacted_identity()
    assert identity["runtimeQualificationEligible"] is False
    assert identity["maximumCostUsd"] == "8.00"
    assert identity["env"]["PUBLIC_KEY"] == "redacted"
    assert "buildah" in spec.provider_payload()["dockerStartCmd"][0]
    assert "RUNPOD" not in json.dumps(spec.provider_payload())


def test_builder_create_consumes_reservation_and_checks_live_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(
            201,
            headers={"content-type": "application/json"},
            json={
                "id": "builder123",
                "name": "folynta-builder-ovis-20260804",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.44,
                "gpu": {"displayName": "A40"},
            },
        )

    budget = AuthorizedSpendBudget(campaign_id="campaign", hard_cap_usd="400")
    client = RunPodBuilderClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        receipt = client.create(_spec(), budget=budget)
    finally:
        client.close()
    assert receipt["hourly_rate_usd"] == "0.44"
    assert receipt["reserved_maximum_cost_usd"] == "8.000000"
    assert receipt["runtime_qualification_eligible"] is False
    assert receipt["gpu_verified_at_creation"] is True
    assert budget.reserved_usd == Decimal("8.000000")


def test_builder_price_drift_is_deleted_and_rejected() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(
            201,
            headers={"content-type": "application/json"},
            json={
                "id": "builder123",
                "name": "folynta-builder-ovis-20260804",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.51,
                "gpu": {"displayName": "A40"},
            },
        )

    budget = AuthorizedSpendBudget(campaign_id="campaign", hard_cap_usd="400")
    client = RunPodBuilderClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BuilderPodError, match="exceeds authorization"):
            client.create(_spec(), budget=budget)
    finally:
        client.close()
    assert methods == ["POST", "DELETE"]


def test_builder_allows_provisioning_response_then_requires_ready_identity() -> None:
    responses = [
        {
            "id": "builder123",
            "name": "folynta-builder-ovis-20260804",
            "desiredStatus": "RUNNING",
            "adjustedCostPerHr": 0.44,
            "gpu": None,
        },
        {
            "id": "builder123",
            "name": "folynta-builder-ovis-20260804",
            "desiredStatus": "RUNNING",
            "adjustedCostPerHr": 0.44,
            "machine": {"gpuDisplayName": "A40"},
            "publicIp": "100.65.0.10",
            "portMappings": {"22": 12022},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201 if request.method == "POST" else 200,
            headers={"content-type": "application/json"},
            json=responses.pop(0),
        )

    budget = AuthorizedSpendBudget(campaign_id="campaign", hard_cap_usd="400")
    client = RunPodBuilderClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        created = client.create(_spec(), budget=budget)
        ready = client.verify_ready(_spec(), pod_id="builder123")
    finally:
        client.close()
    assert created["gpu"] is None
    assert created["gpu_verified_at_creation"] is False
    assert ready["gpu"] == "A40"
    assert ready["gpu_identity_source"] == "rest_pod_response"
    assert ready["ssh_port"] == 12022


def test_builder_ready_accepts_independent_graphql_gpu_cross_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "builder123",
                "name": "folynta-builder-ovis-20260804",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.44,
                "publicIp": "100.65.0.10",
                "portMappings": {"22": 12022},
            },
        )

    client = RunPodBuilderClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        ready = client.verify_ready(
            _spec(), pod_id="builder123", verified_gpu_name="A40"
        )
    finally:
        client.close()
    assert ready["gpu"] == "A40"
    assert ready["gpu_identity_source"] == "graphql_cross_check"
