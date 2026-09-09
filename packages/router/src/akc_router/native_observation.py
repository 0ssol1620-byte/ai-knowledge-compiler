"""Native arm projection from the existing parser's CIR, not an OCR score.

No file access, model invocation, hidden evaluator or automatic acceptance.
Callers run the existing sandboxed native parser first. Every declared page
gets a row, including pages with no text; figure placeholders are not text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from akc_cir import BlockType, CanonicalDocument


class NativeObservationStatus(StrEnum):
    TEXT_OBSERVED = "native_text_observed"
    NO_TEXT_OBSERVED = "native_text_unobserved"
    PARSER_FAILED = "native_parser_failed"


@dataclass(frozen=True, slots=True)
class NativePageObservation:
    page_index0: int
    source_sha256: str
    status: NativeObservationStatus
    text: str
    output_sha256: str
    native_block_ids: tuple[str, ...]
    located_block_count: int
    unlocated_block_count: int
    geometry_available: bool
    # Text being present does not prove its completeness or correctness.
    quality_verified: bool = False


def project_native_pages(
    document: CanonicalDocument, *, expected_source_sha256: str, expected_page_count: int
) -> tuple[NativePageObservation, ...]:
    if document.source_sha256 != expected_source_sha256:
        raise ValueError("NATIVE_SOURCE_BINDING_MISMATCH")
    if type(expected_page_count) is not int or not 1 <= expected_page_count <= 10000:
        raise ValueError("NATIVE_PAGE_COUNT_INVALID")
    geometry = document.metadata.get("pages")
    if not isinstance(geometry, list) or len(geometry) != expected_page_count:
        raise ValueError("NATIVE_PAGE_INVENTORY_MISMATCH")
    # Native PDF text objects are titles, headings or paragraphs. Other semantic block
    # families need their own projection rather than pretending a figure's
    # metadata description was extracted text from its pixels.
    text_types = {BlockType.TITLE, BlockType.PARAGRAPH, BlockType.HEADING}
    text_by_page: list[list[str]] = [[] for _ in range(expected_page_count)]
    ids_by_page: list[list[str]] = [[] for _ in range(expected_page_count)]
    located = [0] * expected_page_count
    unlocated = [0] * expected_page_count
    for block in sorted(document.blocks, key=lambda item: item.order):
        for ref in block.source_refs:
            if (
                ref.document_id != document.document_id
                or ref.document_version_id != document.document_version_id
            ):
                raise ValueError("NATIVE_REFERENCE_IDENTITY_MISMATCH")
            if not 0 <= ref.page_index0 < expected_page_count:
                raise ValueError("NATIVE_LOCATOR_OUTSIDE_DOCUMENT")
        if block.type not in text_types:
            continue
        text = block.raw_text or block.normalized_text or ""
        if not text.strip():
            continue
        page_refs: dict[int, bool] = {}
        for ref in block.source_refs:
            page_refs[ref.page_index0] = (
                page_refs.get(ref.page_index0, False) or ref.bbox1000 is not None
            )
        # A page projection must neither drop an unassigned text block nor copy
        # a whole multi-page block onto every page. A separate span-aware reader
        # is required to split it; this adapter has no evidence to invent one.
        if not page_refs:
            raise ValueError("NATIVE_TEXT_PAGE_UNASSIGNED")
        if len(page_refs) != 1:
            raise ValueError("NATIVE_TEXT_PAGE_SPAN_UNRESOLVED")
        for index, has_location in page_refs.items():
            text_by_page[index].append(text)
            ids_by_page[index].append(block.id)
            if has_location:
                located[index] += 1
            else:
                unlocated[index] += 1
    result = []
    for index in range(expected_page_count):
        text = "\n".join(text_by_page[index])
        result.append(
            NativePageObservation(
                index,
                expected_source_sha256,
                NativeObservationStatus.TEXT_OBSERVED
                if text
                else NativeObservationStatus.NO_TEXT_OBSERVED,
                text,
                "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                tuple(ids_by_page[index]),
                located[index],
                unlocated[index],
                bool(ids_by_page[index]) and unlocated[index] == 0,
            )
        )
    return tuple(result)
