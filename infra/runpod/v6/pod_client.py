"""Fail-closed RunPod Pod REST v1 client for benchmark qualification.

The client is deliberately separate from the Serverless endpoint adapter. It
has no retries after writes, never serializes the API key, and returns a narrow
receipt that omits environment values and provider account identifiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx

from benchmark.v6.contracts import ContractError, canonical_sha256

PODS_BASE_URL: Final = "https://rest.runpod.io/v1"
RUNPOD_KEY_ENV: Final = "RUNPOD_API_KEY"
_POD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
_IMAGE_DIGEST = re.compile(r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_ALLOWED_STATUS = frozenset({"RUNNING", "EXITED", "TERMINATED"})
_ALLOWED_GPU = frozenset(
    {
        "NVIDIA GeForce RTX 4090",
        "NVIDIA A40",
        "NVIDIA RTX A6000",
        "NVIDIA L40S",
    }
)


class PodClientError(RuntimeError):
    """Provider error with credentials and response bodies withheld."""


@dataclass(frozen=True, slots=True)
class PodCreateSpec:
    name: str
    image_name: str
    gpu_type: str
    public_key: str
    container_disk_gb: int = 80
    volume_gb: int = 20
    allowed_cuda_versions: tuple[str, ...] = ("12.8", "12.9")
    docker_entrypoint: tuple[str, ...] = ()
    docker_start_cmd: tuple[str, ...] = ()
    vllm_cuda_compatibility: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PodCreateSpec:
        compatibility = value.get("vllm_cuda_compatibility", False)
        if not isinstance(compatibility, bool):
            raise ContractError("vllm_cuda_compatibility must be a boolean")
        spec = cls(
            name=str(value.get("name", "")).strip(),
            image_name=str(value.get("image_name", "")).strip(),
            gpu_type=str(value.get("gpu_type", "")).strip(),
            public_key=str(value.get("public_key", "")).strip(),
            container_disk_gb=int(value.get("container_disk_gb", 80)),
            volume_gb=int(value.get("volume_gb", 20)),
            allowed_cuda_versions=tuple(
                str(item) for item in value.get("allowed_cuda_versions", ["12.8", "12.9"])
            ),
            docker_entrypoint=tuple(str(item) for item in value.get("docker_entrypoint", [])),
            docker_start_cmd=tuple(str(item) for item in value.get("docker_start_cmd", [])),
            vllm_cuda_compatibility=compatibility,
        )
        if not spec.name or len(spec.name) > 80 or not spec.image_name:
            raise ContractError("pod name and immutable image name are required")
        if not _IMAGE_DIGEST.fullmatch(spec.image_name):
            raise ContractError("image_name must use an immutable sha256 digest")
        if spec.gpu_type not in _ALLOWED_GPU:
            raise ContractError(f"unsupported benchmark GPU: {spec.gpu_type}")
        if not spec.public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
            raise ContractError("public_key must be an OpenSSH public key")
        if not 40 <= spec.container_disk_gb <= 200:
            raise ContractError("container_disk_gb must be between 40 and 200")
        if not 0 <= spec.volume_gb <= 100:
            raise ContractError("volume_gb must be between 0 and 100")
        if not spec.allowed_cuda_versions or not all(
            re.fullmatch(r"1[123]\.\d", item) for item in spec.allowed_cuda_versions
        ):
            raise ContractError("allowed_cuda_versions are invalid")
        for label, command in (
            ("docker_entrypoint", spec.docker_entrypoint),
            ("docker_start_cmd", spec.docker_start_cmd),
        ):
            if len(command) > 16 or any(
                not item or len(item) > 4_096 or "\x00" in item for item in command
            ):
                raise ContractError(f"{label} is invalid")
        return spec

    def provider_payload(self) -> dict[str, Any]:
        environment = {"PUBLIC_KEY": self.public_key}
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
            "dockerEntrypoint": list(self.docker_entrypoint),
            "dockerStartCmd": list(self.docker_start_cmd),
            "env": environment,
        }

    def redacted_identity(self) -> dict[str, Any]:
        payload = self.provider_payload()
        payload["env"] = {
            "PUBLIC_KEY_SHA256": "sha256:"
            + hashlib.sha256(self.public_key.encode("utf-8")).hexdigest()
        }
        if self.vllm_cuda_compatibility:
            payload["env"]["VLLM_ENABLE_CUDA_COMPATIBILITY"] = "1"
        return payload


class RunPodPodClient:
    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key or any(character.isspace() for character in api_key):
            raise ContractError("RUNPOD_API_KEY is missing or malformed")
        self._client = httpx.Client(
            base_url=PODS_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_environment(cls) -> RunPodPodClient:
        return cls(api_key=os.environ.get(RUNPOD_KEY_ENV, ""))

    def close(self) -> None:
        self._client.close()

    def list_pods(self) -> list[dict[str, Any]]:
        value = self._request("GET", "/pods", expected={200})
        if not isinstance(value, list):
            raise PodClientError("provider returned an invalid pod inventory shape")
        return [self._receipt(item) for item in value]

    def get_pod(self, pod_id: str) -> dict[str, Any]:
        self._require_pod_id(pod_id)
        value = self._request("GET", f"/pods/{pod_id}", expected={200})
        return self._receipt(value)

    def create_pod(self, spec: PodCreateSpec) -> dict[str, Any]:
        value = self._request(
            "POST", "/pods", json_body=spec.provider_payload(), expected={200, 201}
        )
        receipt = self._receipt(value)
        receipt["request_sha256"] = canonical_sha256(spec.redacted_identity())
        return receipt

    def delete_pod(self, pod_id: str) -> dict[str, Any]:
        self._require_pod_id(pod_id)
        value = self._request("DELETE", f"/pods/{pod_id}", expected={200, 202, 204})
        return {
            "pod_id": pod_id,
            "delete_acknowledged": True,
            "provider_response_present": value is not None,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        expected: set[int],
    ) -> object:
        try:
            response = self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise PodClientError(f"RunPod {method} transport failure") from exc
        if response.status_code not in expected:
            raise PodClientError(f"RunPod {method} failed with status {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise PodClientError("RunPod returned a non-JSON response")
        try:
            return response.json()
        except ValueError as exc:
            raise PodClientError("RunPod returned malformed JSON") from exc

    @staticmethod
    def _require_pod_id(pod_id: str) -> None:
        if not _POD_ID.fullmatch(pod_id):
            raise ContractError("invalid pod_id")

    @staticmethod
    def _receipt(value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PodClientError("provider returned an invalid pod shape")
        pod_id = str(value.get("id", ""))
        RunPodPodClient._require_pod_id(pod_id)
        status = str(value.get("desiredStatus", ""))
        if status and status not in _ALLOWED_STATUS:
            raise PodClientError(f"provider returned unknown pod status: {status}")
        gpu = value.get("gpu")
        gpu_name = str(gpu.get("displayName", "")) if isinstance(gpu, Mapping) else ""
        ports = value.get("portMappings")
        port_22 = ports.get("22") if isinstance(ports, Mapping) else None
        receipt = {
            "pod_id": pod_id,
            "name": str(value.get("name", "")),
            "status": status,
            "image": str(value.get("image", value.get("imageName", ""))),
            "gpu": gpu_name,
            "cost_per_hour_usd": str(value.get("adjustedCostPerHr", value.get("costPerHr", ""))),
            "public_ip": str(value.get("publicIp", "")) or None,
            "ssh_port": int(port_22) if port_22 is not None else None,
            "last_status_change": str(value.get("lastStatusChange", "")),
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt


def write_receipt_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
