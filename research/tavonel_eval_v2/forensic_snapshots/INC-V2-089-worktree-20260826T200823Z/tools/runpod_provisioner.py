#!/usr/bin/env python3
"""The real Runpod backend for `launch_gpu_successor.RunpodPodProvisioner`.

Split into its own module for one reason: `launch_gpu_successor.py` is tested
by `test_no_bypass_flag_or_env_var_exists`, which asserts that module's own
source text never contains `import os`, `os.environ` or `os.getenv` -- the
test's way of catching a later edit that adds an environment-variable escape
hatch around the preflight gates. Reading `RUNPOD_API_KEY` is a legitimate,
unrelated use of `os.environ`, but it cannot live in `launch_gpu_successor.py`
without tripping that guard, and loosening the guard to allow it would weaken
the exact protection it exists for. So the credential read -- and every other
real network call -- lives here instead, and `launch_gpu_successor.py` only
ever imports the class.

Two Runpod surfaces are used, matching what `infra/runpod/v6/qualification_pod.py`
already established for this repository and what a read-only inspection of
`runpodctl`'s own source (github.com/runpod/runpodctl, `internal/api/`)
confirmed about the split between them:

* **REST v1** (`https://rest.runpod.io/v1`) for `GET`/`DELETE /pods/{id}` --
  the same base URL and bearer-auth convention `qualification_pod.py` uses.
  The REST `Pod` response carries `uptimeSeconds` and `costPerHr`, which is
  where real post-run usage comes from (see `_read_usage`).
* **GraphQL** (`https://api.runpod.io/graphql`, mutation
  `podFindAndDeployOnDemand`) for pod *creation*, because `stopAfter` and
  `terminateAfter` -- the platform-side auto-terminate this study's watchdog
  gap (see `launch_gpu_successor.py`'s module docstring, point 5) needs --
  are GraphQL-only fields. Neither `https://api.runpod.io/v2/openapi.json`
  nor `https://rest.runpod.io/v1/openapi.json` expose an auto-terminate field
  on their pod-creation schemas (checked read-only before writing this file);
  `runpodctl`'s own `cmd/pod/create.go` reaches for
  `internal/api.CreatePodGQLInput{StopAfter, TerminateAfter}` and the
  `podFindAndDeployOnDemand` mutation specifically because the REST path
  cannot express this. This module does the same thing runpodctl does, not a
  guess at an undocumented REST field.

Every field this module fills into a create request is either read from
`protocols/GPU_SUCCESSOR_RUNTIME_V1.yaml` (the GPU type/count this study
already declared, `hardware.gpu_type.value` / `hardware.gpu_count.value`) or
is an explicit constructor parameter with no default invented here. This
module does not choose a GPU type, a data center or a price -- the runtime
protocol already named the GPU (`NVIDIA H200`), and the protocol itself says
a data-center pin is "a launch-time decision, made from a read-only
availability lookup at the moment of `--execute`, not baked in here"
(`GPU_SUCCESSOR_RUNTIME_V1.yaml`, `hardware.region_or_data_center_constraint`).
This module honours that: `dataCenterIds` is left unset in the create
request, and Runpod's own scheduler places the pod. Whoever operationalises
a live `--execute` run is expected to have already run a read-only
`list-gpu-types`/`get-gpu-type` availability check and can extend this class
with a `data_center_ids` constructor argument if a pin turns out to be
needed; inventing one here would be exactly the kind of unmeasured guess the
project's CLAUDE.md forbids ("never invent data to satisfy a schema").

No test in this repository exercises a real Runpod endpoint. Every test that
touches this module injects `transport=httpx.MockTransport(...)` and/or a
fake `credentials=` object, so no test can make a live provisioning call --
see `tests/test_launch_gpu_successor.py`'s `RunpodPodProvisioner` section.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS
from gpu_successor_preflight import CAP_GPU_HOURS, RUNTIME_IMAGE_DIGEST_PATTERN

if str(NS.parents[1]) not in sys.path:  # the ai-knowledge-compiler repo root
    sys.path.insert(0, str(NS.parents[1]))

from infra.runpod.v6.credentials import RunPodCredentialSet

REST_BASE_URL = "https://rest.runpod.io/v1"
GRAPHQL_URL = "https://api.runpod.io/graphql"

RUNTIME_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_RUNTIME_V1.yaml"

NOT_RETRIEVED = "NOT_RETRIEVED"

_POD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")

_CREATE_POD_MUTATION = """
mutation createPod($input: PodFindAndDeployOnDemandInput!) {
  podFindAndDeployOnDemand(input: $input) {
    id
    name
    desiredStatus
    costPerHr
  }
}
"""


class ProvisioningError(RuntimeError):
    """A real Runpod call was refused or failed. Response bodies are withheld,
    matching `infra/runpod/v6/qualification_pod.py::QualificationPodError` --
    an upstream error body can reflect request contents back at the caller."""


def _require_pinned_image(image_digest: str) -> None:
    """Refuse a floating tag before any Runpod call is made.

    Reuses `gpu_successor_preflight.RUNTIME_IMAGE_DIGEST_PATTERN` rather than
    restating the `repository@sha256:<64 hex>` regex a second time -- the
    preflight already checked this once (`runtime_image_pinnable`), and this
    is the same check run again, independently, immediately before the one
    place in this whole path that would actually spend money on the answer.
    """
    if not image_digest or not RUNTIME_IMAGE_DIGEST_PATTERN.match(image_digest):
        raise ProvisioningError(
            f"runtime image {image_digest!r} is not pinned by "
            "repository@sha256:<64 hex>; refusing before any Runpod API call"
        )


def _read_runtime_gpu_declaration(path: Path = RUNTIME_PROTOCOL) -> tuple[str, int]:
    """The GPU type/count this study already declared, read fresh every call.

    Never hardcoded: `GPU_SUCCESSOR_RUNTIME_V1.yaml` is the one place this
    study names its GPU (`hardware.gpu_type.value`, currently `NVIDIA H200`,
    a `declared_assumption` copied from the closed MODEL_ENDPOINT_V1 study's
    attestation -- see that file's own comments). Reading it here instead of
    copying the string into this module means a future revision of the
    protocol cannot silently drift out of step with what actually gets
    provisioned.
    """
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ProvisioningError(
            f"could not read the runtime GPU declaration from {path}: {error}"
        ) from error
    hardware = (body or {}).get("hardware") or {}
    gpu_type = (hardware.get("gpu_type") or {}).get("value")
    gpu_count = (hardware.get("gpu_count") or {}).get("value")
    if not isinstance(gpu_type, str) or not gpu_type.strip():
        raise ProvisioningError(f"{path} carries no hardware.gpu_type.value; refusing to guess")
    if not isinstance(gpu_count, int) or gpu_count < 1:
        raise ProvisioningError(f"{path} carries no valid hardware.gpu_count.value")
    return gpu_type, gpu_count


class RunpodPodProvisioner:
    """Wired against the real Runpod REST v1 and GraphQL APIs.

    Nothing in `__init__` calls the network -- credentials are validated
    (shape only) and a client is prepared, but no request is sent until
    `provision`/`teardown` run.
    """

    def __init__(
        self,
        *,
        credentials: RunPodCredentialSet | None = None,
        rest_base_url: str = REST_BASE_URL,
        graphql_url: str = GRAPHQL_URL,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
        cloud_type: str = "SECURE",
        container_disk_gb: int = 60,
        auto_terminate_hours: float = CAP_GPU_HOURS,
        name_prefix: str = "gpu-successor-study",
        runtime_protocol_path: Path = RUNTIME_PROTOCOL,
    ) -> None:
        self._credentials = credentials or RunPodCredentialSet.from_environment(required=True)
        self._cloud_type = cloud_type
        self._container_disk_gb = container_disk_gb
        # Never wider than the study's own hard cap -- a caller passing a
        # larger number does not get a longer platform-side leash than the
        # process-local Watchdog already enforces.
        self._auto_terminate_hours = min(auto_terminate_hours, CAP_GPU_HOURS)
        self._name_prefix = name_prefix
        self._runtime_protocol_path = runtime_protocol_path
        self._rest = httpx.Client(
            base_url=rest_base_url,
            headers={
                "Authorization": f"Bearer {self._credentials.primary}",
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )
        self._graphql_url = graphql_url
        self._graphql = httpx.Client(
            headers={
                "Authorization": f"Bearer {self._credentials.primary}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._rest.close()
        self._graphql.close()

    @staticmethod
    def execution_readiness(_spec: dict[str, Any]) -> dict[str, Any]:
        """Describe why this backend cannot yet execute the scientific job.

        Pod creation and deletion are real, but this backend currently has no
        content-addressed transport into the pod, no pinned worker entrypoint,
        no terminal-status channel, and no artifact retrieval channel.  Those
        are scientific execution prerequisites, not optional conveniences.
        Returning a typed refusal here keeps `--execute` from spending money
        on an idle pod while making the remaining engineering work explicit.
        """
        missing = [
            {
                "code": "PINNED_WORKER_ENTRYPOINT_ABSENT",
                "detail": "the frozen runtime declares vLLM but no immutable worker command or worker bundle digest",
            },
            {
                "code": "CONTENT_ADDRESSED_INPUT_TRANSPORT_ABSENT",
                "detail": "no authenticated transport uploads the exact materialized input set into the pod",
            },
            {
                "code": "TERMINAL_STATUS_CHANNEL_ABSENT",
                "detail": "no authenticated channel can distinguish running/healthy from terminal completed",
            },
            {
                "code": "CONTENT_ADDRESSED_OUTPUT_RETRIEVAL_ABSENT",
                "detail": "no authenticated transport retrieves the raw scientific output and its digest",
            },
            {
                "code": "LIVE_USAGE_KILL_SWITCH_ABSENT",
                "detail": "usage is read only at teardown; no live cost poll can stop before the dollar cap",
            },
            {
                "code": "FROZEN_SUCCESSOR_SCORER_ABSENT",
                "detail": "the protocol declares answer classes but no frozen reducer/scorer implementation exists",
            },
        ]
        return {
            "passed": False,
            "backend": "runpod_pod_v1_graphql",
            "missing_prerequisites": missing,
            "reason": "Runpod pod lifecycle is wired, but the scientific execution transport is not",
        }

    def execute_scientific_workload(
        self, _handle: dict[str, Any], _spec: dict[str, Any]
    ) -> dict[str, Any]:
        """Fail closed; `execution_readiness` must be made true first."""
        raise ProvisioningError(
            "scientific execution transport is not implemented; refusing to treat a pod as execution"
        )

    # ------------------------------------------------------------------
    # provision
    # ------------------------------------------------------------------

    def provision(self, spec: dict[str, Any]) -> dict[str, Any]:
        image_digest = str(spec.get("runtime_image_digest", ""))
        _require_pinned_image(image_digest)

        # Gate 3 (see launch_gpu_successor.py's module docstring) already ran
        # in `launch()` before this method is ever called. This is the same
        # check run a second time, independently, immediately before the
        # network call it guards -- "every provisioning call is preceded by
        # the cap check, not merely followed by one" -- so a future caller of
        # `provision()` that skips `launch()`'s own gate still cannot reach
        # the API with an unbounded projection.
        projected_cost = spec.get("projected_cost") or {}
        if not projected_cost.get("within_cap"):
            raise ProvisioningError(
                "spec['projected_cost']['within_cap'] is not True; refusing to call the Runpod API"
            )

        gpu_type, gpu_count = _read_runtime_gpu_declaration(self._runtime_protocol_path)
        terminate_at = datetime.now(UTC) + timedelta(hours=self._auto_terminate_hours)
        terminate_after = terminate_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        pod_name = f"{self._name_prefix}-{terminate_at.strftime('%Y%m%dT%H%M%S')}"

        graphql_input: dict[str, Any] = {
            "cloudType": self._cloud_type,
            "containerDiskInGb": self._container_disk_gb,
            "gpuCount": gpu_count,
            "gpuTypeId": gpu_type,
            "imageName": image_digest,
            "name": pod_name,
            "startSsh": False,
            "supportPublicIp": False,
            # The platform-side stop: fires even if this whole process is
            # killed the instant --execute returns. Independent of, not a
            # replacement for, the in-process Watchdog.
            "terminateAfter": terminate_after,
        }

        pod = self._graphql_request(_CREATE_POD_MUTATION, {"input": graphql_input})
        pod_id = str(pod.get("id", "")) if isinstance(pod, dict) else ""
        if not pod_id or not _POD_ID_PATTERN.match(pod_id):
            raise ProvisioningError(
                "Runpod pod creation returned no usable id; refusing to treat "
                "this as a successful provision"
            )

        return {
            "pod_id": pod_id,
            "gpu_type": gpu_type,
            "gpu_count": gpu_count,
            "cloud_type": self._cloud_type,
            "image_digest": image_digest,
            "runpod_terminate_after": terminate_after,
            "torn_down": False,
            "actual_usage": None,
        }

    # ------------------------------------------------------------------
    # teardown -- idempotent, safe on a handle that never provisioned
    # ------------------------------------------------------------------

    def teardown(self, handle: dict[str, Any] | None) -> None:
        """Tear down whatever `provision` stood up.

        Safe to call twice (the second call is a no-op once `torn_down` is
        set) and safe to call with `handle=None` or a handle that carries no
        `pod_id` -- both mean nothing was ever provisioned, so there is
        nothing to delete. A `DELETE` that lands on an already-terminated pod
        (Runpod returns 404) is treated as success, not failure, for the same
        idempotency reason.
        """
        if not handle or handle.get("torn_down"):
            return
        pod_id = handle.get("pod_id")
        if not pod_id:
            handle["torn_down"] = True
            return

        # Read real usage before deleting -- once the pod is gone there is
        # nothing left to read it from.
        handle["actual_usage"] = self._read_usage(pod_id)
        self._delete_pod(pod_id)
        handle["torn_down"] = True

    def _read_usage(self, pod_id: str) -> dict[str, Any]:
        """Real GPU seconds and cost, read from the pod itself.

        Never falls back to the pre-flight estimate: if the pod's own
        `uptimeSeconds`/`costPerHr` cannot be read (transport failure,
        unexpected status, missing/non-numeric fields), both usage fields are
        recorded as the literal string `NOT_RETRIEVED`, never silently
        replaced by a predicted number.
        """
        try:
            response = self._rest.request("GET", f"/pods/{pod_id}")
        except httpx.HTTPError as error:
            return {
                "gpu_seconds": NOT_RETRIEVED,
                "cost_usd": NOT_RETRIEVED,
                "source": "unavailable",
                "reason": f"GET /pods/{pod_id} transport failure: {error}",
            }
        if response.status_code != 200:
            return {
                "gpu_seconds": NOT_RETRIEVED,
                "cost_usd": NOT_RETRIEVED,
                "source": "unavailable",
                "reason": f"GET /pods/{pod_id} returned status {response.status_code}",
            }
        try:
            body = response.json()
        except ValueError:
            body = None
        uptime = (body or {}).get("uptimeSeconds") if isinstance(body, dict) else None
        cost_per_hr = (body or {}).get("costPerHr") if isinstance(body, dict) else None
        if not isinstance(uptime, int | float) or not isinstance(cost_per_hr, int | float):
            return {
                "gpu_seconds": NOT_RETRIEVED,
                "cost_usd": NOT_RETRIEVED,
                "source": "unavailable",
                "reason": "pod response carried no numeric uptimeSeconds/costPerHr",
            }
        return {
            "gpu_seconds": float(uptime),
            "cost_usd": float(cost_per_hr) * (float(uptime) / 3600.0),
            "source": "runpod_pod_snapshot_before_teardown",
        }

    def _delete_pod(self, pod_id: str) -> None:
        try:
            response = self._rest.request("DELETE", f"/pods/{pod_id}")
        except httpx.HTTPError as error:
            raise ProvisioningError(f"Runpod DELETE /pods/{pod_id} transport failure") from error
        # 404 means the pod is already gone -- another teardown path, the
        # platform's own terminateAfter, or a human already removed it. That
        # is the goal state teardown wants, not a failure.
        if response.status_code not in (200, 202, 204, 404):
            raise ProvisioningError(
                f"Runpod DELETE /pods/{pod_id} failed with status {response.status_code}"
            )

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------

    def _graphql_request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._graphql.post(
                self._graphql_url, json={"query": query, "variables": variables}
            )
        except httpx.HTTPError as error:
            raise ProvisioningError("Runpod GraphQL transport failure") from error
        if response.status_code != 200:
            raise ProvisioningError(
                f"Runpod GraphQL call failed with status {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise ProvisioningError("Runpod GraphQL response was not JSON") from error
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            raise ProvisioningError("Runpod GraphQL call returned errors")
        data = (body or {}).get("data") or {}
        pod = data.get("podFindAndDeployOnDemand")
        if not isinstance(pod, dict):
            raise ProvisioningError("Runpod GraphQL call returned no pod")
        return pod


__all__ = ["NOT_RETRIEVED", "ProvisioningError", "RunpodPodProvisioner"]
