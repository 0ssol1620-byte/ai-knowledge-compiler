"""Contract models for the reader provider plane (blueprint §8.2, §9, §22, §44)."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from akc_cir.base import (
    Confidence,
    ContractModel,
    NonEmptyStr,
    Sha256,
    StableId,
    canonical_json,
    sha256_digest,
)
from pydantic import Field, model_validator

from .enums import (
    VERIFIED_STATUSES,
    CapabilityStatus,
    FailureClass,
    ReaderFeature,
    ReaderRegistryStatus,
    SourceFamily,
)

READER_CAPABILITY_SCHEMA: Final = "tavonel.reader_capability.v1"
READER_REGISTRY_ENTRY_SCHEMA: Final = "tavonel.reader_registry_entry.v1"
READER_RUN_SCHEMA: Final = "tavonel.reader_run.v1"


def inprocess_runtime_digest(pins: Mapping[str, str]) -> str:
    """Digest the exact runtime an in-process reader executes in.

    There is no container image behind a stdlib/pypdf reader, so §22's
    ``runtimeDigest`` is computed from what actually varies: the interpreter
    version plus the library versions the provider names. It is a real pin of a
    real runtime, not a placeholder for a container digest.
    """
    payload = {"python": ".".join(str(part) for part in sys.version_info[:3]), **dict(pins)}
    return sha256_digest(canonical_json(payload))


@dataclass(frozen=True, slots=True)
class ReaderInput:
    """One source version's bytes, addressed the way the site addresses them.

    A plain dataclass, not a ``ContractModel``: hostile document bytes must not
    be reachable from anything that serialises itself into a receipt.
    ``object_key`` mirrors the site's key without re-deriving it here.

    ``tenant_id`` is carried, never enforced — the reader plane makes no
    authorization decision. It exists because the native parser this campaign
    wraps builds a ``CanonicalDocument`` that requires tenancy, and stamping an
    invented tenant onto a canonical document is exactly the fabrication the
    project constitution forbids.
    """

    source_version_id: str
    tenant_id: str
    representation_id: str
    filename: str
    declared_mime: str
    content_sha256: str
    data: bytes
    object_key: str | None = None


class SourceInspection(ContractModel):
    """Blueprint §8.2. A diagnosis, never a raise: hostile input is described."""

    detected_mime: NonEmptyStr
    source_family: SourceFamily
    container_kind: str | None = None
    encrypted: bool
    corrupted: bool
    has_native_text: bool | None = None
    has_native_structure: bool | None = None
    has_visual_content: bool | None = None
    page_like_units: Annotated[int, Field(ge=0)] | None = None
    confidence: Confidence
    review_reasons: tuple[str, ...] = ()


class ReaderCapability(ContractModel):
    """Blueprint §9.1. A VERIFIED tier without a receipt digest is refused."""

    schema_version: Literal["tavonel.reader_capability.v1"] = READER_CAPABILITY_SCHEMA
    mime_patterns: tuple[NonEmptyStr, ...]
    source_families: tuple[SourceFamily, ...]
    features: tuple[ReaderFeature, ...]
    qualification_status: CapabilityStatus
    qualification_receipt: Sha256 | None = None

    @model_validator(mode="after")
    def validate_capability(self) -> ReaderCapability:
        if not self.mime_patterns:
            raise ValueError("a capability must declare at least one mime pattern")
        for field_name in ("mime_patterns", "source_families", "features"):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not repeat a value")
        if self.qualification_status in VERIFIED_STATUSES and self.qualification_receipt is None:
            raise ValueError(
                "VERIFIED_NATIVE/VERIFIED_HYBRID require a §27 qualification receipt digest"
            )
        return self


class ExtractedUnit(ContractModel):
    """One addressable piece of reader output.

    Every optional field is the evidence for one declared feature, which is how
    ``ReaderRegistry`` probes a declaration instead of trusting it.
    """

    unit_id: StableId
    text: str = ""
    locator: dict[str, Any] | None = None
    bbox1000: tuple[int, int, int, int] | None = None
    table_id: str | None = None
    formula: str | None = None
    byte_range: tuple[int, int] | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> ExtractedUnit:
        if self.bbox1000 is not None:
            x1, y1, x2, y2 = self.bbox1000
            if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
                raise ValueError("bbox1000 must be an ordered 0..1000 box with positive area")
        if self.byte_range is not None and not 0 <= self.byte_range[0] < self.byte_range[1]:
            raise ValueError("byteRange must be an ordered non-empty half-open range")
        return self


class NativeExtraction(ContractModel):
    """What a reader produced, plus the digest a run receipt binds to."""

    provider_id: NonEmptyStr
    revision: NonEmptyStr
    source_version_id: StableId
    representation_id: StableId
    units: tuple[ExtractedUnit, ...]
    output_digest: Sha256

    def observed_features(self) -> frozenset[ReaderFeature]:
        """Features this output demonstrably carries. Nothing is inferred."""
        observed: set[ReaderFeature] = set()
        for unit in self.units:
            if unit.text.strip():
                observed.add(ReaderFeature.NATIVE_TEXT)
            if unit.bbox1000 is not None:
                observed.add(ReaderFeature.LAYOUT)
            if unit.table_id is not None:
                observed.add(ReaderFeature.TABLES)
            if unit.formula is not None:
                observed.add(ReaderFeature.FORMULA)
        return frozenset(observed)


#: The features ``NativeExtraction`` can witness. A provider declaring anything
#: else cannot be probed, so registration refuses it (fail closed) until the
#: extraction model grows a field that carries that evidence.
PROBEABLE_FEATURES: frozenset[ReaderFeature] = frozenset(
    {
        ReaderFeature.NATIVE_TEXT,
        ReaderFeature.LAYOUT,
        ReaderFeature.TABLES,
        ReaderFeature.FORMULA,
    }
)


class ReaderHealth(ContractModel):
    provider_id: NonEmptyStr
    healthy: bool
    circuit_open: bool
    checked_at: datetime
    detail: str | None = None


class ReaderRun(ContractModel):
    """Blueprint §44 cost-ledger receipt. Unmeasured fields stay ``None``."""

    schema_version: Literal["tavonel.reader_run.v1"] = READER_RUN_SCHEMA
    run_id: StableId
    source_version_id: StableId
    representation_id: StableId
    provider_id: NonEmptyStr
    reader_revision: NonEmptyStr
    runtime_digest: Sha256
    input_digest: Sha256
    output_digest: Sha256 | None = None
    started_at: datetime
    ended_at: datetime
    queue_wait_ms: Annotated[int, Field(ge=0)] = 0
    retries: Annotated[int, Field(ge=0)] = 0
    accepted: bool
    failure_class: FailureClass | None = None
    cpu_seconds: Annotated[float, Field(ge=0.0)] | None = None
    gpu_seconds: Annotated[float, Field(ge=0.0)] | None = None
    provider_cost_usd: Annotated[float, Field(ge=0.0)] | None = None
    escalation_reason: str | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> ReaderRun:
        if self.ended_at < self.started_at:
            raise ValueError("endedAt must not precede startedAt")
        if self.accepted and (self.output_digest is None or self.failure_class is not None):
            raise ValueError("an accepted run carries an output digest and no failure class")
        if not self.accepted and self.failure_class is None:
            raise ValueError("a rejected run must name a frozen failure class")
        return self


class ReaderRegistryEntry(ContractModel):
    """Blueprint §22. A ``qualified`` entry needs at least one evaluator receipt.

    Latency, cost and memory are ``None`` until a Model Arena run measures them
    on this exact revision + runtime digest. They are never estimated here.
    """

    schema_version: Literal["tavonel.reader_registry_entry.v1"] = READER_REGISTRY_ENTRY_SCHEMA
    reader_id: NonEmptyStr
    model_revision: NonEmptyStr
    runtime_digest: Sha256
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    qualified_source_families: tuple[SourceFamily, ...] = ()
    qualified_failure_classes: tuple[FailureClass, ...] = ()
    p50_latency_ms: Annotated[int, Field(ge=0)] | None = None
    p95_latency_ms: Annotated[int, Field(ge=0)] | None = None
    cost_per_unit: Annotated[float, Field(ge=0.0)] | None = None
    memory_requirement: Annotated[int, Field(ge=0)] | None = None
    evaluator_receipts: tuple[Sha256, ...] = ()
    status: ReaderRegistryStatus = ReaderRegistryStatus.CANDIDATE

    @model_validator(mode="after")
    def validate_entry(self) -> ReaderRegistryEntry:
        if self.status is ReaderRegistryStatus.QUALIFIED and not self.evaluator_receipts:
            raise ValueError("a qualified registry entry requires at least one evaluator receipt")
        if (
            self.p50_latency_ms is not None
            and self.p95_latency_ms is not None
            and self.p95_latency_ms < self.p50_latency_ms
        ):
            raise ValueError("p95LatencyMs must not be below p50LatencyMs")
        return self


class ReaderResolution(ContractModel):
    """The registry's answer. Never raises for unknown or hostile input."""

    status: CapabilityStatus
    provider_id: str | None = None
    failure_class: FailureClass | None = None
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_resolution(self) -> ReaderResolution:
        deferred = {CapabilityStatus.UNSUPPORTED, CapabilityStatus.REVIEW_REQUIRED}
        accepted = self.status not in deferred
        if accepted and self.provider_id is None:
            raise ValueError("an accepted resolution names the provider that will read the source")
        if not accepted and self.failure_class is None:
            raise ValueError("a refused or deferred resolution must name a frozen failure class")
        return self


__all__ = [
    "PROBEABLE_FEATURES",
    "READER_CAPABILITY_SCHEMA",
    "READER_REGISTRY_ENTRY_SCHEMA",
    "READER_RUN_SCHEMA",
    "ExtractedUnit",
    "NativeExtraction",
    "ReaderCapability",
    "ReaderHealth",
    "ReaderInput",
    "ReaderRegistryEntry",
    "ReaderResolution",
    "ReaderRun",
    "SourceInspection",
    "inprocess_runtime_digest",
]
