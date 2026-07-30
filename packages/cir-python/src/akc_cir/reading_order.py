"""Deterministic reading-order and document-heading restoration.

This module is deliberately provider-neutral and contains no model client.  It
records each bounded heuristic used by the compiler and exposes ambiguous
heading candidates through a small, untrusted-data-only payload.  A caller may
choose to send that payload to an approved provider, but this module never does
so and never grants such a response direct mutation authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from .normalization import NormalizationBlock

READING_ORDER_VERSION = "akc-reading-order-1.0.0"
HEADING_INFERENCE_VERSION = "akc-heading-inference-1.0.0"

_STAGES = (
    "provider_order",
    "bbox_geometry",
    "column_clustering",
    "semantic_cues",
    "cross_page_continuity",
)
_HEADING_TYPES = frozenset({"title", "heading"})
_NON_HEADING_TYPES = frozenset(
    {
        "code",
        "formula",
        "table",
        "table_cell",
        "figure",
        "caption",
        "footer",
        "header",
        "page_number",
        "footnote",
    }
)
_TERMINAL_PUNCTUATION = frozenset(".!?\u3002\uff01\uff1f…:;")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_TOC_TITLE = re.compile(r"^(?:table\s+of\s+contents|contents|목차)\s*$", re.IGNORECASE)
_TOC_ENTRY = re.compile(r"^\s*(?P<title>.+?)\s*(?:\.{2,}|\s{2,}|\t)\s*(?P<page>\d{1,6})\s*$")
_ATX_HEADING = re.compile(r"^\s*(?P<marks>#{1,6})\s+\S")
_PROVIDER_LEVEL = re.compile(
    r"(?:heading|header|section|title)[_:\-\s]*(?P<level>[1-6])",
    re.IGNORECASE,
)
_ARABIC_NUMBERING = re.compile(r"^\s*(?P<value>\d+(?:\.\d+){0,5})(?:[.)])?(?:\s+|$)")
_ROMAN_NUMBERING = re.compile(
    r"^\s*(?P<value>[IVXLCDM]{1,8})[.)](?:\s+|$)",
    re.IGNORECASE,
)
_LETTER_NUMBERING = re.compile(r"^\s*(?P<value>[A-Z])[.)](?:\s+|$)")
_KOREAN_NUMBERING = re.compile(r"^\s*제\s*(?P<value>\d+)\s*(?P<unit>장|절|항)(?:\s+|$)")


@dataclass(frozen=True, slots=True)
class ReadingOrderRecord:
    """One block's deterministic position and auditable five-stage evidence."""

    block_id: str
    page_number: int
    final_order: int
    page_order: int
    provider_order: int | None
    geometry_order: int | None
    column_index: int | None
    column_count: int
    band_index: int | None
    semantic_role: str
    previous_page_block_id: str | None
    cross_page_relation: str | None
    uncertain: bool
    evidence: tuple[str, ...]
    quality_flags: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": READING_ORDER_VERSION,
            "stages": list(_STAGES),
            "blockId": self.block_id,
            "pageNumber": self.page_number,
            "finalOrder": self.final_order,
            "pageOrder": self.page_order,
            "providerOrder": self.provider_order,
            "bboxGeometry": {
                "geometryOrder": self.geometry_order,
                "available": self.geometry_order is not None,
            },
            "columnClustering": {
                "columnIndex": self.column_index,
                "columnCount": self.column_count,
                "bandIndex": self.band_index,
            },
            "semanticCues": {"role": self.semantic_role},
            "crossPageContinuity": {
                "previousPageBlockId": self.previous_page_block_id,
                "relation": self.cross_page_relation,
            },
            "readingOrderUncertain": self.uncertain,
            "evidence": list(self.evidence),
            "qualityFlags": list(self.quality_flags),
        }


@dataclass(frozen=True, slots=True)
class ReadingOrderResult:
    """Document-wide reading order with a dense, unique final sequence."""

    ordered_block_ids: tuple[str, ...]
    records: tuple[ReadingOrderRecord, ...]
    uncertain_block_ids: tuple[str, ...]

    def record_by_id(self) -> dict[str, ReadingOrderRecord]:
        return {record.block_id: record for record in self.records}


@dataclass(frozen=True, slots=True)
class NumberingSignal:
    family: Literal["arabic", "roman", "letter", "korean"]
    value: str
    depth: int
    parts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TocEntry:
    source_block_id: str
    anchor: str
    title: str
    page_number: int
    level: int | None


@dataclass(frozen=True, slots=True)
class HeadingInferenceRecord:
    """Heading decision and all bounded signals for one source block."""

    block_id: str
    original_type: str
    inferred_type: str
    is_heading: bool
    level: int | None
    parent_id: str | None
    score: float
    numbering_family: str | None
    numbering_value: str | None
    toc_anchor: str | None
    toc_status: str
    ambiguous: bool
    llm_candidate: bool
    features: tuple[tuple[str, float | int | str | bool | None], ...]
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": HEADING_INFERENCE_VERSION,
            "blockId": self.block_id,
            "originalType": self.original_type,
            "inferredType": self.inferred_type,
            "isHeading": self.is_heading,
            "level": self.level,
            "parentId": self.parent_id,
            "score": self.score,
            "numbering": {
                "family": self.numbering_family,
                "value": self.numbering_value,
            },
            "toc": {
                "anchor": self.toc_anchor,
                "status": self.toc_status,
            },
            "ambiguous": self.ambiguous,
            "llmCandidate": self.llm_candidate,
            "llmInvoked": False,
            "features": dict(self.features),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class HeadingInferenceResult:
    """Document-wide hierarchy, validation findings, and safe candidate input."""

    records: tuple[HeadingInferenceRecord, ...]
    heading_block_ids: tuple[str, ...]
    toc_entries: tuple[TocEntry, ...]
    unmatched_toc_anchors: tuple[str, ...]
    llm_candidate_payload: dict[str, object]

    def record_by_id(self) -> dict[str, HeadingInferenceRecord]:
        return {record.block_id: record for record in self.records}


@dataclass(slots=True)
class _Column:
    items: list[NormalizationBlock]
    left: int
    right: int
    center: float


@dataclass(frozen=True, slots=True)
class _PagePosition:
    block: NormalizationBlock
    geometry_order: int | None
    column_index: int | None
    column_count: int
    band_index: int | None
    evidence: tuple[str, ...]
    uncertain: bool


def _provider_order(block: NormalizationBlock) -> int | None:
    if block.provider_order is not None and block.provider_order >= 0:
        return block.provider_order
    if block.order >= 0:
        return block.order
    return None


def _provider_key(block: NormalizationBlock) -> tuple[int, int, str]:
    provider = _provider_order(block)
    return (
        1 if provider is None else 0,
        provider if provider is not None else 2**31 - 1,
        block.block_id,
    )


def _bbox_key(block: NormalizationBlock) -> tuple[int, int, int, int, tuple[int, int, str]]:
    assert block.bbox1000 is not None
    x1, y1, x2, y2 = block.bbox1000
    return y1, x1, y2, x2, _provider_key(block)


def _center_x(block: NormalizationBlock) -> float:
    assert block.bbox1000 is not None
    return (block.bbox1000[0] + block.bbox1000[2]) / 2


def _center_y(block: NormalizationBlock) -> float:
    assert block.bbox1000 is not None
    return (block.bbox1000[1] + block.bbox1000[3]) / 2


def _horizontal_overlap(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    overlap = max(0, min(left[2], right[2]) - max(left[0], right[0]))
    smaller = min(left[2] - left[0], right[2] - right[0])
    return overlap / max(1, smaller)


def _intersection_ratio(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    width = max(0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0, min(left[3], right[3]) - max(left[1], right[1]))
    intersection = width * height
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / max(1, min(left_area, right_area))


def _is_spanning(block: NormalizationBlock) -> bool:
    assert block.bbox1000 is not None
    x1, _y1, x2, _y2 = block.bbox1000
    return x2 - x1 >= 680 or (x1 <= 250 and x2 >= 750)


def _cluster_columns(
    blocks: Sequence[NormalizationBlock],
) -> tuple[list[_Column], bool]:
    columns: list[_Column] = []
    boundary_uncertain = False
    for block in sorted(blocks, key=lambda item: (_center_x(item), _bbox_key(item))):
        assert block.bbox1000 is not None
        x1, _y1, x2, _y2 = block.bbox1000
        center = _center_x(block)
        candidates: list[tuple[float, float, int]] = []
        for index, column in enumerate(columns):
            overlap = max(0, min(x2, column.right) - max(x1, column.left))
            smaller = min(x2 - x1, column.right - column.left)
            overlap_ratio = overlap / max(1, smaller)
            center_distance = abs(center - column.center)
            if overlap_ratio >= 0.30 or center_distance <= 150:
                candidates.append((-overlap_ratio, center_distance, index))
            elif 150 < center_distance < 220:
                boundary_uncertain = True
        if candidates:
            _negative_overlap, _distance, selected = min(candidates)
            column = columns[selected]
            column.items.append(block)
            column.left = min(column.left, x1)
            column.right = max(column.right, x2)
            column.center = statistics.fmean(_center_x(item) for item in column.items)
        else:
            columns.append(_Column(items=[block], left=x1, right=x2, center=center))
    columns.sort(key=lambda column: (column.center, column.left, column.right))
    return columns, boundary_uncertain


def _semantic_role(block: NormalizationBlock) -> str:
    role = block.block_type.casefold()
    if role in {"header", "title"}:
        return role
    if role in {"footer", "page_number"}:
        return role
    if role == "caption":
        return "caption_after_media"
    return "body"


def _apply_semantic_cues(blocks: list[NormalizationBlock]) -> list[NormalizationBlock]:
    prefixes = [block for block in blocks if block.block_type in {"header", "title"}]
    suffixes = [block for block in blocks if block.block_type in {"footer", "page_number"}]
    body = [block for block in blocks if block not in prefixes and block not in suffixes]
    for caption in [item for item in body if item.block_type == "caption"]:
        caption_index = body.index(caption)
        candidates = [
            (index, item)
            for index, item in enumerate(body)
            if item.block_type in {"figure", "table"} and item.page_number == caption.page_number
        ]
        if not candidates:
            continue
        before = [item for item in candidates if item[0] < caption_index]
        selected_index, _selected = (
            max(before, key=lambda item: item[0])
            if before
            else min(candidates, key=lambda item: abs(item[0] - caption_index))
        )
        body.remove(caption)
        selected_index = body.index(_selected)
        body.insert(selected_index + 1, caption)
    return [
        *sorted(prefixes, key=lambda item: (_semantic_role(item) != "header", _bbox_key(item))),
        *body,
        *sorted(suffixes, key=_bbox_key),
    ]


def _page_positions(
    blocks: Sequence[NormalizationBlock],
) -> tuple[list[_PagePosition], set[str]]:
    bounded = [block for block in blocks if block.bbox1000 is not None]
    unbounded = [block for block in blocks if block.bbox1000 is None]
    spanning = sorted((block for block in bounded if _is_spanning(block)), key=_bbox_key)
    ordinary = [block for block in bounded if not _is_spanning(block)]
    band_members: dict[int, list[NormalizationBlock]] = {
        index: [] for index in range(len(spanning) + 1)
    }
    for block in ordinary:
        band = sum(_center_y(anchor) < _center_y(block) for anchor in spanning)
        band_members[band].append(block)

    ordered: list[NormalizationBlock] = []
    metadata: dict[str, tuple[int | None, int, int | None, tuple[str, ...], bool]] = {}
    uncertain_ids: set[str] = set()
    for band in range(len(spanning) + 1):
        columns, boundary_uncertain = _cluster_columns(band_members[band])
        for column_index, column in enumerate(columns):
            for block in sorted(column.items, key=_bbox_key):
                evidence = ["bbox_geometry_applied", "column_cluster_assigned"]
                uncertain = boundary_uncertain
                if boundary_uncertain:
                    evidence.append("column_boundary_near_threshold")
                    uncertain_ids.add(block.block_id)
                metadata[block.block_id] = (
                    column_index,
                    len(columns),
                    band,
                    tuple(evidence),
                    uncertain,
                )
                ordered.append(block)
        if band < len(spanning):
            anchor = spanning[band]
            metadata[anchor.block_id] = (
                None,
                max(1, len(columns)),
                band,
                ("bbox_geometry_applied", "spanning_block_boundary"),
                False,
            )
            ordered.append(anchor)

    for left_index, left in enumerate(bounded):
        assert left.bbox1000 is not None
        for right in bounded[left_index + 1 :]:
            assert right.bbox1000 is not None
            if _intersection_ratio(left.bbox1000, right.bbox1000) >= 0.25:
                uncertain_ids.update((left.block_id, right.block_id))

    semantic = _apply_semantic_cues(ordered)
    semantic.extend(sorted(unbounded, key=_provider_key))
    geometry_orders = {block.block_id: index for index, block in enumerate(ordered)}
    positions: list[_PagePosition] = []
    provider_values = [_provider_order(block) for block in blocks]
    duplicate_provider = len([value for value in provider_values if value is not None]) != len(
        {value for value in provider_values if value is not None}
    )
    for block in semantic:
        column_index_value, column_count_value, band_value, stage_evidence, edge_uncertain = (
            metadata.get(
                block.block_id,
                (None, 0, None, ("bbox_geometry_unavailable", "provider_order_fallback"), False),
            )
        )
        block_evidence = [
            "provider_order_available"
            if _provider_order(block) is not None
            else "provider_order_unavailable",
            *stage_evidence,
            f"semantic_role:{_semantic_role(block)}",
        ]
        block_uncertain = block.block_id in uncertain_ids or edge_uncertain
        if block.bbox1000 is None and _provider_order(block) is None:
            block_uncertain = True
            block_evidence.append("no_provider_or_geometry_order")
        if duplicate_provider and _provider_order(block) is not None and block.bbox1000 is None:
            block_uncertain = True
            block_evidence.append("duplicate_provider_order_without_geometry")
        if block.block_id in uncertain_ids:
            block_evidence.append("substantial_bbox_overlap")
        positions.append(
            _PagePosition(
                block=block,
                geometry_order=geometry_orders.get(block.block_id),
                column_index=column_index_value,
                column_count=column_count_value,
                band_index=band_value,
                evidence=tuple(block_evidence),
                uncertain=block_uncertain,
            )
        )
    return positions, uncertain_ids


def _cross_page_relation(
    previous: NormalizationBlock | None,
    current: NormalizationBlock,
) -> tuple[str | None, bool]:
    if previous is None or current.page_number != previous.page_number + 1:
        return None, False
    previous_text = (previous.normalized_text or previous.raw_text).rstrip()
    if previous.block_type == "heading" and current.block_type in {"paragraph", "list"}:
        return "heading_body_continuity", False
    if (
        previous.block_type in {"paragraph", "list", "quote"}
        and current.block_type in {"paragraph", "list", "quote"}
        and previous_text
        and previous_text[-1] not in _TERMINAL_PUNCTUATION
    ):
        return "possible_prose_continuation", True
    if previous.block_type == "figure" and current.block_type == "caption":
        return "figure_caption_continuity", False
    if previous.block_type == "table" and current.block_type == "table":
        return "possible_split_table", True
    return "page_boundary", False


def infer_reading_order(
    blocks: Sequence[NormalizationBlock],
) -> ReadingOrderResult:
    """Apply the five specified stages and return one dense deterministic order."""

    identities = [block.block_id for block in blocks]
    if len(identities) != len(set(identities)):
        raise ValueError("reading-order block IDs must be unique")
    by_page: dict[int, list[NormalizationBlock]] = {}
    for block in blocks:
        if block.page_number < 1:
            raise ValueError("page_number must be positive")
        by_page.setdefault(block.page_number, []).append(block)

    records: list[ReadingOrderRecord] = []
    ordered_ids: list[str] = []
    previous: NormalizationBlock | None = None
    for page_number in sorted(by_page):
        page_positions, _page_uncertain = _page_positions(by_page[page_number])
        for page_order, position in enumerate(page_positions):
            relation, relation_uncertain = _cross_page_relation(previous, position.block)
            evidence = list(position.evidence)
            if relation is not None:
                evidence.append(f"cross_page:{relation}")
            provider = _provider_order(position.block)
            if (
                position.geometry_order is not None
                and provider is not None
                and position.geometry_order != provider
            ):
                evidence.append("provider_geometry_order_disagreement_resolved")
            uncertain = position.uncertain or relation_uncertain
            quality_flags = ("reading_order_uncertain",) if uncertain else ()
            final_order = len(ordered_ids)
            ordered_ids.append(position.block.block_id)
            records.append(
                ReadingOrderRecord(
                    block_id=position.block.block_id,
                    page_number=page_number,
                    final_order=final_order,
                    page_order=page_order,
                    provider_order=provider,
                    geometry_order=position.geometry_order,
                    column_index=position.column_index,
                    column_count=position.column_count,
                    band_index=position.band_index,
                    semantic_role=_semantic_role(position.block),
                    previous_page_block_id=(
                        previous.block_id if relation is not None and previous is not None else None
                    ),
                    cross_page_relation=relation,
                    uncertain=uncertain,
                    evidence=tuple(evidence),
                    quality_flags=quality_flags,
                )
            )
            previous = position.block
    uncertain_ids = tuple(record.block_id for record in records if record.uncertain)
    return ReadingOrderResult(
        ordered_block_ids=tuple(ordered_ids),
        records=tuple(records),
        uncertain_block_ids=uncertain_ids,
    )


def _normalized_anchor(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _ARABIC_NUMBERING.sub("", normalized, count=1)
    normalized = _ROMAN_NUMBERING.sub("", normalized, count=1)
    normalized = _LETTER_NUMBERING.sub("", normalized, count=1)
    normalized = _KOREAN_NUMBERING.sub("", normalized, count=1)
    normalized = re.sub(r"[^\w가-힣]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-")[:160]


def _numbering_signal(value: str) -> NumberingSignal | None:
    korean = _KOREAN_NUMBERING.match(value)
    if korean:
        unit = korean.group("unit")
        depth = {"장": 1, "절": 2, "항": 3}[unit]
        korean_number = int(korean.group("value"))
        return NumberingSignal(
            "korean",
            f"제{korean_number}{unit}",
            depth,
            (korean_number,),
        )
    arabic = _ARABIC_NUMBERING.match(value)
    if arabic:
        arabic_number = arabic.group("value")
        parts = tuple(int(part) for part in arabic_number.split("."))
        return NumberingSignal("arabic", arabic_number, len(parts), parts)
    roman = _ROMAN_NUMBERING.match(value)
    if roman:
        return NumberingSignal("roman", roman.group("value").upper(), 1, ())
    letter = _LETTER_NUMBERING.match(value)
    if letter:
        return NumberingSignal("letter", letter.group("value"), 1, ())
    return None


def _explicit_heading_level(block: NormalizationBlock) -> int | None:
    if block.explicit_heading_level is not None:
        return max(1, min(6, block.explicit_heading_level))
    provider = block.provider_label or ""
    match = _PROVIDER_LEVEL.search(provider)
    if match:
        return int(match.group("level"))
    markdown = block.markdown or ""
    atx = _ATX_HEADING.match(markdown)
    if atx:
        return len(atx.group("marks"))
    return None


def _toc_entries(
    ordered: Sequence[NormalizationBlock],
) -> tuple[tuple[TocEntry, ...], frozenset[str]]:
    toc_pages: set[int] = set()
    explicit_toc_blocks = {
        block.block_id for block in ordered if block.is_toc_entry or block.toc_level is not None
    }
    for block in ordered:
        text = (block.normalized_text or block.raw_text).strip()
        if _TOC_TITLE.fullmatch(text):
            toc_pages.add(block.page_number)
    entries: list[TocEntry] = []
    entry_blocks: set[str] = set(explicit_toc_blocks)
    for block in ordered:
        if block.page_number not in toc_pages and block.block_id not in explicit_toc_blocks:
            continue
        text = block.normalized_text or block.raw_text
        for line in text.splitlines() or [text]:
            match = _TOC_ENTRY.match(line)
            if not match:
                continue
            title = _WHITESPACE.sub(" ", match.group("title")).strip()
            anchor = _normalized_anchor(title)
            if not anchor:
                continue
            numbering = _numbering_signal(title)
            level = block.toc_level
            if level is None and numbering is not None:
                level = min(6, numbering.depth + 1)
            entries.append(
                TocEntry(
                    source_block_id=block.block_id,
                    anchor=anchor,
                    title=title[:240],
                    page_number=int(match.group("page")),
                    level=level,
                )
            )
            entry_blocks.add(block.block_id)
    unique = {
        (entry.source_block_id, entry.anchor, entry.page_number, entry.level): entry
        for entry in entries
    }
    return (
        tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.source_block_id,
                    item.anchor,
                    item.page_number,
                    item.level or 0,
                ),
            )
        ),
        frozenset(entry_blocks),
    )


def _font_statistics(
    blocks: Sequence[NormalizationBlock],
) -> tuple[float | None, tuple[float, ...]]:
    values = sorted(
        {
            round(block.font_size_pt, 2)
            for block in blocks
            if block.font_size_pt is not None
            and math.isfinite(block.font_size_pt)
            and 1 <= block.font_size_pt <= 200
        },
        reverse=True,
    )
    all_values = [
        block.font_size_pt
        for block in blocks
        if block.font_size_pt is not None
        and math.isfinite(block.font_size_pt)
        and 1 <= block.font_size_pt <= 200
    ]
    return (statistics.median(all_values) if all_values else None, tuple(values))


def _font_level(block: NormalizationBlock, sizes: tuple[float, ...]) -> int | None:
    if block.font_size_pt is None or not sizes:
        return None
    rounded = round(block.font_size_pt, 2)
    try:
        rank = sizes.index(rounded)
    except ValueError:
        return None
    return min(6, rank + 1)


def _style_key(
    block: NormalizationBlock,
    numbering: NumberingSignal | None,
) -> tuple[str, float | None, int | None, str]:
    font = round(block.font_size_pt, 1) if block.font_size_pt is not None else None
    return (
        (block.provider_label or block.block_type).casefold(),
        font,
        numbering.depth if numbering is not None else None,
        numbering.family if numbering is not None else "",
    )


def _feature_tuple(
    values: dict[str, float | int | str | bool | None],
) -> tuple[tuple[str, float | int | str | bool | None], ...]:
    return tuple(sorted(values.items()))


def _safe_candidate_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _CONTROL_CHARACTERS.sub(" ", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    return normalized[:240]


def build_heading_llm_candidate_payload(
    records: Sequence[HeadingInferenceRecord],
    blocks: Sequence[NormalizationBlock],
    *,
    max_candidates: int = 32,
) -> dict[str, object]:
    """Build a bounded candidate-only payload; this function performs no I/O."""

    if not 1 <= max_candidates <= 32:
        raise ValueError("max_candidates must be between 1 and 32")
    blocks_by_id = {block.block_id: block for block in blocks}
    candidates: list[dict[str, object]] = []
    for record in sorted(
        (item for item in records if item.llm_candidate),
        key=lambda item: (-item.score, item.block_id),
    )[:max_candidates]:
        block = blocks_by_id[record.block_id]
        text = _safe_candidate_text(block.normalized_text or block.raw_text)
        candidates.append(
            {
                "blockId": record.block_id,
                "candidateText": text,
                "candidateTextSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "proposedLevel": record.level,
                "features": dict(record.features),
                "evidence": list(record.evidence),
            }
        )
    payload: dict[str, object] = {
        "schemaVersion": "akc-heading-llm-candidates-1.0.0",
        "purpose": "heading_ambiguity_candidate_review",
        "untrustedInput": True,
        "candidateOnly": True,
        "neighborBodyIncluded": False,
        "documentIncluded": False,
        "llmInvoked": False,
        "mutationAuthority": "none",
        "candidates": candidates,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 32_768:
        raise ValueError("heading candidate payload exceeds safe boundary")
    return payload


def infer_heading_hierarchy(
    blocks: Sequence[NormalizationBlock],
) -> HeadingInferenceResult:
    """Infer and validate a stable document heading tree using rules only."""

    identities = [block.block_id for block in blocks]
    if len(identities) != len(set(identities)):
        raise ValueError("heading block IDs must be unique")
    ordered = tuple(
        sorted(
            blocks,
            key=lambda block: (
                block.order,
                block.page_number,
                _provider_key(block),
                block.block_id,
            ),
        )
    )
    median_font, font_sizes = _font_statistics(ordered)
    toc_entries, toc_entry_blocks = _toc_entries(ordered)
    toc_by_anchor: dict[str, list[TocEntry]] = {}
    for entry in toc_entries:
        toc_by_anchor.setdefault(entry.anchor, []).append(entry)

    numberings = {
        block.block_id: _numbering_signal(block.normalized_text or block.raw_text)
        for block in ordered
    }
    style_counts = Counter(
        _style_key(block, numberings[block.block_id])
        for block in ordered
        if block.block_id not in toc_entry_blocks
    )
    draft: list[HeadingInferenceRecord] = []
    matched_toc: set[str] = set()
    for block in ordered:
        text = block.normalized_text or block.raw_text
        numbering = numberings[block.block_id]
        explicit_level = _explicit_heading_level(block)
        anchor = _normalized_anchor(text)
        toc_matches = toc_by_anchor.get(anchor, ())
        toc_level = next(
            (entry.level for entry in toc_matches if entry.level is not None),
            None,
        )
        provider_heading = block.block_type in _HEADING_TYPES or bool(
            re.search(
                r"(?:title|heading|section_header|paragraph_title)",
                block.provider_label or "",
                re.IGNORECASE,
            )
        )
        font_level = _font_level(block, font_sizes)
        font_ratio = (
            block.font_size_pt / median_font
            if block.font_size_pt is not None and median_font is not None and median_font > 0
            else None
        )
        position_signal = bool(
            block.bbox1000 is not None and block.bbox1000[1] <= 220 and block.bbox1000[3] <= 400
        )
        whitespace_signal = bool(
            block.whitespace_before is not None
            and block.whitespace_after is not None
            and block.whitespace_before >= max(12.0, block.whitespace_after * 1.35)
        )
        repeated_signal = style_counts[_style_key(block, numbering)] >= 2
        bold_signal = block.font_weight is not None and block.font_weight >= 600

        score = 0.0
        evidence: list[str] = []
        if block.block_type == "title":
            score += 0.90
            evidence.append("provider_title_type")
        elif block.block_type == "heading":
            score += 0.68
            evidence.append("provider_heading_type")
        elif provider_heading:
            score += 0.50
            evidence.append("provider_heading_label")
        if numbering is not None:
            score += 0.16 if numbering.depth == 1 else 0.24
            evidence.append(f"numbering:{numbering.family}:{numbering.depth}")
        if font_ratio is not None and font_ratio >= 1.30:
            score += 0.24
            evidence.append("font_size_above_body")
        elif font_ratio is not None and font_ratio >= 1.12:
            score += 0.12
            evidence.append("font_size_slightly_above_body")
        if bold_signal:
            score += 0.12
            evidence.append("font_weight_emphasis")
        if position_signal:
            score += 0.07
            evidence.append("upper_page_position")
        if whitespace_signal:
            score += 0.10
            evidence.append("heading_whitespace_pattern")
        if toc_matches:
            score += 0.34
            evidence.append("toc_anchor_match")
            matched_toc.add(anchor)
        if repeated_signal:
            score += 0.10
            evidence.append("repeated_document_style")
        score = round(min(1.0, score), 6)

        excluded = block.block_type in _NON_HEADING_TYPES or block.block_id in toc_entry_blocks
        is_heading = not excluded and (provider_heading or score >= 0.55)
        ambiguous = (
            not excluded
            and 0.38 <= score < 0.72
            and not (block.block_type in _HEADING_TYPES and score >= 0.68)
        )
        level: int | None = None
        if is_heading:
            if block.block_type == "title":
                level = 1
            elif explicit_level is not None:
                level = explicit_level
            elif toc_level is not None:
                level = max(1, min(6, toc_level))
            elif numbering is not None:
                level = min(6, numbering.depth + 1)
            elif font_level is not None:
                level = font_level
            else:
                level = 2
        inferred_type = (
            "title"
            if is_heading and level == 1 and block.block_type != "heading"
            else ("heading" if is_heading else block.block_type)
        )
        toc_status = "not_applicable"
        if is_heading and toc_entries:
            toc_status = "matched" if toc_matches else "heading_not_listed"
        elif block.block_id in toc_entry_blocks:
            toc_status = "toc_entry_source"
        features = _feature_tuple(
            {
                "providerLabel": block.provider_label,
                "providerHeading": provider_heading,
                "fontSizePt": block.font_size_pt,
                "fontRatioToMedian": (round(font_ratio, 6) if font_ratio is not None else None),
                "fontWeight": block.font_weight,
                "bboxUpperPage": position_signal,
                "whitespaceBefore": block.whitespace_before,
                "whitespaceAfter": block.whitespace_after,
                "whitespaceHeadingPattern": whitespace_signal,
                "numberingDepth": numbering.depth if numbering is not None else None,
                "tocMatched": bool(toc_matches),
                "repeatedStyle": repeated_signal,
            }
        )
        draft.append(
            HeadingInferenceRecord(
                block_id=block.block_id,
                original_type=block.block_type,
                inferred_type=inferred_type,
                is_heading=is_heading,
                level=level,
                parent_id=None,
                score=score,
                numbering_family=numbering.family if numbering is not None else None,
                numbering_value=numbering.value if numbering is not None else None,
                toc_anchor=anchor if toc_matches else None,
                toc_status=toc_status,
                ambiguous=ambiguous,
                llm_candidate=ambiguous,
                features=features,
                evidence=tuple(evidence),
                warnings=(),
            )
        )

    title_count = sum(record.is_heading and record.level == 1 for record in draft)
    stack: list[HeadingInferenceRecord] = []
    seen_numbers: dict[tuple[str, str], str] = {}
    seen_arabic: set[tuple[int, ...]] = set()
    final: list[HeadingInferenceRecord] = []
    previous_level: int | None = None
    for record in draft:
        warnings: list[str] = []
        parent_id: str | None = None
        if record.is_heading:
            assert record.level is not None
            while stack and (stack[-1].level or 1) >= record.level:
                stack.pop()
            if stack:
                parent_id = stack[-1].block_id
            if previous_level is not None and record.level > previous_level + 1:
                warnings.append("heading_level_jump")
            if record.level == 1 and title_count > 1:
                warnings.append("multiple_document_titles")
            if record.numbering_family and record.numbering_value:
                number_key = (record.numbering_family, record.numbering_value)
                if number_key in seen_numbers:
                    warnings.append("duplicate_heading_number")
                else:
                    seen_numbers[number_key] = record.block_id
            if record.numbering_family == "arabic" and record.numbering_value:
                parts = tuple(int(part) for part in record.numbering_value.split("."))
                if len(parts) > 1 and parts[:-1] not in seen_arabic:
                    warnings.append("heading_numbering_parent_missing")
                seen_arabic.add(parts)
            if record.toc_status == "matched":
                expected_levels = {
                    entry.level
                    for entry in toc_by_anchor.get(record.toc_anchor or "", ())
                    if entry.level is not None
                }
                if expected_levels and record.level not in expected_levels:
                    warnings.append("toc_anchor_level_mismatch")
            updated = replace(
                record,
                parent_id=parent_id,
                warnings=tuple(sorted(set(warnings))),
            )
            stack.append(updated)
            previous_level = record.level
            final.append(updated)
        else:
            final.append(record)

    unmatched = tuple(sorted(set(toc_by_anchor) - matched_toc))
    if unmatched:
        toc_sources = {entry.source_block_id for entry in toc_entries if entry.anchor in unmatched}
        final = [
            replace(
                record,
                warnings=tuple(sorted({*record.warnings, "toc_anchor_missing_in_body"})),
            )
            if record.block_id in toc_sources
            else record
            for record in final
        ]
    payload = build_heading_llm_candidate_payload(final, ordered)
    return HeadingInferenceResult(
        records=tuple(final),
        heading_block_ids=tuple(record.block_id for record in final if record.is_heading),
        toc_entries=toc_entries,
        unmatched_toc_anchors=unmatched,
        llm_candidate_payload=payload,
    )


def analyze_document_structure(
    blocks: Sequence[NormalizationBlock],
) -> tuple[ReadingOrderResult, HeadingInferenceResult]:
    """Run reading order first, then heading inference on the resulting order."""

    reading = infer_reading_order(blocks)
    records = reading.record_by_id()
    reordered = tuple(replace(block, order=records[block.block_id].final_order) for block in blocks)
    hierarchy = infer_heading_hierarchy(reordered)
    return reading, hierarchy


__all__ = [
    "HEADING_INFERENCE_VERSION",
    "READING_ORDER_VERSION",
    "HeadingInferenceRecord",
    "HeadingInferenceResult",
    "ReadingOrderRecord",
    "ReadingOrderResult",
    "TocEntry",
    "analyze_document_structure",
    "build_heading_llm_candidate_payload",
    "infer_heading_hierarchy",
    "infer_reading_order",
]
