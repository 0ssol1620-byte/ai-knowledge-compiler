#!/usr/bin/env python3
"""Explicit RunPod + R2 composition for the GPU successor controller.

Construction requires every runtime artifact and an already-configured object
transport.  Merely importing this module never reads a key or calls a network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from common import canonical_sha
from gpu_successor_execution import WORKER_RESULT_SCHEMA
from gpu_successor_preflight import CAP_GPU_HOURS, CAP_USD
from gpu_successor_runtime import (
    GpuSuccessorController,
    RuntimeControlError,
    RuntimeLimits,
    load_worker_bundle,
)
from runpod_provisioner import (
    _CREATE_POD_MUTATION,
    GRAPHQL_URL,
    REST_BASE_URL,
    _read_runtime_gpu_declaration,
)

from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.credentials import RunPodCredentialSet


class RunpodLifecycleTransport:
    """Minimal paid-resource surface consumed by ``GpuSuccessorController``."""

    def __init__(
        self,
        *,
        credentials: RunPodCredentialSet,
        runtime_protocol_path: Path,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
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

    def close(self) -> None:
        self.rest.close()
        self.graphql.close()

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        gpu_type, gpu_count = _read_runtime_gpu_declaration(self.runtime_protocol_path)
        bundle = request["worker_bundle"]
        grants = request.get("worker_transport") or {}
        required_grants = {
            "input_get_url",
            "status_put_url",
            "status_put_headers",
            "output_post_url",
            "output_post_fields",
            "output_object_prefix",
        }
        if set(grants) < required_grants:
            raise RuntimeControlError("R2 worker grants are incomplete")
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
        }
        graphql_input = {
            "cloudType": "SECURE",
            "containerDiskInGb": 60,
            "gpuCount": gpu_count,
            "gpuTypeId": gpu_type,
            "imageName": request["runtime_image_digest"],
            "name": request["name"],
            "startSsh": False,
            "supportPublicIp": False,
            "terminateAfter": request["runpod_terminate_after"],
            "dockerEntrypoint": bundle["entrypoint"],
            "env": environment,
        }
        response = self.graphql.post(
            GRAPHQL_URL, json={"query": _CREATE_POD_MUTATION, "variables": {"input": graphql_input}}
        )
        if response.status_code != 200:
            raise RuntimeControlError(f"RunPod create returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise RuntimeControlError("RunPod create returned malformed JSON") from error
        if body.get("errors"):
            raise RuntimeControlError("RunPod create returned GraphQL errors")
        pod = (body.get("data") or {}).get("podFindAndDeployOnDemand")
        if not isinstance(pod, dict) or not pod.get("id"):
            raise RuntimeControlError("RunPod create returned no resource identity")
        return {**pod, "name": request["name"]}

    def list_by_name(self, name: str) -> list[dict[str, Any]]:
        response = self.rest.get("/pods")
        if response.status_code != 200:
            raise RuntimeControlError(f"RunPod inventory returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise RuntimeControlError("RunPod inventory returned malformed JSON") from error
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
            raise RuntimeControlError(f"RunPod snapshot returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise RuntimeControlError("RunPod snapshot returned malformed JSON") from error
        uptime = body.get("uptimeSeconds")
        rate = body.get("costPerHr")
        if not isinstance(uptime, (int, float)) or not isinstance(rate, (int, float)):
            raise RuntimeControlError("RunPod snapshot omitted numeric live usage")
        return {
            **body,
            "gpu_seconds": float(uptime),
            "cost_usd": float(rate) * float(uptime) / 3600.0,
        }

    def delete(self, resource_id: str) -> None:
        response = self.rest.delete(f"/pods/{resource_id}")
        if response.status_code not in {200, 202, 204, 404}:
            raise RuntimeControlError(f"RunPod delete returned status {response.status_code}")


class RunpodScientificProvisioner:
    """Launcher protocol adapter; controller owns create through absence proof."""

    def __init__(
        self,
        *,
        lifecycle: RunpodLifecycleTransport,
        objects: Any,
        worker_bundle_path: Path,
        worker_bundle_sha256: str,
        materialized_input_path: Path,
        output_path: Path,
        ledger_path: Path,
    ) -> None:
        self.lifecycle = lifecycle
        self.objects = objects
        self.worker_bundle_path = worker_bundle_path
        self.worker_bundle_sha256 = worker_bundle_sha256
        self.materialized_input_path = materialized_input_path
        self.output_path = output_path
        self.ledger_path = ledger_path
        self.bundle = load_worker_bundle(worker_bundle_path, worker_bundle_sha256)
        self.controller: GpuSuccessorController | None = None

    def execution_readiness(self, spec: dict[str, Any]) -> dict[str, Any]:
        authority = spec.get("execution_authority") or {}
        required = (
            authority.get("fresh_study_acceptance") is True,
            authority.get("four_link_acceptance") is True,
            self.materialized_input_path.is_file(),
            bool(self.bundle),
        )
        return {
            "passed": all(required),
            "backend": "runpod_r2_frozen_worker_v1",
            "missing_prerequisites": []
            if all(required)
            else [{"code": "EXACT_RUNTIME_CONFIG_INCOMPLETE"}],
            "worker_bundle_manifest_sha256": self.bundle["manifest_file_sha256"],
        }

    def provision(self, spec: dict[str, Any]) -> dict[str, Any]:
        # Reservation and provider create occur inside execute_scientific_workload
        # after its durable create intent, never at this staging transition.
        return {"staged": True, "torn_down": False, "actual_usage": None, "spec": spec}

    def execute_scientific_workload(
        self, handle: dict[str, Any], spec: dict[str, Any]
    ) -> dict[str, Any]:
        if handle.get("staged") is not True:
            raise RuntimeControlError("scientific execution handle was not staged")
        run_identity = canonical_sha(
            {
                "input": spec["input_contract"]["materialized_file_sha256"],
                "bundle": self.bundle["bundle_sha256"],
            }
        )
        ledger = EvidenceLedger(
            self.ledger_path,
            cohort_id="gpu-successor-study",
            run_tag="v6-gpu-successor-" + run_identity[7:23],
        )
        budget = AuthorizedSpendBudget(campaign_id="gpu-successor-study", hard_cap_usd=str(CAP_USD))
        self.controller = GpuSuccessorController(
            provider=self.lifecycle,
            objects=self.objects,
            ledger=ledger,
            budget=budget,
            limits=RuntimeLimits(
                maximum_seconds=CAP_GPU_HOURS * 3600.0,
                maximum_cost_usd=Decimal(str(CAP_USD)),
            ),
        )
        from datetime import UTC, datetime, timedelta

        executable_spec = {
            **spec,
            "runpod_terminate_after": (datetime.now(UTC) + timedelta(hours=CAP_GPU_HOURS)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        completed = self.controller.execute(
            spec=executable_spec,
            input_path=self.materialized_input_path,
            bundle=self.bundle,
            output_path=self.output_path,
        )
        handle["actual_usage"] = completed["actual_usage"]
        handle["torn_down"] = completed["provider_absent"] is True
        return {
            "schema": WORKER_RESULT_SCHEMA,
            "status": "completed",
            "input_set_digest": spec["input_contract"]["input_set_digest"],
            "manifest_sha256": spec["input_contract"]["manifest_sha256"],
            "runtime_image_digest": spec["runtime_image_digest"],
            "model_pin_sha256": spec["model_pin_sha256"],
            "output_path": completed["output_path"],
            "output_sha256": completed["output_sha256"],
        }

    def teardown(self, handle: dict[str, Any]) -> None:
        if self.controller is not None and handle.get("torn_down") is not True:
            self.controller.abort()
        if handle.get("torn_down") is not True:
            handle["actual_usage"] = handle.get("actual_usage") or {
                "gpu_seconds": "NOT_RETRIEVED",
                "cost_usd": "NOT_RETRIEVED",
                "source": "watchdog_abort",
            }
        handle["torn_down"] = True

    def close(self) -> None:
        self.lifecycle.close()


__all__ = ["RunpodLifecycleTransport", "RunpodScientificProvisioner"]


def build_environment_backend(
    *,
    worker_bundle_path: Path,
    worker_bundle_sha256: str,
    materialized_input_path: Path,
    output_path: Path,
    ledger_path: Path,
    r2_endpoint_url: str,
    r2_bucket: str,
    r2_region: str,
) -> RunpodScientificProvisioner:
    """Build only after launcher gates; require explicit scoped credentials."""
    import os

    import boto3
    from gpu_successor_r2 import S3CompatibleObjectTransport

    access = os.environ.get("AKC_S3_ACCESS_KEY_ID")
    secret = os.environ.get("AKC_S3_SECRET_ACCESS_KEY")
    if not access or not secret:
        raise RuntimeControlError("scoped AKC S3/R2 credentials are absent")
    s3 = boto3.client(
        "s3",
        endpoint_url=r2_endpoint_url,
        region_name=r2_region,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )
    lifecycle = RunpodLifecycleTransport(
        credentials=RunPodCredentialSet.from_environment(required=True),
        runtime_protocol_path=Path(__file__).resolve().parents[1]
        / "protocols"
        / "GPU_SUCCESSOR_RUNTIME_V1.yaml",
    )
    return RunpodScientificProvisioner(
        lifecycle=lifecycle,
        objects=S3CompatibleObjectTransport(client=s3, bucket=r2_bucket),
        worker_bundle_path=worker_bundle_path,
        worker_bundle_sha256=worker_bundle_sha256,
        materialized_input_path=materialized_input_path,
        output_path=output_path,
        ledger_path=ledger_path,
    )


__all__.append("build_environment_backend")
