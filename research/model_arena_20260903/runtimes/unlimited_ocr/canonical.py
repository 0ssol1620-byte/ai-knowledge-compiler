"""Canonical markdown for Unlimited-OCR.

Transcription of the ``remove_det`` post-processing the model card publishes
under "For OmniDocBench evaluation, you need to perform the following
post-processing"
(huggingface.co/baidu/Unlimited-OCR @ 07dea832e22aefee32ad281d4b80551282e1c168).

Two behaviours of that function are quirks and are kept, because changing them
would change what the official evaluator is fed:

1. A ``<|det|>image …<|/det|>`` line is skipped with ``continue`` **without
   flushing the block being built**, so the lines that follow an image marker are
   appended to the previous block rather than starting a new one.
2. Blank lines are dropped before block assembly, so the model's own paragraph
   breaks inside one block are lost; blocks are re-joined with ``\\n\\n``.

A third property is a limitation rather than a quirk, and the canary must check
it against real output: ``[^\\]]*`` inside ``DET_RE`` stops at the first ``]``, so
the regex matches a **single-bracket** bbox (``<|det|>title [1, 2, 3, 4]<|/det|>``
— the shape the model card documents) and does **not** match a nested one
(``[[1, 2, 3, 4]]``, the shape DeepSeek-OCR-2 emits). If this model turns out to
emit nested brackets, the official post-processing leaves the markers in the
markdown. That is upstream's function, reproduced; it is not silently patched
here. ``det_elements`` has the same limitation by construction, so `elements` and
`markdown` can never disagree about what was matched.

Nothing here adds content. The ``det`` payloads removed from the markdown are
re-presented in ``elements``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

# Model card DET_RE, verbatim.
DET_RE = re.compile(r"<\|det\|>([^<\s]+)(?:\s*\[[^\]]*\])?\s*<\|/det\|>(.*)", re.DOTALL)
# The bbox group the card's regex deliberately swallows, kept so `elements` can
# carry it instead of throwing it away.
DET_WITH_BBOX_RE = re.compile(r"<\|det\|>([^<\s]+)(\s*\[[^\]]*\])?\s*<\|/det\|>(.*)", re.DOTALL)

IMAGE_CATEGORY = "image"


def remove_det(raw: str) -> str:
    """``remove_det`` from the model card, verbatim in behaviour."""

    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for original in raw.splitlines():
        line = original.rstrip()
        if not line:
            continue
        match = DET_RE.match(line)
        if match:
            category, content = match.group(1).strip(), match.group(2).strip()
            if category == IMAGE_CATEGORY:
                continue
            if cur is not None:
                blocks.append(cur)
            cur = [content] if content else []
            continue
        if cur is None:
            cur = []
        cur.append(line)
    if cur is not None:
        blocks.append(cur)
    return "\n\n".join("\n".join(block) for block in blocks).strip()


def det_elements(raw: str) -> tuple[Mapping[str, Any], ...]:
    """Re-present every ``<|det|>`` marker the markdown drops. No inference, no parsing."""

    elements: list[Mapping[str, Any]] = []
    for original in raw.splitlines():
        line = original.rstrip()
        if not line:
            continue
        match = DET_WITH_BBOX_RE.match(line)
        if not match:
            continue
        bbox = match.group(2)
        elements.append(
            {
                "category": match.group(1).strip(),
                "det_raw": bbox.strip() if bbox else None,
                "dropped_from_markdown": match.group(1).strip() == IMAGE_CATEGORY,
            }
        )
    return tuple(elements)


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = []
    text = raw.raw_text

    if not text.strip():
        return CanonicalOutput(
            markdown="",
            elements=(),
            conversion_notes=("empty model output preserved as empty markdown",),
            lossy=False,
        )

    markdown = remove_det(text)
    elements = det_elements(text)
    lossy = False

    if elements:
        lossy = True
        image_markers = sum(1 for element in elements if element["dropped_from_markdown"])
        notes.append(
            f"remove_det stripped {len(elements)} <|det|> marker(s) from the markdown per the "
            "official OmniDocBench post-processing; category and bbox are kept in elements, "
            "their position in the markdown is not"
        )
        if image_markers:
            notes.append(
                f"{image_markers} <|det|>image<|/det|> block(s) were dropped entirely, and the "
                "official function does not flush the block it was building when it drops one, "
                "so the following lines join the preceding block"
            )
    if "\n\n" in text.strip():
        notes.append(
            "blank lines are removed before block assembly by the official function; "
            "paragraph breaks inside a single block are not preserved"
        )
        lossy = True

    for warning in raw.warnings:
        notes.append(f"adapter warning: {warning}")

    return CanonicalOutput(
        markdown=markdown,
        elements=elements,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )


__all__ = [
    "canonicalize",
    "det_elements",
    "remove_det",
]
