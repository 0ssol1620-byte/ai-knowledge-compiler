"""Adaptive semantic chunking with pluggable tokenizer accounting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from akc_cir import (
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    RagChunk,
    SourceRef,
    sha256_digest,
)

_TOKENISH = re.compile(r"[A-Za-z0-9_]+|[가-힣]|[\u3400-\u9fff]|[^\w\s]", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?。\uff01\uff1f])\s+|\n{2,}")


class Tokenizer(Protocol):
    @property
    def name(self) -> str: ...

    def count(self, text: str) -> int: ...


class UnicodeEstimateTokenizer:
    name = "akmp-unicode-estimator-v1"

    def count(self, text: str) -> int:
        return max(1, len(_TOKENISH.findall(text)))


@dataclass(frozen=True)
class _Unit:
    text: str
    blocks: tuple[CanonicalBlock, ...]
    heading_path: tuple[str, ...]
    content_type: str
    standalone: bool = False


def _block_text(block: CanonicalBlock) -> str:
    if block.type == BlockType.TABLE and block.table:
        return "\n".join(_table_row_text(block, row) for row in range(block.table.row_count))
    if block.type == BlockType.FORMULA and block.formula_latex:
        return f"$$\n{block.formula_latex.strip()}\n$$"
    return (
        block.markdown or block.normalized_text or block.raw_text or block.sanitized_html or ""
    ).strip()


def _table_row_text(block: CanonicalBlock, row_index: int) -> str:
    if block.table is None:
        return ""
    values = ["" for _ in range(block.table.column_count)]
    for cell in sorted(
        block.table.cells,
        key=lambda item: (item.row_index0, item.column_index0, item.id),
    ):
        if cell.row_index0 == row_index:
            values[cell.column_index0] = cell.normalized_text or cell.raw_text
    escaped = [
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        for value in values
    ]
    return "\t".join(escaped)


def _heading(block: CanonicalBlock, text: str) -> tuple[int, str] | None:
    if block.type == BlockType.TITLE:
        return 1, text.lstrip("# ").strip()
    if block.type != BlockType.HEADING:
        return None
    match = re.match(r"^(#{1,6})\s+(.+)$", text, flags=re.DOTALL)
    if match:
        return len(match.group(1)), match.group(2).strip()
    return 1, text


def _update_heading_stack(
    stack: list[tuple[int, str]],
    source_level: int,
    text: str,
) -> tuple[str, ...]:
    while stack and stack[-1][0] >= source_level:
        stack.pop()
    stack.append((source_level, text))
    return tuple(value for _, value in stack)


def _table_units(
    block: CanonicalBlock,
    heading_path: tuple[str, ...],
    tokenizer: Tokenizer,
    max_tokens: int,
) -> list[_Unit]:
    table = block.table
    if table is None:
        return []
    all_rows = [_table_row_text(block, row) for row in range(table.row_count)]
    header_count = table.header_row_count
    headers = all_rows[:header_count]
    body = all_rows[header_count:]

    # A row span crossing a chunk boundary cannot be represented without changing
    # table semantics, so such tables remain one explicit atomic unit.
    if any(cell.row_span > 1 for cell in table.cells):
        text = "\n".join(all_rows).strip()
        oversized = tokenizer.count(text) > max_tokens
        return [
            _Unit(
                text=text,
                blocks=(block,),
                heading_path=heading_path,
                content_type="table_oversized" if oversized else BlockType.TABLE.value,
                standalone=True,
            )
        ]

    if not body:
        text = "\n".join(headers).strip()
        oversized = tokenizer.count(text) > max_tokens
        return [
            _Unit(
                text=text,
                blocks=(block,),
                heading_path=heading_path,
                content_type="table_oversized" if oversized else BlockType.TABLE.value,
                standalone=True,
            )
        ]

    result: list[_Unit] = []
    current: list[str] = []
    for row in body:
        candidate_rows = [*headers, *current, row]
        candidate = "\n".join(candidate_rows).strip()
        if current and tokenizer.count(candidate) > max_tokens:
            text = "\n".join([*headers, *current]).strip()
            oversized = tokenizer.count(text) > max_tokens
            result.append(
                _Unit(
                    text=text,
                    blocks=(block,),
                    heading_path=heading_path,
                    content_type=("table_oversized" if oversized else BlockType.TABLE.value),
                    standalone=True,
                )
            )
            current = [row]
        else:
            current.append(row)
    if current:
        text = "\n".join([*headers, *current]).strip()
        oversized = tokenizer.count(text) > max_tokens
        result.append(
            _Unit(
                text=text,
                blocks=(block,),
                heading_path=heading_path,
                content_type="table_oversized" if oversized else BlockType.TABLE.value,
                standalone=True,
            )
        )
    return result


def _hard_split(text: str, tokenizer: Tokenizer, max_tokens: int) -> list[str]:
    """Split an overlong sentence without dropping or inventing content."""
    remaining = text.strip()
    result: list[str] = []
    while remaining and tokenizer.count(remaining) > max_tokens:
        low, high = 1, len(remaining)
        while low < high:
            midpoint = (low + high + 1) // 2
            if tokenizer.count(remaining[:midpoint]) <= max_tokens:
                low = midpoint
            else:
                high = midpoint - 1
        cut = max(1, low)
        whitespace = max(
            remaining.rfind(" ", 0, cut),
            remaining.rfind("\n", 0, cut),
        )
        if whitespace >= cut // 2:
            cut = whitespace
        piece = remaining[:cut].strip()
        if not piece:
            piece = remaining[:low]
            cut = low
        result.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        result.append(remaining)
    return result


def _units(document: CanonicalDocument, tokenizer: Tokenizer, max_tokens: int) -> list[_Unit]:
    result: list[_Unit] = []
    heading_stack: list[tuple[int, str]] = []
    heading_path: tuple[str, ...] = ()
    ordered = list(document.ordered_blocks())
    index = 0
    while index < len(ordered):
        block = ordered[index]
        text = _block_text(block)
        heading = _heading(block, text)
        if heading is not None and heading[1]:
            heading_path = _update_heading_stack(heading_stack, *heading)
        if not text:
            index += 1
            continue
        if block.type == BlockType.TABLE:
            result.extend(_table_units(block, heading_path, tokenizer, max_tokens))
            index += 1
            continue
        blocks: tuple[CanonicalBlock, ...] = (block,)
        if block.type == BlockType.FIGURE and index + 1 < len(ordered):
            candidate = ordered[index + 1]
            if candidate.type == BlockType.CAPTION:
                caption = _block_text(candidate)
                if caption:
                    text = f"{text}\n\n{caption}"
                    blocks = (block, candidate)
                    index += 1
        if block.type in {BlockType.FIGURE, BlockType.FORMULA}:
            oversized = tokenizer.count(text) > max_tokens
            result.append(
                _Unit(
                    text=text,
                    blocks=blocks,
                    heading_path=heading_path,
                    content_type=(
                        f"{block.type.value}_oversized" if oversized else block.type.value
                    ),
                    standalone=True,
                )
            )
            index += 1
            continue
        if tokenizer.count(text) > max_tokens and block.type not in {
            BlockType.FIGURE,
            BlockType.FORMULA,
        }:
            sentences = [
                piece
                for value in _SENTENCE.split(text)
                if value.strip()
                for piece in _hard_split(value, tokenizer, max_tokens)
            ]
            current: list[str] = []
            for sentence in sentences:
                candidate_text = " ".join([*current, sentence])
                if current and tokenizer.count(candidate_text) > max_tokens:
                    result.append(
                        _Unit(
                            text=" ".join(current),
                            blocks=blocks,
                            heading_path=heading_path,
                            content_type=block.type.value,
                        )
                    )
                    current = [sentence]
                else:
                    current.append(sentence)
            if current:
                result.append(
                    _Unit(
                        text=" ".join(current),
                        blocks=blocks,
                        heading_path=heading_path,
                        content_type=block.type.value,
                    )
                )
        else:
            result.append(
                _Unit(
                    text=text,
                    blocks=blocks,
                    heading_path=heading_path,
                    content_type=block.type.value,
                )
            )
        index += 1
    return result


def _dedupe_refs(blocks: tuple[CanonicalBlock, ...]) -> tuple[SourceRef, ...]:
    seen: set[tuple[object, ...]] = set()
    result: list[SourceRef] = []
    for block in blocks:
        for ref in block.source_refs:
            identity = (
                ref.document_version_id,
                ref.page_index0,
                ref.bbox1000.root if ref.bbox1000 else None,
                ref.time_start_ms,
                ref.time_end_ms,
            )
            if identity not in seen:
                seen.add(identity)
                result.append(ref)
    return tuple(result)


_ORIGIN_RANK = {
    BlockOrigin.NATIVE_EXTRACTED: 0,
    BlockOrigin.OCR_EXTRACTED: 1,
    BlockOrigin.RULE_RECONSTRUCTED: 2,
    BlockOrigin.AI_RECONSTRUCTED: 3,
    BlockOrigin.AI_SUMMARIZED: 4,
    BlockOrigin.AI_INFERRED: 5,
    BlockOrigin.USER_EDITED: 6,
}
_LAYER_RANK = {
    ContentLayer.SOURCE: 0,
    ContentLayer.EXTRACTED: 1,
    ContentLayer.STRUCTURED: 2,
    ContentLayer.KNOWLEDGE: 3,
    ContentLayer.INDEX: 4,
}


def adaptive_chunks(
    document: CanonicalDocument,
    *,
    language: str,
    tokenizer: Tokenizer | None = None,
    target_tokens: int = 700,
    max_tokens: int = 1200,
    overlap_ratio: float = 0.10,
) -> tuple[RagChunk, ...]:
    if not 500 <= target_tokens <= max_tokens:
        raise ValueError("targetTokens must be at least 500 and not exceed maxTokens")
    if not 0.08 <= overlap_ratio <= 0.12:
        raise ValueError("overlapRatio must be within the AKMP 8-12% range")
    tokenizer = tokenizer or UnicodeEstimateTokenizer()
    units = _units(document, tokenizer, max_tokens)
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = tokenizer.count(unit.text)
        if unit.standalone:
            if current:
                groups.append(current)
                current = []
                current_tokens = 0
            groups.append([unit])
            continue
        if current and current_tokens + unit_tokens > target_tokens:
            groups.append(current)
            overlap_target = max(1, int(target_tokens * overlap_ratio))
            overlap: list[_Unit] = []
            overlap_tokens = 0
            for previous in reversed(current):
                if previous.content_type.startswith(BlockType.TABLE.value):
                    continue
                previous_tokens = tokenizer.count(previous.text)
                if (
                    previous_tokens > overlap_target * 2
                    or overlap_tokens + previous_tokens + unit_tokens > max_tokens
                ):
                    continue
                overlap.insert(0, previous)
                overlap_tokens += previous_tokens
                if overlap_tokens >= overlap_target:
                    break
            current = overlap
            current_tokens = overlap_tokens
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        groups.append(current)

    drafts: list[dict[str, object]] = []
    for index, group in enumerate(groups):
        text = "\n\n".join(unit.text for unit in group).strip()
        blocks = tuple(block for unit in group for block in unit.blocks)
        chunk_digest = sha256_digest(
            f"{document.document_id}\0{document.document_version_id}\0{index}\0{text}"
        )
        chunk_id = f"urn:akmp:chunk:{chunk_digest[7:31]}"
        origins = [block.origin for block in blocks]
        layers = [block.content_layer for block in blocks]
        confidences = [block.confidence for block in blocks if block.confidence is not None]
        content_types = {unit.content_type for unit in group}
        heading_path = next(
            (unit.heading_path for unit in reversed(group) if unit.heading_path),
            (),
        )
        drafts.append(
            {
                "chunk_id": chunk_id,
                "title": heading_path[-1] if heading_path else document.title,
                "heading_path": heading_path,
                "content": text,
                "content_type": next(iter(content_types)) if len(content_types) == 1 else "mixed",
                "token_count": tokenizer.count(text),
                "source_refs": _dedupe_refs(blocks),
                "origin": max(origins, key=_ORIGIN_RANK.__getitem__),
                "content_layer": max(layers, key=_LAYER_RANK.__getitem__),
                "quality": min(confidences) if confidences else None,
                "content_hash": sha256_digest(text),
            }
        )
    chunks: list[RagChunk] = []
    for index, draft in enumerate(drafts):
        chunks.append(
            RagChunk(
                chunk_id=draft["chunk_id"],
                document_id=document.document_id,
                document_version=document.document_version_id,
                title=draft["title"],
                heading_path=draft["heading_path"],
                content=draft["content"],
                content_type=draft["content_type"],
                language=language,
                token_count=draft["token_count"],
                tokenizer=tokenizer.name,
                source_refs=draft["source_refs"],
                origin=draft["origin"],
                content_layer=draft["content_layer"],
                quality=draft["quality"],
                previous_chunk_id=drafts[index - 1]["chunk_id"] if index else None,
                next_chunk_id=drafts[index + 1]["chunk_id"] if index + 1 < len(drafts) else None,
                content_hash=draft["content_hash"],
            )
        )
    return tuple(chunks)
