"""Canonicalise GLM-OCR output.

``glmocr``'s ``ResultFormatter`` already emits markdown, so canonicalisation is a
pass-through of that text plus a lift of ``json_result`` into ``elements``.

What is reported rather than repaired:

- The SDK's post-processing switches (``enable_merge_formula_numbers``,
  ``enable_merge_text_blocks``, ``enable_format_bullet_points``) are on by default,
  so the markdown has already been reflowed by the vendor. That is the official
  path and it stays, but it is recorded so a later reader knows the text is not a
  raw model transcript.
- Region labels the SDK's own visualisation mapping does not know are kept verbatim
  and listed, never remapped onto a label that happens to look close.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

#: glmocr/config.yaml v0.1.5, result_formatter.label_visualization_mapping, flattened.
KNOWN_LABELS = frozenset(
    {
        "abstract",
        "algorithm",
        "chart",
        "content",
        "display_formula",
        "doc_title",
        "figure_title",
        "formula_number",
        "image",
        "inline_formula",
        "paragraph_title",
        "reference_content",
        "seal",
        "table",
        "text",
        "vertical_text",
        "vision_footnote",
    }
)

_REGION_LIST_KEYS = ("regions", "blocks", "elements", "layout", "results", "pages")
_IMAGE_REFERENCE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = [
        "markdown is glmocr ResultFormatter output with the SDK's default "
        "post-processing on (merge_formula_numbers, merge_text_blocks, "
        "format_bullet_points); it is the official path, not a raw transcript"
    ]
    lossy = False
    for warning in raw.warnings:
        notes.append(f"adapter_warning:{warning}")
        if "OUTPUT_TRUNCATED" in warning or "OUTPUT_EMPTY" in warning:
            lossy = True

    markdown = raw.raw_text
    references = _IMAGE_REFERENCE.findall(markdown)
    if references:
        notes.append(
            f"{len(references)} image reference(s) point at SDK-side files the arena "
            "does not carry: " + ", ".join(sorted(set(references))[:8])
        )

    regions, unknown = _extract_regions(raw.native_json)
    if regions is None:
        notes.append("no region list in json_result; canonical elements are unavailable")
    elif unknown:
        notes.append(
            "labels outside the SDK's mapping kept verbatim: " + ", ".join(sorted(unknown))
        )

    return CanonicalOutput(
        markdown=markdown.strip(),
        elements=tuple(regions) if regions else None,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


def _extract_regions(native_json: Any) -> tuple[list[dict[str, Any]] | None, set[str]]:
    unknown: set[str] = set()
    if not isinstance(native_json, dict):
        return None, unknown
    raw_regions: Sequence[Any] | None = None
    for key in _REGION_LIST_KEYS:
        value = native_json.get(key)
        if isinstance(value, list):
            raw_regions = value
            break
    if raw_regions is None:
        return None, unknown
    regions: list[dict[str, Any]] = []
    for index, region in enumerate(raw_regions):
        if not isinstance(region, dict):
            continue
        label = region.get("label") or region.get("category") or region.get("type")
        if isinstance(label, str) and label and label not in KNOWN_LABELS:
            unknown.add(label)
        regions.append(
            {
                "index": index,
                "label": label,
                "bbox": _normalise_bbox(region.get("bbox") or region.get("poly")),
                "text": region.get("text") if "text" in region else region.get("content"),
            }
        )
    return (regions or None), unknown


def _normalise_bbox(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


__all__ = ["KNOWN_LABELS", "canonicalize"]
