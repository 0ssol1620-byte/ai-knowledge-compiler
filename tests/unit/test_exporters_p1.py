from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir import (
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
    RelatedNoteCandidate,
    ReviewStatus,
    sha256_digest,
)
from akc_exporters import (
    MarkdownExportOptions,
    MergePolicy,
    adaptive_chunks,
    compile_vault,
    deterministic_zip,
    export_markdown,
    plan_vault_merge,
    validate_internal_links,
)


def _options(profile: ExportProfile = ExportProfile.OBSIDIAN) -> MarkdownExportOptions:
    return MarkdownExportOptions(
        profile=profile,
        language="ko",
        languages=("ko",),
        processed_at=datetime(2026, 7, 29, 9, tzinfo=UTC),
    )


def _note(
    note_id: str,
    title: str,
    note_type: NoteType,
    *,
    review_status: ReviewStatus = ReviewStatus.PENDING,
    related_to: str | None = None,
) -> KnowledgeNote:
    candidates = (
        (
            RelatedNoteCandidate(
                target_id=related_to,
                relation="related concept",
                reason="같은 원문 블록에서 확인됨",
                source_block_ids=("blk_001",),
                confidence=0.88,
            ),
        )
        if related_to
        else ()
    )
    return KnowledgeNote(
        note_id=note_id,
        title=title,
        note_type=note_type,
        content_origin=BlockOrigin.AI_SUMMARIZED,
        evidence_block_ids=("blk_001",),
        summary=f"{title}에 대한 근거 기반 요약",
        claims=(
            Claim(
                text=f"{title}는 원문 근거를 가진다.",
                origin=BlockOrigin.AI_SUMMARIZED,
                source_block_ids=("blk_001",),
                confidence=0.91,
            ),
        ),
        aliases=(f"{title} alias",),
        tags=("knowledge", note_type.value),
        related_note_candidates=candidates,
        review_status=review_status,
    )


def test_knowledge_bundle_builds_complete_link_safe_deterministic_vault(
    canonical_document,
) -> None:
    concept = _note("note_concept", "근거 추적", NoteType.CONCEPT)
    notes = (
        concept,
        _note(
            "note_person",
            "김연구",
            NoteType.PERSON,
            review_status=ReviewStatus.USER_VERIFIED,
            related_to=concept.note_id,
        ),
        _note("note_org", "신뢰 AI 연구소", NoteType.ORGANIZATION),
        _note("note_project", "컴파일러 프로젝트", NoteType.PROJECT),
        _note("note_glossary", "Provenance", NoteType.GLOSSARY),
    )
    bundle = KnowledgeBundle(document_id=canonical_document.document_id, notes=notes)
    artifact = export_markdown(canonical_document, _options())

    vault = compile_vault(
        canonical_document,
        artifact,
        knowledge_bundle=bundle,
        wikilinks=True,
    )
    expected_folders = {
        NoteType.CONCEPT: "20-Concepts/",
        NoteType.PERSON: "30-People/",
        NoteType.ORGANIZATION: "40-Organizations/",
        NoteType.PROJECT: "50-Projects/",
        NoteType.GLOSSARY: "60-Glossary/",
    }
    for note_type, folder in expected_folders.items():
        assert any(path.startswith(folder) for path in vault), note_type
    assert {
        "00-Home/Concepts-MOC.md",
        "00-Home/People-MOC.md",
        "00-Home/Organizations-MOC.md",
        "00-Home/Projects-MOC.md",
        "00-Home/Glossary-MOC.md",
        "00-Home/Review-Queue.md",
    } <= vault.keys()
    assert validate_internal_links(vault) == ()
    review_queue = vault["00-Home/Review-Queue.md"].decode()
    assert "근거 추적" in review_queue
    assert "김연구" not in review_queue

    reversed_bundle = KnowledgeBundle(
        document_id=canonical_document.document_id,
        notes=tuple(reversed(notes)),
    )
    reversed_vault = compile_vault(
        canonical_document,
        artifact,
        knowledge_bundle=reversed_bundle,
        wikilinks=True,
    )
    assert vault == reversed_vault
    assert deterministic_zip(vault) == deterministic_zip(reversed_vault)

    invalid_note = concept.model_copy(update={"evidence_block_ids": ("missing_block",)})
    with pytest.raises(ValueError, match="unknown blocks"):
        compile_vault(
            canonical_document,
            artifact,
            knowledge_bundle=KnowledgeBundle(
                document_id=canonical_document.document_id,
                notes=(invalid_note,),
            ),
        )


def test_internal_link_validation_and_managed_merge_preserve_user_area(
    canonical_document,
) -> None:
    artifact = export_markdown(canonical_document, _options())
    existing = compile_vault(canonical_document, artifact)
    concept = _note("note_concept", "근거 추적", NoteType.CONCEPT)
    incoming = compile_vault(
        canonical_document,
        artifact,
        knowledge_bundle=KnowledgeBundle(
            document_id=canonical_document.document_id,
            notes=(concept,),
        ),
    )
    existing["00-Home/Topics-MOC.md"] += b"\n## User notes\nKeep this text.\n"

    plan = plan_vault_merge(existing, incoming, policy=MergePolicy.UPDATE_MANAGED)
    assert plan.safe_to_apply
    merged_topics = plan.files["00-Home/Topics-MOC.md"].decode()
    assert "Keep this text." in merged_topics
    assert validate_internal_links(plan.files) == ()

    tampered = dict(existing)
    tampered["00-Home/Topics-MOC.md"] = tampered["00-Home/Topics-MOC.md"].replace(
        b"# Topics",
        b"# User-edited topics",
    )
    blocked = plan_vault_merge(tampered, incoming, policy=MergePolicy.UPDATE_MANAGED)
    assert not blocked.safe_to_apply
    assert any(item.reason == "managed_section_modified" for item in blocked.conflicts)

    broken = validate_internal_links({"folder/a.md": b"[missing](b.md)\n"})
    assert len(broken) == 1
    assert broken[0].resolved_path == "folder/b.md"
    unsafe_plan = plan_vault_merge({}, {"folder/a.md": b"[missing](b.md)\n"})
    assert not unsafe_plan.safe_to_apply
    assert unsafe_plan.broken_links == broken

    colliding_artifact = export_markdown(
        canonical_document,
        _options(),
        output_path="README.md",
    )
    with pytest.raises(ValueError, match="path collision"):
        compile_vault(canonical_document, colliding_artifact)


def test_heading_stack_repairs_level_jumps_for_markdown_and_chunks(
    canonical_document,
    source_ref,
) -> None:
    blocks: list[CanonicalBlock] = []
    specifications = (
        (0, "head_a", "# A"),
        (2, "head_b", "#### B"),
        (4, "head_c", "#### C"),
        (6, "head_d", "## D"),
    )
    for order, block_id, markdown in specifications:
        blocks.append(
            CanonicalBlock(
                id=block_id,
                order=order,
                type=BlockType.HEADING,
                content_layer=ContentLayer.STRUCTURED,
                markdown=markdown,
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(source_ref,),
                content_hash=sha256_digest(markdown),
            )
        )
        text = "가" * 420
        blocks.append(
            CanonicalBlock(
                id=f"{block_id}_body",
                order=order + 1,
                type=BlockType.PARAGRAPH,
                content_layer=ContentLayer.STRUCTURED,
                normalized_text=text,
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(source_ref,),
                content_hash=sha256_digest(text),
            )
        )
    document = canonical_document.model_copy(update={"blocks": tuple(blocks)})
    markdown = export_markdown(
        document,
        _options(ExportProfile.PORTABLE_STRUCTURED),
    ).markdown
    assert "\n## A\n" in markdown
    assert "\n### B\n" in markdown
    assert "\n### C\n" in markdown
    assert "\n### D\n" in markdown
    assert "\n#### B\n" not in markdown

    chunks = adaptive_chunks(
        document,
        language="ko",
        target_tokens=500,
        max_tokens=500,
    )
    heading_paths = {chunk.heading_path for chunk in chunks}
    assert ("A", "B") in heading_paths
    assert ("A", "C") in heading_paths
    assert ("A", "D") in heading_paths


def test_large_tables_split_on_rows_with_headers_and_oversized_atoms_are_isolated(
    canonical_document,
    source_ref,
) -> None:
    values = [("Header A", "Header B")]
    values.extend((f"row-{index}-" + "가" * 210, str(index)) for index in range(6))
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
        for row, row_values in enumerate(values)
        for column, value in enumerate(row_values)
    )
    table = CanonicalTable(
        id="table_large",
        row_count=len(values),
        column_count=2,
        header_row_count=1,
        cells=cells,
        source_refs=(source_ref,),
    )
    table_block = CanonicalBlock(
        id="block_table",
        order=0,
        type=BlockType.TABLE,
        content_layer=ContentLayer.STRUCTURED,
        table=table,
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest("large-table"),
    )
    table_document = canonical_document.model_copy(update={"blocks": (table_block,)})
    table_chunks = adaptive_chunks(
        table_document,
        language="ko",
        target_tokens=500,
        max_tokens=500,
    )
    assert len(table_chunks) == 3
    assert all(chunk.content.splitlines()[0] == "Header A\tHeader B" for chunk in table_chunks)
    assert all(chunk.token_count <= 500 for chunk in table_chunks)
    combined = "\n".join(chunk.content for chunk in table_chunks)
    for index in range(6):
        assert combined.count(f"row-{index}-") == 1

    formula = "x+" * 600
    figure_text = "그" * 600
    atomic_blocks = (
        CanonicalBlock(
            id="block_formula",
            order=0,
            type=BlockType.FORMULA,
            content_layer=ContentLayer.STRUCTURED,
            formula_latex=formula,
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest(formula),
        ),
        CanonicalBlock(
            id="block_figure",
            order=1,
            type=BlockType.FIGURE,
            content_layer=ContentLayer.STRUCTURED,
            normalized_text=figure_text,
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest(figure_text),
        ),
    )
    atomic_document = canonical_document.model_copy(update={"blocks": atomic_blocks})
    atomic_chunks = adaptive_chunks(
        atomic_document,
        language="ko",
        target_tokens=500,
        max_tokens=500,
    )
    assert [chunk.content_type for chunk in atomic_chunks] == [
        "formula_oversized",
        "figure_oversized",
    ]
    assert all(chunk.token_count > 500 for chunk in atomic_chunks)
    assert atomic_chunks == adaptive_chunks(
        atomic_document,
        language="ko",
        target_tokens=500,
        max_tokens=500,
    )
