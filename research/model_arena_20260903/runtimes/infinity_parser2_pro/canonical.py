"""Canonicalise Infinity-Parser2-Pro doc2json output into markdown.

Representation conversion only. This module reorders and unwraps what the model
emitted; it never fills a gap, infers a cell, or drops a truncation warning.

The doc2json prompt on the model card fixes the shape of the payload: one JSON
object holding layout elements, each with ``bbox``, ``category`` and ``text``,
already sorted in human reading order, with ``figure`` text empty, ``formula``
text in LaTeX, ``table`` text in HTML and everything else in Markdown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

#: Categories the model card's prompt allows. An unknown label is kept verbatim and
#: reported as a conversion note rather than being silently remapped.
KNOWN_CATEGORIES = (
    "header",
    "title",
    "text",
    "figure",
    "table",
    "formula",
    "figure_caption",
    "table_caption",
    "formula_caption",
    "figure_footnote",
    "table_footnote",
    "page_footnote",
    "footer",
)

_ELEMENT_LIST_KEYS = ("elements", "layout", "layout_elements", "results", "blocks")


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    lossy = False
    for warning in raw.warnings:
        notes.append(f"adapter_warning:{warning}")
        if "OUTPUT_TRUNCATED" in warning or "OUTPUT_EMPTY" in warning:
            lossy = True

    elements = _extract_elements(raw.native_json)
    if elements is None:
        notes.append(
            "native_json carried no recognisable element list; "
            "canonical markdown is the raw model text verbatim"
        )
        return CanonicalOutput(
            markdown=raw.raw_text,
            elements=None,
            conversion_notes=tuple(notes),
            lossy=True,
        )

    blocks: list[str] = []
    canonical_elements: list[Mapping[str, Any]] = []
    textless_figures = 0
    unknown_categories: set[str] = set()

    for index, element in enumerate(elements):
        if not isinstance(element, Mapping):
            notes.append(f"element {index} was not an object and was skipped")
            lossy = True
            continue
        category = str(element.get("category", "")).strip().lower()
        text = element.get("text")
        text = "" if text is None else str(text)
        if category and category not in KNOWN_CATEGORIES:
            unknown_categories.add(category)
        canonical_elements.append(
            {
                "index": index,
                "category": category or None,
                "bbox": _normalise_bbox(element.get("bbox")),
                "text": text,
            }
        )
        rendered = _render(category, text)
        if rendered is None:
            if category == "figure":
                textless_figures += 1
            continue
        blocks.append(rendered)

    if textless_figures:
        notes.append(
            f"{textless_figures} figure element(s) carried the empty text the prompt "
            "mandates and contribute no markdown"
        )
    if unknown_categories:
        notes.append(
            "categories outside the model card's list were kept verbatim: "
            + ", ".join(sorted(unknown_categories))
        )
    if not blocks and raw.raw_text.strip():
        notes.append("every element rendered empty although the model returned text")
        lossy = True

    return CanonicalOutput(
        markdown="\n\n".join(blocks),
        elements=tuple(canonical_elements),
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


def _extract_elements(native_json: Mapping[str, Any] | None) -> Sequence[Any] | None:
    if native_json is None:
        return None
    for key in _ELEMENT_LIST_KEYS:
        value = native_json.get(key)
        if isinstance(value, list):
            return value
    return None


def _normalise_bbox(bbox: Any) -> list[float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


def _render(category: str, text: str) -> str | None:
    if not text.strip():
        return None
    if category == "formula":
        stripped = text.strip()
        if stripped.startswith("$") or stripped.startswith("\\["):
            return stripped
        return f"$$\n{stripped}\n$$"
    return text.strip()


__all__ = ["KNOWN_CATEGORIES", "canonicalize"]
