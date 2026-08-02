"""Strict, dry-run-first RunPod REST API v2 client.

The public management API and the queue API intentionally use different
origins.  This module pins both origins and one documented response dialect;
redirects, undocumented shapes, and unknown statuses are rejected.  There are
no automatic HTTP retries because replay after an ambiguous write can create
duplicate paid work.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Self

import httpx

from benchmark.v6.contracts import ContractError, canonical_sha256, require_sha256

MANAGEMENT_BASE_URL: Final = "https://api.runpod.io/v2"
QUEUE_BASE_URL: Final = "https://api.runpod.ai/v2"
RUNPOD_KEY_ENV: Final = "RUNPOD_API_KEY"

_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RUN_TAG_RE = re.compile(r"^v6-[a-z0-9][a-z0-9._-]{2,127}$")
_IDEMPOTENCY_RE = re.compile(r"^idem-[0-9a-f]{64}$")
_IMAGE_DIGEST_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_ALLOWED_QUEUE_STATUSES = frozenset(
    {"IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
)
_ENDPOINT_KEYS = frozenset(
    {
        "id",
        "name",
        "type",
        "requestUrls",
        "image",
        "args",
        "disk",
        "ports",
        "env",
        "registry",
        "gpu",
        "cpu",
        "workers",
        "scaling",
        "dataCenterIds",
        "networkVolumes",
        "timeout",
        "flashboot",
        "createdAt",
    }
)
_ENDPOINT_REQUIRED = frozenset(
    {
        "id",
        "name",
        "workers",
        "scaling",
        "dataCenterIds",
        "networkVolumes",
        "timeout",
        "flashboot",
        "createdAt",
    }
)


class RunPodClientError(RuntimeError):
    """Sanitized provider or transport failure.

    Provider response bodies are deliberately excluded: an upstream service
    can reflect request headers or inputs in an error response.
    """


class RunPodProtocolError(RunPodClientError):
    """The provider response no longer matches the pinned v2 contract."""


@dataclass(frozen=True, slots=True)
class WorkerBounds:
    minimum: int = 0
    maximum: int = 3
    idle_timeout_seconds: int | None = 300

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < 0 or self.minimum > self.maximum:
            raise ContractError("worker bounds require 0 <= minimum <= maximum")
        if self.idle_timeout_seconds is not None and not 1 <= self.idle_timeout_seconds <= 3_600:
            raise ContractError("worker idle timeout must be between 1 and 3600 seconds")

    def to_dict(self) -> dict[str, int]:
        value = {"min": self.minimum, "max": self.maximum}
        if self.idle_timeout_seconds is not None:
            value["idleTimeout"] = self.idle_timeout_seconds
        return value


@dataclass(frozen=True, slots=True)
class ScalingPolicy:
    scaler_type: str = "QUEUE_DELAY"
    value: Decimal = Decimal("4")

    def __post_init__(self) -> None:
        if self.scaler_type not in {"QUEUE_DELAY", "REQUEST_COUNT"}:
            raise ContractError("scaler_type must be QUEUE_DELAY or REQUEST_COUNT")
        if self.value < Decimal("0.5"):
            raise ContractError("scaling value must be at least 0.5")
        if self.scaler_type == "REQUEST_COUNT" and (
            self.value < 1 or self.value != self.value.to_integral_value()
        ):
            raise ContractError("REQUEST_COUNT scaling requires an integer value of at least 1")

    def to_dict(self) -> dict[str, object]:
        if self.scaler_type == "QUEUE_DELAY":
            return {"type": "QUEUE_DELAY", "queueDelay": float(self.value)}
        return {"type": "REQUEST_COUNT", "requestCount": int(self.value)}


@dataclass(frozen=True, slots=True)
class EndpointCreateSpec:
    name: str
    image: str
    gpu_pools: tuple[str, ...]
    run_tag: str
    gpu_count: int = 1
    workers: WorkerBounds = field(default_factory=WorkerBounds)
    scaling: ScalingPolicy = field(default_factory=ScalingPolicy)
    timeout_ms: int = 300_000
    disk_gb: int = 20
    data_center_ids: tuple[str, ...] = ()
    network_volume_ids: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 128:
            raise ContractError("endpoint name must contain 1-128 characters")
        if not _IMAGE_DIGEST_RE.fullmatch(self.image):
            raise ContractError("endpoint image must be pinned as image@sha256:<64 lowercase hex>")
        if not self.gpu_pools or any(
            not _RESOURCE_ID_RE.fullmatch(item) for item in self.gpu_pools
        ):
            raise ContractError("at least one valid immutable GPU pool ID is required")
        _require_run_tag(self.run_tag)
        if self.gpu_count < 1:
            raise ContractError("gpu_count must be positive")
        if self.scaling.scaler_type == "REQUEST_COUNT" and (
            self.workers.idle_timeout_seconds is not None
        ):
            raise ContractError(
                "REQUEST_COUNT endpoints must omit workers.idle_timeout_seconds"
            )
        if self.scaling.scaler_type == "QUEUE_DELAY" and (
            self.workers.idle_timeout_seconds is None
        ):
            raise ContractError("QUEUE_DELAY endpoints require an automatic worker idle timeout")
        if self.timeout_ms < 5_000 or self.timeout_ms > 604_800_000:
            raise ContractError("endpoint timeout must be between 5 seconds and 7 days")
        if self.disk_gb < 1:
            raise ContractError("endpoint disk must be positive")
        for label, values in (
            ("data_center_ids", self.data_center_ids),
            ("network_volume_ids", self.network_volume_ids),
        ):
            if any(not _RESOURCE_ID_RE.fullmatch(item) for item in values):
                raise ContractError(f"{label} contains an invalid resource ID")
        normalized_env: dict[str, str] = {}
        for key, value in sorted(self.env.items()):
            if not isinstance(key, str) or not _ENV_NAME_RE.fullmatch(key):
                raise ContractError("endpoint environment names must be uppercase identifiers")
            if not isinstance(value, str):
                raise ContractError(f"endpoint environment value for {key} must be a string")
            if key == RUNPOD_KEY_ENV:
                raise ContractError("RUNPOD_API_KEY may not be copied into endpoint environment")
            normalized_env[key] = value
        previous_tag = normalized_env.get("AKC_RUN_TAG") or normalized_env.get(
            "STRUCTARA_RUN_TAG"
        )
        if previous_tag is not None and previous_tag != self.run_tag:
            raise ContractError("run tag conflicts with the immutable run tag")
        normalized_env.pop("STRUCTARA_RUN_TAG", None)
        normalized_env["AKC_RUN_TAG"] = self.run_tag
        object.__setattr__(self, "env", MappingProxyType(normalized_env))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        allowed = {
            "name",
            "image",
            "gpu_pools",
            "run_tag",
            "gpu_count",
            "workers",
            "scaling",
            "timeout_ms",
            "disk_gb",
            "data_center_ids",
            "network_volume_ids",
            "env",
        }
        _reject_unknown_keys(value, allowed, "endpoint create spec")
        workers_raw = value.get("workers", {})
        scaling_raw = value.get("scaling", {})
        if not isinstance(workers_raw, Mapping) or not isinstance(scaling_raw, Mapping):
            raise ContractError("workers and scaling must be objects")
        _reject_unknown_keys(
            workers_raw,
            {"minimum", "maximum", "idle_timeout_seconds"},
            "worker bounds",
        )
        _reject_unknown_keys(
            scaling_raw,
            {"scaler_type", "value"},
            "scaling policy",
        )
        env = value.get("env", {})
        if not isinstance(env, Mapping):
            raise ContractError("env must be an object")
        try:
            return cls(
                name=str(value["name"]),
                image=str(value["image"]),
                gpu_pools=_string_tuple(value["gpu_pools"], "gpu_pools"),
                run_tag=str(value["run_tag"]),
                gpu_count=int(value.get("gpu_count", 1)),
                workers=WorkerBounds(
                    minimum=int(workers_raw.get("minimum", 0)),
                    maximum=int(workers_raw.get("maximum", 3)),
                    idle_timeout_seconds=(
                        None
                        if workers_raw.get("idle_timeout_seconds", 300) is None
                        else int(workers_raw.get("idle_timeout_seconds", 300))
                    ),
                ),
                scaling=ScalingPolicy(
                    scaler_type=str(scaling_raw.get("scaler_type", "QUEUE_DELAY")),
                    value=_decimal(scaling_raw.get("value", "4"), "scaling.value"),
                ),
                timeout_ms=int(value.get("timeout_ms", 300_000)),
                disk_gb=int(value.get("disk_gb", 20)),
                data_center_ids=_string_tuple(
                    value.get("data_center_ids", ()), "data_center_ids"
                ),
                network_volume_ids=_string_tuple(
                    value.get("network_volume_ids", ()), "network_volume_ids"
                ),
                env={str(key): str(item) for key, item in env.items()},
            )
        except KeyError as exc:
            raise ContractError(f"missing endpoint create field: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ContractError("endpoint create fields have invalid scalar types") from exc

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "image": self.image,
            "type": "QUEUE",
            "gpu": {"pools": list(self.gpu_pools), "count": self.gpu_count},
            "workers": self.workers.to_dict(),
            "scaling": self.scaling.to_dict(),
            "dataCenterIds": list(self.data_center_ids),
            "networkVolumes": list(self.network_volume_ids),
            "timeout": self.timeout_ms,
            "disk": self.disk_gb,
            "env": dict(self.env),
        }

    @property
    def spec_sha256(self) -> str:
        return canonical_sha256(self.to_payload())


@dataclass(frozen=True, slots=True)
class EndpointPatch:
    workers: WorkerBounds | None = None
    scaling: ScalingPolicy | None = None
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        if self.workers is None and self.scaling is None and self.timeout_ms is None:
            raise ContractError("endpoint patch must change at least one field")
        if self.timeout_ms is not None and not 5_000 <= self.timeout_ms <= 604_800_000:
            raise ContractError("endpoint timeout must be between 5 seconds and 7 days")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        _reject_unknown_keys(value, {"workers", "scaling", "timeout_ms"}, "endpoint patch")
        workers: WorkerBounds | None = None
        scaling: ScalingPolicy | None = None
        if "workers" in value:
            raw = value["workers"]
            if not isinstance(raw, Mapping):
                raise ContractError("workers patch must be an object")
            _reject_unknown_keys(
                raw,
                {"minimum", "maximum", "idle_timeout_seconds"},
                "worker bounds",
            )
            required = {"minimum", "maximum"}
            if not required.issubset(raw):
                raise ContractError("workers patch requires minimum and maximum")
            idle_raw = raw.get("idle_timeout_seconds")
            workers = WorkerBounds(
                int(raw["minimum"]),
                int(raw["maximum"]),
                None if idle_raw is None else int(idle_raw),
            )
        if "scaling" in value:
            raw = value["scaling"]
            if not isinstance(raw, Mapping):
                raise ContractError("scaling patch must be an object")
            _reject_unknown_keys(
                raw,
                {"scaler_type", "value"},
                "scaling policy",
            )
            required = {"scaler_type", "value"}
            if not required.issubset(raw):
                raise ContractError("scaling patch requires its complete immutable policy")
            scaling = ScalingPolicy(
                str(raw["scaler_type"]),
                _decimal(raw["value"], "scaling.value"),
            )
        timeout = int(value["timeout_ms"]) if "timeout_ms" in value else None
        patch = cls(workers=workers, scaling=scaling, timeout_ms=timeout)
        if scaling is not None and scaling.scaler_type == "REQUEST_COUNT" and (
            workers is None or workers.idle_timeout_seconds is not None
        ):
            raise ContractError(
                "REQUEST_COUNT patch requires complete workers with idle timeout omitted"
            )
        return patch

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.workers is not None:
            payload["workers"] = self.workers.to_dict()
        if self.scaling is not None:
            payload["scaling"] = self.scaling.to_dict()
        if self.timeout_ms is not None:
            payload["timeout"] = self.timeout_ms
        return payload


@dataclass(frozen=True, slots=True)
class QueuePolicy:
    execution_timeout_ms: int = 600_000
    ttl_ms: int = 86_400_000
    low_priority: bool = False

    def __post_init__(self) -> None:
        if not 5_000 <= self.execution_timeout_ms <= 604_800_000:
            raise ContractError("queue execution timeout must be between 5 seconds and 7 days")
        if not 10_000 <= self.ttl_ms <= 604_800_000:
            raise ContractError("queue TTL must be between 10 seconds and 7 days")
        if self.ttl_ms < self.execution_timeout_ms:
            raise ContractError("queue TTL must cover the execution timeout")

    def to_dict(self) -> dict[str, object]:
        return {
            "executionTimeout": self.execution_timeout_ms,
            "ttl": self.ttl_ms,
            "lowPriority": self.low_priority,
        }


@dataclass(frozen=True, slots=True)
class DryRunReceipt:
    action: str
    method: str
    url: str
    request_sha256: str
    run_tag: str | None = None
    idempotency_key: str | None = None
    would_execute: bool = False

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "6.0.0",
            "mode": "dry-run",
            "action": self.action,
            "method": self.method,
            "url": self.url,
            "request_sha256": self.request_sha256,
            "would_execute": self.would_execute,
        }
        if self.run_tag is not None:
            value["run_tag"] = self.run_tag
        if self.idempotency_key is not None:
            value["idempotency_key"] = self.idempotency_key
        value["receipt_sha256"] = canonical_sha256(value)
        return value


@dataclass(frozen=True, slots=True)
class EndpointSummary:
    endpoint_id: str
    name: str
    endpoint_type: str | None
    image: str | None
    workers: WorkerBounds
    scaling: ScalingPolicy
    created_at: str
    env_names: tuple[str, ...]
    run_tag: str | None
    response_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "endpoint_type": self.endpoint_type,
            "image": self.image,
            "workers": self.workers.to_dict(),
            "scaling": self.scaling.to_dict(),
            "created_at": self.created_at,
            "env_names": list(self.env_names),
            "run_tag": self.run_tag,
            "response_sha256": self.response_sha256,
        }


@dataclass(frozen=True, slots=True)
class DeleteAcknowledgement:
    endpoint_id: str
    status_code: int
    observed_at: str

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "endpoint_id": self.endpoint_id,
            "status_code": self.status_code,
            "observed_at": self.observed_at,
        }
        value["acknowledgement_sha256"] = canonical_sha256(value)
        return value


@dataclass(frozen=True, slots=True)
class ProviderAbsenceReceipt:
    endpoint_id: str
    observation: str
    observed_at: str
    management_base_url: str = MANAGEMENT_BASE_URL

    def __post_init__(self) -> None:
        _require_resource_id(self.endpoint_id, "endpoint_id")
        if self.observation != "GET_404_NOT_FOUND":
            raise ContractError("provider absence must be proven by GET 404")
        _require_rfc3339(self.observed_at, "observed_at")
        if self.management_base_url != MANAGEMENT_BASE_URL:
            raise ContractError("provider absence receipt management origin is not pinned")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "6.0.0",
            "endpoint_id": self.endpoint_id,
            "terminal_state": "provider_absent",
            "observation": self.observation,
            "observed_at": self.observed_at,
            "management_base_url": self.management_base_url,
        }
        value["receipt_sha256"] = canonical_sha256(value)
        return value


@dataclass(frozen=True, slots=True)
class OrphanAuditReceipt:
    run_tag: str
    active_endpoint_ids: tuple[str, ...]
    tagged_endpoint_ids: tuple[str, ...]
    orphan_endpoint_ids: tuple[str, ...]
    missing_active_endpoint_ids: tuple[str, ...]
    delete_confirmations: tuple[ProviderAbsenceReceipt, ...]
    observed_at: str

    @property
    def passed(self) -> bool:
        return not self.orphan_endpoint_ids and not self.missing_active_endpoint_ids

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "6.0.0",
            "run_tag": self.run_tag,
            "passed": self.passed,
            "active_endpoint_ids": list(self.active_endpoint_ids),
            "tagged_endpoint_ids": list(self.tagged_endpoint_ids),
            "orphan_endpoint_ids": list(self.orphan_endpoint_ids),
            "missing_active_endpoint_ids": list(self.missing_active_endpoint_ids),
            "delete_confirmations": [item.to_dict() for item in self.delete_confirmations],
            "delete_confirmation_count": len(self.delete_confirmations),
            "observed_at": self.observed_at,
        }
        value["receipt_sha256"] = canonical_sha256(value)
        return value


@dataclass(frozen=True, slots=True)
class QueueJob:
    endpoint_id: str
    job_id: str
    status: str
    output: object | None
    error_present: bool
    delay_time_ms: int | None
    execution_time_ms: int | None
    response_sha256: str

    @property
    def terminal(self) -> bool:
        return self.status in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}

    @property
    def output_sha256(self) -> str | None:
        return canonical_sha256(self.output) if self.output is not None else None

    def to_dict(self, *, include_output: bool = False) -> dict[str, object]:
        value: dict[str, object] = {
            "endpoint_id": self.endpoint_id,
            "job_id": self.job_id,
            "status": self.status,
            "terminal": self.terminal,
            "error_present": self.error_present,
            "delay_time_ms": self.delay_time_ms,
            "execution_time_ms": self.execution_time_ms,
            "output_sha256": self.output_sha256,
            "response_sha256": self.response_sha256,
        }
        if include_output:
            value["output"] = self.output
        return value


@dataclass(frozen=True, slots=True)
class BillingQuery:
    bucket_size: str = "day"
    start_time: str | None = None
    end_time: str | None = None
    last_n: int | None = 30
    endpoint_id: str | None = None

    def __post_init__(self) -> None:
        if self.bucket_size not in {"hour", "day", "week", "month", "year"}:
            raise ContractError("unsupported billing bucket size")
        explicit_range = self.start_time is not None or self.end_time is not None
        if explicit_range:
            if self.start_time is None or self.end_time is None or self.last_n is not None:
                raise ContractError("billing requires either start/end or last_n, never both")
            _require_rfc3339(self.start_time, "start_time")
            _require_rfc3339(self.end_time, "end_time")
        elif self.last_n is None or self.last_n < 1:
            raise ContractError("billing last_n must be positive")
        if self.endpoint_id is not None:
            _require_resource_id(self.endpoint_id, "endpoint_id")

    def to_params(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {"bucketSize": self.bucket_size}
        if self.last_n is not None:
            params["lastN"] = self.last_n
        else:
            if self.start_time is None or self.end_time is None:
                raise ContractError("explicit billing range is incomplete")
            params["startTime"] = self.start_time
            params["endTime"] = self.end_time
        if self.endpoint_id is not None:
            params["serverlessId"] = self.endpoint_id
        return params


@dataclass(frozen=True, slots=True)
class BillingRecord:
    endpoint_id: str
    start_time: str
    end_time: str
    total_amount_usd: Decimal
    gpu_amount_usd: Decimal
    cpu_amount_usd: Decimal
    disk_amount_usd: Decimal
    fee_amount_usd: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "endpoint_id": self.endpoint_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_amount_usd": str(self.total_amount_usd),
            "gpu_amount_usd": str(self.gpu_amount_usd),
            "cpu_amount_usd": str(self.cpu_amount_usd),
            "disk_amount_usd": str(self.disk_amount_usd),
            "fee_amount_usd": str(self.fee_amount_usd),
        }


@dataclass(frozen=True, slots=True)
class BillingHistory:
    records: tuple[BillingRecord, ...]
    provider_total_usd: Decimal
    response_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "records": [item.to_dict() for item in self.records],
            "provider_total_usd": str(self.provider_total_usd),
            "response_sha256": self.response_sha256,
            "user_charge_usd": None,
            "accounting_note": "provider spend is not a user charge",
        }


RunPodResult = (
    DryRunReceipt
    | EndpointSummary
    | tuple[EndpointSummary, ...]
    | DeleteAcknowledgement
    | ProviderAbsenceReceipt
    | OrphanAuditReceipt
    | QueueJob
    | BillingHistory
)


class RunPodV2Client:
    """Synchronous strict client with an explicit execution capability gate."""

    def __init__(
        self,
        *,
        execute: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ContractError("timeout_seconds must be positive")
        self.execute = execute
        self._api_key: str | None = None
        self._http: httpx.Client | None = None
        if execute:
            api_key = os.environ.get(RUNPOD_KEY_ENV, "").strip()
            if not api_key:
                raise ContractError(
                    "RUNPOD_API_KEY is required only when --execute enables provider access"
                )
            self._api_key = api_key
            self._http = httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
            )

    def __repr__(self) -> str:
        mode = "execute" if self.execute else "dry-run"
        return f"RunPodV2Client(mode={mode!r}, management_base={MANAGEMENT_BASE_URL!r})"

    @property
    def provider_retry_count(self) -> int:
        """Provider retries are intentionally and immutably disabled."""

        return 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    def inventory_endpoints(self) -> tuple[EndpointSummary, ...] | DryRunReceipt:
        url = f"{MANAGEMENT_BASE_URL}/serverless"
        if not self.execute:
            return self._dry("endpoint.inventory", "GET", url, None)
        raw = self._request_json("GET", url, expected_status=200)
        root = _strict_object(raw, {"endpoints"}, set(), "endpoint inventory")
        rows = root["endpoints"]
        if not isinstance(rows, list):
            raise RunPodProtocolError("endpoint inventory endpoints must be an array")
        endpoints = tuple(_parse_endpoint(item) for item in rows)
        if len({item.endpoint_id for item in endpoints}) != len(endpoints):
            raise RunPodProtocolError("endpoint inventory contains duplicate endpoint IDs")
        return endpoints

    def create_endpoint(
        self,
        spec: EndpointCreateSpec,
        *,
        idempotency_key: str,
    ) -> EndpointSummary | DryRunReceipt:
        _require_idempotency(idempotency_key)
        url = f"{MANAGEMENT_BASE_URL}/serverless"
        payload = spec.to_payload()
        if not self.execute:
            return self._dry(
                "endpoint.create", "POST", url, payload, spec.run_tag, idempotency_key
            )
        raw = self._request_json(
            "POST",
            url,
            expected_status=201,
            payload=payload,
            extra_headers=_write_headers(spec.run_tag, idempotency_key),
        )
        endpoint = _parse_endpoint(raw)
        raw_object = _as_mapping(raw, "created endpoint")
        if (
            endpoint.name != spec.name
            or endpoint.image != spec.image
            or endpoint.endpoint_type != "QUEUE"
            or endpoint.workers != spec.workers
            or endpoint.scaling != spec.scaling
        ):
            raise RunPodProtocolError("created endpoint identity differs from the requested spec")
        env = raw_object.get("env")
        if not isinstance(env, Mapping) or env.get("AKC_RUN_TAG") != spec.run_tag:
            raise RunPodProtocolError("created endpoint did not preserve AKC_RUN_TAG")
        return endpoint

    def get_endpoint(
        self, endpoint_id: str, *, allow_absent: bool = False
    ) -> EndpointSummary | DryRunReceipt | None:
        _require_resource_id(endpoint_id, "endpoint_id")
        url = f"{MANAGEMENT_BASE_URL}/serverless/{endpoint_id}"
        if not self.execute:
            return self._dry("endpoint.get", "GET", url, None)
        raw = self._request_json(
            "GET", url, expected_status=200, allow_not_found=allow_absent
        )
        if raw is None:
            return None
        endpoint = _parse_endpoint(raw)
        if endpoint.endpoint_id != endpoint_id:
            raise RunPodProtocolError("provider returned a different endpoint ID")
        return endpoint

    def update_endpoint(
        self,
        endpoint_id: str,
        patch: EndpointPatch,
        *,
        run_tag: str,
        idempotency_key: str,
    ) -> EndpointSummary | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        _require_run_tag(run_tag)
        _require_idempotency(idempotency_key)
        url = f"{MANAGEMENT_BASE_URL}/serverless/{endpoint_id}"
        payload = patch.to_payload()
        if not self.execute:
            return self._dry(
                "endpoint.update", "PATCH", url, payload, run_tag, idempotency_key
            )
        raw = self._request_json(
            "PATCH",
            url,
            expected_status=200,
            payload=payload,
            extra_headers=_write_headers(run_tag, idempotency_key),
        )
        endpoint = _parse_endpoint(raw)
        if endpoint.endpoint_id != endpoint_id:
            raise RunPodProtocolError("provider returned a different endpoint ID")
        if patch.workers is not None and endpoint.workers != patch.workers:
            raise RunPodProtocolError("provider did not apply the requested worker bounds")
        if patch.scaling is not None and endpoint.scaling != patch.scaling:
            raise RunPodProtocolError("provider did not apply the requested scaling policy")
        return endpoint

    def drain_endpoint(
        self,
        endpoint_id: str,
        *,
        run_tag: str,
        idempotency_key: str,
    ) -> EndpointSummary | DryRunReceipt:
        return self.update_endpoint(
            endpoint_id,
            EndpointPatch(workers=WorkerBounds(0, 0)),
            run_tag=run_tag,
            idempotency_key=idempotency_key,
        )

    def delete_endpoint(
        self,
        endpoint_id: str,
        *,
        confirmation_endpoint_id: str,
        run_tag: str,
        idempotency_key: str,
    ) -> DeleteAcknowledgement | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        if confirmation_endpoint_id != endpoint_id:
            raise ContractError("delete confirmation must exactly match endpoint_id")
        _require_run_tag(run_tag)
        _require_idempotency(idempotency_key)
        url = f"{MANAGEMENT_BASE_URL}/serverless/{endpoint_id}"
        if not self.execute:
            return self._dry(
                "endpoint.delete", "DELETE", url, None, run_tag, idempotency_key
            )
        self._request_json(
            "DELETE",
            url,
            expected_status=204,
            extra_headers=_write_headers(run_tag, idempotency_key),
            expect_empty=True,
        )
        return DeleteAcknowledgement(endpoint_id, 204, _now_rfc3339())

    def verify_endpoint_absent(
        self, endpoint_id: str
    ) -> ProviderAbsenceReceipt | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        url = f"{MANAGEMENT_BASE_URL}/serverless/{endpoint_id}"
        if not self.execute:
            return self._dry("endpoint.verify_absent", "GET", url, None)
        endpoint = self.get_endpoint(endpoint_id, allow_absent=True)
        if endpoint is not None:
            raise RunPodProtocolError("endpoint is still present; terminal absence is unproven")
        return ProviderAbsenceReceipt(endpoint_id, "GET_404_NOT_FOUND", _now_rfc3339())

    def audit_orphans(
        self,
        *,
        run_tag: str,
        active_endpoint_ids: Sequence[str] = (),
        deleted_endpoint_ids: Sequence[str] = (),
    ) -> OrphanAuditReceipt | DryRunReceipt:
        _require_run_tag(run_tag)
        active = tuple(sorted(set(active_endpoint_ids)))
        deleted = tuple(sorted(set(deleted_endpoint_ids)))
        for endpoint_id in (*active, *deleted):
            _require_resource_id(endpoint_id, "endpoint_id")
        if set(active) & set(deleted):
            raise ContractError("an endpoint cannot be both active and expected deleted")
        url = f"{MANAGEMENT_BASE_URL}/serverless"
        request_contract = {
            "run_tag": run_tag,
            "active_endpoint_ids": list(active),
            "deleted_endpoint_ids": list(deleted),
            "delete_confirmation": "GET_404_NOT_FOUND",
        }
        if not self.execute:
            return self._dry("endpoint.audit_orphans", "GET", url, request_contract, run_tag)
        confirmations: list[ProviderAbsenceReceipt] = []
        for endpoint_id in deleted:
            confirmation = self.verify_endpoint_absent(endpoint_id)
            if not isinstance(confirmation, ProviderAbsenceReceipt):
                raise ContractError("execute orphan audit returned a dry-run absence receipt")
            confirmations.append(confirmation)
        inventory = self.inventory_endpoints()
        if not isinstance(inventory, tuple):
            raise ContractError("execute orphan audit returned a dry-run inventory")
        tagged = tuple(
            sorted(item.endpoint_id for item in inventory if item.run_tag == run_tag)
        )
        orphan_ids = tuple(sorted(set(tagged) - set(active)))
        missing_active = tuple(sorted(set(active) - set(tagged)))
        return OrphanAuditReceipt(
            run_tag=run_tag,
            active_endpoint_ids=active,
            tagged_endpoint_ids=tagged,
            orphan_endpoint_ids=orphan_ids,
            missing_active_endpoint_ids=missing_active,
            delete_confirmations=tuple(confirmations),
            observed_at=_now_rfc3339(),
        )

    def run_job(
        self,
        endpoint_id: str,
        input_payload: Mapping[str, object],
        *,
        run_tag: str,
        idempotency_key: str,
        policy: QueuePolicy | None = None,
    ) -> QueueJob | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        _require_run_tag(run_tag)
        _require_idempotency(idempotency_key)
        if not input_payload:
            raise ContractError("queue input must be a non-empty object")
        payload: dict[str, object] = {"input": dict(input_payload)}
        if policy is not None:
            payload["policy"] = policy.to_dict()
        url = f"{QUEUE_BASE_URL}/{endpoint_id}/run"
        if not self.execute:
            return self._dry("queue.run", "POST", url, payload, run_tag, idempotency_key)
        raw = self._request_json(
            "POST",
            url,
            expected_status=200,
            payload=payload,
            extra_headers=_write_headers(run_tag, idempotency_key),
        )
        job = _parse_queue_job(raw, endpoint_id, context="queue run")
        if job.status not in {"IN_QUEUE", "IN_PROGRESS", "COMPLETED"}:
            raise RunPodProtocolError("new queue job returned an invalid initial status")
        return job

    def job_status(self, endpoint_id: str, job_id: str) -> QueueJob | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        _require_resource_id(job_id, "job_id")
        url = f"{QUEUE_BASE_URL}/{endpoint_id}/status/{job_id}"
        if not self.execute:
            return self._dry("queue.status", "GET", url, None)
        raw = self._request_json("GET", url, expected_status=200)
        job = _parse_queue_job(raw, endpoint_id, context="queue status")
        if job.job_id != job_id:
            raise RunPodProtocolError("status response job ID differs from the request")
        return job

    def cancel_job(
        self,
        endpoint_id: str,
        job_id: str,
        *,
        run_tag: str,
        idempotency_key: str,
    ) -> QueueJob | DryRunReceipt:
        _require_resource_id(endpoint_id, "endpoint_id")
        _require_resource_id(job_id, "job_id")
        _require_run_tag(run_tag)
        _require_idempotency(idempotency_key)
        url = f"{QUEUE_BASE_URL}/{endpoint_id}/cancel/{job_id}"
        if not self.execute:
            return self._dry("queue.cancel", "POST", url, None, run_tag, idempotency_key)
        raw = self._request_json(
            "POST",
            url,
            expected_status=200,
            extra_headers=_write_headers(run_tag, idempotency_key),
        )
        job = _parse_queue_job(raw, endpoint_id, context="queue cancel")
        if job.job_id != job_id or job.status != "CANCELLED":
            raise RunPodProtocolError("cancel response must confirm the requested job as CANCELLED")
        return job

    def billing_history(self, query: BillingQuery) -> BillingHistory | DryRunReceipt:
        url = f"{MANAGEMENT_BASE_URL}/billing/serverless"
        if not self.execute:
            return self._dry("billing.serverless", "GET", url, query.to_params())
        raw = self._request_json("GET", url, expected_status=200, params=query.to_params())
        return _parse_billing_history(raw)

    def _dry(
        self,
        action: str,
        method: str,
        url: str,
        payload: object | None,
        run_tag: str | None = None,
        idempotency_key: str | None = None,
    ) -> DryRunReceipt:
        return DryRunReceipt(
            action=action,
            method=method,
            url=url,
            request_sha256=canonical_sha256(
                {"method": method, "url": url, "payload_or_params": payload}
            ),
            run_tag=run_tag,
            idempotency_key=idempotency_key,
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        expected_status: int,
        payload: Mapping[str, object] | None = None,
        params: Mapping[str, str | int | float | bool | None] | None = None,
        extra_headers: Mapping[str, str] | None = None,
        allow_not_found: bool = False,
        expect_empty: bool = False,
    ) -> object | None:
        if not self.execute or self._http is None or self._api_key is None:
            raise ContractError("provider access is disabled; pass --execute explicitly")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers is not None:
            headers.update(extra_headers)
        try:
            response = self._http.request(
                method,
                url,
                headers=headers,
                json=payload,
                params=params,
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
                raise RunPodProtocolError(
                    f"RunPod {method} {url} returned an unexpected response body"
                )
            return None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise RunPodProtocolError(
                f"RunPod {method} {url} did not return application/json"
            )
        try:
            parsed: object = response.json()
            return parsed
        except ValueError:
            raise RunPodProtocolError(
                f"RunPod {method} {url} returned invalid JSON"
            ) from None


def make_idempotency_key(value: object) -> str:
    return "idem-" + canonical_sha256(value).split(":", 1)[1]


def _parse_endpoint(value: object) -> EndpointSummary:
    raw = _strict_object(value, _ENDPOINT_REQUIRED, _ENDPOINT_KEYS - _ENDPOINT_REQUIRED, "endpoint")
    endpoint_id = _required_string(raw, "id", "endpoint")
    name = _required_string(raw, "name", "endpoint")
    _require_resource_id(endpoint_id, "endpoint.id")
    workers_raw = _strict_object(
        raw["workers"], {"min", "max"}, {"idleTimeout"}, "endpoint.workers"
    )
    idle_timeout_raw = workers_raw.get("idleTimeout")
    if idle_timeout_raw is not None and (
        isinstance(idle_timeout_raw, bool) or not isinstance(idle_timeout_raw, int)
    ):
        raise RunPodProtocolError("endpoint.workers.idleTimeout must be an integer")
    workers = WorkerBounds(
        _required_int(workers_raw, "min", "endpoint.workers"),
        _required_int(workers_raw, "max", "endpoint.workers"),
        idle_timeout_raw,
    )
    scaling = _as_mapping(raw["scaling"], "endpoint.scaling")
    scaling_type = scaling.get("type")
    if scaling_type == "QUEUE_DELAY":
        scaling = _strict_object(
            scaling, {"type", "queueDelay"}, set(), "endpoint.scaling"
        )
        queue_delay = _decimal(
            scaling["queueDelay"], "endpoint.scaling.queueDelay", protocol=True
        )
        if queue_delay < Decimal("0.5"):
            raise RunPodProtocolError("endpoint queueDelay must be at least 0.5")
        parsed_scaling = ScalingPolicy("QUEUE_DELAY", queue_delay)
    elif scaling_type == "REQUEST_COUNT":
        scaling = _strict_object(
            scaling, {"type", "requestCount"}, set(), "endpoint.scaling"
        )
        request_count = _required_int(scaling, "requestCount", "endpoint.scaling")
        if request_count < 1:
            raise RunPodProtocolError("endpoint requestCount must be positive")
        if workers.idle_timeout_seconds is not None:
            raise RunPodProtocolError(
                "REQUEST_COUNT response must omit workers.idleTimeout"
            )
        parsed_scaling = ScalingPolicy("REQUEST_COUNT", Decimal(request_count))
    else:
        raise RunPodProtocolError("endpoint scaling type is unknown")
    for key in ("dataCenterIds", "networkVolumes"):
        if not isinstance(raw[key], list) or any(not isinstance(item, str) for item in raw[key]):
            raise RunPodProtocolError(f"endpoint {key} must be an array of strings")
    _required_int(raw, "timeout", "endpoint")
    if raw["flashboot"] not in {"OFF", "FLASHBOOT", "PRIORITY_FLASHBOOT"}:
        raise RunPodProtocolError("endpoint flashboot mode is unknown")
    created_at = _required_string(raw, "createdAt", "endpoint")
    _require_rfc3339(created_at, "endpoint.createdAt", protocol=True)
    endpoint_type_raw = raw.get("type")
    endpoint_type: str | None
    if endpoint_type_raw is None:
        endpoint_type = None
    elif endpoint_type_raw in {"QUEUE", "LOAD_BALANCER"}:
        endpoint_type = str(endpoint_type_raw)
    else:
        raise RunPodProtocolError("endpoint type is unknown")
    request_urls = raw.get("requestUrls")
    if request_urls is not None:
        _validate_request_urls(request_urls, endpoint_id, endpoint_type)
    image_raw = raw.get("image")
    if image_raw is not None and not isinstance(image_raw, str):
        raise RunPodProtocolError("endpoint image must be a string or null")
    env = raw.get("env", {})
    if env is None:
        env = {}
    if not isinstance(env, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in env.items()
    ):
        raise RunPodProtocolError("endpoint env must be a string map")
    run_tag_raw = env.get("AKC_RUN_TAG") or env.get("STRUCTARA_RUN_TAG")
    if run_tag_raw is not None and (
        not isinstance(run_tag_raw, str) or not _RUN_TAG_RE.fullmatch(run_tag_raw)
    ):
        raise RunPodProtocolError("endpoint run tag is malformed")
    return EndpointSummary(
        endpoint_id=endpoint_id,
        name=name,
        endpoint_type=endpoint_type,
        image=image_raw,
        workers=workers,
        scaling=parsed_scaling,
        created_at=created_at,
        env_names=tuple(sorted(env)),
        run_tag=run_tag_raw,
        response_sha256=canonical_sha256(raw),
    )


def _validate_request_urls(value: object, endpoint_id: str, endpoint_type: str | None) -> None:
    raw = _as_mapping(value, "endpoint.requestUrls")
    if endpoint_type == "QUEUE":
        required = {
            "run",
            "runSync",
            "status",
            "stream",
            "cancel",
            "retry",
            "purgeQueue",
            "health",
        }
        strict = _strict_object(raw, required, set(), "endpoint.requestUrls")
        root = f"{QUEUE_BASE_URL}/{endpoint_id}"
        expected = {
            "run": f"{root}/run",
            "runSync": f"{root}/runsync",
            "status": f"{root}/status/{{job_id}}",
            "stream": f"{root}/stream/{{job_id}}",
            "cancel": f"{root}/cancel/{{job_id}}",
            "retry": f"{root}/retry/{{job_id}}",
            "purgeQueue": f"{root}/purge-queue",
            "health": f"{root}/health",
        }
        if strict != expected:
            raise RunPodProtocolError("queue endpoint request URLs differ from the pinned origin")
    elif endpoint_type == "LOAD_BALANCER":
        strict = _strict_object(raw, {"base", "health"}, set(), "endpoint.requestUrls")
        base = f"https://{endpoint_id}.api.runpod.ai"
        if strict["base"] != base or not str(strict["health"]).startswith(base + "/"):
            raise RunPodProtocolError("load-balancing URL differs from the pinned origin")
    else:
        raise RunPodProtocolError("requestUrls require a documented endpoint type")


def _parse_queue_job(value: object, endpoint_id: str, *, context: str) -> QueueJob:
    allowed = {"id", "status", "output", "error", "delayTime", "executionTime", "workerId"}
    raw = _strict_object(value, {"id", "status"}, allowed - {"id", "status"}, context)
    job_id = _required_string(raw, "id", context)
    _require_resource_id(job_id, f"{context}.id", protocol=True)
    status = _required_string(raw, "status", context)
    if status not in _ALLOWED_QUEUE_STATUSES:
        raise RunPodProtocolError(f"{context} returned an unknown status")
    for key in ("delayTime", "executionTime"):
        if key in raw and raw[key] is not None and (
            isinstance(raw[key], bool) or not isinstance(raw[key], int) or raw[key] < 0
        ):
            raise RunPodProtocolError(f"{context}.{key} must be a non-negative integer")
    if status == "COMPLETED" and "output" not in raw:
        raise RunPodProtocolError("COMPLETED queue result must carry output")
    return QueueJob(
        endpoint_id=endpoint_id,
        job_id=job_id,
        status=status,
        output=raw.get("output"),
        error_present=raw.get("error") is not None,
        delay_time_ms=raw.get("delayTime"),
        execution_time_ms=raw.get("executionTime"),
        response_sha256=canonical_sha256(raw),
    )


def _parse_billing_history(value: object) -> BillingHistory:
    root = _strict_object(value, {"records", "metadata"}, set(), "billing history")
    rows = root["records"]
    if not isinstance(rows, list):
        raise RunPodProtocolError("billing records must be an array")
    records = tuple(_parse_billing_record(item) for item in rows)
    metadata = _strict_object(
        root["metadata"],
        {"query", "recordCount", "uniqueServerlessCount", "totals"},
        set(),
        "billing metadata",
    )
    if _required_int(metadata, "recordCount", "billing metadata") != len(records):
        raise RunPodProtocolError("billing recordCount differs from records length")
    unique_count = _required_int(metadata, "uniqueServerlessCount", "billing metadata")
    if unique_count != len({item.endpoint_id for item in records}):
        raise RunPodProtocolError("billing uniqueServerlessCount is inconsistent")
    _parse_billing_query_echo(metadata["query"])
    totals = _parse_billing_amounts(metadata["totals"], "billing totals")
    total_amount = totals[0]
    if total_amount != sum((item.total_amount_usd for item in records), Decimal("0")):
        raise RunPodProtocolError("billing totalAmount differs from the record sum")
    return BillingHistory(records, total_amount, canonical_sha256(root))


def _parse_billing_record(value: object) -> BillingRecord:
    raw = _strict_object(
        value,
        {
            "serverlessId",
            "startTime",
            "endTime",
            "totalAmount",
            "gpuAmount",
            "cpuAmount",
            "diskAmount",
            "feeAmount",
        },
        set(),
        "billing record",
    )
    endpoint_id = _required_string(raw, "serverlessId", "billing record")
    _require_resource_id(endpoint_id, "billing.serverlessId", protocol=True)
    start = _required_string(raw, "startTime", "billing record")
    end = _required_string(raw, "endTime", "billing record")
    _require_rfc3339(start, "billing.startTime", protocol=True)
    _require_rfc3339(end, "billing.endTime", protocol=True)
    amounts = _parse_billing_amounts(raw, "billing record")
    return BillingRecord(endpoint_id, start, end, *amounts)


def _parse_billing_amounts(value: object, context: str) -> tuple[Decimal, ...]:
    raw = _as_mapping(value, context)
    keys = ("totalAmount", "gpuAmount", "cpuAmount", "diskAmount", "feeAmount")
    amounts = tuple(_decimal(raw.get(key), f"{context}.{key}", protocol=True) for key in keys)
    if any(item < 0 for item in amounts):
        raise RunPodProtocolError(f"{context} cannot contain negative amounts")
    return amounts


def _parse_billing_query_echo(value: object) -> None:
    raw = _strict_object(
        value,
        {"startTime", "endTime", "bucketSize"},
        {"serverlessId"},
        "billing query echo",
    )
    _require_rfc3339(
        _required_string(raw, "startTime", "billing query echo"),
        "startTime",
        protocol=True,
    )
    _require_rfc3339(
        _required_string(raw, "endTime", "billing query echo"),
        "endTime",
        protocol=True,
    )
    if raw["bucketSize"] not in {"hour", "day", "week", "month", "year"}:
        raise RunPodProtocolError("billing query echo has an unknown bucket size")
    if "serverlessId" in raw and raw["serverlessId"] is not None:
        if not isinstance(raw["serverlessId"], str):
            raise RunPodProtocolError("billing query serverlessId must be a string or null")
        _require_resource_id(raw["serverlessId"], "billing.query.serverlessId", protocol=True)


def _write_headers(run_tag: str, idempotency_key: str) -> dict[str, str]:
    return {"Idempotency-Key": idempotency_key, "X-AKC-Run-Tag": run_tag}


def _strict_object(
    value: object,
    required: set[str] | frozenset[str],
    optional: set[str] | frozenset[str],
    context: str,
) -> Mapping[str, Any]:
    raw = _as_mapping(value, context)
    keys = set(raw)
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing or unknown:
        raise RunPodProtocolError(
            f"{context} shape drift (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    if any(not isinstance(key, str) for key in raw):
        raise RunPodProtocolError(f"{context} keys must be strings")
    return raw


def _as_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunPodProtocolError(f"{context} must be a JSON object")
    return value


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        unknown_names = sorted(str(item) for item in unknown)
        raise ContractError(f"{context} contains unknown fields: {unknown_names}")


def _required_string(raw: Mapping[str, Any], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RunPodProtocolError(f"{context}.{key} must be a non-empty string")
    return value


def _required_int(raw: Mapping[str, Any], key: str, context: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunPodProtocolError(f"{context}.{key} must be an integer")
    return value


def _decimal(value: object, field_name: str, *, protocol: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        if protocol:
            raise RunPodProtocolError(f"{field_name} must be a finite number")
        raise ContractError(f"{field_name} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        if protocol:
            raise RunPodProtocolError(f"{field_name} must be a finite number") from None
        raise ContractError(f"{field_name} must be a finite number") from None
    if not result.is_finite():
        if protocol:
            raise RunPodProtocolError(f"{field_name} must be finite")
        raise ContractError(f"{field_name} must be finite")
    return result


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{field_name} must be an array of strings")
    return tuple(value)


def _require_resource_id(value: str, field_name: str, *, protocol: bool = False) -> str:
    if not _RESOURCE_ID_RE.fullmatch(value):
        if protocol:
            raise RunPodProtocolError(f"{field_name} is not a valid provider resource ID")
        raise ContractError(f"{field_name} is not a valid provider resource ID")
    return value


def _require_run_tag(value: str) -> str:
    if not _RUN_TAG_RE.fullmatch(value):
        raise ContractError("run_tag must match v6-[a-z0-9][a-z0-9._-]{2,127}")
    return value


def _require_idempotency(value: str) -> str:
    if not _IDEMPOTENCY_RE.fullmatch(value):
        raise ContractError("idempotency_key must be idem- followed by 64 lowercase hex")
    return value


def _require_rfc3339(value: str, field_name: str, *, protocol: bool = False) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        if protocol:
            raise RunPodProtocolError(f"{field_name} must be RFC 3339") from None
        raise ContractError(f"{field_name} must be RFC 3339") from None
    if parsed.tzinfo is None:
        if protocol:
            raise RunPodProtocolError(f"{field_name} must include a timezone")
        raise ContractError(f"{field_name} must include a timezone")
    return value


def _now_rfc3339() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_receipt_sha256(value: str) -> str:
    """Public helper used by the coordinator for provider receipt binding."""

    return require_sha256(value, "receipt_sha256")
