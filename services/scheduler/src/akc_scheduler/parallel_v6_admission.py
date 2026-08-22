"""Fail-closed admission of GPU output into the v6 parallel runtime.

The provider never selects a collection, shard, or durable parse attempt.  A
server-authored envelope, already content-bound by the GPU invocation request
manifest, supplies those identities.  This module validates the complete
envelope against both the claimed invocation and the durable projection before
calling :class:`akc_api.parallel_orchestrator.DurableParallelOrchestrator`.

Only output receipt and usage evidence are persisted here.  Validation,
arbitration, acceptance, and customer-credit consumption remain separate
orchestrator gates.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from akc_api.gpu_provider import GpuJobResult
from akc_api.parallel_models import ParallelParseAttempt, ParallelParseShard
from akc_api.parallel_orchestrator import (
    DurableParallelOrchestrator,
    ParallelRuntimeScope,
)
from akc_parallel_runtime import AttemptOutput, CostRecord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SCHEMA_VERSION = "parallel-v6-output-admission-1.0"
_ISSUER = "akc-api"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENVELOPE_FIELDS = frozenset(
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
_MAX_GPU_SECONDS = Decimal("604800")
_MAX_PROVIDER_COST_USD = Decimal("1000000")


class ParallelV6AdmissionError(RuntimeError):
    """The server envelope or its durable scope failed closed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ParallelV6Envelope:
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: str
    shard_id: uuid.UUID
    attempt_id: uuid.UUID
    expected_input_sha256: str
    expected_shard_input_sha256: str
    expected_request_sha256: str
    expected_output_object_key: str
    expected_model_revision: str
    expected_runtime_image_digest: str
    expected_adapter_version: str

    @classmethod
    def parse(cls, value: object) -> ParallelV6Envelope:
        if not isinstance(value, dict) or set(value) != _ENVELOPE_FIELDS:
            raise ParallelV6AdmissionError("GPU_PARALLEL_V6_ENVELOPE_INVALID_OUTPUT")
        if value.get("schema_version") != _SCHEMA_VERSION or value.get("issuer") != _ISSUER:
            raise ParallelV6AdmissionError("GPU_PARALLEL_V6_ENVELOPE_INVALID_OUTPUT")
        try:
            identifiers = {
                field: _canonical_uuid(value.get(field))
                for field in (
                    "tenant_id",
                    "collection_id",
                    "processing_job_id",
                    "document_id",
                    "shard_id",
                    "attempt_id",
                )
            }
            strings = {
                field: _bounded_string(value.get(field), maximum=500)
                for field in (
                    "document_version_id",
                    "expected_output_object_key",
                    "expected_model_revision",
                    "expected_runtime_image_digest",
                    "expected_adapter_version",
                )
            }
            hashes = {
                field: _exact_sha256(value.get(field))
                for field in (
                    "expected_input_sha256",
                    "expected_shard_input_sha256",
                    "expected_request_sha256",
                )
            }
        except (TypeError, ValueError) as exc:
            raise ParallelV6AdmissionError("GPU_PARALLEL_V6_ENVELOPE_INVALID_OUTPUT") from exc
        return cls(
            tenant_id=identifiers["tenant_id"],
            collection_id=identifiers["collection_id"],
            processing_job_id=identifiers["processing_job_id"],
            document_id=identifiers["document_id"],
            document_version_id=strings["document_version_id"],
            shard_id=identifiers["shard_id"],
            attempt_id=identifiers["attempt_id"],
            expected_input_sha256=hashes["expected_input_sha256"],
            expected_shard_input_sha256=hashes["expected_shard_input_sha256"],
            expected_request_sha256=hashes["expected_request_sha256"],
            expected_output_object_key=strings["expected_output_object_key"],
            expected_model_revision=strings["expected_model_revision"],
            expected_runtime_image_digest=strings["expected_runtime_image_digest"],
            expected_adapter_version=strings["expected_adapter_version"],
        )


def _canonical_uuid(value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise TypeError("UUID must be a string")
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError("UUID must use canonical form")
    return parsed


def _bounded_string(value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("invalid bounded string")
    return value


def _exact_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("invalid SHA-256")
    return value


def _metric_decimal(
    metrics: Mapping[str, Any],
    key: str,
    *,
    maximum: Decimal,
) -> Decimal:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_USAGE_INVALID_OUTPUT")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_USAGE_INVALID_OUTPUT") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > maximum:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_USAGE_INVALID_OUTPUT")
    exponent = parsed.as_tuple().exponent
    if key == "estimated_cost_usd" and isinstance(exponent, int) and exponent < -8:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_USAGE_INVALID_OUTPUT")
    return parsed


def _assert_claim_scope(
    envelope: ParallelV6Envelope,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: str,
    input_sha256: str,
    output_object_key: str,
    model_revision: str,
    runtime_image_digest: str,
    adapter_version: str,
) -> None:
    if (
        envelope.tenant_id != tenant_id
        or envelope.processing_job_id != job_id
        or envelope.document_id != document_id
        or envelope.document_version_id != document_version_id
        or envelope.expected_input_sha256 != input_sha256
        or envelope.expected_output_object_key != output_object_key
        or envelope.expected_model_revision != model_revision
        or envelope.expected_runtime_image_digest != runtime_image_digest
        or envelope.expected_adapter_version != adapter_version
    ):
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH")


def _assert_result_scope(
    envelope: ParallelV6Envelope,
    result: GpuJobResult,
    *,
    provider_job_id: str | None,
    provider_key: str,
    endpoint_id: str,
) -> str:
    output_sha256 = result.output_sha256.removeprefix("sha256:")
    if _SHA256.fullmatch(output_sha256) is None:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH")
    if (
        provider_job_id is None
        or result.provider_job_id != provider_job_id
        or result.provider_key != provider_key
        or result.endpoint_id != endpoint_id
        or result.output_object_key != envelope.expected_output_object_key
        or result.model_revision != envelope.expected_model_revision
        or result.runtime_image_digest != envelope.expected_runtime_image_digest
        or result.adapter_version != envelope.expected_adapter_version
    ):
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH")
    return output_sha256


async def _assert_durable_scope(
    session: AsyncSession,
    envelope: ParallelV6Envelope,
    *,
    provider_invocation_id: uuid.UUID,
) -> ParallelParseAttempt:
    row = (
        await session.execute(
            select(ParallelParseAttempt, ParallelParseShard)
            .join(
                ParallelParseShard,
                (ParallelParseShard.tenant_id == ParallelParseAttempt.tenant_id)
                & (ParallelParseShard.id == ParallelParseAttempt.shard_id),
            )
            .where(
                ParallelParseAttempt.tenant_id == envelope.tenant_id,
                ParallelParseAttempt.id == envelope.attempt_id,
                ParallelParseAttempt.shard_id == envelope.shard_id,
                ParallelParseAttempt.provider_invocation_id == provider_invocation_id,
                ParallelParseShard.collection_id == envelope.collection_id,
                ParallelParseShard.document_id == envelope.document_id,
                ParallelParseShard.processing_job_id == envelope.processing_job_id,
            )
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH")
    attempt, shard = row
    if (
        shard.input_sha256 != envelope.expected_shard_input_sha256
        or attempt.request_sha256 != envelope.expected_request_sha256
        or attempt.model_revision != envelope.expected_model_revision
        or attempt.runtime_identity != envelope.expected_runtime_image_digest
    ):
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_SCOPE_MISMATCH")
    if attempt.state not in {"RUNNING", "OUTPUT_RECEIVED"}:
        raise ParallelV6AdmissionError("GPU_PARALLEL_V6_RESULT_STATE_INVALID_OUTPUT")
    return cast(ParallelParseAttempt, attempt)


async def admit_parallel_v6_output(
    session: AsyncSession,
    *,
    options: Mapping[str, Any],
    provider_invocation_id: uuid.UUID,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: str,
    provider_job_id: str | None,
    provider_key: str,
    endpoint_id: str,
    input_sha256: str,
    output_object_key: str,
    model_revision: str,
    runtime_image_digest: str,
    adapter_version: str,
    result: GpuJobResult,
    output_payload: Mapping[str, Any],
    completion_source: Literal["poll", "callback"],
    completed_at: datetime,
) -> bool:
    """Admit a v6 output in the caller's transaction.

    ``False`` means the invocation is a legacy/non-v6 request.  ``True`` means
    the durable attempt and ``attempt.output.received.v1`` projection were
    written (or replayed) without accepting or billing the result.
    """

    if "parallel_v6" not in options:
        return False
    envelope = ParallelV6Envelope.parse(options["parallel_v6"])
    _assert_claim_scope(
        envelope,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        document_version_id=document_version_id,
        input_sha256=input_sha256,
        output_object_key=output_object_key,
        model_revision=model_revision,
        runtime_image_digest=runtime_image_digest,
        adapter_version=adapter_version,
    )
    output_sha256 = _assert_result_scope(
        envelope,
        result,
        provider_job_id=provider_job_id,
        provider_key=provider_key,
        endpoint_id=endpoint_id,
    )
    attempt = await _assert_durable_scope(
        session,
        envelope,
        provider_invocation_id=provider_invocation_id,
    )
    gpu_seconds = _metric_decimal(
        result.metrics,
        "gpu_seconds",
        maximum=_MAX_GPU_SECONDS,
    )
    provider_cost = _metric_decimal(
        result.metrics,
        "estimated_cost_usd",
        maximum=_MAX_PROVIDER_COST_USD,
    )
    orchestrator = DurableParallelOrchestrator(
        session,
        ParallelRuntimeScope(
            tenant_id=envelope.tenant_id,
            collection_id=envelope.collection_id,
            document_id=envelope.document_id,
            processing_job_id=envelope.processing_job_id,
            document_version_id=envelope.document_version_id,
        ),
    )
    output = AttemptOutput(
        prediction_uri=envelope.expected_output_object_key,
        prediction_sha256=output_sha256,
        completed_at=completed_at,
        cost=CostRecord(
            gpu_seconds=gpu_seconds,
            provider_cost=provider_cost,
            user_credits=Decimal("0"),
            duplicate_compute=attempt.attempt_kind in {"hedge", "straggler", "shadow"},
        ),
    )
    await orchestrator.receive_output(
        envelope.attempt_id,
        output,
        output_summary={
            "provider_invocation_id": str(provider_invocation_id),
            "provider_job_id": result.provider_job_id,
            "provider_key": result.provider_key,
            "endpoint_id": result.endpoint_id,
            "result_id": result.result_id,
            "output_bytes": result.output_bytes,
            "warning_count": len(result.warnings),
            "completion_source": completion_source,
            "schema_version": output_payload.get("schema_version"),
            "raw_provider_response_sha256": result.raw_provider_response_sha256,
        },
        operation_key=(f"gpu-output:{provider_invocation_id}:{output_sha256}:{completion_source}"),
    )
    return True


__all__ = [
    "ParallelV6AdmissionError",
    "ParallelV6Envelope",
    "admit_parallel_v6_output",
]
