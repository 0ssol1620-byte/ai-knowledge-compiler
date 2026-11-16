"""HWP adapter contract: request, result, outcome models and the two engines that exist.

Contract only. No third-party HWP parser is adopted or wired in; the production
engine is `UnavailableEngine`, which holds every input. `FixtureEngine` returns
synthetic canned IR written in this file for boundary tests.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Protocol

from akc_cir import ContractModel, canonical_json, sha256_digest
from pydantic import Field, StringConstraints, field_validator, model_validator

from .models import ParserLimits

ADAPTER_VERSION = "hwp-adapter-contract/1"
IR_SCHEMA = "hwp-ir/1"

HwpFormat = Literal["hwp3", "hwp5", "hwpx", "hwpml"]
DeclaredFormat = Literal["hwp3", "hwp5", "hwpx", "hwpml", "unknown"]

# Worker vocabulary (workers/cpu-document) plus the HWP-specific holds.
REASON_CODES = frozenset(
    {
        "PARSER_TIMEOUT",
        "PARSER_PROCESS_CRASH",
        "PARSER_RESULT_TOO_LARGE",
        "PARSER_RESULT_INVALID",
        "HWP_ENGINE_UNAVAILABLE",
        "HWP_SIGNATURE_MISMATCH",
        "HWP_ENCRYPTED",
        "HWP_CONTAINER_LIMIT",
        "HWP_XML_UNSAFE",
        "HWP_SOURCE_HASH_MISMATCH",
        "HWP_NOT_HWP_OLE",
    }
)

_HOST_PATH_OR_URL = re.compile(r"(?:^[A-Za-z]:[\\/]|^[\\/]|^[A-Za-z][A-Za-z0-9+.-]*://|\\\\)")


def _no_path_or_url(value: str) -> str:
    if _HOST_PATH_OR_URL.search(value):
        raise ValueError("value must not be an absolute path or URL")
    return value


class HwpAdapterRequest(ContractModel):
    job_id: str = Field(min_length=1, max_length=128)
    source_handle: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")]
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    declared_format: DeclaredFormat
    authorized_scope_ref: str = Field(min_length=1, max_length=256)
    parser_profile: str = Field(min_length=1, max_length=128)
    max_bytes: int = Field(ge=1, le=ParserLimits().max_input_bytes)
    max_runtime_ms: int = Field(ge=1, le=600_000)
    model_policy: Literal["none"] = "none"
    requested_regions: tuple[str, ...] = ()


class TableCell(ContractModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str


class HwpBlock(ContractModel):
    id: str = Field(min_length=1, max_length=256)
    kind: Literal[
        "paragraph",
        "heading",
        "table",
        "figure",
        "equation",
        "footnote",
        "header",
        "footer",
        "unknown",
    ]
    text: str = ""
    table_grid: tuple[TableCell, ...] | None = None
    bbox_or_element_anchor: str = Field(min_length=1, max_length=512)
    original_ref: str = Field(min_length=1, max_length=512)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: Literal["native_unverified", "verified", "held"] = "native_unverified"

    @field_validator("original_ref", "bbox_or_element_anchor")
    @classmethod
    def _refs_are_not_paths(cls, value: str) -> str:
        return _no_path_or_url(value)


class UnresolvedRegion(ContractModel):
    anchor: str = Field(min_length=1, max_length=512)
    reason: Literal[
        "embedded_image", "scan_region", "equation_render", "unsupported_object", "decode_error"
    ]
    critical: bool

    @field_validator("anchor")
    @classmethod
    def _anchor_is_not_a_path(cls, value: str) -> str:
        return _no_path_or_url(value)


class ResourceReceipt(ContractModel):
    wall_ms: int = Field(ge=0)
    input_bytes: int = Field(ge=0)
    output_bytes: int = Field(ge=0)
    exit_code: int
    peak_rss_bytes: int | None = None


class HwpManifest(ContractModel):
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    detected_format: HwpFormat
    ir_schema: str = IR_SCHEMA


def result_hash(
    manifest: HwpManifest,
    blocks: tuple[HwpBlock, ...],
    unresolved_regions: tuple[UnresolvedRegion, ...],
) -> str:
    return sha256_digest(
        canonical_json(
            {
                "manifest": manifest.model_dump(mode="json", by_alias=True),
                "blocks": [b.model_dump(mode="json", by_alias=True) for b in blocks],
                "unresolvedRegions": [
                    r.model_dump(mode="json", by_alias=True) for r in unresolved_regions
                ],
            }
        )
    )


class HwpAdapterResult(ContractModel):
    adapter_version: str
    engine_id: str
    engine_version: str
    manifest: HwpManifest
    blocks: tuple[HwpBlock, ...]
    unresolved_regions: tuple[UnresolvedRegion, ...] = ()
    resource_receipt: ResourceReceipt
    warnings: tuple[str, ...] = ()
    artifact_hashes: dict[str, str]

    @model_validator(mode="after")
    def _caps_and_hash(self) -> HwpAdapterResult:
        limits = ParserLimits()
        if len(self.blocks) > limits.max_blocks:
            raise ValueError("too many blocks")
        if sum(len(b.text) for b in self.blocks) > limits.max_total_text_chars:
            raise ValueError("total text too large")
        cells = sum(len(b.table_grid or ()) for b in self.blocks)
        if cells > limits.max_table_cells:
            raise ValueError("too many table cells")
        if self.artifact_hashes.get("result_sha256") != result_hash(
            self.manifest, self.blocks, self.unresolved_regions
        ):
            raise ValueError("result_sha256 does not match content")
        return self


def build_result(
    *,
    engine_id: str,
    engine_version: str,
    manifest: HwpManifest,
    blocks: tuple[HwpBlock, ...],
    unresolved_regions: tuple[UnresolvedRegion, ...] = (),
    resource_receipt: ResourceReceipt,
    warnings: tuple[str, ...] = (),
) -> HwpAdapterResult:
    return HwpAdapterResult(
        adapter_version=ADAPTER_VERSION,
        engine_id=engine_id,
        engine_version=engine_version,
        manifest=manifest,
        blocks=blocks,
        unresolved_regions=unresolved_regions,
        resource_receipt=resource_receipt,
        warnings=warnings,
        artifact_hashes={"result_sha256": result_hash(manifest, blocks, unresolved_regions)},
    )


class Accepted(ContractModel):
    result: HwpAdapterResult


class Held(ContractModel):
    reason_code: str
    detail: str | None = None  # body-free stable sub-code, e.g. ARCHIVE_RATIO_LIMIT

    @field_validator("reason_code")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in REASON_CODES:
            raise ValueError("unknown reason code")
        return value


class Retryable(Held):
    pass


HwpOutcome = Accepted | Held | Retryable


class HwpEngine(Protocol):
    def parse(self, data: bytes, request: HwpAdapterRequest) -> HwpAdapterResult: ...


class UnavailableEngine:
    """Production default: no reader is licensed or adopted, so everything is held."""

    def parse(self, data: bytes, request: HwpAdapterRequest) -> HwpAdapterResult:
        raise HwpEngineHold("HWP_ENGINE_UNAVAILABLE")


class HwpEngineHold(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def run_engine(engine: HwpEngine, data: bytes, request: HwpAdapterRequest) -> HwpOutcome:
    """In-process outcome mapping. Process isolation, timeouts and crashes are 7b's job."""

    try:
        return Accepted(result=engine.parse(data, request))
    except HwpEngineHold as hold:
        return Held(reason_code=hold.reason_code)
    except ValueError:
        return Held(reason_code="PARSER_RESULT_INVALID")


def _fixture_result(
    request: HwpAdapterRequest,
    data: bytes,
    blocks: tuple[HwpBlock, ...],
    unresolved: tuple[UnresolvedRegion, ...] = (),
    *,
    source_sha256: str | None = None,
    detected: HwpFormat = "hwp5",
) -> HwpAdapterResult:
    return build_result(
        engine_id="fixture",
        engine_version="1",
        manifest=HwpManifest(
            source_sha256=source_sha256 or request.source_sha256, detected_format=detected
        ),
        blocks=blocks,
        unresolved_regions=unresolved,
        resource_receipt=ResourceReceipt(
            wall_ms=0, input_bytes=len(data), output_bytes=0, exit_code=0
        ),
    )


_P1 = HwpBlock(
    id="b0001",
    kind="paragraph",
    text="synthetic paragraph",
    bbox_or_element_anchor="section0/p1",
    original_ref="section0/p1",
)
_TABLE = HwpBlock(
    id="b0002",
    kind="table",
    table_grid=(
        TableCell(row=0, col=0, col_span=2, text="header"),
        TableCell(row=1, col=0, text="a"),
        TableCell(row=1, col=1, text="b"),
    ),
    bbox_or_element_anchor="section0/tbl1",
    original_ref="section0/tbl1",
)


class FixtureEngine:
    """Canned behaviour chosen by `parser_profile`; synthetic content only.

    `crash`, `hang`, `attempt_network` and `stderr_leak` only mean something across
    a process boundary (WO-D07-7b); in-process they raise or act so a boundary can
    observe them, which is why this engine is never a production default.
    """

    def parse(self, data: bytes, request: HwpAdapterRequest) -> HwpAdapterResult:
        profile = request.parser_profile
        if profile == "fixture:complex_table":
            return _fixture_result(request, data, (_P1, _TABLE))
        if profile == "fixture:embedded_image":
            return _fixture_result(
                request,
                data,
                (_P1,),
                (UnresolvedRegion(anchor="section0/pic1", reason="embedded_image", critical=True),),
            )
        if profile == "fixture:encrypted":
            raise HwpEngineHold("HWP_ENCRYPTED")
        if profile == "fixture:hash_mismatch":
            return _fixture_result(request, data, (_P1,), source_sha256="0" * 64)
        if profile == "fixture:garbage_output":
            raise ValueError("garbage output")
        if profile == "fixture:oversized_output":
            filler = "x" * 1_000_000
            big = tuple(
                _P1.model_copy(update={"id": f"b{i:05d}", "text": filler}) for i in range(12)
            )
            return _fixture_result(request, data, big)
        if profile == "fixture:crash":
            raise SystemExit(70)
        if profile == "fixture:hang":
            while True:  # killed by the boundary's timeout
                pass
        if profile == "fixture:attempt_network":
            import socket

            socket.create_connection(("192.0.2.1", 9), timeout=1)
            return _fixture_result(request, data, (_P1,))
        if profile == "fixture:stderr_leak":
            import sys

            sys.stderr.write(data.decode("utf-8", "replace"))
            return _fixture_result(request, data, (_P1,))
        raise HwpEngineHold("HWP_ENGINE_UNAVAILABLE")
