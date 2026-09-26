"""RunPod REST v2 pods client for the arena (ARENA_CONTRACT section 5).

Design rules that are contract, not style:

- **Dry run by default.** Without ``execute=True`` no socket is opened; every
  call returns a :class:`ProviderReceipt` describing the exact request.
- **Zero client-side retries on writes.** Replaying an ambiguous create can
  produce a second paid pod. Reads are not retried either; the caller decides.
- **Strict parsing.** An unknown pod status, an unknown cloud tier or a
  missing required field is a protocol error, never a shrug.
- **Idempotent create.** ``create_pod`` lists first and adopts an existing pod
  with the same name and campaign tag rather than creating a duplicate.
- **The key never leaves this module.** It is held as a
  :class:`~arena.provider.secrets.Secret` and revealed only when the
  ``Authorization`` header is built. No receipt, error or log carries it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from types import MappingProxyType, TracebackType
from typing import Any, Final, Self

import httpx

from arena.constants import CAMPAIGN_ID, WORKER_PORT
from arena.provider.safety import (
    assert_secret_free,
    canonical_sha256,
    timestamp_slug,
    utc_now_iso,
    write_json_atomic,
)
from arena.provider.secrets import Secret

__all__ = [
    "CAMPAIGN_SHORT",
    "USER_AGENT",
    "BillingWindow",
    "GpuPriceRow",
    "Pod",
    "PodSpec",
    "PriceSnapshot",
    "ProviderReceipt",
    "RunPodClientError",
    "RunPodPodsClient",
    "RunPodProtocolError",
    "is_campaign_pod_name",
    "pod_name",
]

MANAGEMENT_BASE_URL: Final = "https://api.runpod.io/v2"
CAMPAIGN_SHORT: Final = "20260903v1"
CAMPAIGN_ENV_KEY: Final = "ARENA_CAMPAIGN_ID"

# Cloudflare in front of api.runpod.io answers 403 (error 1010) to the default
# Python User-Agent -- observed 2026-09-03. Both API versions send an explicit
# one (ARENA_CONTRACT section 11 D2).
USER_AGENT: Final = f"tavonel-arena/1 (+{CAMPAIGN_ID})"

POD_STATUSES: Final = ("PROVISIONING", "STARTING", "RUNNING", "EXITED", "ERROR", "TERMINATED")
LIVE_POD_STATUSES: Final = frozenset({"PROVISIONING", "STARTING", "RUNNING"})
CLOUD_TYPES: Final = ("SECURE", "COMMUNITY")
POD_ACTIONS: Final = ("start", "stop", "restart", "terminate")
BILLING_BUCKETS: Final = ("hour", "day", "week", "month", "year")
# The log endpoint keeps the two sources as separate sequences, not one
# time-ordered stream, so a tail over "both" keeps only whichever block comes
# last. Every caller that needs both asks for each source separately.
LOG_SOURCES: Final = ("container", "system", "both")

# Secrets and presigned URLs are passed to the pod but never written down.
REDACTED_ENV_KEYS: Final = frozenset({"ARENA_WORKER_TOKEN", "ARENA_BUNDLE_URL", "HF_TOKEN"})

# ARENA_CONTRACT 11.3(2) / 11.5 D17: the bundle unpacks prompt_registry/ here
# and every baked Dockerfile copies it to the same place, so one env value
# resolves the prompt in both runtime modes.
POD_PROMPT_REGISTRY_DIR: Final = "/opt/arena/prompt_registry"

_POD_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_ENV_NAME_RE: Final = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_POD_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODEL_KEY_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_]{0,60}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CUDA_VERSION_RE: Final = re.compile(r"^\d+\.\d+$")


class RunPodClientError(RuntimeError):
    """Sanitized provider or transport failure. Response bodies are withheld.

    An upstream service can reflect request headers into an error body, so the
    body never reaches an exception message or a receipt.
    """


class RunPodProtocolError(RunPodClientError):
    """The response no longer matches the pinned REST v2 contract."""


def is_campaign_pod_name(name: str, *, campaign_short: str = CAMPAIGN_SHORT) -> bool:
    """``arena-...-<campaign short>`` (ARENA_CONTRACT 11.5 D24).

    Campaign membership is normally read from ``ARENA_CAMPAIGN_ID`` in the pod
    env, but a pod whose env the provider does not return -- or whose env was
    lost to a partial create -- would then look like somebody else's pod and
    survive cleanup. The name is the second, independent witness: this campaign
    is the only thing on this account that names pods this way.
    """

    return name.startswith("arena-") and name.endswith(f"-{campaign_short}")


def pod_name(model_key: str, replica_index: int, *, campaign_short: str = CAMPAIGN_SHORT) -> str:
    """``arena-<model_key>-w<n>-<campaign short>`` (ARENA_CONTRACT section 5)."""

    if not _MODEL_KEY_RE.fullmatch(model_key):
        raise RunPodClientError(f"model_key {model_key!r} is not a valid arena model key")
    if replica_index < 0:
        raise RunPodClientError("replica index must be non-negative")
    name = f"arena-{model_key}-w{replica_index}-{campaign_short}".replace("_", "-")
    if not _POD_NAME_RE.fullmatch(name):
        raise RunPodClientError(f"derived pod name {name!r} is not provider-safe")
    return name


@dataclass(frozen=True, slots=True)
class PodSpec:
    """Everything needed to create one arena worker pod.

    ``worker_token`` and ``bundle_url`` are held apart from ``env`` so the
    redacted payload written into a receipt cannot accidentally include them.
    """

    name: str
    image_name: str
    gpu_type_ids: tuple[str, ...]
    model_key: str
    model_revision: str
    runtime_mode: str
    image_digest: str
    cloud_type: str = "COMMUNITY"
    gpu_count: int = 1
    container_disk_gb: int = 80
    ports: tuple[str, ...] = (f"{WORKER_PORT}/http",)
    network_volume_id: str | None = None
    network_volume_path: str = "/workspace"
    volume_gb: int = 0
    data_center_ids: tuple[str, ...] = ()
    # Host CUDA versions this pod may be placed on, as ``major.minor``. Empty
    # states no constraint to the provider, so the controller's CUDA gate
    # (arena.controller.provision) fills it before a GPU pod is created --
    # pod 3xag0y00rgoj4n died with CUDA error 804 for want of it.
    allowed_cuda_versions: tuple[str, ...] = ()
    max_lifetime_hours: int = 6
    campaign_id: str = CAMPAIGN_ID
    # ARENA_CONTRACT 11.5 D15/D17: the prompt the worker must resolve on the
    # pod. It is an id, never the prompt text -- the text travels in the bundle
    # and in the baked image, and the run request carries only its sha256.
    prompt_id: str | None = None
    worker_token: Secret | None = None
    bundle_url: Secret | None = None
    bundle_sha256: str | None = None
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _POD_NAME_RE.fullmatch(self.name):
            raise RunPodClientError(f"pod name {self.name!r} is not provider-safe")
        if not self.image_name.strip():
            raise RunPodClientError("image name is required")
        if not self.gpu_type_ids:
            raise RunPodClientError("at least one gpuTypeId is required")
        if self.cloud_type not in CLOUD_TYPES:
            raise RunPodClientError(f"cloud tier must be one of {CLOUD_TYPES}")
        if self.runtime_mode not in {"baked", "bootstrap"}:
            raise RunPodClientError("runtime_mode must be 'baked' or 'bootstrap'")
        if self.runtime_mode == "bootstrap" and self.bundle_url is None:
            raise RunPodClientError("bootstrap mode requires a presigned bundle URL")
        if self.runtime_mode == "bootstrap" and (
            self.bundle_sha256 is None or not _SHA256_HEX_RE.fullmatch(self.bundle_sha256)
        ):
            # ARENA_CONTRACT 11.3(1): the digest is pinned into the start command,
            # so a bootstrap spec without it could accept any bundle.
            raise RunPodClientError(
                "bootstrap mode requires bundle_sha256 as 64 lowercase hex characters"
            )
        if self.gpu_count < 1:
            raise RunPodClientError("gpu_count must be positive")
        if self.container_disk_gb < 1:
            raise RunPodClientError("container disk must be positive")
        if self.volume_gb < 0:
            raise RunPodClientError("volume_gb must not be negative")
        if self.max_lifetime_hours < 1:
            raise RunPodClientError("max_lifetime_hours must be positive")
        for version in self.allowed_cuda_versions:
            if not _CUDA_VERSION_RE.fullmatch(version):
                raise RunPodClientError(
                    f"allowed CUDA version {version!r} must be major.minor, as both REST v1's "
                    "allowedCudaVersions enum and REST v2's gpu.allowedCudaVersions pattern "
                    "require"
                )
        if self.network_volume_id is not None and not self.data_center_ids:
            raise RunPodClientError(
                "a network volume only attaches when the pod is pinned to its data center"
            )
        for key in self.extra_env:
            if not _ENV_NAME_RE.fullmatch(key):
                raise RunPodClientError(f"environment name {key!r} must be an uppercase identifier")
            if key in REDACTED_ENV_KEYS:
                raise RunPodClientError(f"{key} must be passed as a Secret, not through extra_env")

    def env(self) -> dict[str, str]:
        """Full pod environment including secrets. Never write this to disk."""

        values: dict[str, str] = {
            "ARENA_CAMPAIGN_ID": self.campaign_id,
            "ARENA_MODEL_KEY": self.model_key,
            "ARENA_MODEL_REVISION": self.model_revision,
            "ARENA_RUNTIME_MODE": self.runtime_mode,
            "ARENA_IMAGE_DIGEST": self.image_digest,
            "ARENA_MAX_POD_AGE_HOURS": str(self.max_lifetime_hours),
            "ARENA_WORKER_PORT": str(WORKER_PORT),
        }
        if self.prompt_id is not None:
            # D17: the worker resolves ARENA_PROMPT_FILE, fails closed when it
            # is missing, and refuses a run whose prompt_sha256 differs from
            # the file's hash.
            values["ARENA_PROMPT_ID"] = self.prompt_id
            values["ARENA_PROMPT_FILE"] = f"{POD_PROMPT_REGISTRY_DIR}/{self.prompt_id}.txt"
        values.update(dict(self.extra_env))
        if self.worker_token is not None:
            values["ARENA_WORKER_TOKEN"] = self.worker_token.reveal()
        if self.bundle_url is not None:
            values["ARENA_BUNDLE_URL"] = self.bundle_url.reveal()
        return values

    def to_payload(self, gpu_type_id: str) -> dict[str, object]:
        """REST v2 ``CreatePodRequest`` for a **baked** image.

        v2 has no ENTRYPOINT override (only ``args``), so a bootstrap spec has
        no v2 payload at all -- it goes through
        :mod:`arena.provider.runpod_v1` (ARENA_CONTRACT section 11 D2).
        """

        if self.runtime_mode != "baked":
            raise RunPodClientError(
                "REST v2 cannot override an image ENTRYPOINT; a bootstrap pod is created "
                "through arena.provider.runpod_v1 (ARENA_CONTRACT section 11 D2)"
            )
        if gpu_type_id not in self.gpu_type_ids:
            raise RunPodClientError("gpu_type_id must come from the spec's priority list")
        gpu: dict[str, object] = {"id": gpu_type_id, "count": self.gpu_count}
        if self.allowed_cuda_versions:
            # v2 carries the host CUDA constraint inside ``gpu`` (OpenAPI
            # ``CreateGpuConfig``), not at the body's top level as v1 does, so
            # it is unrepresentable on a CPU pod. The floor is expressed as the
            # allowed *set* rather than ``minCudaVersion`` because the two are
            # mutually exclusive and v1 -- the bootstrap path -- offers only
            # the set; sending the same shape on both keeps the receipts
            # comparable.
            gpu["allowedCudaVersions"] = list(self.allowed_cuda_versions)
        payload: dict[str, object] = {
            "name": self.name,
            "image": self.image_name,
            "cloud": self.cloud_type,
            "gpu": gpu,
            "disk": self.container_disk_gb,
            "ports": list(self.ports),
            "env": self.env(),
        }
        if self.data_center_ids:
            payload["dataCenterIds"] = list(self.data_center_ids)
        if self.network_volume_id is not None:
            payload["mounts"] = {
                "network": [
                    {"volumeId": self.network_volume_id, "path": self.network_volume_path}
                ]
            }
        return payload

    def redacted_payload(self, gpu_type_id: str) -> dict[str, object]:
        """The payload with every secret env value replaced. Receipt-safe."""

        payload = self.to_payload(gpu_type_id)
        payload["env"] = {
            key: ("<redacted>" if key in REDACTED_ENV_KEYS else value)
            for key, value in sorted(self.env().items())
        }
        return payload


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    """One provider interaction, live or dry. Never carries the key."""

    action: str
    method: str
    url: str
    mode: str  # "dry_run" | "live"
    request_sha256: str
    ts: str
    status_code: int | None = None
    summary: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": "tavonel.arena.provider_receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "action": self.action,
            "method": self.method,
            "url": self.url,
            "mode": self.mode,
            "request_sha256": self.request_sha256,
            "status_code": self.status_code,
            "ts": self.ts,
            "key_withheld": True,
            "summary": dict(self.summary),
        }
        assert_secret_free(value, context=f"provider receipt {self.action}")
        return value


@dataclass(frozen=True, slots=True)
class Pod:
    pod_id: str
    name: str
    status: str
    cloud: str
    image: str
    cost_usd_per_hour: float
    data_center_id: str | None
    gpu_type_id: str | None
    gpu_count: int
    created_at: str
    started_at: str | None
    env: Mapping[str, str]
    uptime_seconds: int | None
    gpu_utilization_percent: float | None

    @property
    def campaign_id(self) -> str | None:
        return self.env.get(CAMPAIGN_ENV_KEY)

    @property
    def model_key(self) -> str | None:
        return self.env.get("ARENA_MODEL_KEY")

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_POD_STATUSES

    def belongs_to(self, campaign_id: str) -> bool:
        """D24: the campaign env tag **or** the arena pod-name prefix."""

        return self.campaign_id == campaign_id or is_campaign_pod_name(self.name)

    def to_summary(self) -> dict[str, object]:
        """Receipt-safe projection: env values are dropped, only names kept."""

        return {
            "pod_id": self.pod_id,
            "name": self.name,
            "status": self.status,
            "cloud": self.cloud,
            "image": self.image,
            "cost_usd_per_hour": self.cost_usd_per_hour,
            "data_center_id": self.data_center_id,
            "gpu_type_id": self.gpu_type_id,
            "gpu_count": self.gpu_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "env_names": sorted(self.env),
            "campaign_id": self.campaign_id,
            "model_key": self.model_key,
            "uptime_seconds": self.uptime_seconds,
            "gpu_utilization_percent": self.gpu_utilization_percent,
        }


@dataclass(frozen=True, slots=True)
class GpuPriceRow:
    gpu_type_id: str
    display_name: str
    memory_gb: int
    secure_available: bool
    community_available: bool
    price_secure_usd_per_hour: float | None
    price_community_usd_per_hour: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "gpu_type_id": self.gpu_type_id,
            "display_name": self.display_name,
            "memory_gb": self.memory_gb,
            "secure_available": self.secure_available,
            "community_available": self.community_available,
            "price_secure_usd_per_hour": self.price_secure_usd_per_hour,
            "price_community_usd_per_hour": self.price_community_usd_per_hour,
        }

    def row_sha256(self) -> str:
        """The hash recorded on every provisioning decision (MP section 13.2)."""

        return canonical_sha256(self.to_dict())

    def rate_for(self, cloud: str) -> float | None:
        """The hourly rate on this cloud tier, or ``None`` when there is none.

        The live catalog reports ``0.0`` for a GPU that tier does not offer --
        observed 2026-09-03 on ``NVIDIA A100-SXM4-40GB`` (secure 0.0, community
        1.0) and on a placeholder row whose id is literally ``unknown``. Zero is
        an absent price, not a free GPU, and returning it as a rate would put a
        $0 line into a cost projection and a budget watchdog.
        """

        if cloud == "SECURE":
            rate = self.price_secure_usd_per_hour
        elif cloud == "COMMUNITY":
            rate = self.price_community_usd_per_hour
        else:
            raise RunPodClientError(f"unknown cloud tier {cloud!r}")
        return rate if rate is not None and rate > 0.0 else None


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """A catalog read, frozen. Provisioning quotes a row hash from here."""

    captured_at: str
    rows: tuple[GpuPriceRow, ...]
    path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.price_snapshot.v1",
            "campaign_id": CAMPAIGN_ID,
            "captured_at": self.captured_at,
            "source": f"{MANAGEMENT_BASE_URL}/catalog/gpus",
            "row_count": len(self.rows),
            "rows": [row.to_dict() for row in self.rows],
        }

    def snapshot_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def row(self, gpu_type_id: str) -> GpuPriceRow:
        for row in self.rows:
            if row.gpu_type_id == gpu_type_id:
                return row
        raise RunPodClientError(f"gpu type {gpu_type_id!r} is absent from the price snapshot")

    def cheapest(self, gpu_type_ids: Sequence[str], cloud: str) -> GpuPriceRow | None:
        """The cheapest of these GPUs that this tier actually prices.

        A row the tier does not offer has no rate (see :meth:`GpuPriceRow.rate_for`)
        and is skipped rather than winning at $0.
        """

        priced = [
            row
            for gpu_type_id in gpu_type_ids
            for row in (self._maybe_row(gpu_type_id),)
            if row is not None and row.rate_for(cloud) is not None
        ]
        if not priced:
            return None
        return min(priced, key=lambda row: row.rate_for(cloud) or 0.0)

    def priced_rows(self, cloud: str) -> tuple[GpuPriceRow, ...]:
        """Every row this cloud tier actually prices."""

        return tuple(row for row in self.rows if row.rate_for(cloud) is not None)

    def _maybe_row(self, gpu_type_id: str) -> GpuPriceRow | None:
        try:
            return self.row(gpu_type_id)
        except RunPodClientError:
            return None


@dataclass(frozen=True, slots=True)
class BillingWindow:
    bucket_size: str = "hour"
    last_n: int | None = 24
    start_time: str | None = None
    end_time: str | None = None
    pod_id: str | None = None

    def __post_init__(self) -> None:
        if self.bucket_size not in BILLING_BUCKETS:
            raise RunPodClientError(f"bucketSize must be one of {BILLING_BUCKETS}")
        if self.last_n is not None and (self.start_time or self.end_time):
            raise RunPodClientError("lastN is mutually exclusive with startTime/endTime")
        if self.last_n is None and not (self.start_time and self.end_time):
            raise RunPodClientError("provide lastN, or both startTime and endTime")
        if self.last_n is not None and self.last_n < 1:
            raise RunPodClientError("lastN must be positive")

    def to_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {"bucketSize": self.bucket_size}
        if self.last_n is not None:
            params["lastN"] = self.last_n
        if self.start_time:
            params["startTime"] = self.start_time
        if self.end_time:
            params["endTime"] = self.end_time
        if self.pod_id:
            params["podId"] = self.pod_id
        return params


class RunPodPodsClient:
    """REST v2 pods, catalog and billing. Reads are safe; writes are gated."""

    def __init__(
        self,
        *,
        key: Secret,
        execute: bool = False,
        base_url: str = MANAGEMENT_BASE_URL,
        campaign_id: str = CAMPAIGN_ID,
        receipts_dir: Path | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise RunPodClientError("the provider base URL must be https")
        self._key = key
        self.execute = execute
        self.base_url = base_url.rstrip("/")
        self.campaign_id = campaign_id
        self.receipts_dir = receipts_dir
        self._timeout_seconds = timeout_seconds
        self._receipts: list[ProviderReceipt] = []
        self._http: httpx.Client | None = None
        if execute:
            self._http = httpx.Client(
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                transport=transport,
            )

    def __repr__(self) -> str:
        return f"RunPodPodsClient(base_url={self.base_url!r}, execute={self.execute})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    @property
    def receipts(self) -> tuple[ProviderReceipt, ...]:
        return tuple(self._receipts)

    # ---------------------------------------------------------------- reads

    def list_pods(self) -> tuple[Pod, ...] | ProviderReceipt:
        url = f"{self.base_url}/pods"
        if not self.execute:
            return self._dry("list_pods", "GET", url, None)
        body = self._request("GET", url, expected_status=200)
        raw = _require_mapping(body, "listPods")
        pods = tuple(_parse_pod(item) for item in _require_list(raw.get("pods"), "listPods.pods"))
        self._record("list_pods", "GET", url, None, 200, {"pod_count": len(pods)})
        return pods

    def get_pod(self, pod_id: str) -> Pod | ProviderReceipt | None:
        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}"
        if not self.execute:
            return self._dry("get_pod", "GET", url, None)
        body = self._request("GET", url, expected_status=200, allow_not_found=True)
        if body is None:
            self._record("get_pod", "GET", url, None, 404, {"pod_id": pod_id, "present": False})
            return None
        pod = _parse_pod(body)
        self._record("get_pod", "GET", url, None, 200, pod.to_summary())
        return pod

    def catalog_gpus(self, *, cloud: str | None = None) -> PriceSnapshot | ProviderReceipt:
        """Snapshot list prices and persist them under provider_receipts/."""

        url = f"{self.base_url}/catalog/gpus"
        params: dict[str, str | int] = {}
        if cloud is not None:
            if cloud not in CLOUD_TYPES:
                raise RunPodClientError(f"cloud tier must be one of {CLOUD_TYPES}")
            params["cloud"] = cloud
        if not self.execute:
            return self._dry("catalog_gpus", "GET", url, params or None)
        body = self._request("GET", url, expected_status=200, params=params or None)
        raw = _require_mapping(body, "catalogGpus")
        rows = tuple(
            _parse_gpu_type(item) for item in _require_list(raw.get("gpus"), "catalogGpus.gpus")
        )
        snapshot = PriceSnapshot(captured_at=utc_now_iso(), rows=rows)
        written = self._write_price_snapshot(snapshot)
        self._record(
            "catalog_gpus",
            "GET",
            url,
            params or None,
            200,
            {
                "row_count": len(rows),
                "snapshot_sha256": snapshot.snapshot_sha256(),
                "snapshot_path": None if written is None else written.name,
            },
        )
        return PriceSnapshot(captured_at=snapshot.captured_at, rows=rows, path=written)

    def billing_pods(self, window: BillingWindow) -> Mapping[str, object] | ProviderReceipt:
        url = f"{self.base_url}/billing/pods"
        params = window.to_params()
        if not self.execute:
            return self._dry("billing_pods", "GET", url, params)
        body = self._request("GET", url, expected_status=200, params=params)
        raw = _require_mapping(body, "billingPods")
        records = _require_list(raw.get("records"), "billingPods.records")
        metadata = _require_mapping(raw.get("metadata"), "billingPods.metadata")
        totals = _require_mapping(metadata.get("totals"), "billingPods.metadata.totals")
        result: dict[str, object] = {
            "record_count": _require_int(metadata, "recordCount", "billingPods.metadata"),
            "unique_pod_count": _require_int(metadata, "uniquePodCount", "billingPods.metadata"),
            "total_amount_usd": _require_number(totals, "totalAmount", "billingPods.totals"),
            "gpu_amount_usd": _require_number(totals, "gpuAmount", "billingPods.totals"),
            "disk_amount_usd": _require_number(totals, "diskAmount", "billingPods.totals"),
            "records": [_parse_billing_record(item) for item in records],
        }
        self._record(
            "billing_pods",
            "GET",
            url,
            params,
            200,
            {key: result[key] for key in result if key != "records"},
        )
        return result

    def network_volumes(self) -> tuple[Mapping[str, object], ...] | ProviderReceipt:
        url = f"{self.base_url}/network-volumes"
        if not self.execute:
            return self._dry("network_volumes", "GET", url, None)
        body = self._request("GET", url, expected_status=200)
        raw = _require_mapping(body, "networkVolumes")
        volumes = tuple(
            _parse_network_volume(item)
            for item in _require_list(raw.get("networkVolumes"), "networkVolumes.networkVolumes")
        )
        self._record("network_volumes", "GET", url, None, 200, {"volume_count": len(volumes)})
        return volumes

    def get_logs(
        self,
        pod_id: str,
        *,
        tail: int = 200,
        max_lines: int = 2000,
        source: str | None = None,
        quiet_seconds: float = 2.0,
        total_seconds: float = 10.0,
    ) -> tuple[Mapping[str, object], ...] | ProviderReceipt:
        """Drain the SSE log stream for diagnostics. Bounded in lines *and* time.

        The stream stays open after the backfill, waiting for live lines, so
        "the backfill ended" is not something the caller can be told. Four
        things end the drain and the first one to happen wins:

        * ``max_lines`` entries arrived;
        * nothing arrived for ``quiet_seconds`` **after the backfill delivered
          the ``tail`` lines that were asked for**;
        * ``total_seconds`` elapsed (a chatty pod cannot hold the caller);
        * the server closed the stream.

        A read timeout is the *expected* end of a bounded drain, so it is not
        an error once any line has been read. With zero lines it still is:
        nothing was learned and the caller must not mistake that for silence.

        The ordering of the quiet rule is what pod jdwdnvg8a2rzx6 cost: the
        backfill paused mid-replay, the per-read timeout fired, and the tail
        that reached the receipt stopped a minute short of the crash it was
        read to explain. So while fewer than ``tail`` lines have arrived only
        ``total_seconds`` bounds the read; ``quiet_seconds`` is the per-read
        timeout only once the requested backfill is in hand, and httpx fixes
        that timeout when the stream opens, so a read still owing backfill is
        opened with the whole time budget instead.

        ``source`` selects ``container``, ``system`` or ``both``. It matters:
        the endpoint returns the two as separate sequences rather than merged
        by time, so a bounded tail over ``both`` can keep only the system block
        and miss every line the runtime itself printed.
        """

        _require_pod_id(pod_id)
        if source is not None and source not in LOG_SOURCES:
            raise RunPodClientError(f"log source must be one of {LOG_SOURCES}")
        url = f"{self.base_url}/pods/{pod_id}/logs"
        wanted = max(0, min(tail, 5000))
        params: dict[str, str | int] = {"tail": wanted}
        if source is not None:
            params["source"] = source
        if not self.execute:
            return self._dry("get_logs", "GET", url, params)
        if self._http is None:
            raise RunPodClientError("provider access is disabled; pass execute=True")
        lines: list[Mapping[str, object]] = []
        stop = "stream_end"
        deadline = monotonic() + max(0.0, total_seconds)
        # Quiet may not end the read before ``wanted`` lines exist, so the
        # per-read timeout starts as the whole budget and the quiet rule is
        # applied against ``last_event`` once the backfill has arrived.
        read_timeout = max(0.05, total_seconds if wanted else quiet_seconds)
        last_event = monotonic()
        try:
            with self._http.stream(
                "GET",
                url,
                headers=self._headers(accept="text/event-stream"),
                params=params,
                # The per-read timeout is what turns "the pod went quiet" into
                # a return instead of a wait for the whole client timeout.
                timeout=httpx.Timeout(self._timeout_seconds, read=read_timeout),
            ) as response:
                if response.status_code != 200:
                    raise RunPodClientError(
                        f"RunPod returned HTTP {response.status_code} for GET {url}; body withheld"
                    )
                for raw in response.iter_lines():
                    now = monotonic()
                    entry = _parse_sse_line(raw)
                    if entry is not None:
                        lines.append(entry)
                        if len(lines) >= max_lines:
                            stop = "max_lines"
                            break
                        if len(lines) >= wanted and now - last_event >= quiet_seconds:
                            # The backfill is in hand and the pod paused: this
                            # is the silence the quiet rule was written for.
                            stop = "quiet"
                            break
                        last_event = now
                    # Checked on every raw line, keepalives included: a stream
                    # that never goes quiet and never sends data would
                    # otherwise never reach a bound at all.
                    if now >= deadline:
                        stop = "deadline"
                        break
        except httpx.HTTPError as exc:
            if not lines:
                raise RunPodClientError(
                    f"RunPod log stream failed for pod {pod_id}: {type(exc).__name__}"
                ) from None
            if not isinstance(exc, httpx.TimeoutException):
                stop = "transport_error"
            elif len(lines) >= wanted:
                stop = "quiet"
            else:
                # The read timeout is the whole budget while backfill is owed,
                # so a timeout here is the deadline, not silence -- and the
                # tail is short of what was asked for. Say so.
                stop = "deadline_before_tail"
        self._record(
            "get_logs",
            "GET",
            url,
            params,
            200,
            {
                "tail_requested": wanted,
                "line_count": len(lines),
                "stopped_because": stop,
                "source": source or "both",
            },
        )
        return tuple(lines)

    # --------------------------------------------------------------- writes

    def create_pod(
        self,
        spec: PodSpec,
        *,
        price_snapshot: PriceSnapshot | None = None,
    ) -> Pod | ProviderReceipt:
        """Create one pod, or adopt the existing pod with the same name.

        The GPU priority list is tried in order. Between attempts the pod list
        is re-read, so a rejected request can never leave a pod behind that a
        later attempt duplicates.
        """

        url = f"{self.base_url}/pods"
        if spec.runtime_mode != "baked":
            raise RunPodClientError(
                "REST v2 creates baked-image pods only; bootstrap goes through "
                "arena.provider.runpod_v1 (ARENA_CONTRACT section 11 D2)"
            )
        if price_snapshot is not None:
            # MP section 13.2: quote the exact price row on the decision.
            price_snapshot.row(spec.gpu_type_ids[0])
        if not self.execute:
            return self._dry(
                "create_pod",
                "POST",
                url,
                spec.redacted_payload(spec.gpu_type_ids[0]),
                extra={
                    "gpu_priority": list(spec.gpu_type_ids),
                    "price_snapshot_sha256": (
                        None if price_snapshot is None else price_snapshot.snapshot_sha256()
                    ),
                },
            )

        existing = self._find_existing(spec.name)
        if existing is not None:
            self._record(
                "create_pod",
                "POST",
                url,
                None,
                None,
                {"adopted": True, **existing.to_summary()},
            )
            return existing

        last_error: RunPodClientError | None = None
        for index, gpu_type_id in enumerate(spec.gpu_type_ids):
            if index > 0:
                # Confirm the rejected attempt really created nothing.
                adopted = self._find_existing(spec.name)
                if adopted is not None:
                    summary = {
                        "adopted": True,
                        "attempt": index + 1,
                        **adopted.to_summary(),
                    }
                    self._record("create_pod", "POST", url, None, None, summary)
                    return adopted
            payload = spec.to_payload(gpu_type_id)
            try:
                body = self._request("POST", url, expected_status=201, payload=payload)
            except RunPodClientError as exc:
                if not _is_request_rejected(exc):
                    # ARENA_CONTRACT 11.5 D24: a 5xx or a transport failure is
                    # *ambiguous* -- the pod may exist and be billing. Re-list
                    # by name and campaign before propagating, so an ambiguous
                    # create becomes an adoption rather than an orphan.
                    ambiguous = self._find_existing(spec.name)
                    if ambiguous is not None:
                        self._record(
                            "create_pod",
                            "POST",
                            url,
                            None,
                            None,
                            {
                                "adopted": True,
                                "attempt": index + 1,
                                "adopted_after": "ambiguous create; re-listed by name",
                                **ambiguous.to_summary(),
                            },
                        )
                        return ambiguous
                    raise
                # A refused attempt is receipted too: the pool walk that
                # followed it is otherwise invisible, and the ledger line would
                # name a GPU type without saying which ones were tried first.
                self._record(
                    "create_pod",
                    "POST",
                    url,
                    None,
                    None,
                    {
                        "created": False,
                        "attempt": index + 1,
                        "gpu_type_ids": [gpu_type_id],
                        "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                        "refused": str(exc),
                    },
                )
                last_error = exc
                continue
            pod = _parse_pod(body)
            self._record(
                "create_pod",
                "POST",
                url,
                spec.redacted_payload(gpu_type_id),
                201,
                {
                    "adopted": False,
                    "created": True,
                    "attempt": index + 1,
                    "gpu_type_ids": [gpu_type_id],
                    "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                    "gpu_type_id": gpu_type_id,
                    "price_row_sha256": (
                        None
                        if price_snapshot is None
                        else price_snapshot.row(gpu_type_id).row_sha256()
                    ),
                    **pod.to_summary(),
                },
            )
            return pod
        raise RunPodClientError(
            f"no GPU type in {list(spec.gpu_type_ids)} accepted the create request"
        ) from last_error

    def stop_pod(self, pod_id: str) -> Pod | ProviderReceipt | None:
        return self._action(pod_id, "stop")

    def start_pod(self, pod_id: str) -> Pod | ProviderReceipt | None:
        return self._action(pod_id, "start")

    def delete_pod(self, pod_id: str) -> ProviderReceipt | None:
        """Permanently remove a pod (DELETE /v2/pods/{id}, 204 no content)."""

        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}"
        if not self.execute:
            return self._dry("delete_pod", "DELETE", url, None)
        self._request("DELETE", url, expected_status=204, expect_empty=True, allow_not_found=True)
        self._record("delete_pod", "DELETE", url, None, 204, {"pod_id": pod_id})
        return None

    def _action(self, pod_id: str, action: str) -> Pod | ProviderReceipt | None:
        if action not in POD_ACTIONS:
            raise RunPodClientError(f"pod action must be one of {POD_ACTIONS}")
        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}/action"
        payload = {"action": action}
        if not self.execute:
            return self._dry(f"{action}_pod", "POST", url, payload)
        body = self._request("POST", url, expected_status=200, payload=payload, allow_empty=True)
        pod = None if body is None else _parse_pod(body)
        self._record(
            f"{action}_pod",
            "POST",
            url,
            payload,
            200,
            {"pod_id": pod_id} if pod is None else pod.to_summary(),
        )
        return pod

    # -------------------------------------------------------------- internals

    def _find_existing(self, name: str) -> Pod | None:
        """The live pod with this name, or ``None``.

        A live pod with our name whose ``ARENA_CAMPAIGN_ID`` is somebody
        else's is neither adopted nor duplicated: it is a refusal. Adopting it
        would send this campaign's pages to a worker configured by another
        campaign; creating alongside it would buy a second GPU under the same
        name. Both are worse than stopping and saying so (D24).
        """

        listed = self.list_pods()
        if isinstance(listed, ProviderReceipt):  # pragma: no cover - execute guarded above
            return None
        for pod in listed:
            if pod.name != name or not pod.is_live:
                continue
            if pod.campaign_id == self.campaign_id:
                return pod
            raise RunPodClientError(
                f"a live pod named {name!r} already exists but carries campaign "
                f"{pod.campaign_id!r}, not {self.campaign_id!r}; refusing to adopt it or to "
                "create a second pod under the same name (ARENA_CONTRACT 11.5 D24)"
            )
        return None

    def campaign_pods(self, *, live_only: bool = False) -> tuple[Pod, ...]:
        """Every pod this campaign owns by env tag or by name prefix (D24)."""

        listed = self.list_pods()
        if isinstance(listed, ProviderReceipt):
            return ()
        return tuple(
            pod
            for pod in listed
            if pod.belongs_to(self.campaign_id) and (pod.is_live or not live_only)
        )

    def _headers(self, *, accept: str = "application/json") -> dict[str, str]:
        # The single audited place the key is revealed.
        return {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self._key.reveal()}",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected_status: int,
        payload: Mapping[str, object] | None = None,
        params: Mapping[str, str | int] | None = None,
        allow_not_found: bool = False,
        expect_empty: bool = False,
        allow_empty: bool = False,
    ) -> object | None:
        if not self.execute or self._http is None:
            raise RunPodClientError("provider access is disabled; pass execute=True")
        headers = self._headers()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._http.request(
                method, url, headers=headers, json=payload, params=params
            )
        except httpx.HTTPError as exc:
            raise RunPodClientError(
                f"RunPod transport failure for {method} {url}: {type(exc).__name__}"
            ) from None
        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code != expected_status:
            raise RunPodClientError(
                f"RunPod returned HTTP {response.status_code} for {method} {url}; body withheld"
            )
        if expect_empty:
            if response.content.strip():
                raise RunPodProtocolError(f"RunPod {method} {url} returned an unexpected body")
            return None
        if allow_empty and not response.content.strip():
            return None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise RunPodProtocolError(f"RunPod {method} {url} did not return application/json")
        try:
            parsed: object = response.json()
        except ValueError:
            raise RunPodProtocolError(f"RunPod {method} {url} returned invalid JSON") from None
        return parsed

    def _dry(
        self,
        action: str,
        method: str,
        url: str,
        payload: object | None,
        *,
        extra: Mapping[str, object] | None = None,
    ) -> ProviderReceipt:
        summary: dict[str, object] = {"would_send": payload}
        if extra:
            summary.update(dict(extra))
        receipt = ProviderReceipt(
            action=action,
            method=method,
            url=url,
            mode="dry_run",
            request_sha256=canonical_sha256({"method": method, "url": url, "payload": payload}),
            ts=utc_now_iso(),
            status_code=None,
            summary=MappingProxyType(summary),
        )
        self._append(receipt)
        return receipt

    def _record(
        self,
        action: str,
        method: str,
        url: str,
        payload: object | None,
        status_code: int | None,
        summary: Mapping[str, object],
    ) -> ProviderReceipt:
        receipt = ProviderReceipt(
            action=action,
            method=method,
            url=url,
            mode="live",
            request_sha256=canonical_sha256({"method": method, "url": url, "payload": payload}),
            ts=utc_now_iso(),
            status_code=status_code,
            summary=MappingProxyType(dict(summary)),
        )
        self._append(receipt)
        return receipt

    def _append(self, receipt: ProviderReceipt) -> None:
        record = receipt.to_dict()  # raises SecretLeak before anything is kept
        self._receipts.append(receipt)
        if self.receipts_dir is not None:
            short = receipt.request_sha256[:12]
            target = self.receipts_dir / f"{receipt.action}-{timestamp_slug()}-{short}.json"
            write_json_atomic(target, record, context=f"provider receipt {receipt.action}")

    def _write_price_snapshot(self, snapshot: PriceSnapshot) -> Path | None:
        if self.receipts_dir is None:
            return None
        target = self.receipts_dir / f"catalog-{timestamp_slug()}.json"
        write_json_atomic(target, snapshot.to_dict(), context="catalog price snapshot")
        return target


# ------------------------------------------------------------------ parsing


def _is_request_rejected(error: RunPodClientError) -> bool:
    """True when the provider refused the request outright (nothing created).

    Only the statuses the OpenAPI documents as validation/capacity rejections
    with no response body are treated as safe to follow with a different GPU
    type. A 5xx or a transport failure is ambiguous and stops the loop.
    """

    return any(f"HTTP {code} " in str(error) for code in (400, 404, 422))


def _require_pod_id(pod_id: str) -> str:
    if not _POD_ID_RE.fullmatch(pod_id):
        raise RunPodClientError("pod id is not a valid provider resource id")
    return pod_id


def _require_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunPodProtocolError(f"{context} is not a JSON object")
    return value


def _require_list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise RunPodProtocolError(f"{context} is not a JSON array")
    return value


def _require_string(raw: Mapping[str, Any], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RunPodProtocolError(f"{context}.{key} is missing or not a non-empty string")
    return value


def _optional_string(raw: Mapping[str, Any], key: str, context: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunPodProtocolError(f"{context}.{key} is not a string or null")
    return value


def _require_int(raw: Mapping[str, Any], key: str, context: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunPodProtocolError(f"{context}.{key} is missing or not an integer")
    return value


def _require_number(raw: Mapping[str, Any], key: str, context: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunPodProtocolError(f"{context}.{key} is missing or not a number")
    return float(value)


def _parse_pod(value: object) -> Pod:
    raw = _require_mapping(value, "pod")
    status = _require_string(raw, "status", "pod")
    if status not in POD_STATUSES:
        raise RunPodProtocolError(f"pod.status {status!r} is outside the pinned v2 enum")
    cloud = _require_string(raw, "cloud", "pod")
    if cloud not in CLOUD_TYPES:
        raise RunPodProtocolError(f"pod.cloud {cloud!r} is outside the pinned v2 enum")
    # ARENA_CONTRACT 11.5 D24: a pod record without env is a protocol error.
    # Campaign membership, the model key and the worker port all live in env;
    # treating an absent env as an empty one turns "the provider did not tell
    # us" into "this pod is not ours", which is how a paid pod survives
    # cleanup.
    if "env" not in raw or raw.get("env") is None:
        raise RunPodProtocolError(
            "pod record carries no env; campaign membership and model key cannot be "
            "established from it (ARENA_CONTRACT 11.5 D24)"
        )
    env_map = _require_mapping(raw.get("env"), "pod.env")
    environment: dict[str, str] = {}
    for key, item in env_map.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise RunPodProtocolError("pod.env must map strings to strings")
        environment[key] = item
    gpu_raw = raw.get("gpu")
    gpu_type_id: str | None = None
    gpu_count = 0
    if gpu_raw is not None:
        gpu = _require_mapping(gpu_raw, "pod.gpu")
        gpu_type_id = _require_string(gpu, "id", "pod.gpu")
        count = gpu.get("count", 1)
        gpu_count = count if isinstance(count, int) and not isinstance(count, bool) else 1
    uptime: int | None = None
    utilization: float | None = None
    runtime_raw = raw.get("runtime")
    if runtime_raw is not None:
        runtime = _require_mapping(runtime_raw, "pod.runtime")
        raw_uptime = runtime.get("uptime")
        if isinstance(raw_uptime, int) and not isinstance(raw_uptime, bool):
            uptime = raw_uptime
        gpus = runtime.get("gpus")
        if isinstance(gpus, list) and gpus:
            percents = [
                float(entry["utilizationPercent"])
                for entry in gpus
                if isinstance(entry, Mapping)
                and isinstance(entry.get("utilizationPercent"), (int, float))
                and not isinstance(entry.get("utilizationPercent"), bool)
            ]
            if percents:
                utilization = sum(percents) / len(percents)
    return Pod(
        pod_id=_require_string(raw, "id", "pod"),
        name=_require_string(raw, "name", "pod"),
        status=status,
        cloud=cloud,
        image=_optional_string(raw, "image", "pod") or "",
        cost_usd_per_hour=_require_number(raw, "cost", "pod"),
        data_center_id=_optional_string(raw, "dataCenterId", "pod"),
        gpu_type_id=gpu_type_id,
        gpu_count=gpu_count,
        created_at=_require_string(raw, "createdAt", "pod"),
        started_at=_optional_string(raw, "startedAt", "pod"),
        env=MappingProxyType(environment),
        uptime_seconds=uptime,
        gpu_utilization_percent=utilization,
    )


def _parse_gpu_type(value: object) -> GpuPriceRow:
    raw = _require_mapping(value, "gpuType")
    price = _require_mapping(raw.get("price"), "gpuType.price")
    secure_price = price.get("secure")
    community_price = price.get("community")
    return GpuPriceRow(
        gpu_type_id=_require_string(raw, "id", "gpuType"),
        display_name=_require_string(raw, "name", "gpuType"),
        memory_gb=_require_int(raw, "memory", "gpuType"),
        secure_available=bool(raw.get("secure")),
        community_available=bool(raw.get("community")),
        price_secure_usd_per_hour=(
            float(secure_price)
            if isinstance(secure_price, (int, float)) and not isinstance(secure_price, bool)
            else None
        ),
        price_community_usd_per_hour=(
            float(community_price)
            if isinstance(community_price, (int, float)) and not isinstance(community_price, bool)
            else None
        ),
    )


def _parse_billing_record(value: object) -> dict[str, object]:
    raw = _require_mapping(value, "podBillingRecord")
    return {
        "pod_id": _require_string(raw, "podId", "podBillingRecord"),
        "start_time": _require_string(raw, "startTime", "podBillingRecord"),
        "end_time": _require_string(raw, "endTime", "podBillingRecord"),
        "total_amount_usd": _require_number(raw, "totalAmount", "podBillingRecord"),
        "gpu_amount_usd": _require_number(raw, "gpuAmount", "podBillingRecord"),
        "disk_amount_usd": _require_number(raw, "diskAmount", "podBillingRecord"),
    }


def _parse_network_volume(value: object) -> dict[str, object]:
    raw = _require_mapping(value, "networkVolume")
    return {
        "id": _require_string(raw, "id", "networkVolume"),
        "name": _require_string(raw, "name", "networkVolume"),
        "size_gb": _require_int(raw, "size", "networkVolume"),
        "data_center": _require_string(raw, "dataCenter", "networkVolume"),
        "type": _require_string(raw, "type", "networkVolume"),
    }


def _parse_sse_line(line: str) -> Mapping[str, object] | None:
    """One SSE line to one log entry, or ``None`` for keepalives and framing."""

    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = {"line": payload}
    if not isinstance(parsed, Mapping):
        return None
    return {
        "source": parsed.get("source"),
        "line": parsed.get("line"),
        "ts": parsed.get("ts"),
    }
