"""Durable serverless-GPU invocation contracts and enqueue operations.

Only immutable object references and bounded execution options cross this
boundary. Source bytes, extracted text, signed URLs, and provider credentials
are deliberately absent from database rows and event payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    Document,
    GpuInvocationEvent,
    GpuProviderInvocation,
    ProcessingJob,
    Project,
    utcnow,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
_ENDPOINT = re.compile(r"^[A-Za-z0-9_-]{3,80}$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "dead_letter", "cancelled"})
_TRANSITION_CATEGORIES = frozenset({"gpu_oom", "invalid_output"})
_TRANSITION_STRATEGIES = frozenset({"reduce_or_escalate", "fallback"})
_TRANSITION_ACTIONS = frozenset({"reduce", "escalate", "fallback"})
_TRANSITION_ROUTES = frozenset(
    {
        "hpd_fast",
        "paddle_fast",
        "paddle_vl",
        "unlimited_long",
    }
)
_ALLOWED_OPTION_KEYS = frozenset(
    {
        "artifact_contract",
        "batch_size",
        "bbox1000",
        "chart_recognition",
        "colorspace",
        "deterministic_seed",
        "dpi",
        "formula_recognition",
        "language_hints",
        "knowledge_schema_sha256",
        "knowledge_stage",
        "knowledge_unit_id",
        "knowledge_compile_input_sha256",
        "max_output_tokens",
        "max_pages",
        "ocr_image_blocks",
        "orientation_classify",
        "input_size_bytes",
        "page_height_px",
        "page_asset_id",
        "page_index0",
        "page_range",
        "page_width_px",
        "parallel_v6",
        "preprocessing_transform_sha256",
        "prompt_revision",
        "quality_profile",
        "route_profile",
        "schema_profile",
        "table_recognition",
        "temperature",
        "tile_size",
        "top_p",
        "unwarp",
    }
)

_PARALLEL_V6_SCHEMA_VERSION = "parallel-v6-output-admission-1.0"
_PARALLEL_V6_ISSUER = "akc-api"
_PARALLEL_V6_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "issuer",
        "tenant_id",
        "collection_id",
        "processing_job_id",
        "document_id",
        "document_version_id",
        "shard_id",
        "attempt_id",
        "expected_input_sha256",
        "expected_shard_input_sha256",
        "expected_request_sha256",
        "expected_output_object_key",
        "expected_model_revision",
        "expected_runtime_image_digest",
        "expected_adapter_version",
    }
)


class GpuInvocationConflict(RuntimeError):
    """An idempotency key was reused for a different immutable request."""


class GpuInvocationRejected(RuntimeError):
    """The request violates scope, lifecycle, or content-isolation policy."""


@dataclass(frozen=True, slots=True)
class GpuTransitionTarget:
    """One exact, registry-approved internal provider binding."""

    route: str
    route_profile: str
    provider_key: str
    endpoint_id: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    registry_policy_version: str

    def __post_init__(self) -> None:
        if self.route not in _TRANSITION_ROUTES:
            raise ValueError("invalid transition route")
        if not _IDENTIFIER.fullmatch(self.route_profile):
            raise ValueError("invalid transition route_profile")
        if not _IDENTIFIER.fullmatch(self.provider_key):
            raise ValueError("invalid transition provider_key")
        if not _ENDPOINT.fullmatch(self.endpoint_id):
            raise ValueError("invalid transition endpoint_id")
        if not _REVISION.fullmatch(self.model_revision):
            raise ValueError("exact transition model_revision is required")
        if not _IMAGE_DIGEST.fullmatch(self.runtime_image_digest):
            raise ValueError("exact transition runtime_image_digest is required")
        if not _IDENTIFIER.fullmatch(self.adapter_version):
            raise ValueError("exact transition adapter_version is required")
        if not _IDENTIFIER.fullmatch(self.registry_policy_version):
            raise ValueError("invalid transition registry_policy_version")

    @property
    def manifest(self) -> dict[str, str]:
        return {
            "route": self.route,
            "route_profile": self.route_profile,
            "provider_key": self.provider_key,
            "endpoint_id": self.endpoint_id,
            "model_revision": self.model_revision,
            "runtime_image_digest": self.runtime_image_digest,
            "adapter_version": self.adapter_version,
            "registry_policy_version": self.registry_policy_version,
        }

    @classmethod
    def from_manifest(cls, value: object) -> GpuTransitionTarget:
        if not isinstance(value, dict) or set(value) != {
            "route",
            "route_profile",
            "provider_key",
            "endpoint_id",
            "model_revision",
            "runtime_image_digest",
            "adapter_version",
            "registry_policy_version",
        }:
            raise ValueError("invalid transition target manifest")
        if not all(isinstance(item, str) for item in value.values()):
            raise ValueError("invalid transition target manifest")
        return cls(**cast(dict[str, str], value))


@dataclass(frozen=True, slots=True)
class GpuTransitionPolicy:
    """Immutable approval snapshot for bounded internal provider transitions."""

    source_route: str
    source_provider_key: str
    router_policy_version: str
    invalid_output_fallback: GpuTransitionTarget | None = None
    oom_escalation: GpuTransitionTarget | None = None

    def __post_init__(self) -> None:
        if self.source_route not in _TRANSITION_ROUTES:
            raise ValueError("invalid transition source_route")
        if not _IDENTIFIER.fullmatch(self.source_provider_key):
            raise ValueError("invalid transition source_provider_key")
        if not _IDENTIFIER.fullmatch(self.router_policy_version):
            raise ValueError("invalid transition router_policy_version")

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source_route": self.source_route,
            "source_provider_key": self.source_provider_key,
            "router_policy_version": self.router_policy_version,
            "invalid_output_fallback": (
                self.invalid_output_fallback.manifest
                if self.invalid_output_fallback is not None
                else None
            ),
            "oom_escalation": (
                self.oom_escalation.manifest if self.oom_escalation is not None else None
            ),
        }

    @classmethod
    def from_manifest(cls, value: object) -> GpuTransitionPolicy | None:
        if value in (None, {}):
            return None
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "source_route",
            "source_provider_key",
            "router_policy_version",
            "invalid_output_fallback",
            "oom_escalation",
        }:
            raise ValueError("invalid GPU transition policy manifest")
        if value.get("schema_version") != "1.0":
            raise ValueError("unsupported GPU transition policy")
        source_route = value.get("source_route")
        source_provider_key = value.get("source_provider_key")
        router_policy_version = value.get("router_policy_version")
        if not all(
            isinstance(item, str)
            for item in (source_route, source_provider_key, router_policy_version)
        ):
            raise ValueError("invalid GPU transition policy manifest")
        fallback = value.get("invalid_output_fallback")
        escalation = value.get("oom_escalation")
        return cls(
            source_route=cast(str, source_route),
            source_provider_key=cast(str, source_provider_key),
            router_policy_version=cast(str, router_policy_version),
            invalid_output_fallback=(
                GpuTransitionTarget.from_manifest(fallback) if fallback is not None else None
            ),
            oom_escalation=(
                GpuTransitionTarget.from_manifest(escalation) if escalation is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class GpuInvocationSpec:
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: str
    provider_key: str
    endpoint_id: str
    idempotency_key: str
    input_bucket: Literal["source", "derived"]
    input_object_key: str
    input_sha256: str
    output_object_key: str
    model_revision: str
    runtime_image_digest: str
    adapter_version: str
    page_id: uuid.UUID | None = None
    options: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 3
    transition_policy: GpuTransitionPolicy | None = None
    parent_invocation_id: uuid.UUID | None = None
    lineage_root_invocation_id: uuid.UUID | None = None
    transition_category: str | None = None
    transition_strategy: str | None = None
    transition_action: str | None = None
    transition_attempt: int = 0

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.provider_key):
            raise ValueError("invalid provider_key")
        if not _IDENTIFIER.fullmatch(self.document_version_id):
            raise ValueError("invalid document_version_id")
        if not _ENDPOINT.fullmatch(self.endpoint_id):
            raise ValueError("invalid endpoint_id")
        if not _IDENTIFIER.fullmatch(self.idempotency_key):
            raise ValueError("invalid idempotency_key")
        if not _REVISION.fullmatch(self.model_revision):
            raise ValueError("exact model_revision is required")
        if not _IMAGE_DIGEST.fullmatch(self.runtime_image_digest):
            raise ValueError("exact runtime_image_digest is required")
        if not _IDENTIFIER.fullmatch(self.adapter_version):
            raise ValueError("exact adapter_version is required")
        normalized_sha = self.input_sha256.removeprefix("sha256:")
        if not _SHA256.fullmatch(normalized_sha):
            raise ValueError("invalid input_sha256")
        object.__setattr__(self, "input_sha256", normalized_sha)
        if self.input_bucket not in {"source", "derived"}:
            raise ValueError("invalid input_bucket")
        _validate_object_key(self.input_object_key, tenant_id=self.tenant_id)
        _validate_object_key(self.output_object_key, tenant_id=self.tenant_id)
        if "/derived/" not in f"/{self.output_object_key}":
            raise ValueError("GPU output must use the tenant derived prefix")
        if self.input_object_key == self.output_object_key:
            raise ValueError("GPU input and output object keys must differ")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be 1..10")
        _validate_options(self.options, spec=self)
        if (
            self.transition_policy is not None
            and self.transition_policy.source_provider_key != self.provider_key
            and self.parent_invocation_id is None
        ):
            raise ValueError("transition policy source provider mismatch")
        transition_values = (
            self.parent_invocation_id,
            self.lineage_root_invocation_id,
            self.transition_category,
            self.transition_strategy,
            self.transition_action,
        )
        if self.parent_invocation_id is None:
            if any(value is not None for value in transition_values[1:]):
                raise ValueError("root invocation cannot carry transition metadata")
            if self.transition_attempt != 0:
                raise ValueError("root invocation transition_attempt must be zero")
        else:
            if self.lineage_root_invocation_id is None:
                raise ValueError("child invocation requires lineage root")
            if self.transition_category not in _TRANSITION_CATEGORIES:
                raise ValueError("invalid transition category")
            if self.transition_strategy not in _TRANSITION_STRATEGIES:
                raise ValueError("invalid transition strategy")
            if self.transition_action not in _TRANSITION_ACTIONS:
                raise ValueError("invalid transition action")
            if not 1 <= self.transition_attempt <= 10:
                raise ValueError("transition_attempt must be 1..10")

    @property
    def request_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "tenant_id": str(self.tenant_id),
            "job_id": str(self.job_id),
            "project_id": str(self.project_id),
            "document_id": str(self.document_id),
            "document_version_id": self.document_version_id,
            "page_id": str(self.page_id) if self.page_id is not None else None,
            "provider": "runpod",
            "provider_key": self.provider_key,
            "endpoint_id": self.endpoint_id,
            "idempotency_key": self.idempotency_key,
            "input_bucket": self.input_bucket,
            "input_object_key": self.input_object_key,
            "input_sha256": self.input_sha256,
            "output_object_key": self.output_object_key,
            "model_revision": self.model_revision,
            "runtime_image_digest": self.runtime_image_digest,
            "adapter_version": self.adapter_version,
            "options": self.options,
            "max_attempts": self.max_attempts,
            "transition_policy": (
                self.transition_policy.manifest if self.transition_policy is not None else {}
            ),
            "parent_invocation_id": (
                str(self.parent_invocation_id) if self.parent_invocation_id is not None else None
            ),
            "lineage_root_invocation_id": (
                str(self.lineage_root_invocation_id)
                if self.lineage_root_invocation_id is not None
                else None
            ),
            "transition_category": self.transition_category,
            "transition_strategy": self.transition_strategy,
            "transition_action": self.transition_action,
            "transition_attempt": self.transition_attempt,
        }

    @property
    def request_manifest_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.request_manifest)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _validate_object_key(value: str, *, tenant_id: uuid.UUID) -> None:
    if not value or len(value) > 500 or "\\" in value or "\x00" in value:
        raise ValueError("invalid tenant object key")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid tenant object key")
    if not value.startswith(f"tenants/{tenant_id}/"):
        raise ValueError("object key crosses tenant scope")


def _validate_options(options: dict[str, Any], *, spec: GpuInvocationSpec) -> None:
    if set(options) - _ALLOWED_OPTION_KEYS:
        raise ValueError("unknown or content-bearing GPU option")
    if len(_canonical_json(options)) > 16 * 1024:
        raise ValueError("GPU options too large")
    for key, value in options.items():
        if key == "parallel_v6":
            _validate_parallel_v6_envelope(value, spec=spec)
            continue
        values = value if isinstance(value, list) else [value]
        if isinstance(value, (dict, bytes, bytearray)) or len(values) > 64:
            raise ValueError(f"invalid GPU option: {key}")
        for item in values:
            if item is None or isinstance(item, bool):
                continue
            if isinstance(item, int):
                if isinstance(item, bool) or not -(2**31) <= item < 2**31:
                    raise ValueError(f"invalid GPU option: {key}")
                continue
            if isinstance(item, float):
                if not math.isfinite(item):
                    raise ValueError(f"invalid GPU option: {key}")
                continue
            if isinstance(item, str) and 0 < len(item) <= 160:
                continue
            raise ValueError(f"invalid GPU option: {key}")


def _validate_parallel_v6_envelope(value: object, *, spec: GpuInvocationSpec) -> None:
    if not isinstance(value, dict) or set(value) != _PARALLEL_V6_ENVELOPE_FIELDS:
        raise ValueError("invalid parallel_v6 GPU option")
    if (
        value.get("schema_version") != _PARALLEL_V6_SCHEMA_VERSION
        or value.get("issuer") != _PARALLEL_V6_ISSUER
    ):
        raise ValueError("invalid parallel_v6 GPU option")

    for key in (
        "tenant_id",
        "collection_id",
        "processing_job_id",
        "document_id",
        "shard_id",
        "attempt_id",
    ):
        raw = value.get(key)
        if not isinstance(raw, str):
            raise ValueError("invalid parallel_v6 GPU option")
        try:
            parsed = uuid.UUID(raw)
        except ValueError as exc:
            raise ValueError("invalid parallel_v6 GPU option") from exc
        if str(parsed) != raw:
            raise ValueError("invalid parallel_v6 GPU option")

    for key in (
        "expected_input_sha256",
        "expected_shard_input_sha256",
        "expected_request_sha256",
    ):
        raw = value.get(key)
        if not isinstance(raw, str) or _SHA256.fullmatch(raw) is None:
            raise ValueError("invalid parallel_v6 GPU option")

    expected = {
        "tenant_id": str(spec.tenant_id),
        "processing_job_id": str(spec.job_id),
        "document_id": str(spec.document_id),
        "document_version_id": spec.document_version_id,
        "expected_input_sha256": spec.input_sha256,
        "expected_output_object_key": spec.output_object_key,
        "expected_model_revision": spec.model_revision,
        "expected_runtime_image_digest": spec.runtime_image_digest,
        "expected_adapter_version": spec.adapter_version,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("parallel_v6 GPU option scope mismatch")

    for key in (
        "document_version_id",
        "expected_output_object_key",
        "expected_model_revision",
        "expected_runtime_image_digest",
        "expected_adapter_version",
    ):
        raw = value.get(key)
        if (
            not isinstance(raw, str)
            or not raw
            or len(raw) > 500
            or any(ord(character) < 32 for character in raw)
        ):
            raise ValueError("invalid parallel_v6 GPU option")
    _validate_object_key(spec.output_object_key, tenant_id=spec.tenant_id)


async def append_gpu_event(
    session: AsyncSession,
    invocation: GpuProviderInvocation,
    *,
    event_type: str,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> GpuInvocationEvent:
    """Append a bounded event while the invocation row is locked by the caller."""

    safe_payload = payload or {}
    if len(_canonical_json(safe_payload)) > 16 * 1024:
        raise ValueError("GPU event payload too large")
    forbidden = {
        key
        for key in safe_payload
        if any(marker in key.casefold() for marker in ("url", "content", "text", "token", "secret"))
    }
    if forbidden:
        raise ValueError("GPU event payload contains sensitive fields")
    invocation.event_sequence += 1
    event = GpuInvocationEvent(
        tenant_id=invocation.tenant_id,
        invocation_id=invocation.id,
        sequence=invocation.event_sequence,
        event_type=event_type,
        payload=safe_payload,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(event)
    await session.flush()
    return event


async def _active_target(
    session: AsyncSession,
    spec: GpuInvocationSpec,
) -> ProcessingJob | None:
    return cast(
        ProcessingJob | None,
        await session.scalar(
            select(ProcessingJob)
            .join(
                Project,
                (Project.tenant_id == ProcessingJob.tenant_id)
                & (Project.id == ProcessingJob.project_id),
            )
            .join(
                Document,
                (Document.tenant_id == ProcessingJob.tenant_id)
                & (Document.id == ProcessingJob.document_id),
            )
            .where(
                ProcessingJob.tenant_id == spec.tenant_id,
                ProcessingJob.id == spec.job_id,
                ProcessingJob.project_id == spec.project_id,
                ProcessingJob.document_id == spec.document_id,
                ProcessingJob.status.in_(("queued", "running")),
                Project.deletion_requested_at.is_(None),
                Document.deletion_requested_at.is_(None),
            )
            .with_for_update()
        ),
    )


async def enqueue_gpu_invocation(
    session: AsyncSession,
    spec: GpuInvocationSpec,
) -> GpuProviderInvocation:
    """Idempotently enqueue one immutable invocation in the caller transaction."""

    existing = await session.scalar(
        select(GpuProviderInvocation).where(
            GpuProviderInvocation.tenant_id == spec.tenant_id,
            GpuProviderInvocation.idempotency_key == spec.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_manifest_sha256 != spec.request_manifest_sha256:
            raise GpuInvocationConflict("gpu_invocation_idempotency_conflict")
        return existing
    if await _active_target(session, spec) is None:
        raise GpuInvocationRejected("gpu_invocation_target_not_active")

    invocation = GpuProviderInvocation(
        tenant_id=spec.tenant_id,
        job_id=spec.job_id,
        project_id=spec.project_id,
        document_id=spec.document_id,
        document_version_id=spec.document_version_id,
        page_id=spec.page_id,
        provider="runpod",
        provider_key=spec.provider_key,
        endpoint_id=spec.endpoint_id,
        idempotency_key=spec.idempotency_key,
        request_manifest_sha256=spec.request_manifest_sha256,
        status="queued",
        input_bucket=spec.input_bucket,
        input_object_key=spec.input_object_key,
        input_sha256=spec.input_sha256,
        output_object_key=spec.output_object_key,
        options=spec.options,
        model_revision=spec.model_revision,
        runtime_image_digest=spec.runtime_image_digest,
        adapter_version=spec.adapter_version,
        max_attempts=spec.max_attempts,
        transition_policy=(
            spec.transition_policy.manifest if spec.transition_policy is not None else {}
        ),
        parent_invocation_id=spec.parent_invocation_id,
        lineage_root_invocation_id=spec.lineage_root_invocation_id,
        transition_category=spec.transition_category,
        transition_strategy=spec.transition_strategy,
        transition_action=spec.transition_action,
        transition_attempt=spec.transition_attempt,
    )
    try:
        async with session.begin_nested():
            session.add(invocation)
            await session.flush()
            await append_gpu_event(
                session,
                invocation,
                event_type="gpu.invocation.queued.v1",
                payload={
                    "attempt": 0,
                    "endpoint_id": spec.endpoint_id,
                    "provider_key": spec.provider_key,
                    "parent_invocation_id": (
                        str(spec.parent_invocation_id)
                        if spec.parent_invocation_id is not None
                        else None
                    ),
                    "transition_action": spec.transition_action,
                    "transition_attempt": spec.transition_attempt,
                    "transition_category": spec.transition_category,
                    "transition_strategy": spec.transition_strategy,
                },
            )
    except IntegrityError:
        existing = await session.scalar(
            select(GpuProviderInvocation).where(
                GpuProviderInvocation.tenant_id == spec.tenant_id,
                GpuProviderInvocation.idempotency_key == spec.idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_manifest_sha256 != spec.request_manifest_sha256:
            raise GpuInvocationConflict("gpu_invocation_idempotency_conflict") from None
        return cast(GpuProviderInvocation, existing)
    return invocation


async def request_gpu_cancellation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invocation_id: uuid.UUID,
    reason: Literal["user", "tombstone", "job_cancelled"] = "user",
) -> GpuProviderInvocation | None:
    invocation = await session.scalar(
        select(GpuProviderInvocation)
        .where(
            GpuProviderInvocation.tenant_id == tenant_id,
            GpuProviderInvocation.id == invocation_id,
        )
        .with_for_update()
    )
    if invocation is None or invocation.status in _TERMINAL_STATES:
        return invocation
    if invocation.status != "cancel_requested" or invocation.cancellation_reason != reason:
        invocation.status = "cancel_requested"
        invocation.cancellation_reason = reason
        invocation.available_at = utcnow()
        invocation.lease_token = None
        invocation.lease_expires_at = None
        await append_gpu_event(
            session,
            invocation,
            event_type="gpu.invocation.cancel_requested.v1",
            payload={"reason": reason},
        )
    return invocation


__all__ = [
    "GpuInvocationConflict",
    "GpuInvocationRejected",
    "GpuInvocationSpec",
    "GpuTransitionPolicy",
    "GpuTransitionTarget",
    "append_gpu_event",
    "enqueue_gpu_invocation",
    "request_gpu_cancellation",
]
