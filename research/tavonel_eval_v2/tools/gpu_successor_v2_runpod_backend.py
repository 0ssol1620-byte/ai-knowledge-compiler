#!/usr/bin/env python3
"""Provider-ready RunPod/R2 composition for GPU successor V2.

Import and construction are side-effect free. Network access begins only when
``V2Controller.execute`` calls the injected lifecycle transport.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from gpu_successor_v2_runtime import INNER_SECONDS, V2RuntimeError
from runpod_provisioner import (
    _CREATE_POD_MUTATION,
    GRAPHQL_URL,
    REST_BASE_URL,
    _read_runtime_gpu_declaration,
)

from infra.runpod.v6.credentials import RunPodCredentialSet


class RunpodV2LifecycleTransport:
    """RunPod adapter with a V2-only environment and final delete evidence."""

    def __init__(
        self,
        *,
        credentials: RunPodCredentialSet,
        runtime_protocol_path: Path,
        signing_private_key_b64: str,
        worker_bundle_path_in_image: str,
        model_path_in_image: str,
        model_manifest_path_in_image: str,
        tokenizer_path_in_image: str,
        tokenizer_manifest_path_in_image: str,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not signing_private_key_b64:
            raise V2RuntimeError("ephemeral V2 signing material is absent")
        for value, label in (
            (worker_bundle_path_in_image, "worker bundle path"),
            (model_path_in_image, "model path"),
            (model_manifest_path_in_image, "model manifest path"),
            (tokenizer_path_in_image, "tokenizer path"),
            (tokenizer_manifest_path_in_image, "tokenizer manifest path"),
        ):
            if not value.startswith("/") or ".." in Path(value).parts:
                raise V2RuntimeError(f"{label} must be an absolute image path")
        headers = {"Authorization": f"Bearer {credentials.primary}", "Accept": "application/json"}
        self.rest = httpx.Client(
            base_url=REST_BASE_URL,
            headers=headers,
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self.graphql = httpx.Client(
            headers={**headers, "Content-Type": "application/json"},
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self.runtime_protocol_path = runtime_protocol_path
        self._signing_key = signing_private_key_b64
        self._bundle_path = worker_bundle_path_in_image
        self._model_path = model_path_in_image
        self._model_manifest_path = model_manifest_path_in_image
        self._tokenizer_path = tokenizer_path_in_image
        self._tokenizer_manifest_path = tokenizer_manifest_path_in_image

    def close(self) -> None:
        self.rest.close()
        self.graphql.close()

    @staticmethod
    def _usage(body: dict[str, Any]) -> dict[str, float]:
        uptime, rate = body.get("uptimeSeconds"), body.get("costPerHr")
        if (
            isinstance(uptime, bool)
            or isinstance(rate, bool)
            or not isinstance(uptime, (int, float))
            or not isinstance(rate, (int, float))
        ):
            raise V2RuntimeError("RunPod omitted numeric provider usage")
        return {"gpu_seconds": float(uptime), "cost_usd": float(rate) * float(uptime) / 3600.0}

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        gpu_type, gpu_count = _read_runtime_gpu_declaration(self.runtime_protocol_path)
        bundle, grants = request["worker_bundle"], request.get("worker_transport") or {}
        required = {
            "input_get_url",
            "status_put_url",
            "status_put_headers",
            "output_post_url",
            "output_post_fields",
            "output_object_prefix",
        }
        if set(grants) < required:
            raise V2RuntimeError("bounded R2 V2 grants are incomplete")
        image = request.get("runtime_image_digest")
        if not isinstance(image, str) or "@sha256:" not in image:
            raise V2RuntimeError("V2 runtime image must be pinned by OCI digest")
        environment = {
            "TAVONEL_INPUT_GET_URL": grants["input_get_url"],
            "TAVONEL_INPUT_SHA256": request["input_sha256"],
            "TAVONEL_STATUS_PUT_URL": grants["status_put_url"],
            "TAVONEL_STATUS_PUT_HEADERS_JSON": json.dumps(
                grants["status_put_headers"], sort_keys=True
            ),
            "TAVONEL_OUTPUT_POST_URL": grants["output_post_url"],
            "TAVONEL_OUTPUT_POST_FIELDS_JSON": json.dumps(
                grants["output_post_fields"], sort_keys=True
            ),
            "TAVONEL_OUTPUT_OBJECT_PREFIX": grants["output_object_prefix"],
            "TAVONEL_WORKER_BUNDLE_FACTS_SHA256": bundle["facts_digest"],
            "TAVONEL_WORKER_BUNDLE_PATH": self._bundle_path,
            "TAVONEL_MODEL_PATH": self._model_path,
            "TAVONEL_MODEL_MANIFEST_PATH": self._model_manifest_path,
            "TAVONEL_TOKENIZER_PATH": self._tokenizer_path,
            "TAVONEL_TOKENIZER_MANIFEST_PATH": self._tokenizer_manifest_path,
            "TAVONEL_VLLM_BASE_URL": "http://127.0.0.1:8000",
            "TAVONEL_TERMINAL_PRIVATE_KEY_B64": self._signing_key,
        }
        graphql_input = {
            "cloudType": "SECURE",
            "containerDiskInGb": 80,
            "gpuCount": gpu_count,
            "gpuTypeId": gpu_type,
            "imageName": image,
            "name": request["name"],
            "startSsh": False,
            "supportPublicIp": False,
            "terminateAfter": (datetime.now(UTC) + timedelta(seconds=INNER_SECONDS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "dockerEntrypoint": bundle["entrypoint"],
            "env": environment,
        }
        response = self.graphql.post(
            GRAPHQL_URL, json={"query": _CREATE_POD_MUTATION, "variables": {"input": graphql_input}}
        )
        if response.status_code != 200:
            raise V2RuntimeError(f"RunPod V2 create returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise V2RuntimeError("RunPod V2 create returned malformed JSON") from error
        if body.get("errors"):
            raise V2RuntimeError("RunPod V2 create returned GraphQL errors")
        pod = (body.get("data") or {}).get("podFindAndDeployOnDemand")
        if not isinstance(pod, dict) or not pod.get("id"):
            raise V2RuntimeError("RunPod V2 create returned no identity")
        return {**pod, "name": request["name"]}

    def list_by_name(self, name: str) -> list[dict[str, Any]]:
        response = self.rest.get("/pods")
        if response.status_code != 200:
            raise V2RuntimeError(f"RunPod V2 inventory returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise V2RuntimeError("RunPod V2 inventory returned malformed JSON") from error
        pods = (
            body
            if isinstance(body, list)
            else body.get("pods", [])
            if isinstance(body, dict)
            else []
        )
        return [pod for pod in pods if isinstance(pod, dict) and pod.get("name") == name]

    def snapshot(self, resource_id: str) -> dict[str, Any] | None:
        response = self.rest.get(f"/pods/{resource_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise V2RuntimeError(f"RunPod V2 snapshot returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise V2RuntimeError("RunPod V2 snapshot returned malformed JSON") from error
        return {**body, **self._usage(body)}

    def delete_and_finalize(self, resource_id: str) -> dict[str, Any]:
        """Use authoritative pre-delete usage, accept 204, and repeat absence proof."""
        before = self.snapshot(resource_id)
        if before is None:
            raise V2RuntimeError("RunPod resource absent before final billing evidence")
        response = self.rest.delete(f"/pods/{resource_id}")
        if response.status_code not in {200, 202, 204}:
            raise V2RuntimeError(f"RunPod V2 delete returned status {response.status_code}")
        for _ in range(3):
            if self.snapshot(resource_id) is not None:
                raise V2RuntimeError("RunPod V2 resource remains during repeated absence proof")
        usage = {"gpu_seconds": before["gpu_seconds"], "cost_usd": before["cost_usd"]}
        return {
            **usage,
            "source": "provider_predelete_usage_with_delete_absence",
            "provider_absent": True,
            "delete_status": response.status_code,
            "absence_observations": 3,
        }


def build_environment_transport(
    *,
    runtime_protocol_path: Path,
    worker_bundle_path_in_image: str,
    model_path_in_image: str,
    model_manifest_path_in_image: str,
    tokenizer_path_in_image: str,
    tokenizer_manifest_path_in_image: str,
) -> RunpodV2LifecycleTransport:
    """Read exact secrets only at the explicit execute boundary."""
    import os

    signing = os.environ.get("TAVONEL_TERMINAL_PRIVATE_KEY_B64", "")
    return RunpodV2LifecycleTransport(
        credentials=RunPodCredentialSet.from_environment(required=True),
        runtime_protocol_path=runtime_protocol_path,
        signing_private_key_b64=signing,
        worker_bundle_path_in_image=worker_bundle_path_in_image,
        model_path_in_image=model_path_in_image,
        model_manifest_path_in_image=model_manifest_path_in_image,
        tokenizer_path_in_image=tokenizer_path_in_image,
        tokenizer_manifest_path_in_image=tokenizer_manifest_path_in_image,
    )


__all__ = ["RunpodV2LifecycleTransport", "build_environment_transport"]
