"""Ask the provider for one worker pod, and write down exactly what was asked.

The routing rule is ARENA_CONTRACT section 11 D2 and it is not a preference:

    baked image  -> REST v2   (the image ENTRYPOINT is the arena worker)
    bootstrap    -> REST v1   (only v1 can override ENTRYPOINT / start CMD)

Every provisioning decision -- dry or live -- appends one record to
``cost/pod_provisioning.jsonl`` carrying the API version, the redacted payload
(the presigned bundle URL reduced to ``host/object-key``), the authorization
receipt path and sha256, and the price row that was quoted. A pod that appears
on the provider without a matching line here is a pod nobody authorized.

The host CUDA floor lives here too. Pod ``3xag0y00rgoj4n`` (GLM-OCR, RTX 4090
SECURE) passed its architecture preflight and then died in
``torch._C._cuda_init`` with CUDA error 804, "forward compatibility was
attempted on non supported HW": the image ships a CUDA 12.9 runtime and RunPod
placed it on a host reporting ``cudaVersion: "12.8"``, which a GeForce card
cannot bridge. The constraint was never expressed in the create payload, so
:func:`allowed_cuda_versions` turns a runtime's ``min_cuda_version`` into the
list RunPod filters hosts by, and :func:`check_cuda_constraint` refuses to
create a GPU pod for a runtime that has not declared one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from arena.constants import CAMPAIGN_ID, WORKER_PORT
from arena.controller.paths import CampaignPaths
from arena.provider.runpod_pods import (
    PodSpec,
    PriceSnapshot,
    ProviderReceipt,
    RunPodClientError,
    RunPodPodsClient,
    pod_name,
)
from arena.provider.runpod_v1 import (
    RunPodV1Client,
    render_start_cmd,
    v1_redacted_payload,
)
from arena.provider.safety import utc_now_iso, write_jsonl_append
from arena.provider.secrets import Secret

__all__ = [
    "PROVISIONING_INTENT_SCHEMA",
    "PROVISIONING_SCHEMA",
    "RUNPOD_CUDA_VERSIONS",
    "CudaConstraint",
    "ProvisionError",
    "ProvisionResult",
    "allowed_cuda_versions",
    "build_pod_spec",
    "check_cuda_constraint",
    "check_runtime_mode",
    "parse_cuda_version",
    "provision_pod",
    "record_provisioning",
    "record_provisioning_intent",
]

PROVISIONING_SCHEMA: Final = "tavonel.arena.pod_provisioning.v1"
# ARENA_CONTRACT 11.5 D24: written *before* the POST, so an ambiguous create
# leaves a line naming the pod even when the response never arrives.
PROVISIONING_INTENT_SCHEMA: Final = "tavonel.arena.pod_provisioning_intent.v1"
DEFAULT_CONTAINER_DISK_GB: Final = 80

#: Every CUDA version RunPod will filter hosts by, from the REST v1
#: ``PodCreateInput.allowedCudaVersions`` enum in the 2026-09-03 OpenAPI
#: snapshot (REST v2's ``CreateGpuConfig.allowedCudaVersions`` takes the same
#: ``major.minor`` strings, unconstrained). Ordered low to high; the create
#: payload sends every entry at or above the runtime's floor, because a host on
#: a newer driver runs an older-CUDA image and excluding it only costs capacity.
RUNPOD_CUDA_VERSIONS: Final = (
    "11.8",
    "12.0",
    "12.1",
    "12.2",
    "12.3",
    "12.4",
    "12.5",
    "12.6",
    "12.7",
    "12.8",
    "12.9",
    "13.0",
)
_CUDA_VERSION_RE: Final = re.compile(r"^\d+\.\d+$")


class ProvisionError(RuntimeError):
    """The pod could not be described or created as specified."""


def parse_cuda_version(value: str) -> tuple[int, int]:
    """``"12.9"`` -> ``(12, 9)``, compared component-wise, never as a decimal.

    RunPod documents the comparison as numeric per component, so 12.11 is
    *above* 12.2. Reading these as floats would order them the other way round
    and silently drop the newest hosts from the allowed list.
    """

    if not isinstance(value, str) or not _CUDA_VERSION_RE.fullmatch(value):
        raise ProvisionError(f"CUDA version {value!r} is not major.minor")
    major, _, minor = value.partition(".")
    return int(major), int(minor)


def allowed_cuda_versions(min_cuda_version: str) -> tuple[str, ...]:
    """Every version RunPod offers at or above ``min_cuda_version``.

    A floor RunPod does not list at all is a refusal, not an empty filter: an
    empty ``allowedCudaVersions`` states "no constraint" to the provider, which
    is the opposite of what a floor means, and would place the pod on exactly
    the host that failed.
    """

    floor = parse_cuda_version(min_cuda_version)
    allowed = tuple(
        version for version in RUNPOD_CUDA_VERSIONS if parse_cuda_version(version) >= floor
    )
    if not allowed:
        raise ProvisionError(
            f"min_cuda_version {min_cuda_version!r} is above every CUDA version RunPod "
            f"lists {list(RUNPOD_CUDA_VERSIONS)}; no host can run this image"
        )
    return allowed


@dataclass(frozen=True, slots=True)
class CudaConstraint:
    """The host CUDA floor one runtime asked for, and what it becomes."""

    model_key: str
    runtime_json: str
    min_cuda_version: str
    allowed_cuda_versions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "runtime_json": self.runtime_json,
            "min_cuda_version": self.min_cuda_version,
            "allowed_cuda_versions": list(self.allowed_cuda_versions),
            "provider_field": "allowedCudaVersions",
        }


def check_cuda_constraint(
    *,
    model_key: str,
    runtime_json: str,
    min_cuda_version: str | None,
    gpu_pool_priority: Sequence[str],
) -> CudaConstraint:
    """Refuse to create a GPU pod for a runtime with no declared CUDA floor.

    The trigger is "this runtime rents a GPU", read from its own
    ``gpu_pool_priority``, not from the base image's *name*. D25 already
    refused a name heuristic for the compute-capability floor, and the name is
    wrong here in both directions: ``paddlepaddle/paddleocr-vl`` says nothing
    about CUDA and still installs a cu126 build, while a name carrying
    ``cuda12.9`` would only repeat what the image config already states. The
    version itself always comes from evidence recorded in the runtime lane.
    """

    if not gpu_pool_priority:
        raise ProvisionError(f"{runtime_json}.gpu_pool_priority is empty; no GPU could be rented")
    if min_cuda_version is None:
        raise ProvisionError(
            f"{model_key} rents a GPU but {runtime_json} declares no min_cuda_version. "
            "A CUDA image placed on a host with an older driver fails at "
            "torch._C._cuda_init with error 804 after the pod is already billing "
            "(pod 3xag0y00rgoj4n). Record the base image's CUDA runtime there first."
        )
    return CudaConstraint(
        model_key=model_key,
        runtime_json=runtime_json,
        min_cuda_version=min_cuda_version,
        allowed_cuda_versions=allowed_cuda_versions(min_cuda_version),
    )


def build_pod_spec(
    *,
    model_key: str,
    replica_index: int,
    image_name: str,
    image_digest: str,
    model_revision: str,
    runtime_mode: str,
    gpu_type_ids: Sequence[str],
    gpu_count: int,
    max_lifetime_hours: int,
    cloud_type: str = "SECURE",
    container_disk_gb: int = DEFAULT_CONTAINER_DISK_GB,
    volume_gb: int = 0,
    data_center_ids: Sequence[str] = (),
    worker_token: Secret | None = None,
    bundle_url: Secret | None = None,
    bundle_sha256: str | None = None,
    prompt_id: str | None = None,
    allowed_cuda_versions: Sequence[str] = (),
    extra_env: Mapping[str, str] | None = None,
) -> PodSpec:
    """One arena worker pod, named by the contract's convention."""

    return PodSpec(
        name=pod_name(model_key, replica_index),
        image_name=image_name,
        prompt_id=prompt_id,
        gpu_type_ids=tuple(gpu_type_ids),
        allowed_cuda_versions=tuple(allowed_cuda_versions),
        model_key=model_key,
        model_revision=model_revision,
        runtime_mode=runtime_mode,
        image_digest=image_digest,
        cloud_type=cloud_type,
        gpu_count=gpu_count,
        container_disk_gb=container_disk_gb,
        ports=(f"{WORKER_PORT}/http",),
        volume_gb=volume_gb,
        data_center_ids=tuple(data_center_ids),
        max_lifetime_hours=max_lifetime_hours,
        worker_token=worker_token,
        bundle_url=bundle_url,
        bundle_sha256=bundle_sha256,
        extra_env=dict(extra_env or {}),
    )


def check_runtime_mode(
    runtime_mode: str, allowed: Sequence[str], *, runtime_json: str
) -> None:
    """ARENA_CONTRACT 11.5 D25: the computed mode must be permitted.

    The refusal names the file that forbids it, because the answer is always
    "edit that runtime.json or pick the other mode", and a message that only
    says "mode not allowed" leaves the operator guessing which of the eleven
    runtimes objected.
    """

    if runtime_mode not in allowed:
        raise ProvisionError(
            f"runtime mode {runtime_mode!r} is not in runtime_mode_allowed {list(allowed)}; "
            f"{runtime_json} forbids it (ARENA_CONTRACT 11.5 D25)"
        )


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    provider_api_version: str
    mode: str
    pod_id: str | None
    redacted_payload: Mapping[str, object]
    summary: Mapping[str, object] = field(default_factory=dict)
    #: One entry per create request the provider answered, in the order they
    #: were sent. A pool walk leaves the refusals here rather than only the
    #: attempt that succeeded.
    attempts: tuple[Mapping[str, object], ...] = ()

    @property
    def gpu_type_id_created(self) -> str | None:
        """The GPU type the provider reports for the pod it created.

        D48: when the pod record answers with no GPU type -- which a v1 record
        does for a pod that has not scheduled yet -- the winning create attempt
        is what names it, because the walk sends exactly one type per request.
        """

        value = self.summary.get("gpu_type_id")
        if isinstance(value, str) and value:
            return value
        for attempt in reversed(self.attempts):
            if attempt.get("created") is not True:
                continue
            sent = attempt.get("gpu_type_ids")
            if isinstance(sent, list) and sent:
                return str(sent[0])
        return None

    @property
    def host_cuda_version(self) -> str | None:
        """The host CUDA version the pod record reports, when it carries one."""

        value = self.summary.get("cuda_version")
        return value if isinstance(value, str) and value else None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_api_version": self.provider_api_version,
            "mode": self.mode,
            "pod_id": self.pod_id,
            "redacted_payload": dict(self.redacted_payload),
            "summary": dict(self.summary),
            "attempts": [dict(attempt) for attempt in self.attempts],
        }


def provision_pod(
    spec: PodSpec,
    *,
    v1_client: RunPodV1Client | None = None,
    v2_client: RunPodPodsClient | None = None,
    price_snapshot: PriceSnapshot | None = None,
) -> ProvisionResult:
    """Create the pod on the API its runtime mode requires (D2)."""

    if spec.runtime_mode == "bootstrap":
        if v1_client is None:
            raise ProvisionError("a bootstrap pod needs the REST v1 client")
        return _provision_v1(spec, v1_client, price_snapshot)
    if spec.runtime_mode == "baked":
        if v2_client is None:
            raise ProvisionError("a baked pod needs the REST v2 client")
        return _provision_v2(spec, v2_client, price_snapshot)
    raise ProvisionError(f"unknown runtime mode {spec.runtime_mode!r}")


def _create_attempts(
    receipts: Sequence[ProviderReceipt],
) -> tuple[Mapping[str, object], ...]:
    """The create requests one ``create_pod`` call made, in order.

    Both clients walk the GPU priority list and receipt every attempt, so the
    walk is already on disk. This projection is what the pod ledger keeps, so a
    line records the refusals as well as the attempt that answered.
    """

    attempts: list[Mapping[str, object]] = []
    for receipt in receipts:
        if receipt.action != "create_pod":
            continue
        summary = receipt.summary
        attempts.append(
            {
                "attempt": summary.get("attempt"),
                "gpu_type_ids": summary.get("gpu_type_ids"),
                "created": summary.get("created"),
                "adopted": summary.get("adopted"),
                "refused": summary.get("refused"),
                "status_code": receipt.status_code,
            }
        )
    return tuple(attempts)


def _winning_gpu_types(
    attempts: Sequence[Mapping[str, object]], spec: PodSpec
) -> tuple[str, ...]:
    """The GPU list the create that succeeded actually sent.

    The redacted payload written to the ledger must be the request the provider
    answered, not the one the walk started from; falling back to the whole
    priority list would leave a receipt describing a payload nobody sent.
    """

    for attempt in reversed(attempts):
        if attempt.get("created") is not True:
            continue
        sent = attempt.get("gpu_type_ids")
        if isinstance(sent, list) and sent:
            return tuple(str(item) for item in sent)
    return tuple(spec.gpu_type_ids)


def _provision_v1(
    spec: PodSpec, client: RunPodV1Client, price_snapshot: PriceSnapshot | None
) -> ProvisionResult:
    if spec.bundle_sha256 is None:  # pragma: no cover - PodSpec refuses this first
        raise ProvisionError("a bootstrap pod needs the bundle sha256")
    command = render_start_cmd(spec.model_key, spec.bundle_sha256)
    redacted = v1_redacted_payload(spec, gpu_type_ids=spec.gpu_type_ids, start_command=command)
    start_cmd = redacted["dockerStartCmd"]
    if not isinstance(start_cmd, list) or len(start_cmd) != 1:
        raise ProvisionError("dockerStartCmd must carry exactly one element")
    mark = len(client.receipts)
    try:
        outcome = client.create_pod(spec, price_snapshot=price_snapshot)
    except RunPodClientError as exc:
        raise ProvisionError(f"REST v1 refused the create: {exc}") from exc
    attempts = _create_attempts(client.receipts[mark:])
    if isinstance(outcome, ProviderReceipt):
        return ProvisionResult(
            provider_api_version="v1",
            mode="dry_run",
            pod_id=None,
            redacted_payload=redacted,
            summary=dict(outcome.summary),
            attempts=attempts,
        )
    return ProvisionResult(
        provider_api_version="v1",
        mode="live",
        pod_id=outcome.pod_id,
        redacted_payload=v1_redacted_payload(
            spec,
            gpu_type_ids=_winning_gpu_types(attempts, spec),
            start_command=command,
        ),
        summary=outcome.to_summary(),
        attempts=attempts,
    )


def _provision_v2(
    spec: PodSpec, client: RunPodPodsClient, price_snapshot: PriceSnapshot | None
) -> ProvisionResult:
    redacted = spec.redacted_payload(spec.gpu_type_ids[0])
    mark = len(client.receipts)
    try:
        outcome = client.create_pod(spec, price_snapshot=price_snapshot)
    except RunPodClientError as exc:
        raise ProvisionError(f"REST v2 refused the create: {exc}") from exc
    attempts = _create_attempts(client.receipts[mark:])
    if isinstance(outcome, ProviderReceipt):
        return ProvisionResult(
            provider_api_version="v2",
            mode="dry_run",
            pod_id=None,
            redacted_payload=redacted,
            summary=dict(outcome.summary),
            attempts=attempts,
        )
    summary = outcome.to_summary()
    created = summary.get("gpu_type_id")
    return ProvisionResult(
        provider_api_version="v2",
        mode="live",
        pod_id=outcome.pod_id,
        redacted_payload=spec.redacted_payload(
            created if isinstance(created, str) and created in spec.gpu_type_ids
            else spec.gpu_type_ids[0]
        ),
        summary=summary,
        attempts=attempts,
    )


def record_provisioning_intent(
    paths: CampaignPaths,
    *,
    spec: PodSpec,
    phase: str,
    provider_api_version: str,
    required_usd: float | None,
    authorization_receipt_path: str | None,
    authorization_receipt_sha256: str | None,
    campaign_id: str = CAMPAIGN_ID,
) -> dict[str, object]:
    """Write the D24 provisional ledger line **before** the create is sent.

    A create that times out or answers 5xx may still have produced a billing
    pod. If the only record were written after a successful response, that pod
    would exist with nothing on disk naming it. This line names it first --
    ``pod_name`` is deterministic, so the reconciler can find the pod from the
    line even when the response never arrived.
    """

    record: dict[str, object] = {
        "schema": PROVISIONING_INTENT_SCHEMA,
        "campaign_id": campaign_id,
        "recorded_at": utc_now_iso(),
        "phase": phase,
        "mode": "intent",
        "provider_api_version": provider_api_version,
        "pod_id": None,
        "pod_name": spec.name,
        "model_key": spec.model_key,
        "runtime_mode": spec.runtime_mode,
        "gpu_pool_priority": list(spec.gpu_type_ids),
        "gpu_count": spec.gpu_count,
        "allowed_cuda_versions": list(spec.allowed_cuda_versions),
        "cloud_type": spec.cloud_type,
        "container_disk_gb": spec.container_disk_gb,
        "volume_gb": spec.volume_gb,
        "max_pod_lifetime_hours": spec.max_lifetime_hours,
        "required_usd": None if required_usd is None else round(required_usd, 4),
        "authorization_receipt_path": authorization_receipt_path,
        "authorization_receipt_sha256": authorization_receipt_sha256,
        "note": (
            "provisional: the create request had not been answered when this line was "
            "written. A pod with this name may exist even if no live line follows."
        ),
    }
    write_jsonl_append(
        paths.pod_provisioning_ledger, record, context="pod provisioning intent"
    )
    return record


def record_provisioning(
    paths: CampaignPaths,
    *,
    result: ProvisionResult,
    spec: PodSpec,
    phase: str,
    authorization_receipt_path: str | None,
    authorization_receipt_sha256: str | None,
    price_snapshot_sha256: str | None,
    price_row_sha256: str | None,
    listed_rate_usd_per_hour: float | None,
    required_usd: float | None,
    campaign_id: str = CAMPAIGN_ID,
) -> dict[str, object]:
    """Append the create-time pod-ledger line (D2, D6) and return it."""

    record: dict[str, object] = {
        "schema": PROVISIONING_SCHEMA,
        "campaign_id": campaign_id,
        "recorded_at": utc_now_iso(),
        "phase": phase,
        "mode": result.mode,
        "provider_api_version": result.provider_api_version,
        "pod_id": result.pod_id,
        "pod_name": spec.name,
        "model_key": spec.model_key,
        "model_revision": spec.model_revision,
        "runtime_mode": spec.runtime_mode,
        "runtime_image_digest": spec.image_digest,
        "gpu_pool_priority": list(spec.gpu_type_ids),
        # Which pool entry the provider actually rented, and which CUDA
        # versions it was allowed to pick a host from. The priority list alone
        # does not say which entry answered once the pool is walked.
        "gpu_type_id_created": result.gpu_type_id_created,
        "gpu_count": spec.gpu_count,
        "allowed_cuda_versions": list(spec.allowed_cuda_versions),
        "host_cuda_version": result.host_cuda_version,
        "provider_attempts": [dict(attempt) for attempt in result.attempts],
        "cloud_type": spec.cloud_type,
        "container_disk_gb": spec.container_disk_gb,
        "volume_gb": spec.volume_gb,
        "max_pod_lifetime_hours": spec.max_lifetime_hours,
        "bundle_sha256": spec.bundle_sha256,
        "authorization_receipt_path": authorization_receipt_path,
        "authorization_receipt_sha256": authorization_receipt_sha256,
        "price_snapshot_sha256": price_snapshot_sha256,
        "price_row_sha256": price_row_sha256,
        "listed_rate_usd_per_hour": listed_rate_usd_per_hour,
        "required_usd": None if required_usd is None else round(required_usd, 4),
        "create_payload_redacted": dict(result.redacted_payload),
    }
    write_jsonl_append(paths.pod_provisioning_ledger, record, context="pod provisioning ledger")
    return record
