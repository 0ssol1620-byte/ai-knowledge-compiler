"""Bounded, qualification-only RunPod capacity for a newly baked image.

This is the sole exception to the normal READY-image admission rule.  A Pod
created here may run identity and deterministic smoke checks, but it cannot run
public benchmark inference or produce a promotion claim.  Successful evidence
must be converted to ``BakedRuntimeQualification`` before normal capacity is
created.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from ipaddress import IPv4Address
from typing import Any, Final

import httpx

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget

PODS_BASE_URL: Final = "https://rest.runpod.io/v1"
_IMAGE_DIGEST = re.compile(r"^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_POD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
_GPU_ALIASES: Final = {
    "NVIDIA A40": frozenset({"NVIDIA A40", "A40"}),
    "NVIDIA RTX A6000": frozenset({"NVIDIA RTX A6000", "RTX A6000"}),
    "NVIDIA L40S": frozenset({"NVIDIA L40S", "L40S"}),
    "NVIDIA GeForce RTX 4090": frozenset(
        {"NVIDIA GeForce RTX 4090", "GeForce RTX 4090", "RTX 4090"}
    ),
}


class QualificationPodError(RuntimeError):
    """Qualification-only provider error with response bodies withheld."""


@dataclass(frozen=True, slots=True)
class QualificationPodSpec:
    name: str
    image_name: str
    gpu_type: str
    public_key: str
    allocation_id: str
    maximum_hourly_rate_usd: Decimal
    maximum_runtime_hours: Decimal
    non_compute_contingency_usd: Decimal = Decimal("2")
    container_disk_gb: int = 80
    volume_gb: int = 20
    allowed_cuda_versions: tuple[str, ...] = ("12.8", "12.9")
    vllm_cuda_compatibility: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"folynta-qualification-[a-z0-9-]{3,45}", self.name):
            raise ContractError("qualification Pod name is invalid")
        if not _IMAGE_DIGEST.fullmatch(self.image_name):
            raise ContractError("qualification image must be an immutable GHCR digest")
        if self.gpu_type not in _GPU_ALIASES:
            raise ContractError("qualification GPU type is unsupported")
        if not self.public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
            raise ContractError("qualification public key is invalid")
        if not self.allocation_id.strip():
            raise ContractError("qualification allocation_id is required")
        if not 40 <= self.container_disk_gb <= 200:
            raise ContractError("qualification container disk is out of bounds")
        if not 0 <= self.volume_gb <= 100:
            raise ContractError("qualification volume is out of bounds")
        if self.maximum_hourly_rate_usd <= 0 or self.maximum_hourly_rate_usd > 5:
            raise ContractError("qualification hourly-rate ceiling is invalid")
        if self.maximum_runtime_hours <= 0 or self.maximum_runtime_hours > 8:
            raise ContractError("qualification runtime ceiling is invalid")
        if not self.allowed_cuda_versions or not all(
            re.fullmatch(r"1[123]\.\d", item) for item in self.allowed_cuda_versions
        ):
            raise ContractError("qualification CUDA versions are invalid")

    @property
    def maximum_cost_usd(self) -> Decimal:
        return (
            self.maximum_hourly_rate_usd * self.maximum_runtime_hours
            + self.non_compute_contingency_usd
        )

    def provider_payload(self) -> dict[str, Any]:
        environment = {
            "PUBLIC_KEY": self.public_key,
            "FOLYNTA_IMAGE_DIGEST": self.image_name,
            "FOLYNTA_QUALIFICATION_ONLY": "1",
        }
        if self.vllm_cuda_compatibility:
            environment["VLLM_ENABLE_CUDA_COMPATIBILITY"] = "1"
        return {
            "name": self.name,
            "imageName": self.image_name,
            "cloudType": "SECURE",
            "computeType": "GPU",
            "gpuTypeIds": [self.gpu_type],
            "gpuTypePriority": "availability",
            "gpuCount": 1,
            "containerDiskInGb": self.container_disk_gb,
            "volumeInGb": self.volume_gb,
            "volumeMountPath": "/workspace",
            "ports": ["22/tcp"],
            "supportPublicIp": True,
            "interruptible": False,
            "allowedCudaVersions": list(self.allowed_cuda_versions),
            "env": environment,
        }

    def redacted_identity(self) -> dict[str, Any]:
        payload = self.provider_payload()
        payload["env"] = {
            "PUBLIC_KEY": "redacted",
            "FOLYNTA_IMAGE_DIGEST": self.image_name,
            "FOLYNTA_QUALIFICATION_ONLY": "1",
        }
        if self.vllm_cuda_compatibility:
            payload["env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] = "1"
        payload["allocationId"] = self.allocation_id
        payload["maximumCostUsd"] = str(self.maximum_cost_usd)
        payload["publicBenchmarkInferenceAllowed"] = False
        return payload


class RunPodQualificationClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key or any(character.isspace() for character in api_key):
            raise ContractError("RunPod API key is missing or malformed")
        self._client = httpx.Client(
            base_url=PODS_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def create(
        self, spec: QualificationPodSpec, *, budget: AuthorizedSpendBudget
    ) -> dict[str, Any]:
        reservation = budget.reserve(
            allocation_id=spec.allocation_id,
            maximum_cost_usd=spec.maximum_cost_usd,
        )
        value = self._request("POST", "/pods", spec.provider_payload(), {201})
        if not isinstance(value, dict):
            raise QualificationPodError("RunPod returned an invalid qualification Pod")
        pod_id = str(value.get("id", ""))
        self._require_pod_id(pod_id)
        if str(value.get("name", "")) != spec.name:
            self.delete(pod_id)
            raise QualificationPodError("qualification Pod name drifted")
        gpu_name = self._gpu_name(value)
        if gpu_name and gpu_name not in _GPU_ALIASES[spec.gpu_type]:
            self.delete(pod_id)
            raise QualificationPodError("qualification GPU identity drifted")
        hourly_rate = self._rate(value)
        if hourly_rate > spec.maximum_hourly_rate_usd:
            self.delete(pod_id)
            raise QualificationPodError("qualification hourly rate exceeds authorization")
        receipt: dict[str, Any] = {
            "schema": "folynta.runpod-qualification-create.v1",
            "pod_id": pod_id,
            "name": spec.name,
            "status": str(value.get("desiredStatus", "")),
            "gpu": gpu_name or None,
            "hourly_rate_usd": str(hourly_rate),
            "allocation_id": reservation.allocation_id,
            "reserved_maximum_cost_usd": str(reservation.maximum_cost_usd),
            "request_sha256": canonical_sha256(spec.redacted_identity()),
            "public_benchmark_inference_allowed": False,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def verify_ready(
        self,
        spec: QualificationPodSpec,
        *,
        pod_id: str,
        verified_gpu_name: str | None = None,
    ) -> dict[str, Any]:
        value = self.get(pod_id)
        if str(value.get("name", "")) != spec.name:
            raise QualificationPodError("qualification Pod name drifted during readiness")
        if str(value.get("desiredStatus", "")) != "RUNNING":
            raise QualificationPodError("qualification Pod is not running")
        rest_gpu = self._gpu_name(value)
        gpu_name = rest_gpu or (verified_gpu_name or "").strip()
        if gpu_name not in _GPU_ALIASES[spec.gpu_type]:
            raise QualificationPodError("qualification GPU is not verified")
        hourly_rate = self._rate(value)
        if hourly_rate > spec.maximum_hourly_rate_usd:
            raise QualificationPodError("qualification hourly rate exceeds authorization")
        public_ip = str(value.get("publicIp", ""))
        try:
            IPv4Address(public_ip)
        except ValueError as exc:
            raise QualificationPodError("qualification public IP is unavailable") from exc
        mappings = value.get("portMappings")
        ssh_value = mappings.get("22") if isinstance(mappings, dict) else None
        if not isinstance(ssh_value, (int, str)):
            raise QualificationPodError("qualification SSH port is unavailable")
        try:
            ssh_port = int(ssh_value)
        except (TypeError, ValueError) as exc:
            raise QualificationPodError("qualification SSH port is unavailable") from exc
        if not 1 <= ssh_port <= 65535:
            raise QualificationPodError("qualification SSH port is invalid")
        receipt: dict[str, Any] = {
            "schema": "folynta.runpod-qualification-ready.v1",
            "pod_id": pod_id,
            "name": spec.name,
            "gpu": gpu_name,
            "gpu_identity_source": ("rest_pod_response" if rest_gpu else "graphql_cross_check"),
            "hourly_rate_usd": str(hourly_rate),
            "public_ip": public_ip,
            "ssh_port": ssh_port,
            "public_benchmark_inference_allowed": False,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def get(self, pod_id: str) -> dict[str, Any]:
        self._require_pod_id(pod_id)
        value = self._request("GET", f"/pods/{pod_id}", None, {200})
        if not isinstance(value, dict):
            raise QualificationPodError("RunPod returned an invalid qualification Pod")
        return value

    def delete(self, pod_id: str) -> None:
        self._require_pod_id(pod_id)
        self._request("DELETE", f"/pods/{pod_id}", None, {200, 202, 204})

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
        expected: set[int],
    ) -> object:
        try:
            response = self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise QualificationPodError(f"RunPod {method} transport failure") from exc
        if response.status_code not in expected:
            raise QualificationPodError(
                f"RunPod {method} failed with status {response.status_code}"
            )
        if response.status_code == 204 or not response.content:
            return None
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise QualificationPodError("RunPod returned a non-JSON response")
        try:
            return response.json()
        except ValueError as exc:
            raise QualificationPodError("RunPod returned malformed JSON") from exc

    @staticmethod
    def _require_pod_id(pod_id: str) -> None:
        if not _POD_ID.fullmatch(pod_id):
            raise ContractError("invalid qualification pod_id")

    @staticmethod
    def _gpu_name(value: dict[str, Any]) -> str:
        gpu = value.get("gpu")
        if isinstance(gpu, dict) and str(gpu.get("displayName", "")).strip():
            return str(gpu["displayName"]).strip()
        machine = value.get("machine")
        return str(machine.get("gpuDisplayName", "")).strip() if isinstance(machine, dict) else ""

    @staticmethod
    def _rate(value: dict[str, Any]) -> Decimal:
        try:
            rate = Decimal(str(value.get("adjustedCostPerHr", value.get("costPerHr", ""))))
        except InvalidOperation as exc:
            raise QualificationPodError("qualification hourly rate is invalid") from exc
        if not rate.is_finite() or rate < 0:
            raise QualificationPodError("qualification hourly rate is invalid")
        return rate


__all__ = [
    "QualificationPodError",
    "QualificationPodSpec",
    "RunPodQualificationClient",
]
