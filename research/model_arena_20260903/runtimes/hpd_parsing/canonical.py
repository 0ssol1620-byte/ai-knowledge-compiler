"""Canonicalize HPD-Parsing output.

HPD-Parsing does not emit Markdown. It emits a flat block stream:

    <BLOCK>title [12,30,900,80]<CHILD>Annual Report<BLOCK>image [10,90,900,400]

Each block carries a category, a bounding box and, for blocks that have text, a
``<CHILD>`` payload. Blocks such as ``image`` carry no ``<CHILD>``. The regex
below is the one published in the official tutorial, unmodified.

Conversion rules, all representation-only:

* block text is copied verbatim; nothing is rewritten, merged or inferred;
* a block with no ``<CHILD>`` contributes no Markdown, because there is no text
  to contribute - it still appears in ``elements`` with ``content: null``;
* only these categories become headings, and the map is fixed:
  ``doc_title``/``title`` -> ``#``, ``paragraph_title``/``sub_title`` -> ``##``;
* anything the block grammar could not account for (text before the first
  ``<BLOCK>``) is preserved verbatim and the output is flagged ``lossy``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from arena.worker.adapter_api import CanonicalOutput, RawOutput

MODEL_KEY = "hpd_parsing"

# Published verbatim in docs/version3.x/pipeline_usage/HPD-Parsing.en.md.
BLOCK_PATTERN = re.compile(
    r"<BLOCK>(\w+)\s*\[([^\]]*)\](?:<CHILD>)?(.*?)(?=<BLOCK>|\Z)", re.DOTALL
)

HEADING_LEVELS: Mapping[str, int] = {
    "doc_title": 1,
    "title": 1,
    "paragraph_title": 2,
    "sub_title": 2,
}


def normalize_markdown(text: str) -> str:
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


def parse_bbox(raw: str) -> list[int] | None:
    """Integer bbox, or None when the model did not emit four usable numbers."""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) != 4:
        return None
    values: list[int] = []
    for part in parts:
        try:
            values.append(int(float(part)))
        except ValueError:
            return None
    return values


def parse_blocks(text: str) -> list[dict[str, Any]]:
    """All layout blocks, in emission order, with text copied verbatim."""
    blocks: list[dict[str, Any]] = []
    for order, match in enumerate(BLOCK_PATTERN.finditer(text)):
        block_type, coords, content = match.group(1), match.group(2), match.group(3)
        blocks.append(
            {
                "reading_order": order,
                "type": block_type,
                "bbox": parse_bbox(coords),
                "bbox_raw": coords.strip(),
                "content": content.strip() or None,
            }
        )
    return blocks


def render_markdown(blocks: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for block in blocks:
        content = block["content"]
        if not isinstance(content, str) or not content:
            continue
        level = HEADING_LEVELS.get(str(block["type"]))
        chunks.append(f"{'#' * level} {content}" if level else content)
    return "\n\n".join(chunks)


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    notes: list[str] = [f"warning:{warning}" for warning in raw.warnings]
    if raw.output_format != "hpd_blocks":
        notes.append(f"unexpected_output_format:{raw.output_format}")

    text = raw.raw_text
    if not text.strip():
        notes.append("empty_raw_text")
        return CanonicalOutput(markdown="", elements=(), conversion_notes=tuple(notes), lossy=False)

    first = text.find("<BLOCK>")
    if first < 0:
        # No block grammar at all. Keep the model's bytes as a single unstructured
        # body rather than dropping them, and say so - never a silent fallback.
        notes.append("no_block_markers:kept_raw_text_as_single_body")
        return CanonicalOutput(
            markdown=normalize_markdown(text),
            elements=None,
            conversion_notes=tuple(notes),
            lossy=False,
        )

    preamble = text[:first].strip()
    blocks = parse_blocks(text)
    if not blocks:
        notes.append("block_markers_present_but_unparsable")
        return CanonicalOutput(
            markdown=normalize_markdown(text),
            elements=None,
            conversion_notes=tuple(notes),
            lossy=True,
        )

    body = render_markdown(blocks)
    lossy = False
    if preamble:
        # Text outside the grammar. It is preserved verbatim above the blocks and
        # the output is marked lossy because the structure could not hold it.
        body = f"{preamble}\n\n{body}" if body else preamble
        notes.append("text_before_first_block_preserved_verbatim")
        lossy = True

    empty_blocks = sum(1 for block in blocks if not block["content"])
    if empty_blocks:
        notes.append(f"blocks_without_child_text:{empty_blocks}")
    unparsed_bbox = sum(1 for block in blocks if block["bbox"] is None)
    if unparsed_bbox:
        notes.append(f"blocks_with_unparsable_bbox:{unparsed_bbox}")

    elements = tuple(dict(block) for block in blocks)
    return CanonicalOutput(
        markdown=normalize_markdown(body),
        elements=elements,
        conversion_notes=tuple(notes),
        lossy=lossy,
    )
