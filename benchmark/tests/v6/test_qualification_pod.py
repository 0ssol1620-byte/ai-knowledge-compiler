from __future__ import annotations

from decimal import Decimal

import httpx

from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.qualification_pod import (
    QualificationPodSpec,
    RunPodQualificationClient,
)


def _spec() -> QualificationPodSpec:
    return QualificationPodSpec(
        name="folynta-qualification-ovis-20260804",
        image_name="ghcr.io/example/ovis@sha256:" + "a" * 64,
        gpu_type="NVIDIA A40",
        public_key="ssh-ed25519 AAAATEST test",
        allocation_id="qualify-ovis",
        maximum_hourly_rate_usd=Decimal("0.50"),
        maximum_runtime_hours=Decimal("4"),
        vllm_cuda_compatibility=True,
    )


def test_qualification_capacity_is_bounded_and_forbids_public_benchmark() -> None:
    responses = [
        {
            "id": "qualification123",
            "name": "folynta-qualification-ovis-20260804",
            "desiredStatus": "RUNNING",
            "adjustedCostPerHr": 0.44,
        },
        {
            "id": "qualification123",
            "name": "folynta-qualification-ovis-20260804",
            "desiredStatus": "RUNNING",
            "adjustedCostPerHr": 0.44,
            "publicIp": "100.65.0.11",
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
    client = RunPodQualificationClient(api_key="secret", transport=httpx.MockTransport(handler))
    try:
        created = client.create(_spec(), budget=budget)
        ready = client.verify_ready(_spec(), pod_id="qualification123", verified_gpu_name="A40")
    finally:
        client.close()

    assert created["public_benchmark_inference_allowed"] is False
    assert created["reserved_maximum_cost_usd"] == "4.000000"
    assert _spec().provider_payload()["env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "1"
    assert ready["gpu_identity_source"] == "graphql_cross_check"
    assert ready["public_benchmark_inference_allowed"] is False
