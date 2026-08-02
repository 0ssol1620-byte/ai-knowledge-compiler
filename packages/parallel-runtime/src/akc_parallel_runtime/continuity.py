"""Continuity-graph merge; parallel outputs are never blindly concatenated."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from threading import RLock

from .contracts import EventJournal
from .identity import canonical_sha256, stable_id
from .validation import EvidenceReceipt


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    OTHER = "other"


class MarginalRole(StrEnum):
    HEADER = "header"
    FOOTER = "footer"


class ContinuityEdgeKind(StrEnum):
    CONTINUES = "continues"
    BELONGS_TO = "belongs_to"
    CAPTION_OF = "caption_of"
    HEADER_OF = "header_of"
    FOOTNOTE_OF = "footnote_of"
    SAME_TABLE = "same_table"
    DUPLICATE_MARGINAL = "duplicate_marginal"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


@dataclass(frozen=True, slots=True)
class TableIdentity:
    normalized_header: tuple[str, ...]
    column_geometry: tuple[int, ...]
    title: str
    unit: str
    row_style: str = ""
    surrounding_text: str = ""

    def __post_init__(self) -> None:
        if not self.normalized_header or not self.column_geometry:
            raise ValueError("table identity requires header and column geometry")
        if len(self.normalized_header) != len(self.column_geometry):
            raise ValueError("table header and column geometry must have equal columns")
        if any(width <= 0 for width in self.column_geometry):
            raise ValueError("table column geometry must be positive")

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(
            {
                "header": tuple(_normalize_text(item) for item in self.normalized_header),
                "column_geometry": self.column_geometry,
                "title": _normalize_text(self.title),
                "unit": _normalize_text(self.unit),
                "row_style": _normalize_text(self.row_style),
                "surrounding_text": _normalize_text(self.surrounding_text),
            }
        )


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    block_id: str
    page_id: str
    page_index0: int
    order: int
    kind: BlockKind
    text: str
    source_refs: tuple[str, ...]
    heading_depth: int | None = None
    marginal_role: MarginalRole | None = None
    table_identity: TableIdentity | None = None
    table_row_count: int = 0

    def __post_init__(self) -> None:
        if not self.block_id or not self.page_id or self.page_index0 < 0 or self.order < 0:
            raise ValueError("block identity and non-negative position are required")
        if not self.text.strip() or not self.source_refs:
            raise ValueError("blocks require content and source references")
        if self.kind is BlockKind.HEADING:
            if self.heading_depth is None or not 1 <= self.heading_depth <= 6:
                raise ValueError("heading blocks require a depth between 1 and 6")
        elif self.heading_depth is not None:
            raise ValueError("only heading blocks can declare heading_depth")
        if self.kind is BlockKind.TABLE:
            if self.table_identity is None or self.table_row_count < 0:
                raise ValueError("table blocks require an identity and non-negative row count")
        elif self.table_identity is not None or self.table_row_count:
            raise ValueError("only table blocks can carry table metadata")

    @property
    def stable_fingerprint(self) -> str:
        return canonical_sha256(
            {
                "kind": self.kind,
                "text": _normalize_text(self.text),
                "heading_depth": self.heading_depth,
                "table": self.table_identity.fingerprint if self.table_identity else None,
            }
        )


@dataclass(frozen=True, slots=True)
class ShardOutput:
    shard_id: str
    primary_page_ids: tuple[str, ...]
    context_page_ids: tuple[str, ...]
    blocks: tuple[ParsedBlock, ...]

    def __post_init__(self) -> None:
        if not self.shard_id or not self.primary_page_ids:
            raise ValueError("shard output requires an id and primary pages")
        if set(self.primary_page_ids) & set(self.context_page_ids):
            raise ValueError("primary and context page sets must be disjoint")
        input_pages = set(self.primary_page_ids) | set(self.context_page_ids)
        if any(block.page_id not in input_pages for block in self.blocks):
            raise ValueError("shard output contains a block outside its input page set")


@dataclass(frozen=True, slots=True)
class ContinuityEdge:
    from_block_id: str
    to_block_id: str
    kind: ContinuityEdgeKind
    evidence: tuple[EvidenceReceipt, ...]

    def __post_init__(self) -> None:
        if self.from_block_id == self.to_block_id:
            raise ValueError("continuity edges cannot be self-referential")
        if not self.evidence:
            raise ValueError("continuity edges require evidence")


@dataclass(frozen=True, slots=True)
class MergedBlock:
    merged_block_id: str
    kind: BlockKind
    text: str
    page_ids: tuple[str, ...]
    page_index0: int
    order: int
    source_refs: tuple[str, ...]
    provenance_block_ids: tuple[str, ...]
    heading_depth: int | None = None
    table_identity: TableIdentity | None = None
    table_row_count: int = 0


@dataclass(frozen=True, slots=True)
class ContinuityMergeResult:
    merge_id: str
    accepted: bool
    markdown: str | None
    blocks: tuple[MergedBlock, ...]
    dropped_marginal_block_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    merge_sha256: str


class ContinuityMergeConflict(RuntimeError):
    pass


class ContinuityMerger:
    def __init__(self, *, events: EventJournal | None = None) -> None:
        self._events = events
        self._results: dict[str, tuple[str, ContinuityMergeResult]] = {}
        self._lock = RLock()

    @staticmethod
    def _owned_blocks(outputs: tuple[ShardOutput, ...]) -> tuple[ParsedBlock, ...]:
        ownership: dict[str, str] = {}
        for output in outputs:
            for page_id in output.primary_page_ids:
                if page_id in ownership:
                    raise ContinuityMergeConflict("a page has multiple primary owners")
                ownership[page_id] = output.shard_id
        owned: list[ParsedBlock] = []
        seen_ids: set[str] = set()
        for output in outputs:
            primary = set(output.primary_page_ids)
            for block in output.blocks:
                if block.page_id not in primary:
                    continue
                if block.block_id in seen_ids:
                    raise ContinuityMergeConflict("a primary block id appears more than once")
                seen_ids.add(block.block_id)
                owned.append(block)
        return tuple(
            sorted(owned, key=lambda block: (block.page_index0, block.order, block.block_id))
        )

    @staticmethod
    def _repeated_marginals(blocks: tuple[ParsedBlock, ...]) -> frozenset[str]:
        groups: dict[tuple[MarginalRole, str], list[ParsedBlock]] = {}
        for block in blocks:
            if block.marginal_role is not None:
                groups.setdefault((block.marginal_role, block.stable_fingerprint), []).append(block)
        return frozenset(
            block.block_id
            for group in groups.values()
            if len({block.page_id for block in group}) >= 2
            for block in group
        )

    @staticmethod
    def _join_chains(
        blocks: dict[str, ParsedBlock],
        edges: tuple[ContinuityEdge, ...],
    ) -> tuple[tuple[str, ...], ...]:
        join_edges = tuple(
            edge
            for edge in edges
            if edge.kind in {ContinuityEdgeKind.CONTINUES, ContinuityEdgeKind.SAME_TABLE}
        )
        outgoing: dict[str, str] = {}
        incoming: dict[str, str] = {}
        for edge in join_edges:
            if edge.from_block_id not in blocks or edge.to_block_id not in blocks:
                raise ContinuityMergeConflict("continuity edge references a missing primary block")
            if edge.from_block_id in outgoing or edge.to_block_id in incoming:
                raise ContinuityMergeConflict("continuity graph has an ambiguous join")
            source = blocks[edge.from_block_id]
            target = blocks[edge.to_block_id]
            if target.page_index0 < source.page_index0:
                raise ContinuityMergeConflict("continuity edge points backwards")
            if edge.kind is ContinuityEdgeKind.SAME_TABLE:
                if source.kind is not BlockKind.TABLE or target.kind is not BlockKind.TABLE:
                    raise ContinuityMergeConflict("same_table edge requires two table blocks")
                source_table = source.table_identity
                target_table = target.table_identity
                if source_table is None or target_table is None:
                    raise ContinuityMergeConflict("table identity metadata is missing")
                if source_table.fingerprint != target_table.fingerprint:
                    raise ContinuityMergeConflict("cross-page table identity mismatch")
                if target.page_index0 != source.page_index0 + 1:
                    raise ContinuityMergeConflict(
                        "cross-page table continuation must be page-adjacent"
                    )
            elif source.kind != target.kind or source.kind not in {
                BlockKind.PARAGRAPH,
                BlockKind.LIST_ITEM,
            }:
                raise ContinuityMergeConflict(
                    "continues edge requires compatible paragraph or list blocks"
                )
            outgoing[edge.from_block_id] = edge.to_block_id
            incoming[edge.to_block_id] = edge.from_block_id
        chains: list[tuple[str, ...]] = []
        visited: set[str] = set()
        for block_id in sorted(blocks):
            if block_id in incoming:
                continue
            chain: list[str] = []
            current: str | None = block_id
            while current is not None:
                if current in visited:
                    raise ContinuityMergeConflict("continuity graph contains a cycle")
                visited.add(current)
                chain.append(current)
                current = outgoing.get(current)
            chains.append(tuple(chain))
        if visited != set(blocks):
            raise ContinuityMergeConflict("continuity graph contains an unrooted cycle")
        return tuple(chains)

    @staticmethod
    def _validate_relationship_edges(
        blocks: dict[str, ParsedBlock],
        edges: tuple[ContinuityEdge, ...],
        dropped: frozenset[str],
    ) -> None:
        for edge in edges:
            if edge.kind is ContinuityEdgeKind.DUPLICATE_MARGINAL:
                if edge.from_block_id not in dropped or edge.to_block_id not in dropped:
                    raise ContinuityMergeConflict(
                        "duplicate_marginal edge must reference detected repeated marginals"
                    )
                continue
            if edge.from_block_id not in blocks or edge.to_block_id not in blocks:
                raise ContinuityMergeConflict(
                    "continuity relationship references a missing primary block"
                )
            source = blocks[edge.from_block_id]
            target = blocks[edge.to_block_id]
            if edge.kind is ContinuityEdgeKind.CAPTION_OF and not (
                source.kind is BlockKind.CAPTION and target.kind is BlockKind.FIGURE
            ):
                raise ContinuityMergeConflict("caption_of requires caption to figure")
            if (
                edge.kind is ContinuityEdgeKind.FOOTNOTE_OF
                and source.kind is not BlockKind.FOOTNOTE
            ):
                raise ContinuityMergeConflict("footnote_of requires a footnote source")
            if edge.kind is ContinuityEdgeKind.HEADER_OF and source.kind is not BlockKind.HEADING:
                raise ContinuityMergeConflict("header_of requires a heading source")

    @staticmethod
    def _order_relationships(
        merged: tuple[MergedBlock, ...], edges: tuple[ContinuityEdge, ...]
    ) -> tuple[MergedBlock, ...]:
        by_original = {
            original_id: block.merged_block_id
            for block in merged
            for original_id in block.provenance_block_ids
        }
        by_id = {block.merged_block_id: block for block in merged}
        base_order = {block.merged_block_id: index for index, block in enumerate(merged)}
        before_after: set[tuple[str, str]] = set()
        for edge in edges:
            source_id = by_original.get(edge.from_block_id)
            target_id = by_original.get(edge.to_block_id)
            if source_id is None or target_id is None or source_id == target_id:
                continue
            if edge.kind in {
                ContinuityEdgeKind.CAPTION_OF,
                ContinuityEdgeKind.FOOTNOTE_OF,
                ContinuityEdgeKind.BELONGS_TO,
            }:
                before_after.add((target_id, source_id))
            elif edge.kind is ContinuityEdgeKind.HEADER_OF:
                before_after.add((source_id, target_id))
        incoming = {block_id: 0 for block_id in by_id}
        outgoing: dict[str, set[str]] = {block_id: set() for block_id in by_id}
        for before, after in before_after:
            if after not in outgoing[before]:
                outgoing[before].add(after)
                incoming[after] += 1
        ready = sorted(
            (block_id for block_id, count in incoming.items() if count == 0),
            key=lambda block_id: (base_order[block_id], block_id),
        )
        ordered: list[MergedBlock] = []
        while ready:
            block_id = ready.pop(0)
            ordered.append(by_id[block_id])
            for successor in sorted(
                outgoing[block_id], key=lambda item: (base_order[item], item)
            ):
                incoming[successor] -= 1
                if incoming[successor] == 0:
                    ready.append(successor)
                    ready.sort(key=lambda item: (base_order[item], item))
        if len(ordered) != len(merged):
            raise ContinuityMergeConflict("continuity relationship graph contains a cycle")
        return tuple(ordered)

    @staticmethod
    def _merge_chain(chain: tuple[str, ...], blocks: dict[str, ParsedBlock]) -> MergedBlock:
        members = tuple(blocks[block_id] for block_id in chain)
        first = members[0]
        if first.kind is BlockKind.PARAGRAPH or first.kind is BlockKind.LIST_ITEM:
            text = " ".join(block.text.strip() for block in members)
        elif first.kind is BlockKind.TABLE:
            text = "\n".join(block.text.rstrip() for block in members)
        else:
            text = first.text
        provenance = tuple(block.block_id for block in members)
        page_ids = tuple(dict.fromkeys(block.page_id for block in members))
        source_refs = tuple(dict.fromkeys(ref for block in members for ref in block.source_refs))
        return MergedBlock(
            merged_block_id=stable_id("block", provenance, canonical_sha256(text)),
            kind=first.kind,
            text=text,
            page_ids=page_ids,
            page_index0=first.page_index0,
            order=first.order,
            source_refs=source_refs,
            provenance_block_ids=provenance,
            heading_depth=first.heading_depth,
            table_identity=first.table_identity,
            table_row_count=sum(block.table_row_count for block in members),
        )

    @staticmethod
    def _markdown(blocks: tuple[MergedBlock, ...]) -> str:
        parts: list[str] = []
        for block in blocks:
            if block.kind is BlockKind.HEADING:
                parts.append(f"{'#' * (block.heading_depth or 1)} {block.text.strip()}")
            elif block.kind is BlockKind.LIST_ITEM:
                parts.append(f"- {block.text.strip()}")
            elif block.kind is BlockKind.CAPTION:
                parts.append(f"*{block.text.strip()}*")
            elif block.kind is BlockKind.FOOTNOTE:
                parts.append(f"[^source-{block.merged_block_id[:8]}]: {block.text.strip()}")
            else:
                parts.append(block.text.strip())
        return "\n\n".join(parts).strip() + "\n"

    @staticmethod
    def _validate(
        *,
        owned_blocks: tuple[ParsedBlock, ...],
        merged_blocks: tuple[MergedBlock, ...],
        dropped: frozenset[str],
        expected_page_ids: tuple[str, ...],
        markdown: str,
    ) -> tuple[str, ...]:
        reasons: set[str] = set()
        provenance = [
            block_id for merged in merged_blocks for block_id in merged.provenance_block_ids
        ]
        expected_ids = {block.block_id for block in owned_blocks} - set(dropped)
        if set(provenance) != expected_ids or len(provenance) != len(set(provenance)):
            reasons.add("block_count_conservation_failed")
        covered_pages = {page_id for merged in merged_blocks for page_id in merged.page_ids}
        covered_pages.update(
            block.page_id for block in owned_blocks if block.block_id in dropped
        )
        if set(expected_page_ids) != covered_pages:
            reasons.add("page_coverage_failed")
        if any(not block.source_refs for block in merged_blocks):
            reasons.add("source_reference_missing")
        positions = [(block.page_index0, block.order) for block in merged_blocks]
        if len(positions) != len(set(positions)):
            reasons.add("sequence_invalid")
        heading_depths = [
            block.heading_depth for block in merged_blocks if block.kind is BlockKind.HEADING
        ]
        if any(
            current is not None and previous is not None and current > previous + 1
            for previous, current in pairwise(heading_depths)
        ):
            reasons.add("heading_depth_jump")
        input_rows = sum(
            block.table_row_count
            for block in owned_blocks
            if block.block_id not in dropped
        )
        output_rows = sum(block.table_row_count for block in merged_blocks)
        if input_rows != output_rows:
            reasons.add("table_row_conservation_failed")
        if "\x00" in markdown or markdown.count("```") % 2:
            reasons.add("markdown_invalid")
        return tuple(sorted(reasons))

    def merge(
        self,
        *,
        document_version_id: str,
        outputs: tuple[ShardOutput, ...],
        edges: tuple[ContinuityEdge, ...],
        expected_page_ids: tuple[str, ...],
        occurred_at: datetime,
        idempotency_key: str,
    ) -> ContinuityMergeResult:
        input_digest = canonical_sha256(
            {
                "document_version_id": document_version_id,
                "outputs": outputs,
                "edges": edges,
                "expected_page_ids": expected_page_ids,
            }
        )
        with self._lock:
            existing = self._results.get(idempotency_key)
            if existing is not None:
                existing_digest, result = existing
                if existing_digest != input_digest:
                    raise ContinuityMergeConflict(
                        "merge idempotency key reused with different merge input"
                    )
                return result
            if self._events is not None:
                self._events.append(
                    event_type="continuity.merge.started.v1",
                    aggregate_id=document_version_id,
                    payload={"input_sha256": input_digest, "shards": len(outputs)},
                    occurred_at=occurred_at,
                    idempotency_key=f"merge-started:{idempotency_key}",
                )
            owned = self._owned_blocks(outputs)
            actual_owned_pages = tuple(
                dict.fromkeys(page_id for output in outputs for page_id in output.primary_page_ids)
            )
            if set(actual_owned_pages) != set(expected_page_ids) or len(actual_owned_pages) != len(
                expected_page_ids
            ):
                raise ContinuityMergeConflict(
                    "shard ownership does not cover expected pages exactly"
                )
            dropped = self._repeated_marginals(owned)
            active = {block.block_id: block for block in owned if block.block_id not in dropped}
            self._validate_relationship_edges(active, edges, dropped)
            active_edges = tuple(
                edge
                for edge in edges
                if edge.from_block_id in active and edge.to_block_id in active
            )
            chains = self._join_chains(active, active_edges)
            merged_in_source_order = tuple(
                sorted(
                    (self._merge_chain(chain, active) for chain in chains),
                    key=lambda block: (block.page_index0, block.order, block.merged_block_id),
                )
            )
            merged = self._order_relationships(merged_in_source_order, active_edges)
            markdown = self._markdown(merged)
            reasons = self._validate(
                owned_blocks=owned,
                merged_blocks=merged,
                dropped=dropped,
                expected_page_ids=expected_page_ids,
                markdown=markdown,
            )
            accepted = not reasons
            payload = {
                "input_sha256": input_digest,
                "accepted": accepted,
                "blocks": merged,
                "dropped": tuple(sorted(dropped)),
                "reasons": reasons,
                "markdown_sha256": canonical_sha256(markdown),
            }
            digest = canonical_sha256(payload)
            result = ContinuityMergeResult(
                merge_id=stable_id("merge", document_version_id, digest),
                accepted=accepted,
                markdown=markdown if accepted else None,
                blocks=merged,
                dropped_marginal_block_ids=tuple(sorted(dropped)),
                reason_codes=reasons,
                merge_sha256=digest,
            )
            self._results[idempotency_key] = (input_digest, result)
            if self._events is not None:
                self._events.append(
                    event_type="continuity.merge.completed.v1",
                    aggregate_id=document_version_id,
                    payload={
                        "merge_sha256": digest,
                        "accepted": accepted,
                        "reason_codes": reasons,
                    },
                    occurred_at=occurred_at,
                    idempotency_key=f"merge-completed:{idempotency_key}",
                )
            return result


__all__ = [
    "BlockKind",
    "ContinuityEdge",
    "ContinuityEdgeKind",
    "ContinuityMergeConflict",
    "ContinuityMergeResult",
    "ContinuityMerger",
    "MarginalRole",
    "MergedBlock",
    "ParsedBlock",
    "ShardOutput",
    "TableIdentity",
]
