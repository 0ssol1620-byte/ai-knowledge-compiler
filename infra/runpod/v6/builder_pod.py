"""Temporary RunPod image-builder client with absolute cost reservation.

Builder Pods are intentionally not benchmark runtimes and cannot produce a
runtime-qualification claim. They exist only to build and publish immutable
images, then are terminated.
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
_IMAGE_DIGEST = re.compile(r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_POD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
_ALLOWED_GPU = frozenset(
    {"NVIDIA A40", "NVIDIA RTX A6000", "NVIDIA L40S", "NVIDIA GeForce RTX 4090"}
)
_GPU_ALIASES: Final = {
    "NVIDIA A40": frozenset({"NVIDIA A40", "A40"}),
    "NVIDIA RTX A6000": frozenset({"NVIDIA RTX A6000", "RTX A6000"}),
    "NVIDIA L40S": frozenset({"NVIDIA L40S", "L40S"}),
    "NVIDIA GeForce RTX 4090": frozenset(
        {"NVIDIA GeForce RTX 4090", "GeForce RTX 4090", "RTX 4090"}
    ),
}
_BOOTSTRAP = r"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  openssh-server git buildah jq curl ca-certificates uidmap fuse-overlayfs
rm -rf /var/lib/apt/lists/*
install -d -m 0700 /root/.ssh
printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
install -d -m 0755 /run/sshd /workspace/folynta-builder
buildah --version
exec /usr/sbin/sshd -D -e
"""


class BuilderPodError(RuntimeError):
    """Provider or builder-contract error with response bodies withheld."""


@dataclass(frozen=True, slots=True)
class BuilderPodSpec:
    name: str
    image_name: str
    gpu_type: str
    public_key: str
    allocation_id: str
    maximum_hourly_rate_usd: Decimal
    maximum_runtime_hours: Decimal
    non_compute_contingency_usd: Decimal = Decimal("4")
    container_disk_gb: int = 200
    volume_gb: int = 20

    def __post_init__(self) -> None:
        if not re.fullmatch(r"folynta-builder-[a-z0-9-]{3,50}", self.name):
            raise ContractError("builder Pod name is invalid")
        if not _IMAGE_DIGEST.fullmatch(self.image_name):
            raise ContractError("builder image must use an immutable sha256 digest")
        if self.gpu_type not in _ALLOWED_GPU:
            raise ContractError("builder GPU type is unsupported")
        if not self.public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
            raise ContractError("builder public key is invalid")
        if not self.allocation_id.strip():
            raise ContractError("builder allocation_id is required")
        if not 80 <= self.container_disk_gb <= 400:
            raise ContractError("builder container disk must be between 80 and 400 GB")
        if not 0 <= self.volume_gb <= 100:
            raise ContractError("builder volume must be between 0 and 100 GB")
        if self.maximum_hourly_rate_usd <= 0 or self.maximum_hourly_rate_usd > 5:
            raise ContractError("builder hourly-rate ceiling is invalid")
        if self.maximum_runtime_hours <= 0 or self.maximum_runtime_hours > 24:
            raise ContractError("builder runtime ceiling is invalid")
        if self.non_compute_contingency_usd < 0 or self.non_compute_contingency_usd > 20:
            raise ContractError("builder non-compute contingency is invalid")

    @property
    def maximum_cost_usd(self) -> Decimal:
        return (
            self.maximum_hourly_rate_usd * self.maximum_runtime_hours
            + self.non_compute_contingency_usd
        )

    def provider_payload(self) -> dict[str, Any]:
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
            "allowedCudaVersions": ["12.8", "12.9"],
            "dockerEntrypoint": ["/bin/bash", "-lc"],
            "dockerStartCmd": [_BOOTSTRAP],
            "env": {
                "PUBLIC_KEY": self.public_key,
                "FOLYNTA_BUILDER_ROLE": "temporary-image-builder-not-qualified-runtime",
            },
        }

    def redacted_identity(self) -> dict[str, Any]:
        payload = self.provider_payload()
        payload["env"] = {
            "PUBLIC_KEY": "redacted",
            "FOLYNTA_BUILDER_ROLE": payload["env"]["FOLYNTA_BUILDER_ROLE"],
        }
        payload["allocationId"] = self.allocation_id
        payload["maximumHourlyRateUsd"] = str(self.maximum_hourly_rate_usd)
        payload["maximumRuntimeHours"] = str(self.maximum_runtime_hours)
        payload["nonComputeContingencyUsd"] = str(self.non_compute_contingency_usd)
        payload["maximumCostUsd"] = str(self.maximum_cost_usd)
        payload["runtimeQualificationEligible"] = False
        return payload


class RunPodBuilderClient:
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
        self, spec: BuilderPodSpec, *, budget: AuthorizedSpendBudget
    ) -> dict[str, Any]:
        reservation = budget.reserve(
            allocation_id=spec.allocation_id,
            maximum_cost_usd=spec.maximum_cost_usd,
        )
        try:
            value = self._request(
                "POST", "/pods", json_body=spec.provider_payload(), expected={201}
            )
        except Exception:
            # The write outcome may be ambiguous. Keep the reservation and
            # require inventory reconciliation; never auto-retry a paid write.
            raise
        if not isinstance(value, dict):
            raise BuilderPodError("RunPod returned an invalid builder Pod")
        pod_id = str(value.get("id", ""))
        if not _POD_ID.fullmatch(pod_id):
            raise BuilderPodError("RunPod returned an invalid builder Pod ID")
        if str(value.get("name", "")) != spec.name:
            self.delete(pod_id)
            raise BuilderPodError("RunPod builder Pod name drifted")
        gpu_name = self._gpu_name(value)
        if gpu_name and gpu_name not in _GPU_ALIASES[spec.gpu_type]:
            self.delete(pod_id)
            raise BuilderPodError("RunPod builder GPU identity drifted")
        try:
            hourly_rate = Decimal(
                str(value.get("adjustedCostPerHr", value.get("costPerHr", "")))
            )
        except InvalidOperation as exc:
            self.delete(pod_id)
            raise BuilderPodError("RunPod builder hourly price is invalid") from exc
        if not hourly_rate.is_finite() or hourly_rate > spec.maximum_hourly_rate_usd:
            self.delete(pod_id)
            raise BuilderPodError("RunPod builder hourly price exceeds authorization")
        receipt: dict[str, Any] = {
            "schema": "folynta.runpod-builder-create.v1",
            "pod_id": pod_id,
            "name": spec.name,
            "status": str(value.get("desiredStatus", "")),
            "gpu": gpu_name or None,
            "gpu_verified_at_creation": bool(gpu_name),
            "hourly_rate_usd": str(hourly_rate),
            "allocation_id": reservation.allocation_id,
            "reserved_maximum_cost_usd": str(reservation.maximum_cost_usd),
            "maximum_runtime_hours": str(spec.maximum_runtime_hours),
            "request_sha256": canonical_sha256(spec.redacted_identity()),
            "runtime_qualification_eligible": False,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def verify_ready(
        self,
        spec: BuilderPodSpec,
        *,
        pod_id: str,
        verified_gpu_name: str | None = None,
    ) -> dict[str, Any]:
        value = self.get(pod_id)
        if str(value.get("name", "")) != spec.name:
            raise BuilderPodError("RunPod builder Pod name drifted during readiness")
        if str(value.get("desiredStatus", "")) != "RUNNING":
            raise BuilderPodError("RunPod builder Pod is not running")
        rest_gpu_name = self._gpu_name(value)
        gpu_name = rest_gpu_name or (verified_gpu_name or "").strip()
        if gpu_name not in _GPU_ALIASES[spec.gpu_type]:
            raise BuilderPodError("RunPod builder GPU is not verified")
        try:
            hourly_rate = Decimal(
                str(value.get("adjustedCostPerHr", value.get("costPerHr", "")))
            )
        except InvalidOperation as exc:
            raise BuilderPodError("RunPod builder hourly price is invalid") from exc
        if not hourly_rate.is_finite() or hourly_rate > spec.maximum_hourly_rate_usd:
            raise BuilderPodError("RunPod builder hourly price exceeds authorization")
        public_ip = str(value.get("publicIp", ""))
        try:
            IPv4Address(public_ip)
        except ValueError as exc:
            raise BuilderPodError("RunPod builder public IP is unavailable") from exc
        mappings = value.get("portMappings")
        ssh_port_value = mappings.get("22") if isinstance(mappings, dict) else None
        if not isinstance(ssh_port_value, (int, str)):
            raise BuilderPodError("RunPod builder SSH port is unavailable")
        try:
            ssh_port = int(ssh_port_value)
        except (TypeError, ValueError) as exc:
            raise BuilderPodError("RunPod builder SSH port is unavailable") from exc
        if not 1 <= ssh_port <= 65535:
            raise BuilderPodError("RunPod builder SSH port is invalid")
        receipt: dict[str, Any] = {
            "schema": "folynta.runpod-builder-ready.v1",
            "pod_id": pod_id,
            "name": spec.name,
            "status": "RUNNING",
            "gpu": gpu_name,
            "gpu_identity_source": (
                "rest_pod_response" if rest_gpu_name else "graphql_cross_check"
            ),
            "hourly_rate_usd": str(hourly_rate),
            "public_ip": public_ip,
            "ssh_port": ssh_port,
            "allocation_id": spec.allocation_id,
            "runtime_qualification_eligible": False,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def get(self, pod_id: str) -> dict[str, Any]:
        self._require_pod_id(pod_id)
        value = self._request("GET", f"/pods/{pod_id}", None, {200})
        if not isinstance(value, dict):
            raise BuilderPodError("RunPod returned an invalid builder Pod")
        return value

    def delete(self, pod_id: str) -> dict[str, Any]:
        self._require_pod_id(pod_id)
        value = self._request("DELETE", f"/pods/{pod_id}", None, {200, 202, 204})
        return {
            "pod_id": pod_id,
            "delete_acknowledged": True,
            "provider_response_present": value is not None,
        }

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
            raise BuilderPodError(f"RunPod {method} transport failure") from exc
        if response.status_code not in expected:
            raise BuilderPodError(f"RunPod {method} failed with status {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise BuilderPodError("RunPod returned a non-JSON response")
        try:
            return response.json()
        except ValueError as exc:
            raise BuilderPodError("RunPod returned malformed JSON") from exc

    @staticmethod
    def _require_pod_id(pod_id: str) -> None:
        if not _POD_ID.fullmatch(pod_id):
            raise ContractError("invalid builder pod_id")

    @staticmethod
    def _gpu_name(value: dict[str, Any]) -> str:
        gpu = value.get("gpu")
        if isinstance(gpu, dict) and str(gpu.get("displayName", "")).strip():
            return str(gpu["displayName"]).strip()
        machine = value.get("machine")
        if isinstance(machine, dict):
            return str(machine.get("gpuDisplayName", "")).strip()
        return ""


__all__ = ["BuilderPodError", "BuilderPodSpec", "RunPodBuilderClient"]
