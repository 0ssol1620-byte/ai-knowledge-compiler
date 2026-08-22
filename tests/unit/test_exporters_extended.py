from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from akc_cir import (
    AssertionStatus,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalTable,
    Claim,
    ContentLayer,
    ExportProfile,
    KnowledgeBundle,
    KnowledgeNote,
    NoteType,
    RelationAssertion,
    sha256_digest,
)
from akc_exporters import (
    AKMP_CONTEXT,
    KNOWLEDGE_NOTE_SHACL,
    MarkdownExportOptions,
    adaptive_chunks,
    chunks_jsonl,
    compile_vault,
    context_jsonld,
    deterministic_zip,
    documents_jsonl,
    export_markdown,
    knowledge_jsonld,
    portable_slug,
    source_map_json,
    table_to_csv,
    table_to_gfm,
    table_to_html,
    validate_internal_links,
)


def simple_table(source_ref) -> CanonicalTable:
    cells = tuple(
        CanonicalCell(
            id=f"cell_{row}_{column}",
            row_index0=row,
            column_index0=column,
            raw_text=value,
            normalized_text=value,
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
        )
        for row, values in enumerate((("Name", "Value"), ("Formula", "=1+1")))
        for column, value in enumerate(values)
    )
    return CanonicalTable(
        id="tbl_001",
        row_count=2,
        column_count=2,
        header_row_count=1,
        cells=cells,
        source_refs=(source_ref,),
    )


def test_markdown_emits_loss_aware_table_formula_and_figure_assets(
    canonical_document,
    source_ref,
) -> None:
    table = simple_table(source_ref)
    blocks = (
        CanonicalBlock(
            id="block_table_assets",
            order=0,
            type=BlockType.TABLE,
            content_layer=ContentLayer.STRUCTURED,
            table=table,
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("table-assets"),
        ),
        CanonicalBlock(
            id="block_formula_assets",
            order=1,
            type=BlockType.FORMULA,
            content_layer=ContentLayer.STRUCTURED,
            formula_latex=r"E = mc^2",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("formula-assets"),
        ),
        CanonicalBlock(
            id="block_figure_assets",
            order=2,
            type=BlockType.FIGURE,
            content_layer=ContentLayer.STRUCTURED,
            normalized_text="Measured source diagram",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("figure-assets"),
        ),
    )
    artifact = export_markdown(
        canonical_document.model_copy(update={"blocks": blocks}),
        MarkdownExportOptions(
            profile=ExportProfile.PORTABLE_STRUCTURED,
            processed_at=datetime(2026, 7, 29, tzinfo=UTC),
            figure_asset_paths={"block_figure_assets": "../assets/figures/block-figure-assets.png"},
        ),
    )

    assert artifact.table_assets["../assets/tables/tbl_001.csv"] == ("Name,Value\nFormula,'=1+1")
    assert artifact.supplemental_assets["../assets/formulas/block_formula_assets.tex"] == "E = mc^2"
    assert "[Download CSV](../assets/tables/tbl_001.csv)" in artifact.markdown
    assert "[LaTeX source](../assets/formulas/block_formula_assets.tex)" in artifact.markdown
    assert (
        "![Measured source diagram](../assets/figures/block-figure-assets.png)" in artifact.markdown
    )
    figure_bytes = b"\x89PNG\r\n\x1a\nbounded-test-payload"
    vault = compile_vault(
        canonical_document.model_copy(update={"blocks": blocks}),
        artifact,
        binary_assets={"assets/figures/block-figure-assets.png": figure_bytes},
    )
    assert vault["assets/figures/block-figure-assets.png"] == figure_bytes
    assert validate_internal_links(vault) == ()


def test_table_profiles_are_loss_aware_and_safe(source_ref) -> None:
    table = simple_table(source_ref)
    assert "| Name | Value |" in table_to_gfm(table)
    assert "'=1+1" in table_to_csv(table)
    html = table_to_html(table)
    assert "<thead>" in html and "<tbody>" in html

    header_only = table.model_copy(
        update={"row_count": 1, "header_row_count": 1, "cells": table.cells[:2]}
    )
    assert table_to_html(header_only).endswith("</table>")

    merged = CanonicalTable(
        id="tbl_merged",
        row_count=1,
        column_count=2,
        header_row_count=1,
        cells=(
            CanonicalCell(
                id="cell_merged",
                row_index0=0,
                column_index0=0,
                column_span=2,
                raw_text="Merged",
                normalized_text="Merged",
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(source_ref,),
            ),
        ),
        source_refs=(source_ref,),
    )
    with pytest.raises(ValueError, match="losslessly"):
        table_to_gfm(merged)


def test_complex_table_export_creates_sidecar_asset(canonical_document, source_ref) -> None:
    merged = CanonicalTable(
        id="tbl_merged",
        row_count=1,
        column_count=2,
        header_row_count=1,
        cells=(
            CanonicalCell(
                id="cell_merged",
                row_index0=0,
                column_index0=0,
                column_span=2,
                raw_text="Merged",
                normalized_text="Merged",
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(source_ref,),
            ),
        ),
        source_refs=(source_ref,),
    )
    table_block = CanonicalBlock(
        id="blk_table",
        order=2,
        type=BlockType.TABLE,
        content_layer=ContentLayer.STRUCTURED,
        table=merged,
        origin=BlockOrigin.RULE_RECONSTRUCTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest("table"),
    )
    document = canonical_document.model_copy(
        update={"blocks": (*canonical_document.blocks, table_block)}
    )
    artifact = export_markdown(
        document,
        MarkdownExportOptions(
            profile=ExportProfile.PORTABLE_STRUCTURED,
            processed_at=datetime(2026, 7, 29, tzinfo=UTC),
        ),
    )
    assert artifact.table_assets
    assert "Complex table" in artifact.markdown
    assert json.loads(source_map_json(artifact.source_map))["entries"]


def test_jsonld_and_jsonl_are_deterministic(canonical_document) -> None:
    note = KnowledgeNote(
        note_id="urn:akmp:note:001",
        title="Revenue",
        note_type=NoteType.CONCEPT,
        content_origin=BlockOrigin.AI_SUMMARIZED,
        evidence_block_ids=("blk_001",),
        claims=(
            Claim(
                text="Revenue increased.",
                origin=BlockOrigin.AI_SUMMARIZED,
                source_block_ids=("blk_001",),
                confidence=0.9,
            ),
        ),
    )
    relation = RelationAssertion(
        id="urn:akmp:relation:001",
        subject="urn:akmp:entity:a",
        predicate="akmp:relatedTo",
        object="urn:akmp:entity:b",
        assertion_status=AssertionStatus.AI_INFERRED,
        confidence=0.8,
        evidence_block_ids=("blk_001",),
    )
    bundle = KnowledgeBundle(
        document_id=canonical_document.document_id,
        notes=(note,),
        relations=(relation,),
    )
    payload = json.loads(knowledge_jsonld(canonical_document, bundle))
    assert payload["@context"]["akmp"].startswith("https://schemas.")
    assert payload["@context"] == AKMP_CONTEXT
    assert json.loads(context_jsonld()) == {"@context": AKMP_CONTEXT}
    assert "akmp:KnowledgeNoteShape" in KNOWLEDGE_NOTE_SHACL
    assert {
        "reviewStatus",
        "assertionStatus",
        "subject",
        "predicate",
        "object",
    } <= payload["@context"].keys()
    note_node = next(node for node in payload["@graph"] if node["@type"] == "akmp:KnowledgeNote")
    assert note_node["noteType"] == "concept"
    assert note_node["origin"] == "ai_summarized"
    assert note_node["supportedBy"] == ["urn:akmp:block:blk_001"]
    assert {node["@type"] for node in payload["@graph"]} == {
        "akmp:KnowledgeNote",
        "akmp:RelationAssertion",
    }
    assert json.loads(documents_jsonl(canonical_document))["documentId"] == "doc_001"

    from akc_exporters import adaptive_chunks

    chunks = adaptive_chunks(canonical_document, language="ko")
    assert chunks_jsonl(chunks).count("\n") == len(chunks)


def test_reserved_filename_and_zip_collision_are_rejected() -> None:
    assert portable_slug("CON") == "_CON"
    with pytest.raises(ValueError, match="duplicate"):
        deterministic_zip({"A.txt": b"a", "a.TXT": b"b"})


def test_export_path_heading_and_long_chunk_are_bounded(
    canonical_document,
    source_ref,
) -> None:
    heading = CanonicalBlock(
        id="blk_heading",
        order=2,
        type=BlockType.HEADING,
        content_layer=ContentLayer.STRUCTURED,
        markdown="# Source tried another H1",
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest("heading"),
    )
    long_text = "가" * 2500
    long_block = CanonicalBlock(
        id="blk_long",
        order=3,
        type=BlockType.PARAGRAPH,
        content_layer=ContentLayer.STRUCTURED,
        normalized_text=long_text,
        origin=BlockOrigin.OCR_EXTRACTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest(long_text),
    )
    document = canonical_document.model_copy(
        update={"blocks": (*canonical_document.blocks, heading, long_block)}
    )
    export_options = MarkdownExportOptions(
        profile=ExportProfile.PORTABLE_STRUCTURED,
        processed_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    artifact = export_markdown(document, export_options)
    assert "\n## Source tried another H1\n" in artifact.markdown
    with pytest.raises(ValueError, match="relative path"):
        export_markdown(document, export_options, output_path="../escape.md")
    chunks = adaptive_chunks(document, language="ko")
    assert len(chunks) >= 3
    assert all(chunk.token_count <= 1200 for chunk in chunks)


def test_math_notation_is_not_mistaken_for_a_wikilink() -> None:
    """Bracketed notation inside math must not be read as a link target.

    Extracted papers contain notation such as ``$[[s \\otimes f]]$``. Treating it
    as a wikilink invents a broken reference, and because a Vault with an
    unresolved link is refused outright, one formula would block a document that
    has nothing broken in it.
    """
    from akc_exporters.vault import validate_internal_links

    files = {
        "note.md": (
            "# Paper\n\n"
            r"The isomorphism sends class $[[s \otimes f]]$ to $F(f)(s)$." + "\n"
        ).encode("utf-8"),
    }
    assert validate_internal_links(files) == ()


def test_display_math_is_also_excluded_from_link_scanning() -> None:
    from akc_exporters.vault import validate_internal_links

    files = {
        "note.md": ("# Paper\n\n$$\n" + r"[[A \otimes B]]" + "\n$$\n").encode("utf-8"),
    }
    assert validate_internal_links(files) == ()


def test_a_genuine_wikilink_outside_math_is_still_reported() -> None:
    from akc_exporters.vault import validate_internal_links

    files = {
        "note.md": (
            "# Paper\n\nSee [[Missing Note]] and " + r"$[[x \otimes y]]$." + "\n"
        ).encode("utf-8"),
    }
    broken = validate_internal_links(files)
    # The real dangling link is still caught; only the formula is spared.
    assert len(broken) == 1
    assert broken[0].target == "Missing Note"


def test_escaped_dollar_does_not_open_a_math_span() -> None:
    from akc_exporters.vault import validate_internal_links

    files = {
        "note.md": (
            "# Prices\n\n" + r"Costs \$5 then [[Missing Note]] then \$9." + "\n"
        ).encode("utf-8"),
    }
    broken = validate_internal_links(files)
    assert len(broken) == 1
    assert broken[0].target == "Missing Note"
