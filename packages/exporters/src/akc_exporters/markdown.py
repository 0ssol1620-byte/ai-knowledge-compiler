"""Portable/Obsidian Markdown compiler with authoritative source maps."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated

import yaml
from akc_cir import (
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    ContractModel,
    ExportProfile,
    Frontmatter,
    MarkdownRange,
    ReviewStatus,
    SourceMap,
    SourceMapEntry,
)
from akc_security import (
    ensure_portable_markdown_safe,
    safe_relative_path,
    sanitize_display_filename,
)
from pydantic import Field

from .filenames import portable_slug, stable_markdown_filename
from .tables import table_to_csv, table_to_gfm, table_to_html


class MarkdownExportOptions(ContractModel):
    profile: ExportProfile = ExportProfile.PORTABLE_STRUCTURED
    document_type: str = "other"
    semantic_type: str | None = None
    topics: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    semantic_evidence_block_ids: tuple[str, ...] = ()
    semantic_model_attestation: dict[str, str] = Field(default_factory=dict)
    language: str = "unknown"
    languages: tuple[str, ...] = ("unknown",)
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    review_status: ReviewStatus = ReviewStatus.AUTO_WITH_WARNINGS
    model_policy: str = "parse_balanced_v1"
    processed_at: datetime
    include_provenance_comments: bool = True
    include_ai_knowledge: bool = False
    wikilinks: bool = False
    quality_score: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    provenance_file: str | None = None
    quality_file: str | None = None
    figure_asset_paths: dict[str, str] = Field(default_factory=dict)


class MarkdownArtifact(ContractModel):
    path: str
    markdown: str
    source_map: SourceMap
    table_assets: dict[str, str] = Field(default_factory=dict)
    supplemental_assets: dict[str, str] = Field(default_factory=dict)


def _urn(kind: str, value: str) -> str:
    return value if value.startswith("urn:") else f"urn:akmp:{kind}:{value}"


def _page_range(document: CanonicalDocument) -> str:
    pages = sorted({ref.page_number1 for block in document.blocks for ref in block.source_refs})
    if not pages:
        return "unknown"
    ranges: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _frontmatter(document: CanonicalDocument, options: MarkdownExportOptions, path: str) -> str:
    source_map_path = options.provenance_file or (
        f"../source-map/{portable_slug(document.document_id)}.json"
    )
    quality_path = options.quality_file or (
        f"../quality/{portable_slug(document.document_id)}.json"
    )
    value = Frontmatter(
        id=_urn("doc", document.document_id),
        title=document.title,
        aliases=options.aliases,
        tags=options.tags,
        document_type=options.document_type,
        semantic_type=options.semantic_type,
        topics=options.topics,
        domains=options.domains,
        semantic_evidence_block_ids=options.semantic_evidence_block_ids,
        semantic_model_attestation=options.semantic_model_attestation,
        content_layer=(
            ContentLayer.EXTRACTED
            if options.profile == ExportProfile.PORTABLE_RAW
            else document.content_layer
        ),
        review_status=options.review_status,
        language=options.language,
        languages=options.languages,
        source_file=sanitize_display_filename(document.source_filename),
        source_sha256=document.source_sha256,
        source_pages=_page_range(document),
        source_document_id=_urn("source", document.document_id),
        created_at=document.created_at,
        processed_at=options.processed_at,
        model_policy=options.model_policy,
        provenance_file=source_map_path,
        quality_file=quality_path,
    )
    payload = value.model_dump(mode="json", by_alias=False, exclude_none=True)
    yaml_text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n"


def _visible_block(block: CanonicalBlock, options: MarkdownExportOptions) -> bool:
    if options.profile == ExportProfile.PORTABLE_RAW:
        return block.origin in {
            BlockOrigin.NATIVE_EXTRACTED,
            BlockOrigin.OCR_EXTRACTED,
            BlockOrigin.RULE_RECONSTRUCTED,
            BlockOrigin.USER_EDITED,
        }
    return not (
        block.origin in {BlockOrigin.AI_SUMMARIZED, BlockOrigin.AI_INFERRED}
        and not options.include_ai_knowledge
    )


def _render_heading(
    block: CanonicalBlock,
    text: str,
    heading_stack: list[tuple[int, int]],
) -> str:
    if block.type == BlockType.TITLE:
        source_level = 1
        value = text.lstrip("# ").strip()
    else:
        match = re.match(r"^(#{1,6})\s+(.+)$", text, flags=re.DOTALL)
        source_level = len(match.group(1)) if match else 1
        value = match.group(2).strip() if match else text

    while heading_stack and heading_stack[-1][0] >= source_level:
        heading_stack.pop()
    parent_output_level = heading_stack[-1][1] if heading_stack else 1
    output_level = min(6, parent_output_level + 1)
    heading_stack.append((source_level, output_level))
    return f"{'#' * output_level} {value}"


def _fenced_code(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _render_block(
    block: CanonicalBlock,
    table_assets: dict[str, str],
    supplemental_assets: dict[str, str],
    heading_stack: list[tuple[int, int]],
    figure_asset_paths: dict[str, str],
) -> str:
    if block.type == BlockType.TABLE and block.table is not None:
        asset_stem = portable_slug(block.table.id)
        csv_path = f"../assets/tables/{asset_stem}.csv"
        table_assets[csv_path] = table_to_csv(block.table)
        if block.table.is_simple_gfm:
            return f"{table_to_gfm(block.table)}\n\n[Download CSV]({csv_path})"
        asset_path = f"../assets/tables/{asset_stem}.html"
        table_assets[asset_path] = table_to_html(block.table)
        label = block.table.caption or "Complex table"
        return f"[{label} (HTML)]({asset_path}) · [Download CSV]({csv_path})"
    text = block.markdown or block.normalized_text or block.raw_text or ""
    text = text.strip()
    if block.type in {BlockType.TITLE, BlockType.HEADING}:
        return _render_heading(block, text, heading_stack)
    if block.type == BlockType.FORMULA and block.formula_latex:
        latex = block.formula_latex.strip()
        asset_path = f"../assets/formulas/{portable_slug(block.id)}.tex"
        supplemental_assets[asset_path] = f"{latex}\n"
        return f"$$\n{latex}\n$$\n\n[LaTeX source]({asset_path})"
    if block.type == BlockType.FIGURE:
        figure_asset_path = figure_asset_paths.get(block.id)
        if figure_asset_path is not None:
            alt_text = re.sub(r"[\[\]\r\n]+", " ", text).strip() or "Source figure"
            return f"![{alt_text}]({figure_asset_path})"
        return text or "_Figure asset unavailable: no verified source crop was retained._"
    if block.type == BlockType.CODE:
        return _fenced_code(text)
    if block.type == BlockType.QUOTE and not text.startswith(">"):
        return "\n".join(f"> {line}" for line in text.splitlines())
    return text


def export_markdown(
    document: CanonicalDocument,
    options: MarkdownExportOptions,
    *,
    output_path: str | None = None,
) -> MarkdownArtifact:
    if options.profile not in {
        ExportProfile.PORTABLE_RAW,
        ExportProfile.PORTABLE_STRUCTURED,
        ExportProfile.OBSIDIAN,
    }:
        raise ValueError("Markdown exporter requires a Markdown profile")
    path = safe_relative_path(
        output_path
        or f"10-Documents/{stable_markdown_filename(document.title, document.document_id)}"
    )
    prefix = _frontmatter(document, options, path)
    title = f"# {document.title.strip()}\n\n"
    parts = [prefix, title]
    cursor = len(prefix) + len(title)
    current_line = prefix.count("\n") + title.count("\n") + 1
    entries: list[SourceMapEntry] = []
    table_assets: dict[str, str] = {}
    supplemental_assets: dict[str, str] = {}
    heading_stack: list[tuple[int, int]] = []
    for block in document.ordered_blocks():
        if not _visible_block(block, options):
            continue
        rendered = _render_block(
            block,
            table_assets,
            supplemental_assets,
            heading_stack,
            options.figure_asset_paths,
        ).strip()
        if not rendered:
            continue
        if options.wikilinks and options.profile == ExportProfile.OBSIDIAN:
            rendered = re.sub(
                r"\[([^\]]+)]\(\.\./20-Concepts/([^)]+)\.md\)",
                r"[[20-Concepts/\2|\1]]",
                rendered,
            )
        comment = ""
        if options.include_provenance_comments:
            first_ref = block.source_refs[0]
            bbox = (
                ",".join(str(value) for value in first_ref.bbox1000.root)
                if first_ref.bbox1000
                else "none"
            )
            confidence = "unknown" if block.confidence is None else f"{block.confidence:.4f}"
            comment = (
                f"<!-- akmp:block id={block.id} page={first_ref.page_number1} "
                f"bbox={bbox} origin={block.origin.value} confidence={confidence} -->\n"
            )
        block_start = cursor + len(comment)
        start_line = current_line + comment.count("\n")
        block_end = block_start + len(rendered)
        end_line = start_line + rendered.count("\n")
        segment = f"{comment}{rendered}\n\n"
        parts.append(segment)
        cursor += len(segment)
        current_line += segment.count("\n")
        entries.append(
            SourceMapEntry(
                block_id=block.id,
                revision=block.revision,
                content_hash=block.content_hash,
                markdown_path=path,
                markdown_range=MarkdownRange(
                    start_line1=start_line,
                    end_line1=end_line,
                    start_codepoint0=block_start,
                    end_codepoint0=block_end,
                ),
                source_refs=block.source_refs,
                origin=block.origin,
                confidence=block.confidence,
            )
        )
    markdown = "".join(parts).rstrip() + "\n"
    ensure_portable_markdown_safe(markdown)
    return MarkdownArtifact(
        path=path,
        markdown=markdown,
        source_map=SourceMap(
            document_id=document.document_id,
            document_version_id=document.document_version_id,
            source_sha256=document.source_sha256,
            entries=tuple(entries),
        ),
        table_assets=dict(sorted(table_assets.items())),
        supplemental_assets=dict(sorted(supplemental_assets.items())),
    )


def source_map_json(source_map: SourceMap) -> str:
    return (
        json.dumps(
            source_map.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
