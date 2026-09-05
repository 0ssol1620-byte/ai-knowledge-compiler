"""Canonicalize MinerU pipeline output.

MinerU writes Markdown of its own, plus ``*_middle.json``, ``*_model.json`` and
``*_content_list.json``. Masterplan §7 is explicit that the native output is
never discarded, so the rule here is narrow:

* **the Markdown is kept**, whitespace-normalised and otherwise byte-for-byte;
  it is never regenerated from the JSON, because regenerating it would score a
  different artefact than the one MinerU produced;
* the element list is **attached from** ``content_list.json`` (falling back to
  the ``pdf_info`` blocks of ``middle.json`` when the content list is absent),
  and never invented;
* nothing is added. If MinerU emitted no content list and no middle JSON,
  ``elements`` is ``None`` with a note naming the reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

MODEL_KEY = "mineru_pipeline"


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


def _from_content_list(
    content_list: list[Any],
) -> tuple[Mapping[str, Any], ...]:
    elements: list[Mapping[str, Any]] = []
    for order, item in enumerate(content_list):
        if not isinstance(item, Mapping):
            continue
        elements.append(
            {
                "reading_order": order,
                "source": "content_list",
                "type": item.get("type"),
                "page_index": item.get("page_idx"),
                "text": item.get("text"),
                "text_level": item.get("text_level"),
                "img_path": item.get("img_path"),
                "table_body": item.get("table_body"),
            }
        )
    return tuple(elements)


def _from_middle_json(middle: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...] | None:
    pages = middle.get("pdf_info")
    if not isinstance(pages, list):
        return None
    elements: list[Mapping[str, Any]] = []
    order = 0
    for page_index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            continue
        blocks = page.get("para_blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            elements.append(
                {
                    "reading_order": order,
                    "source": "middle_json.para_blocks",
                    "type": block.get("type"),
                    "page_index": page_index,
                    "bbox": block.get("bbox"),
                }
            )
            order += 1
    return tuple(elements) if elements else None


def extract_elements(
    native_json: Mapping[str, Any] | None,
) -> tuple[tuple[Mapping[str, Any], ...] | None, str | None]:
    if native_json is None:
        return None, "no_elements_available:native_json_absent"
    content_list = native_json.get("content_list")
    if isinstance(content_list, list) and content_list:
        return _from_content_list(content_list), None
    middle = native_json.get("middle_json")
    if isinstance(middle, Mapping):
        elements = _from_middle_json(middle)
        if elements is not None:
            return elements, "elements_from_middle_json:content_list_absent_or_empty"
    return None, "no_elements_available:neither_content_list_nor_middle_json_usable"


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

    lossy = bool(raw.raw_text.strip()) and not markdown
    return CanonicalOutput(
        markdown=markdown,
        elements=elements,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )
