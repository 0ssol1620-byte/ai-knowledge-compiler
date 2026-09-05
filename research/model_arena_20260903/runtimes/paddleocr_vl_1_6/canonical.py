"""Canonicalize PaddleOCR-VL 1.6 output.

PaddleOCR-VL already emits Markdown, so canonicalization is representation-only:
line endings are normalised, trailing spaces are dropped and runs of blank lines
are collapsed. No content is added, reordered or inferred. The element list is
lifted from the PaddleX result JSON when the pipeline provided one; when it did
not, ``elements`` is ``None`` with a note saying why, never a fabricated list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

MODEL_KEY = "paddleocr_vl_1_6"

# PaddleX exposes layout blocks under one of these keys depending on version.
_BLOCK_LIST_KEYS = ("parsing_res_list", "layout_parsing_result", "layout_det_res")
_LABEL_KEYS = ("block_label", "label", "type")
_BBOX_KEYS = ("block_bbox", "bbox", "coordinate")
_CONTENT_KEYS = ("block_content", "content", "text")


def normalize_markdown(text: str) -> str:
    """Deterministic whitespace normalisation. Content-preserving."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    collapsed: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            collapsed.append(line)
            continue
        blanks += 1
        if blanks <= 2:
            collapsed.append(line)
    while collapsed and not collapsed[0]:
        collapsed.pop(0)
    while collapsed and not collapsed[-1]:
        collapsed.pop()
    return "\n".join(collapsed)


def _first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _blocks(page: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    payload = page.get("res") if isinstance(page.get("res"), Mapping) else page
    if not isinstance(payload, Mapping):
        return None
    for key in _BLOCK_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return None


def extract_elements(
    native_json: Mapping[str, Any] | None,
) -> tuple[tuple[Mapping[str, Any], ...] | None, str | None]:
    """Return (elements, reason_when_none). Never invents a block."""
    if native_json is None:
        return None, "no_elements_available:native_json_absent"
    pages = native_json.get("pages")
    if not isinstance(pages, list) or not pages:
        return None, "no_elements_available:no_pages_in_native_json"
    elements: list[Mapping[str, Any]] = []
    saw_block_list = False
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            continue
        blocks = _blocks(page)
        if blocks is None:
            continue
        saw_block_list = True
        for order, block in enumerate(blocks):
            label = _first(block, _LABEL_KEYS)
            bbox = _first(block, _BBOX_KEYS)
            content = _first(block, _CONTENT_KEYS)
            elements.append(
                {
                    "page_index": index,
                    "reading_order": order,
                    "type": label if isinstance(label, str) else None,
                    "bbox": list(bbox) if isinstance(bbox, (list, tuple)) else None,
                    "content": content if isinstance(content, str) else None,
                }
            )
    if not saw_block_list:
        return None, "no_elements_available:pipeline_emitted_no_parsing_res_list"
    return tuple(elements), None


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = [f"warning:{warning}" for warning in raw.warnings]
    if raw.output_format != "markdown":
        notes.append(f"unexpected_output_format:{raw.output_format}")

    markdown = normalize_markdown(raw.raw_text)
    if not markdown:
        notes.append("empty_raw_text")

    elements, reason = extract_elements(raw.native_json)
    if reason is not None:
        notes.append(reason)

    # Lossy means the conversion could not represent something the model emitted.
    # Normalised whitespace is not loss; a dropped block list would be, and the
    # note above records that the pipeline never emitted one in the first place.
    lossy = bool(raw.raw_text.strip()) and not markdown
    return CanonicalOutput(
        markdown=markdown,
        elements=elements,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )
