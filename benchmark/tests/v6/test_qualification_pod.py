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
            "ports": ["8001/http"],
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
    payload = _spec().provider_payload()
    assert payload["volumeInGb"] == 0
    assert payload["ports"] == ["8001/http"]
    assert "PUBLIC_KEY" not in payload["env"]
    assert payload["env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] == "1"
    assert ready["gpu_identity_source"] == "graphql_cross_check"
    assert ready["evidence_access"] == "runpod_http_proxy"
    assert ready["evidence_port"] == 8001
    assert ready["evidence_url"] == "https://qualification123-8001.proxy.runpod.net"
    assert ready["ssh_required"] is False
    assert ready["public_benchmark_inference_allowed"] is False


def test_qualification_can_opt_into_ssh_without_making_it_a_runtime_dependency() -> None:
    spec = QualificationPodSpec(
        name="folynta-qualification-ssh-compat",
        image_name="ghcr.io/example/ovis@sha256:" + "b" * 64,
        gpu_type="NVIDIA A40",
        allocation_id="qualify-ovis-ssh-compat",
        maximum_hourly_rate_usd=Decimal("0.50"),
        maximum_runtime_hours=Decimal("1"),
        public_key="ssh-ed25519 AAAATEST test",
    )
    payload = spec.provider_payload()
    assert payload["ports"] == ["8001/http", "22/tcp"]
    assert payload["env"]["PUBLIC_KEY"] == "ssh-ed25519 AAAATEST test"
    assert spec.redacted_identity()["env"]["PUBLIC_KEY"] == "redacted"
