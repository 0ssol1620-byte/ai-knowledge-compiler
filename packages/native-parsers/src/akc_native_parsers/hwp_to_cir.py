"""Map an `HwpAdapterResult` onto CIR through `CirBuilder`.

Nothing is invented: a table with a missing cell position or overlapping spans is
held, an unresolved region becomes a held block carrying its anchor, and a block
is only listed as accepted when the engine marked it `verified` and nothing else
holds it. Native, unverified blocks (everything a fixture engine produces) are
never accepted here.
"""

from __future__ import annotations

from akc_cir import BlockType, CanonicalBlock, CanonicalDocument

from .hwp_contract import HwpAdapterResult, HwpBlock, UnresolvedRegion
from .models import (
    CirBuilder,
    ParseContext,
    ParserLimits,
    SourceLocation,
    StructuredParseError,
    TableCellSpec,
)

# ponytail: WO-D07-2 owns the shared constant; inline until that lane merges.
LOCATOR_PAGE_SEMANTICS = "container_ordinal"

_KIND_TO_TYPE = {
    "paragraph": BlockType.PARAGRAPH,
    "heading": BlockType.HEADING,
    "table": BlockType.TABLE,
    "figure": BlockType.FIGURE,
    "footnote": BlockType.FOOTNOTE,
    "header": BlockType.HEADER,
    "footer": BlockType.FOOTER,
    # No LaTeX is known for an HWP equation, so it is not a FORMULA block.
    "equation": BlockType.UNKNOWN,
    "unknown": BlockType.UNKNOWN,
}


def _location(ref: str) -> SourceLocation:
    # page_index0=0 is the schema's container ordinal, not a page (see LOCATOR_PAGE_SEMANTICS).
    return SourceLocation(page_index0=0, native_object_id=f"hwp/{ref}")


def _grid_shape(block: HwpBlock, limits: ParserLimits) -> tuple[int, int, bool, bool]:
    """Return (rows, cols, complete, overlapping) without enumerating hostile spans."""

    cells = block.table_grid or ()
    rows = max((c.row + c.row_span for c in cells), default=0)
    cols = max((c.col + c.col_span for c in cells), default=0)
    if rows > limits.max_table_rows:
        raise StructuredParseError("TABLE_ROW_LIMIT")
    if cols > limits.max_table_columns:
        raise StructuredParseError("TABLE_COLUMN_LIMIT")
    if rows * cols > limits.max_table_cells:
        raise StructuredParseError("TABLE_CELL_LIMIT")
    occupied: set[tuple[int, int]] = set()
    for c in cells:
        for r in range(c.row, c.row + c.row_span):
            for k in range(c.col, c.col + c.col_span):
                if (r, k) in occupied:
                    return rows, cols, False, True
                occupied.add((r, k))
    return rows, cols, rows > 0 and len(occupied) == rows * cols, False


def _add_table(builder: CirBuilder, block: HwpBlock, flags: list[str]) -> CanonicalBlock:
    cells = block.table_grid or ()
    rows, cols, complete, overlapping = _grid_shape(block, builder.limits)
    loc = _location(block.original_ref)
    if not complete:
        flags.append("held_incomplete_grid")
    if not cells or overlapping:
        # Cannot be a CanonicalTable without guessing which cell wins; keep the text, hold it.
        return builder.add_block(
            block_type=BlockType.UNKNOWN,
            location=loc,
            raw_text="\n".join(c.text for c in cells),
            quality_flags=tuple(flags),
        )
    specs = tuple(
        TableCellSpec(
            row_index0=c.row,
            column_index0=c.col,
            raw_text=c.text,
            row_span=c.row_span,
            column_span=c.col_span,
            location=_location(f"{block.original_ref}/r/{c.row:06d}/c/{c.col:06d}"),
        )
        for c in cells
    )
    return builder.add_table(
        location=loc,
        row_count=rows,
        column_count=cols,
        cells=specs,
        quality_flags=tuple(flags),
    )


def _add_region(builder: CirBuilder, region: UnresolvedRegion) -> CanonicalBlock:
    flags = ["held_unresolved_region", f"hwp_region_{region.reason}"]
    if region.critical:
        flags.append("hwp_region_critical")
    return builder.add_block(
        block_type=BlockType.FIGURE if region.reason == "embedded_image" else BlockType.UNKNOWN,
        location=_location(f"unresolved/{region.anchor}"),
        raw_text="",
        quality_flags=tuple(flags),
    )


def hwp_result_to_cir(
    result: HwpAdapterResult,
    context: ParseContext,
    *,
    source_filename: str | None = None,
    limits: ParserLimits | None = None,
) -> CanonicalDocument:
    fmt = result.manifest.detected_format
    builder = CirBuilder(
        context=context,
        source_filename=source_filename or f"source.{fmt}",
        source_sha256=f"sha256:{result.manifest.source_sha256}",
        document_type=fmt,
        limits=limits or ParserLimits(),
    )
    held_ids: list[str] = []
    accepted_ids: list[str] = []
    held_regions: list[dict[str, object]] = []
    seen: set[str] = set()
    for src in result.blocks:
        if src.original_ref in seen:
            raise StructuredParseError("PARSER_RESULT_INVALID")
        seen.add(src.original_ref)
        flags = [f"hwp_{src.verification_state}"]
        if src.kind == "equation":
            flags.append("hwp_equation_text")
        if src.kind == "table":
            built = _add_table(builder, src, flags)
        else:
            built = builder.add_block(
                block_type=_KIND_TO_TYPE[src.kind],
                location=_location(src.original_ref),
                raw_text=src.text,
                quality_flags=tuple(flags),
            )
        if src.confidence is not None:
            built = built.model_copy(update={"confidence": src.confidence})
            builder.blocks[-1] = built
        if (
            src.verification_state == "verified"
            and "held_incomplete_grid" not in built.quality_flags
        ):
            accepted_ids.append(built.id)
        else:
            held_ids.append(built.id)
    for region in result.unresolved_regions:
        built = _add_region(builder, region)
        held_ids.append(built.id)
        held_regions.append(
            {"anchor": region.anchor, "reason": region.reason, "critical": region.critical}
        )
    builder.metadata["locatorPageSemantics"] = LOCATOR_PAGE_SEMANTICS
    builder.metadata["hwp"] = {
        "engineId": result.engine_id,
        "engineVersion": result.engine_version,
        "resultSha256": result.artifact_hashes["result_sha256"],
        "acceptedBlockIds": accepted_ids,
        "heldBlockIds": held_ids,
        "heldRegions": held_regions,
    }
    return builder.build(title="")
