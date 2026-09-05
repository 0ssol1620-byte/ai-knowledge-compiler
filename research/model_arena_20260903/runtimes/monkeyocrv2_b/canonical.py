"""Canonicalise MonkeyOCRv2-B-Parsing output.

The official pipeline already emits markdown (``<out>/markdowns/<stem>.md``), so
canonicalisation here is almost a pass-through: the markdown is kept verbatim and
the accompanying ``jsons/`` block list is lifted into ``elements``.

Two things are reported rather than fixed:

- The recognition prompt for a table asks the model for **OTSL**, and the official
  formatter converts it to HTML on the way into markdown. If OTSL survives into the
  markdown the conversion did not fire, and that is flagged as lossy rather than
  translated here — translating it would be this lane inventing a table.
- Image references. With ``use_base64: false`` the formatter writes picture blocks
  as relative paths into an ``images/`` directory the arena does not keep. Those
  references are recorded and flagged; the alternative, deleting them, would drop
  evidence that a figure existed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

_BLOCK_LIST_KEYS = ("blocks", "content_list", "elements", "results", "layout")
_IMAGE_REFERENCE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_OTSL_MARKER = re.compile(r"<(fcel|ecel|nl|lcel|ucel|xcel)\b", re.IGNORECASE)


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    lossy = False
    for warning in raw.warnings:
        notes.append(f"adapter_warning:{warning}")
        if "OUTPUT_TRUNCATED" in warning or "OUTPUT_EMPTY" in warning:
            lossy = True

    markdown = raw.raw_text

    if _OTSL_MARKER.search(markdown):
        notes.append(
            "markdown still contains OTSL table markup; the official formatter's "
            "OTSL-to-HTML conversion did not fire and this lane does not translate it"
        )
        lossy = True

    references = _IMAGE_REFERENCE.findall(markdown)
    if references:
        notes.append(
            f"{len(references)} image reference(s) point at pipeline-side files the "
            "arena does not carry: " + ", ".join(sorted(set(references))[:8])
        )

    elements = _extract_blocks(raw.native_json)
    if elements is None:
        notes.append("no block list in native_json; canonical elements are unavailable")
    return CanonicalOutput(
        markdown=markdown.strip(),
        elements=tuple(elements) if elements else None,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


def _extract_blocks(native_json: Any) -> list[dict[str, Any]] | None:
    if not isinstance(native_json, dict):
        return None
    raw_blocks: Sequence[Any] | None = None
    for key in _BLOCK_LIST_KEYS:
        value = native_json.get(key)
        if isinstance(value, list):
            raw_blocks = value
            break
    if raw_blocks is None:
        return None
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(raw_blocks):
        if not isinstance(block, dict):
            continue
        blocks.append(
            {
                "index": index,
                "label": block.get("label") or block.get("category") or block.get("type"),
                "bbox": _normalise_bbox(block.get("bbox")),
                "text": block.get("content") if "content" in block else block.get("text"),
            }
        )
    return blocks or None


def _normalise_bbox(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


__all__ = ["canonicalize"]
