"""Campaign records: typed models, JSON Schema validation, atomic writers.

Every artifact the campaign keeps passes through here, so this module is where
three repository rules become mechanical rather than aspirational.

*Never invent data to satisfy a schema.* A metric that was not measured is
``null``; there is no default of ``0``. Cross-field validators refuse the
combinations that would look complete while hiding a gap - a ``SUCCESS`` page
receipt without an output hash, a ``PASS`` canary without a projection, a
model marked ``full_run_eligible`` whose canary has not passed.

*Secrets never enter files, receipts or logs.* :func:`assert_secret_free` runs
before any byte is written, from both :func:`write_atomic_json` and
:func:`append_jsonl`. It is a guard, not a proof: it rejects the credential
shapes this campaign can actually produce, and it deliberately does not reject
sha256 references or base64 page images.

*Partial files are never mistaken for results.* :func:`write_atomic_json`
writes ``<name>.tmp``, fsyncs it, re-reads it to confirm the bytes landed, and
only then calls :func:`os.replace` (masterplan section 15.8). A crash leaves a
``.tmp`` that no reader looks at.

The pydantic models and ``arena/core/schemas/*.json`` are two views of one
contract; ``tests/core/test_schema_sync.py`` fails if they drift.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated, Any, ClassVar, Final, Literal, get_args

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as _JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from arena.constants import (
    BENCHMARK_KEYS,
    HISTORICAL_EVALUATOR_PINS,
    MODEL_KEYS,
    TOTAL_SAMPLES,
)
from arena.core.errors import ErrorClass
from arena.core.ids import (
    RECOVERY_TYPES,
    canonical_json,
    canonical_json_bytes,
    sha256_file,
    sha256_ref,
)
from arena.core.states import WorkerState

__all__ = [
    "CANARY_CRITERIA",
    "SCHEMAS_DIR",
    "SCHEMA_NAMES",
    "SEMANTIC_ERROR_CLASSES",
    "AuthorizationReceiptRecord",
    "BundlePublishReceipt",
    "CanaryCriterion",
    "CanaryReceipt",
    "CanonicalPayload",
    "ConcurrencyPolicy",
    "EvaluatorRegistryRecord",
    "Event",
    "FrozenManifest",
    "HeartbeatReport",
    "LatencyQuantiles",
    "LicenseRef",
    "ModelRegistryRecord",
    "PageReceipt",
    "PodLedgerEntry",
    "ProvisionGateReceipt",
    "RawOutputPayload",
    "ReadyResponse",
    "ReceiptError",
    "RecoveryJob",
    "RouteDecision",
    "RunSummary",
    "RuntimeSpec",
    "SchemaValidationError",
    "SecretMaterialError",
    "TimingsMs",
    "WeightsRef",
    "WorkerRunRequest",
    "WorkerRunResponse",
    "append_jsonl",
    "assert_secret_free",
    "iter_jsonl",
    "load_schema",
    "model_for_schema",
    "read_jsonl",
    "schema_name_for_id",
    "utc_timestamp",
    "validate",
    "write_atomic_json",
]

SCHEMAS_DIR: Final = Path(__file__).resolve().parent / "schemas"


class ReceiptError(ValueError):
    """Raised when a record cannot be written or read safely."""


class SchemaValidationError(ReceiptError):
    """Raised when a record does not satisfy its JSON Schema."""


class SecretMaterialError(ReceiptError):
    """Raised when credential-shaped material would be persisted."""


# --------------------------------------------------------------------------
# shared field types
# --------------------------------------------------------------------------

SHA256_REF_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
HEX64_PATTERN: Final = r"^[0-9a-f]{64}$"
UTC_TIMESTAMP_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
AUTH_TIMESTAMP_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
IMAGE_DIGEST_PATTERN: Final = r"^[^\s@]+@sha256:[0-9a-f]{64}$"
DECISION_PATTERN: Final = r"^[A-Z][A-Z_]{1,31}$"
SAFE_NAME_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$"
# A CUDA version as RunPod reports and filters on it: major.minor, no patch.
CUDA_VERSION_PATTERN: Final = r"^\d+\.\d+$"

Sha256Ref = Annotated[str, StringConstraints(pattern=SHA256_REF_PATTERN)]
# Either form of a sha256, for the two places where both are legitimately in
# use: the bundle receipt (11.5 D21) carries the bare hex the on-pod
# ``sha256sum -c`` line consumes, while contract section 2 writes file
# references as "sha256:<hex>". Both are unambiguous; neither is inferred.
SHA256_VALUE_PATTERN: Final = r"^(?:sha256:)?[0-9a-f]{64}$"
Sha256Value = Annotated[str, StringConstraints(pattern=SHA256_VALUE_PATTERN)]
HexDigest = Annotated[str, StringConstraints(pattern=HEX64_PATTERN)]
UtcTimestamp = Annotated[str, StringConstraints(pattern=UTC_TIMESTAMP_PATTERN)]
AuthTimestamp = Annotated[str, StringConstraints(pattern=AUTH_TIMESTAMP_PATTERN)]
SafeName = Annotated[str, StringConstraints(pattern=SAFE_NAME_PATTERN)]
CudaVersion = Annotated[str, StringConstraints(pattern=CUDA_VERSION_PATTERN)]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
ErrorMessage = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeFloat = Annotated[float, Field(ge=0)]

Benchmark = Literal["parsebench", "omnidoc", "olmocr"]
ModelKey = Literal[
    "paddleocr_vl_1_6",
    "mineru_pipeline",
    "mineru_vlm",
    "deepseek_ocr2",
    "ovisocr2",
    "unlimited_ocr",
    "infinity_parser2_pro",
    "infinity_parser2_flash",
    "monkeyocrv2_b",
    "olmocr2",
    "hpd_parsing",
    "glm_ocr",
    "opus5_subscription",
]
RecoveryType = Literal[
    "overlap_tiling",
    "crop",
    "region_extract",
    "higher_dpi",
    "alternative_prompt",
    "safer_config",
    "partial_page",
]
RuntimeMode = Literal["baked", "bootstrap", "subscription"]
# ARENA_CONTRACT 11.5 D34: how the adapter gets its prompt. "text" sends
# AdapterConfig.prompt_text, "toolkit" hashes what the official toolkit built
# and compares, "none" is a pipeline with no prompt at all.
PromptKind = Literal["text", "toolkit", "none"]
JobKind = Literal["inference", "canary", "recovery"]
# ARENA_CONTRACT 11.1 D3. A semantic error class says the model was wrong, not
# that the run failed: an empty page still has status SUCCESS and carries
# OUTPUT_EMPTY here (masterplan section 41). Operational failure stays in
# ``error_class``; the two are never merged.
SemanticErrorClass = Literal[
    "OUTPUT_EMPTY",
    "OUTPUT_TRUNCATED",
    "OUTPUT_REPETITION",
    "OUTPUT_MALFORMED",
]
SEMANTIC_ERROR_CLASSES: Final = get_args(SemanticErrorClass)
# How a peak_vram_mb was obtained. "nvidia-smi" is the whole device -- anything
# else on the card is inside the number -- and "adapter" is the adapter's own
# in-process figure. They do not measure the same thing, so the source travels
# with the value instead of being assumed.
VramMeasurementSource = Literal["nvidia-smi", "adapter"]
PageStatus = Literal["SUCCESS", "FAILED", "QUARANTINED", "PAUSED"]
WeightsStrategy = Literal["baked", "volume_cache", "boot_download"]
OfficialRuntime = Literal["vllm", "transformers", "paddle", "mineru_cli", "custom"]
EntityKind = Literal["campaign", "model", "shard", "worker", "job"]

for _literal, _constant, _label in (
    (Benchmark, BENCHMARK_KEYS, "BENCHMARK_KEYS"),
    (ModelKey, MODEL_KEYS, "MODEL_KEYS"),
    (RecoveryType, RECOVERY_TYPES, "RECOVERY_TYPES"),
):
    if get_args(_literal) != _constant:  # pragma: no cover - import-time guard
        raise RuntimeError(f"arena.core.receipts drifted from {_label}")
del _literal, _constant, _label

# Masterplan section 17: the canary judges runtime correctness only, never
# output quality. These names are the criteria a canary receipt must carry.
CanaryCriterionId = Literal[
    "process_start",
    "correct_model_revision",
    "output_non_empty_on_nonblank",
    "output_schema_valid",
    "evaluator_adapter_accepts_output",
    "zero_hard_crash",
    "zero_deterministic_runtime_bug",
    "measured_sec_per_page",
    "vram_headroom",
    "full_run_projection_computable",
]
CANARY_CRITERIA: Final = (
    "process_start",
    "correct_model_revision",
    "output_non_empty_on_nonblank",
    "output_schema_valid",
    "evaluator_adapter_accepts_output",
    "zero_hard_crash",
    "zero_deterministic_runtime_bug",
    "measured_sec_per_page",
    "vram_headroom",
    "full_run_projection_computable",
)


def utc_timestamp(moment: datetime | None = None) -> str:
    """An ISO-8601 UTC timestamp in the exact shape every record requires."""

    value = (moment or datetime.now(tz=UTC)).astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"


# --------------------------------------------------------------------------
# model bases
# --------------------------------------------------------------------------


class _ArenaModel(BaseModel):
    """Shared config: unknown fields are an error, ``model_`` names are ours."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        protected_namespaces=(),
    )

    SCHEMA_ID: ClassVar[str] = ""

    def to_record(self) -> dict[str, Any]:
        """JSON-ready dict with the on-disk field names (``schema``, not alias)."""

        return self.model_dump(by_alias=True, mode="json")


class ArenaRecord(_ArenaModel):
    """A persisted campaign record. ``schema`` is required on disk."""

    record_schema: str = Field(alias="schema")

    @model_validator(mode="before")
    @classmethod
    def _default_record_schema(cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and cls.SCHEMA_ID
            and "schema" not in data
            and "record_schema" not in data
        ):
            return {**data, "schema": cls.SCHEMA_ID}
        return data


class ArenaDocument(_ArenaModel):
    """A wire object or config file. ``schema`` is optional but constant."""

    record_schema: str = Field(default="", alias="schema")


# --------------------------------------------------------------------------
# nested value objects
# --------------------------------------------------------------------------


class LatencyQuantiles(_ArenaModel):
    p50_ms: NonNegativeFloat
    p90_ms: NonNegativeFloat
    p95_ms: NonNegativeFloat


class CanaryCriterion(_ArenaModel):
    """One named masterplan section 17 PASS condition and its result."""

    criterion: CanaryCriterionId
    passed: bool
    detail: NonEmptyStr


class ConcurrencyPolicy(_ArenaModel):
    per_worker: PositiveInt
    scale: Literal["replicas_only", "replicas_and_concurrency"]


class LicenseRef(_ArenaModel):
    id: NonEmptyStr
    url: str | None = None
    # ARENA_CONTRACT 11.1 D5: the union actually written by A3 and C1-C3.
    # "approved" is A3's word for a licence it cleared; it is kept because
    # renaming another lane's data would be inventing it.
    status: Literal[
        "verified",
        "approved",
        "unverified",
        "review_required",
        "blocked",
        "none_found",
        "not_reusable",
    ]
    # Founder decision 2026-09-03 (infinity_parser2_pro / mineru_pipeline /
    # mineru_vlm licence clearance): a licence that is Apache-2.0 plus
    # additional terms (MinerU) needs a base SPDX id distinct from `id`, a
    # flag for whether extra terms exist, the sha256 of the fetched licence
    # text, the exact URL that was hashed, and free-text notes for terms that
    # do not fit a scalar field. All nullable and optional: most licences use
    # only `id`/`url`/`status`.
    name: str | None = None
    spdx_base: str | None = None
    additional_terms: bool | None = None
    text_sha256: str | None = None
    source_url: str | None = None
    notes: str | None = None


class WeightsRef(_ArenaModel):
    repo: NonEmptyStr
    revision: NonEmptyStr
    largest_file: NonEmptyStr
    largest_file_sha256: Sha256Ref


class TimingsMs(_ArenaModel):
    load_ms: NonNegativeInt
    preprocess_ms: NonNegativeInt
    inference_ms: NonNegativeInt
    postprocess_ms: NonNegativeInt
    total_ms: NonNegativeInt


class RawOutputPayload(_ArenaModel):
    raw_text: str
    output_format: NonEmptyStr
    native_json: dict[str, JsonValue] | None = None
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CanonicalPayload(_ArenaModel):
    markdown: str
    elements: list[dict[str, JsonValue]] | None = None
    lossy: bool = False
    conversion_notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 3.1 page receipt (masterplan section 11)
# --------------------------------------------------------------------------


class PageReceipt(ArenaRecord):
    """One page of inference. ``runs/<model_key>/receipts/<case_key>.json``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.page-receipt.v1"
    # ARENA_CONTRACT 11.1 D4: extension-open. Lane D's Opus receipts carry
    # subscription-specific columns that no core consumer may require.
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.page-receipt.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    inference_job_id: HexDigest
    benchmark: Benchmark
    sample_id: NonEmptyStr
    case_key: SafeName
    source_sha256: Sha256Ref

    model_key: ModelKey
    model_revision: NonEmptyStr
    runtime_image_digest: NonEmptyStr
    runtime_mode: RuntimeMode
    job_kind: JobKind
    gpu_type: str | None = None
    gpu_id: str | None = None
    pod_id: str | None = None
    worker_id: str | None = None
    shard_id: str | None = None

    prompt_id: NonEmptyStr
    prompt_sha256: Sha256Ref
    inference_config_sha256: Sha256Ref
    # ARENA_CONTRACT 11.6 D38: null only when the page did not succeed and the
    # image could not be read. A SUCCESS receipt still carries both, >= 1.
    # The keys stay required so a null means "there was none", never "omitted".
    image_width: PositiveInt | None
    image_height: PositiveInt | None

    queued_at: UtcTimestamp
    worker_ready_at: UtcTimestamp | None = None
    started_at: UtcTimestamp
    first_token_at: UtcTimestamp | None = None
    finished_at: UtcTimestamp

    queue_ms: NonNegativeInt | None = None
    load_ms: NonNegativeInt | None = None
    preprocess_ms: NonNegativeInt | None = None
    inference_ms: NonNegativeInt | None = None
    postprocess_ms: NonNegativeInt | None = None
    total_ms: NonNegativeInt

    peak_vram_mb: NonNegativeInt | None = None
    baseline_vram_mb: NonNegativeInt | None = None
    vram_total_mb: NonNegativeInt | None = None
    vram_measurement_source: VramMeasurementSource | None = None
    input_bytes: NonNegativeInt
    output_bytes: NonNegativeInt
    output_chars: NonNegativeInt
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None

    attempt: PositiveInt
    retry_count: NonNegativeInt
    retry_reason: str | None = None
    status: PageStatus
    error_class: ErrorClass | None = None
    semantic_error_class: SemanticErrorClass | None = None
    error_message: ErrorMessage | None = None
    wasted_gpu_seconds: NonNegativeFloat
    recovery_job_id: str | None = None

    raw_output_path: str | None = None
    raw_output_sha256: Sha256Ref | None = None
    canonical_output_path: str | None = None
    canonical_output_sha256: Sha256Ref | None = None

    @model_validator(mode="after")
    def _check_status_consistency(self) -> PageReceipt:
        if self.status == "SUCCESS":
            if self.raw_output_sha256 is None or self.canonical_output_sha256 is None:
                raise ValueError("a SUCCESS page receipt must carry both output hashes")
            if self.error_class is not None:
                raise ValueError("a SUCCESS page receipt may not carry an error_class")
            if self.image_width is None or self.image_height is None:
                raise ValueError(
                    "a SUCCESS page receipt must carry image_width and image_height"
                )
        elif self.error_class is None:
            raise ValueError(f"a {self.status} page receipt must carry an error_class")
        if self.runtime_mode != "subscription" and (self.pod_id is None or self.gpu_type is None):
            raise ValueError("a GPU page receipt must name its pod_id and gpu_type")
        return self


# --------------------------------------------------------------------------
# 3.2 event (masterplan section 33)
# --------------------------------------------------------------------------


class Event(ArenaRecord):
    """Append-only state-transition log line. ``receipts/events.jsonl``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.event.v1"
    record_schema: Literal["tavonel.arena.event.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    ts: UtcTimestamp
    entity_kind: EntityKind
    entity_id: NonEmptyStr
    from_state: str | None = None
    to_state: NonEmptyStr
    reason: NonEmptyStr
    detail: dict[str, JsonValue] | None = None


# --------------------------------------------------------------------------
# 3.3 pod cost ledger (masterplan section 42)
# --------------------------------------------------------------------------


class PodLedgerEntry(ArenaRecord):
    """One pod's billed life. ``cost/pod_ledger.jsonl``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.pod-ledger.v1"
    record_schema: Literal["tavonel.arena.pod-ledger.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    runtime_mode: RuntimeMode
    pod_id: NonEmptyStr
    gpu_type: NonEmptyStr
    data_center_id: str | None = None
    # Per-GPU rate (D57). A pod with more than one GPU is priced at
    # listed_rate_usd_per_hour * gpu_count, never at the multi-GPU total.
    listed_rate_usd_per_hour: NonNegativeFloat
    # D57: how many GPUs this pod was provisioned with. Defaults to 1 so a
    # row written before this field existed still loads and validates.
    gpu_count: PositiveInt = 1
    price_snapshot_sha256: Sha256Ref

    provisioned_at: UtcTimestamp
    model_ready_at: UtcTimestamp | None = None
    last_job_finished_at: UtcTimestamp | None = None
    terminated_at: UtcTimestamp | None = None

    billed_seconds: NonNegativeFloat
    model_loading_seconds: NonNegativeFloat
    useful_inference_seconds: NonNegativeFloat
    retry_seconds: NonNegativeFloat
    idle_seconds: NonNegativeFloat

    estimated_provider_cost_usd: NonNegativeFloat
    useful_cost_usd: NonNegativeFloat
    wasted_cost_usd: NonNegativeFloat


# --------------------------------------------------------------------------
# 3.4 error record (masterplan section 16)
# --------------------------------------------------------------------------


class ErrorRecord(ArenaRecord):
    """One error signature over the campaign. ``failures/errors.jsonl``.

    ``root_cause`` and ``resolution`` are ``null`` until somebody diagnoses
    them; null here means "not yet determined", never "none".
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.error-record.v1"
    record_schema: Literal["tavonel.arena.error-record.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    error_class: ErrorClass
    first_seen: UtcTimestamp
    last_seen: UtcTimestamp
    count: PositiveInt
    affected_model: ModelKey | None = None
    affected_image_digest: str | None = None
    affected_gpu_type: str | None = None
    retryability: bool
    root_cause: str | None = None
    resolution: str | None = None
    wasted_gpu_seconds: NonNegativeFloat


# --------------------------------------------------------------------------
# 3.5 route decision (masterplan section 23.2)
# --------------------------------------------------------------------------


class RouteDecision(ArenaRecord):
    """A GT-blind route decision, frozen before any evaluator runs."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.route-decision.v1"
    record_schema: Literal["tavonel.arena.route-decision.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    variant: SafeName
    case_key: SafeName
    sample_id: NonEmptyStr
    primary: ModelKey
    signals: dict[str, JsonValue]
    signals_sha256: Sha256Ref
    decision: Annotated[str, StringConstraints(pattern=DECISION_PATTERN)]
    target: ModelKey | None = None
    decision_sha256: Sha256Ref
    decided_before_gt: Literal[True]
    policy_id: NonEmptyStr
    policy_sha256: Sha256Ref


class FrozenManifest(ArenaRecord):
    """``FROZEN.json`` for a model's outputs or a variant's route decisions."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.frozen.v1"
    record_schema: Literal["tavonel.arena.frozen.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    frozen_at: UtcTimestamp
    manifest_sha256: Sha256Ref
    sample_count: NonNegativeInt
    success_count: NonNegativeInt
    failed_count: NonNegativeInt
    model_revision: NonEmptyStr
    runtime_image_digest: NonEmptyStr

    @model_validator(mode="after")
    def _check_counts(self) -> FrozenManifest:
        if self.success_count + self.failed_count > self.sample_count:
            raise ValueError("success_count + failed_count exceeds sample_count")
        return self


# --------------------------------------------------------------------------
# 3.6 recovery job (masterplan section 24)
# --------------------------------------------------------------------------


class RecoveryJob(ArenaRecord):
    """One planned recovery re-inference. ``tavonel/recovery_jobs/plan.jsonl``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.recovery-job.v1"
    record_schema: Literal["tavonel.arena.recovery-job.v1"] = Field(alias="schema")

    recovery_job_id: HexDigest
    base_inference_job_id: HexDigest
    case_key: SafeName
    sample_id: NonEmptyStr
    model_key: ModelKey
    recovery_type: RecoveryType
    recovery_config: dict[str, JsonValue]
    recovery_config_sha256: Sha256Ref
    round: PositiveInt
    trigger_signals: list[str]
    planned_before_gt: Literal[True]


# --------------------------------------------------------------------------
# run summary
# --------------------------------------------------------------------------


class RunSummary(ArenaRecord):
    """``runs/<model_key>/run-summary.json``.

    ``total_gpu_seconds`` is ``null`` for the subscription lane, which has no
    GPU seconds to report - not ``0``.
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.run-summary.v1"
    record_schema: Literal["tavonel.arena.run-summary.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    model_revision: NonEmptyStr
    runtime_image_digest: NonEmptyStr
    runtime_mode: RuntimeMode
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None = None
    sample_count: NonNegativeInt
    success_count: NonNegativeInt
    failed_count: NonNegativeInt
    quarantined_count: NonNegativeInt
    paused_count: NonNegativeInt
    per_benchmark_counts: dict[str, int] = Field(default_factory=dict)
    error_class_counts: dict[str, int] = Field(default_factory=dict)
    total_gpu_seconds: NonNegativeFloat | None = None
    wasted_gpu_seconds: NonNegativeFloat
    receipt_manifest_sha256: Sha256Ref | None = None
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# canary receipt (masterplan sections 17-18)
# --------------------------------------------------------------------------


class CanaryReceipt(ArenaRecord):
    """``receipts/canary-<model_key>.json``.

    PASS is runtime correctness only (masterplan section 17). A PASS is
    refused unless every criterion passed and the section 18 projection is
    computable, because "we could not measure it" is not a pass.
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.canary-receipt.v1"
    # ARENA_CONTRACT 11.5 D26: extension-open, like the page receipt. The
    # driver that actually runs a canary knows detail the core does not, and
    # it must not need a schema round-trip to record it. Core keys stay
    # required and no core consumer may depend on a non-core key.
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.canary-receipt.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    model_revision: NonEmptyStr
    runtime_image_digest: NonEmptyStr
    runtime_mode: RuntimeMode
    # The container the pod actually booted (11.5 D15). A bootstrap canary's
    # ``runtime_image_digest`` is "bootstrap:<bundle sha256>", so without this
    # field the base image it ran on would be unrecorded.
    base_image: NonEmptyStr | None = None
    # 11.6 D37: null only when ``runtime_mode == "subscription"`` - a hosted
    # lane has no GPU and no pod. Required, and non-null, for every other mode.
    gpu_type: NonEmptyStr | None
    # 11.5 D25: the device's *reported* compute capability. No floor is
    # enforced from it - that needs a sourced table, not a name heuristic -
    # but a canary that did not read it says null rather than guessing.
    gpu_compute_capability: NonEmptyStr | None = None
    # Provenance of the run: which pod, which authorization allowed it, and
    # where its billed seconds landed (11.5 D26/D28). A subscription canary
    # has no pod and no ledger line, so these are nullable rather than
    # required; a null here means "there was none", never "not recorded".
    pod_id: NonEmptyStr | None = None
    authorization_receipt_path: NonEmptyStr | None = None
    authorization_receipt_sha256: Sha256Value | None = None
    pod_ledger_path: NonEmptyStr | None = None
    started_at: UtcTimestamp
    finished_at: UtcTimestamp
    page_count: PositiveInt
    success_count: NonNegativeInt
    failed_count: NonNegativeInt

    stage_latency_ms: dict[str, LatencyQuantiles]
    peak_vram_mb: NonNegativeInt | None = None
    gpu_total_vram_mb: NonNegativeInt | None = None
    vram_headroom_mb: NonNegativeInt | None = None

    warm_sec_per_page: NonNegativeFloat | None = None
    total_samples: PositiveInt = TOTAL_SAMPLES
    replica_count: PositiveInt = 1
    overhead_factor: NonNegativeFloat = 1.15
    selected_gpu_hourly_rate_usd: NonNegativeFloat | None = None
    price_snapshot_sha256: Sha256Ref | None = None
    gpu_hours_projected: NonNegativeFloat | None = None
    raw_gpu_cost_projected_usd: NonNegativeFloat | None = None
    wall_time_hours_projected: NonNegativeFloat | None = None

    status: Literal["PASS", "FAIL"]
    criteria: list[CanaryCriterion]
    fail_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_verdict(self) -> CanaryReceipt:
        # 11.6 D37: the same cross-field rule the page receipt carries.
        if self.runtime_mode != "subscription" and (
            self.pod_id is None or self.gpu_type is None
        ):
            raise ValueError("a GPU canary receipt must name its pod_id and gpu_type")
        seen = {item.criterion for item in self.criteria}
        missing = sorted(set(CANARY_CRITERIA) - seen)
        if missing:
            raise ValueError(f"canary receipt is missing criteria: {missing}")
        failed = sorted(item.criterion for item in self.criteria if not item.passed)
        if self.status == "PASS":
            if failed:
                raise ValueError(f"canary cannot PASS with failed criteria: {failed}")
            if self.fail_reasons:
                raise ValueError("a PASS canary may not carry fail_reasons")
            projection = (
                self.warm_sec_per_page,
                self.gpu_hours_projected,
                self.raw_gpu_cost_projected_usd,
                self.wall_time_hours_projected,
            )
            if any(value is None for value in projection):
                raise ValueError(
                    "a PASS canary must carry the section 18 projection "
                    "(warm_sec_per_page, gpu_hours, raw cost, wall time)"
                )
        elif not self.fail_reasons:
            raise ValueError("a FAIL canary must state at least one reason")
        return self


# --------------------------------------------------------------------------
# provisioning gate + bundle publication (ARENA_CONTRACT 11.5 D20, D21, D26)
# --------------------------------------------------------------------------


class ProvisionGateReceipt(ArenaRecord):
    """``receipts/canary-provision-<model_key>.json``.

    What the controller decided *before* it was allowed to create a pod: the
    licence check, the GPU-pool check, the authorization gate and the redacted
    create payload. The nested blocks stay untyped on purpose - the controller
    lane owns their shape and this record exists so a reader can trust the
    envelope, not so the core can second-guess the gate.
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.provision_gate.v1"
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.provision_gate.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    phase: NonEmptyStr
    evaluated_at: UtcTimestamp
    authorization: dict[str, JsonValue]
    provisioning: dict[str, JsonValue] | None
    gpu_pool: dict[str, JsonValue] | None = None
    license: dict[str, JsonValue] | None = None


class BundlePublishReceipt(ArenaRecord):
    """``receipts/bundles/<model_key>.json`` (ARENA_CONTRACT 11.5 D21).

    Written after the bundle was built, uploaded and read back. It is the only
    place a canary may learn the bundle sha256 that its
    ``bootstrap:<sha>`` runtime digest is derived from, so a bundle that was
    not verified against the object store has no receipt and therefore no
    canary.
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.bundle-publish.v1"
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.bundle-publish.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    model_key: ModelKey
    bundle_sha256: Sha256Value
    bundle_size_bytes: PositiveInt
    bundle_file_count: PositiveInt
    bundle_manifest_sha256: Sha256Value
    # A bucket and a key, never a signed URL (11.5 D21).
    r2_bucket: NonEmptyStr
    r2_key: NonEmptyStr
    uploaded_at: UtcTimestamp


# --------------------------------------------------------------------------
# 3.7 model registry record (masterplan section 10)
# --------------------------------------------------------------------------


class ModelRegistryRecord(ArenaRecord):
    """One row of ``model_registry.json``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.model-registry-record.v1"
    # ARENA_CONTRACT 11.1 D4: extension-open.
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.model-registry-record.v1"] = Field(alias="schema")

    model_key: ModelKey
    display_name: NonEmptyStr
    # A subscription model has no weights repo, a pipeline runtime has no
    # single version and a hosted lane has no VRAM floor: null, never a
    # placeholder (ARENA_CONTRACT 11.1 D5).
    repo: NonEmptyStr | None
    revision: NonEmptyStr
    license: NonEmptyStr
    runtime_type: Literal[
        "vllm", "transformers", "pipeline", "custom", "subscription",
        "paddle", "mineru_cli",
    ]
    runtime_version: NonEmptyStr | None
    container_image: str | None = None
    container_digest: str | None = None
    cuda: str | None = None
    torch: str | None = None
    gpu_min_vram_gb: NonNegativeFloat | None
    gpu_count_min: PositiveInt | None = None
    prompt_id: NonEmptyStr
    # ARENA_CONTRACT 11.6: promoted from extension keys to named optional
    # properties. ``prompt_sha256``/``prompt_kind`` are copied from the
    # runtime.json the row resolved; ``runtime_repository``/``runtime_revision``
    # are null for a runtime that names no source repository.
    prompt_sha256: Sha256Ref | None = None
    prompt_kind: PromptKind | None = None
    runtime_repository: NonEmptyStr | None = None
    runtime_revision: NonEmptyStr | None = None
    preprocess_config_id: NonEmptyStr
    max_concurrency_per_worker: PositiveInt
    recommended_gpu_pool: list[str]
    canary_status: Literal["PENDING", "PASS", "FAIL"]
    full_run_eligible: bool

    official_source_urls: list[str]
    resolved_at: UtcTimestamp
    resolution_method: NonEmptyStr
    license_evidence_url: str | None = None
    license_notes: NonEmptyStr
    weights_strategy: WeightsStrategy
    runtime_mode_allowed: list[RuntimeMode]
    official_prompt_id: NonEmptyStr
    official_inference_config: dict[str, JsonValue]
    official_inference_config_sha256: Sha256Ref
    gpu_pool_priority: list[str]
    concurrency_policy: ConcurrencyPolicy
    shard_size_hint: PositiveInt

    @model_validator(mode="after")
    def _check_eligibility(self) -> ModelRegistryRecord:
        if self.full_run_eligible and self.canary_status != "PASS":
            raise ValueError("full_run_eligible requires canary_status == 'PASS'")
        if not self.runtime_mode_allowed:
            raise ValueError("runtime_mode_allowed may not be empty")
        # Masterplan section 14: the MinerU VLM tensor-shape incident. Scaling
        # this model is replicas only, one page at a time per worker.
        if self.model_key == "mineru_vlm":
            if self.concurrency_policy.per_worker != 1 or self.max_concurrency_per_worker != 1:
                raise ValueError("mineru_vlm is hard-limited to concurrency 1 (section 14)")
            if self.concurrency_policy.scale != "replicas_only":
                raise ValueError("mineru_vlm scales by replicas only (section 14)")
        return self


# --------------------------------------------------------------------------
# 3.8 evaluator registry record
# --------------------------------------------------------------------------


class EvaluatorRegistryRecord(ArenaRecord):
    """One benchmark's evaluator pins. ``evaluator_registry.json``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.evaluator-registry-record.v1"
    # ARENA_CONTRACT 11.1 D4: extension-open.
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["tavonel.arena.evaluator-registry-record.v1"] = Field(alias="schema")

    benchmark: Benchmark
    repository: NonEmptyStr
    historical_pin: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    upstream_head_at_start: NonEmptyStr
    main_pin: NonEmptyStr
    main_pin_rationale: NonEmptyStr
    historical_lane_required: bool
    entrypoint: NonEmptyStr
    dataset_repository: NonEmptyStr
    dataset_revision: NonEmptyStr
    dataset_manifest_sha256: Sha256Ref
    gt_paths: list[str]
    license: NonEmptyStr
    frozen: bool = False

    @model_validator(mode="after")
    def _check_historical_pin(self) -> EvaluatorRegistryRecord:
        expected = HISTORICAL_EVALUATOR_PINS[self.benchmark]
        if self.historical_pin != expected:
            raise ValueError(
                f"historical_pin for {self.benchmark} must be the FOLYNTA campaign pin "
                f"{expected}, got {self.historical_pin}"
            )
        return self


# --------------------------------------------------------------------------
# authorization receipt (ARENA_CONTRACT 11.1 D6 / 11.4)
# --------------------------------------------------------------------------


class AuthorizationReceiptRecord(ArenaRecord):
    """One founder decision that lets a money-spending phase run.

    ``arena.core.authorizations`` owns the gate logic and validates with its
    own validator; this model exists so the receipt participates in the same
    schema registry as every other campaign record and so schema/model drift
    is caught by the core tests.
    """

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.authorization-receipt.v1"
    record_schema: Literal["tavonel.arena.authorization-receipt.v1"] = Field(alias="schema")

    campaign_id: NonEmptyStr
    phase: Literal["phase1_canary", "phase2_full_run", "phase3_opus_full_run", "builder_pod"]
    authorized_by: Literal["founder", "orchestrator-on-founder-instruction"]
    authorized_at: AuthTimestamp
    expires_at: AuthTimestamp | None
    max_usd: Annotated[float, Field(gt=0)]
    model_keys: Literal["*"] | list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]]
    statement: NonEmptyStr
    notes: str | None = None

    @model_validator(mode="after")
    def _check_window(self) -> AuthorizationReceiptRecord:
        if self.expires_at is not None and self.expires_at <= self.authorized_at:
            raise ValueError("expires_at must be after authorized_at")
        if isinstance(self.model_keys, list) and not self.model_keys:
            raise ValueError("model_keys must be '*' or a non-empty list")
        return self


# --------------------------------------------------------------------------
# runtime.json (ARENA_CONTRACT section 6)
# --------------------------------------------------------------------------


class RuntimeSpec(ArenaDocument):
    """``runtimes/<model_key>/runtime.json``."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.runtime.v1"
    record_schema: Literal["", "tavonel.arena.runtime.v1"] = Field(default="", alias="schema")

    model_key: ModelKey
    display_name: NonEmptyStr
    model_repo: NonEmptyStr
    model_revision: NonEmptyStr
    official_runtime: OfficialRuntime
    runtime_version: NonEmptyStr
    # ARENA_CONTRACT 11.5 D16: runtime.json owns the runtime repository and
    # revision too, and the model registry is a derived copy of them. A
    # runtime whose official code is the base image itself has none, so these
    # are nullable - null means "there is no separate repository", never
    # "unrecorded".
    runtime_repository: NonEmptyStr | None = None
    runtime_revision: NonEmptyStr | None = None
    base_image: Annotated[str, StringConstraints(pattern=IMAGE_DIGEST_PATTERN)]
    gpu_min_vram_gb: NonNegativeFloat
    gpu_count_min: PositiveInt = 1
    gpu_pool_priority: list[str]
    max_concurrency_per_worker: PositiveInt
    shard_size_hint: PositiveInt
    per_page_timeout_seconds: PositiveInt
    prompt_id: NonEmptyStr
    # ARENA_CONTRACT 11.5 D34. Optional here only because the runtime lanes
    # are still declaring it; it is not a default. A worker that is handed a
    # runtime with no prompt_kind has no rule to enforce and must fail closed
    # rather than pick one.
    prompt_kind: PromptKind | None = None
    # The lowest CUDA version a host driver may report for this runtime's base
    # image to start (pod 3xag0y00rgoj4n: a cu129 image on a host reporting
    # 12.8 died in torch._C._cuda_init with CUDA error 804). Nullable because a
    # runtime that starts no CUDA process has no floor; a null on one that does
    # is refused at the provisioning gate, never read as "any host will do".
    min_cuda_version: CudaVersion | None = None
    inference_config: dict[str, JsonValue]
    weights_strategy: WeightsStrategy
    runtime_mode_allowed: list[RuntimeMode]
    official_source_urls: list[str]
    license: LicenseRef
    notes: str | list[str]
    weights: WeightsRef

    @model_validator(mode="after")
    def _check_weights(self) -> RuntimeSpec:
        if self.weights.repo != self.model_repo:
            raise ValueError("weights.repo must equal model_repo")
        if self.weights.revision != self.model_revision:
            raise ValueError("weights.revision must equal model_revision")
        return self


# --------------------------------------------------------------------------
# worker HTTP contract (ARENA_CONTRACT section 4)
# --------------------------------------------------------------------------


class WorkerRunRequest(ArenaDocument):
    """``POST /v1/run`` body."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.worker-run-request.v1"
    record_schema: Literal["", "tavonel.arena.worker-run-request.v1"] = Field(
        default="", alias="schema"
    )

    campaign_id: NonEmptyStr
    inference_job_id: HexDigest
    sample_id: NonEmptyStr
    case_key: SafeName
    benchmark: Benchmark
    source_sha256: Sha256Ref
    image_b64: NonEmptyStr
    width: PositiveInt
    height: PositiveInt
    prompt_id: NonEmptyStr
    prompt_sha256: Sha256Ref
    inference_config_sha256: Sha256Ref
    job_kind: JobKind
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: PositiveInt | None = None


class WorkerRunResponse(ArenaDocument):
    """``POST /v1/run`` response, persisted before the worker answers."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.worker-run-response.v1"
    record_schema: Literal["", "tavonel.arena.worker-run-response.v1"] = Field(
        default="", alias="schema"
    )

    inference_job_id: HexDigest
    status: Literal["SUCCESS", "FAILED"]
    error_class: ErrorClass | None = None
    semantic_error_class: SemanticErrorClass | None = None
    error_message: ErrorMessage | None = None
    worker_id: NonEmptyStr
    model_key: ModelKey
    model_revision: NonEmptyStr
    runtime_mode: RuntimeMode
    runtime_image_digest: NonEmptyStr
    gpu_type: str | None = None
    pod_id: str | None = None
    started_at: UtcTimestamp
    first_token_at: UtcTimestamp | None = None
    finished_at: UtcTimestamp
    timings_ms: TimingsMs
    peak_vram_mb: NonNegativeInt | None = None
    baseline_vram_mb: NonNegativeInt | None = None
    vram_total_mb: NonNegativeInt | None = None
    vram_measurement_source: VramMeasurementSource | None = None
    input_bytes: NonNegativeInt
    output_bytes: NonNegativeInt
    output_chars: NonNegativeInt
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    raw_output: RawOutputPayload | None = None
    canonical: CanonicalPayload | None = None
    raw_output_sha256: Sha256Ref | None = None
    canonical_output_sha256: Sha256Ref | None = None

    @model_validator(mode="after")
    def _check_status(self) -> WorkerRunResponse:
        if self.status == "SUCCESS":
            missing = [
                name
                for name, value in (
                    ("raw_output", self.raw_output),
                    ("canonical", self.canonical),
                    ("raw_output_sha256", self.raw_output_sha256),
                    ("canonical_output_sha256", self.canonical_output_sha256),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"a SUCCESS run response is missing {missing}")
            if self.error_class is not None:
                raise ValueError("a SUCCESS run response may not carry an error_class")
        elif self.error_class is None:
            raise ValueError("a FAILED run response must carry an error_class")
        return self


class ReadyResponse(ArenaDocument):
    """``GET /v1/ready`` response."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.ready-response.v1"
    record_schema: Literal["", "tavonel.arena.ready-response.v1"] = Field(
        default="", alias="schema"
    )

    stage: WorkerState
    worker_id: NonEmptyStr
    model_key: ModelKey
    model_revision: NonEmptyStr
    runtime_mode: RuntimeMode
    runtime_image_digest: NonEmptyStr
    load_receipt: dict[str, JsonValue] | None = None
    warmup_receipt: dict[str, JsonValue] | None = None
    started_at: UtcTimestamp
    ready_at: UtcTimestamp | None = None
    last_error: ErrorMessage | None = None


class HeartbeatReport(ArenaDocument):
    """``GET /v1/heartbeat`` response (masterplan section 15.4 + contract 4)."""

    SCHEMA_ID: ClassVar[str] = "tavonel.arena.heartbeat.v1"
    # ARENA_CONTRACT 11.1 D4: extension-open, and ``state`` is now the full
    # WORKER_STATES vocabulary rather than a second coarse one.
    model_config = ConfigDict(extra="allow")
    record_schema: Literal["", "tavonel.arena.heartbeat.v1"] = Field(default="", alias="schema")

    worker_id: NonEmptyStr
    state: WorkerState
    stage: WorkerState
    job_id: str | None = None
    ts: UtcTimestamp | None = None
    last_progress_at: UtcTimestamp
    # A worker with no readable GPU metric says so; it never reports 0.
    gpu_util: NonNegativeFloat | None = None
    vram_used: NonNegativeInt | None = None
    gpu_metrics_unavailable_reason: str | None = None
    output_progress: NonNegativeInt
    jobs_done: NonNegativeInt
    jobs_failed: NonNegativeInt
    pid: PositiveInt

    @model_validator(mode="after")
    def _check_gpu_metrics(self) -> HeartbeatReport:
        if (self.gpu_util is None or self.vram_used is None) and not (
            self.gpu_metrics_unavailable_reason or ""
        ).strip():
            raise ValueError(
                "a heartbeat without gpu_util/vram_used must name "
                "gpu_metrics_unavailable_reason"
            )
        return self


# --------------------------------------------------------------------------
# schema registry
# --------------------------------------------------------------------------

_MODELS: Final[tuple[tuple[str, type[_ArenaModel]], ...]] = (
    ("page-receipt", PageReceipt),
    ("event", Event),
    ("pod-ledger", PodLedgerEntry),
    ("error-record", ErrorRecord),
    ("route-decision", RouteDecision),
    ("recovery-job", RecoveryJob),
    ("run-summary", RunSummary),
    ("frozen", FrozenManifest),
    ("canary-receipt", CanaryReceipt),
    ("provision_gate", ProvisionGateReceipt),
    ("bundle-publish", BundlePublishReceipt),
    ("model-registry-record", ModelRegistryRecord),
    ("evaluator-registry-record", EvaluatorRegistryRecord),
    ("authorization-receipt", AuthorizationReceiptRecord),
    ("runtime", RuntimeSpec),
    ("worker-run-request", WorkerRunRequest),
    ("worker-run-response", WorkerRunResponse),
    ("ready-response", ReadyResponse),
    ("heartbeat", HeartbeatReport),
)

SCHEMA_NAMES: Final = tuple(name for name, _ in _MODELS)
MODEL_BY_SCHEMA_NAME: Final[Mapping[str, type[_ArenaModel]]] = dict(_MODELS)
SCHEMA_NAME_BY_ID: Final[Mapping[str, str]] = {
    model.SCHEMA_ID: name for name, model in _MODELS if model.SCHEMA_ID
}


def model_for_schema(name: str) -> type[_ArenaModel]:
    """The pydantic model that owns one schema name."""

    try:
        return MODEL_BY_SCHEMA_NAME[name]
    except KeyError as exc:
        raise ReceiptError(f"unknown schema name {name!r}") from exc


def schema_name_for_id(schema_id: str) -> str:
    """Map ``tavonel.arena.<name>.v1`` back to ``<name>``."""

    try:
        return SCHEMA_NAME_BY_ID[schema_id]
    except KeyError as exc:
        raise ReceiptError(f"unknown schema id {schema_id!r}") from exc


@cache
def load_schema(name: str) -> Mapping[str, Any]:
    """Read one JSON Schema file. Unknown names raise rather than default."""

    if name not in MODEL_BY_SCHEMA_NAME:
        raise ReceiptError(f"unknown schema name {name!r}")
    path = SCHEMAS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise ReceiptError(f"schema file is missing: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ReceiptError(f"schema file {path} is not a JSON object")
    return loaded


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _resolve_schema_name(record: Mapping[str, Any], schema_name: str | None) -> str | None:
    if schema_name is not None:
        if schema_name not in MODEL_BY_SCHEMA_NAME:
            raise ReceiptError(f"unknown schema name {schema_name!r}")
        return schema_name
    declared = record.get("schema")
    if isinstance(declared, str) and declared:
        return schema_name_for_id(declared)
    return None


def validate(record: Mapping[str, Any], schema_name: str | None = None) -> None:
    """Validate a record against ``arena/core/schemas/<name>.schema.json``.

    The name comes from ``record["schema"]`` unless the caller names it. A
    record that declares no schema and is given no name raises: guessing which
    contract a record belongs to is exactly the silent fallback the campaign
    forbids.
    """

    if not isinstance(record, Mapping):
        raise ReceiptError(f"record must be a mapping, got {type(record).__name__}")
    name = _resolve_schema_name(record, schema_name)
    if name is None:
        raise ReceiptError("record declares no 'schema' and no schema_name was given")
    errors = sorted(_validator(name).iter_errors(dict(record)), key=lambda err: list(err.path))
    if errors:
        first: _JsonSchemaValidationError = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise SchemaValidationError(
            f"record does not satisfy {name}.schema.json at {location}: {first.message} "
            f"({len(errors)} error(s) total)"
        )


# --------------------------------------------------------------------------
# secret-free guard
# --------------------------------------------------------------------------

# Prefixes this campaign can actually leak: RunPod (rpa_), HuggingFace (hf_),
# OpenAI-style (sk-), GitHub (ghp_, gho_, github_pat_), Slack (xoxb-), AWS/R2
# (AKIA/ASIA). The payload must be long AND contain a digit, so ordinary
# identifiers such as "hf_hub_cache_dir" are not mistaken for credentials.
_TOKEN_RE: Final = re.compile(
    r"(?<![A-Za-z0-9_\-])(?:rpa_|hf_|ghp_|gho_|github_pat_|xoxb-|sk-)"
    r"(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{20,}"
)
_AWS_KEY_RE: Final = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{12,}")
_BEARER_RE: Final = re.compile(r"(?i)\bbearer\s+\S+")
# A presigned URL's *path* is fine; its signing query parameters are not.
_PRESIGNED_RE: Final = re.compile(r"(?i)x-amz-(?:signature|credential|security-token)=")
_DIGEST_RE: Final = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

_SECRET_KEY_WORDS: Final = (
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "credential",
    "private_key",
)
# Field names that contain a trigger word but count tokens or name a tokenizer.
_SAFE_KEY_NAMES: Final = frozenset(
    {
        "tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "max_tokens",
        "max_new_tokens",
        "tokens_per_second",
        "output_tokens_per_second",
        "tokenizer",
        "tokenizer_class",
        "tokenizer_config",
    }
)


def _is_secret_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _SAFE_KEY_NAMES:
        return False
    return any(word in lowered for word in _SECRET_KEY_WORDS)


def _scan_string(value: str, path: str, parent_key: str | None) -> None:
    if parent_key is not None and _is_secret_key(parent_key):
        raise SecretMaterialError(
            f"{path} is a string under credential-shaped key {parent_key!r}; "
            "secrets are read only through arena/provider/secrets.py and never persisted"
        )
    if _DIGEST_RE.fullmatch(value):
        return
    for pattern, label in (
        (_TOKEN_RE, "an API token prefix"),
        (_AWS_KEY_RE, "an AWS/R2 access key id"),
        (_BEARER_RE, "an Authorization bearer value"),
        (_PRESIGNED_RE, "presigned-URL signing parameters"),
    ):
        if pattern.search(value):
            raise SecretMaterialError(f"{path} contains {label}")


def _scan(value: object, path: str, parent_key: str | None) -> None:
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str):
        _scan_string(value, path, parent_key)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReceiptError(f"{path} has a non-string key {key!r}")
            child = f"{path}.{key}"
            _scan_string(key, child, None)
            _scan(item, child, key)
        return
    if isinstance(value, Sequence):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]", parent_key)
        return
    raise ReceiptError(f"{path} holds a non-JSON value of type {type(value).__name__}")


def assert_secret_free(obj: object) -> None:
    """Reject credential-shaped material anywhere in a record.

    Raises :class:`SecretMaterialError` for a known token prefix, an AWS-style
    access key id, a bearer value, presigned-URL signing parameters, or any
    string stored under a key whose name reads like a credential.

    sha256 references, bare 64-hex ids and base64 page images are *not*
    secrets and are never rejected on shape alone.
    """

    _scan(obj, "$", None)


# --------------------------------------------------------------------------
# writers and readers
# --------------------------------------------------------------------------


def _as_record(record: Mapping[str, Any] | _ArenaModel) -> dict[str, Any]:
    if isinstance(record, _ArenaModel):
        return record.to_record()
    if not isinstance(record, Mapping):
        raise ReceiptError(f"record must be a mapping or arena model, got {type(record).__name__}")
    return dict(record)


def _prepare(
    record: Mapping[str, Any] | _ArenaModel, schema_name: str | None
) -> tuple[dict[str, Any], bytes]:
    payload = _as_record(record)
    assert_secret_free(payload)
    if schema_name is not None or "schema" in payload:
        validate(payload, schema_name)
    return payload, canonical_json_bytes(payload)


def write_atomic_json(
    path: Path | str,
    record: Mapping[str, Any] | _ArenaModel,
    *,
    schema_name: str | None = None,
) -> str:
    """Write one record atomically and return ``"sha256:<hex>"`` of its bytes.

    ``<name>.tmp`` -> ``fsync`` -> read back and hash -> :func:`os.replace`
    (masterplan section 15.8). The read-back is what makes the returned digest
    evidence rather than an assertion about what was intended.

    Validation runs when the record declares a ``schema`` or the caller names
    one; a record that declares neither is written unvalidated but still
    passes the secret-free guard.
    """

    target = Path(path)
    payload, data = _prepare(record, schema_name)
    del payload
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    digest = sha256_ref(data)
    on_disk = sha256_file(tmp)
    if on_disk != digest:  # pragma: no cover - filesystem corruption
        tmp.unlink(missing_ok=True)
        raise ReceiptError(f"atomic write verification failed for {target}")
    os.replace(tmp, target)
    return digest


def append_jsonl(
    path: Path | str,
    record: Mapping[str, Any] | _ArenaModel,
    *,
    schema_name: str | None = None,
) -> str:
    """Append one canonical JSON line, fsynced, and return its ``sha256:`` ref."""

    target = Path(path)
    _, data = _prepare(record, schema_name)
    line = data + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256_ref(line)


def iter_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    """Yield each JSON object in a .jsonl file. Blank lines are skipped."""

    target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReceiptError(f"{target}:{number} is not valid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ReceiptError(f"{target}:{number} is not a JSON object")
            yield value


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Read a whole .jsonl file into a list of objects."""

    return list(iter_jsonl(path))


def record_sha256(record: Mapping[str, Any] | _ArenaModel) -> str:
    """``"sha256:<hex>"`` over a record's canonical JSON, without writing it."""

    return sha256_ref(canonical_json(_as_record(record)))
