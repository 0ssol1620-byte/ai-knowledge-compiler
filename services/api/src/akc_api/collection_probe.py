"""Fail-closed contract for sampled parser/model preflight probes."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CollectionProbeRequest:
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    source_file_id: uuid.UUID
    source_sha256: str
    source_filename: str
    source_bytes: bytes
    page_index: int
    source_page_input_sha256: str
    predicted_route: str


class CollectionProbeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    probe_kind: Literal["native_parser", "ocr_model", "vlm_model"]
    probe_revision: Literal["collection-parser-model-probe-v1"]
    execution_receipt_id: uuid.UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_index: int = Field(ge=0)
    selected_route: str = Field(min_length=1, max_length=80)
    recovery_probability: float = Field(ge=0, le=1)
    parser_revision: str = Field(min_length=1, max_length=160)
    model_revision: str = Field(min_length=1, max_length=160)
    provider_revision: str = Field(min_length=1, max_length=160)
    runtime_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    started_monotonic_ns: int = Field(ge=0)
    completed_monotonic_ns: int = Field(gt=0)
    runtime_seconds: float = Field(gt=0, le=86_400)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_length: int = Field(gt=0)
    output_tokens: int = Field(ge=0)
    artifact: dict[str, Any]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation: dict[str, Any]
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation_key_id: str = Field(min_length=1, max_length=160)
    attestation_signature: str = Field(min_length=16, max_length=4096)

    @model_validator(mode="after")
    def verify_internal_receipt(self) -> CollectionProbeReceipt:
        if self.completed_monotonic_ns <= self.started_monotonic_ns:
            raise ValueError("probe monotonic interval is invalid")
        measured = (self.completed_monotonic_ns - self.started_monotonic_ns) / 1_000_000_000
        if abs(measured - self.runtime_seconds) > max(0.001, measured * 0.01):
            raise ValueError("probe runtime does not match monotonic timing")
        artifact_fields = {
            "execution_receipt_id": str(self.execution_receipt_id),
            "source_page_input_sha256": self.source_page_input_sha256,
            "selected_route": self.selected_route,
            "recovery_probability": self.recovery_probability,
            "parser_revision": self.parser_revision,
            "model_revision": self.model_revision,
            "provider_revision": self.provider_revision,
            "runtime_image_digest": self.runtime_image_digest,
            "output_sha256": self.output_sha256,
            "output_length": self.output_length,
        }
        if any(self.artifact.get(key) != value for key, value in artifact_fields.items()):
            raise ValueError("probe artifact does not bind the execution result")
        if hashlib.sha256(canonical_json(self.artifact)).hexdigest() != self.artifact_sha256:
            raise ValueError("probe artifact digest mismatch")
        attestation_fields = {
            "schema_version": self.schema_version,
            "probe_kind": self.probe_kind,
            "probe_revision": self.probe_revision,
            "execution_receipt_id": str(self.execution_receipt_id),
            "source_sha256": self.source_sha256,
            "source_page_input_sha256": self.source_page_input_sha256,
            "page_index": self.page_index,
            "artifact_sha256": self.artifact_sha256,
            "runtime_seconds": self.runtime_seconds,
            "output_tokens": self.output_tokens,
            "parser_revision": self.parser_revision,
            "model_revision": self.model_revision,
            "provider_revision": self.provider_revision,
            "runtime_image_digest": self.runtime_image_digest,
            "output_sha256": self.output_sha256,
            "output_length": self.output_length,
            "started_monotonic_ns": self.started_monotonic_ns,
            "completed_monotonic_ns": self.completed_monotonic_ns,
        }
        if self.attestation != attestation_fields:
            raise ValueError("probe attestation does not exactly bind the receipt")
        if hashlib.sha256(canonical_json(self.attestation)).hexdigest() != self.attestation_sha256:
            raise ValueError("probe attestation digest mismatch")
        return self


class CollectionProbeExecutor(Protocol):
    async def execute(self, request: CollectionProbeRequest) -> CollectionProbeReceipt: ...


class CollectionProbeAttestationVerifier(Protocol):
    async def verify(
        self,
        *,
        key_id: str,
        attestation: bytes,
        signature: str,
    ) -> bool: ...


def source_page_input_sha256(source_bytes: bytes, page_index: int) -> str:
    return hashlib.sha256(
        b"akc-collection-probe-input-v1\0"
        + hashlib.sha256(source_bytes).digest()
        + page_index.to_bytes(8, "big", signed=False)
    ).hexdigest()


__all__ = [
    "CollectionProbeAttestationVerifier",
    "CollectionProbeExecutor",
    "CollectionProbeReceipt",
    "CollectionProbeRequest",
    "canonical_json",
    "source_page_input_sha256",
]
