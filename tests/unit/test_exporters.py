from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

from akc_cir import ExportProfile, QualityReport
from akc_exporters import (
    MarkdownExportOptions,
    MergePolicy,
    adaptive_chunks,
    compile_vault,
    deterministic_zip,
    export_markdown,
    plan_vault_merge,
)


def options(profile: ExportProfile) -> MarkdownExportOptions:
    return MarkdownExportOptions(
        profile=profile,
        document_type="business_report",
        language="ko",
        languages=("ko",),
        processed_at=datetime(2026, 7, 29, 8, tzinfo=UTC),
    )


def test_raw_export_excludes_ai_layer_and_offsets_are_exact(canonical_document) -> None:
    raw_options = options(ExportProfile.PORTABLE_RAW).model_copy(
        update={"provenance_file": "../source-map/document.raw.json"}
    )
    artifact = export_markdown(canonical_document, raw_options)
    assert "매출은 10% 증가했다." in artifact.markdown
    assert "AI 요약 문장" not in artifact.markdown
    assert "content_layer: extracted" in artifact.markdown
    assert "provenance_file: ../source-map/document.raw.json" in artifact.markdown
    assert len(artifact.source_map.entries) == 1
    entry = artifact.source_map.entries[0]
    selected = artifact.markdown[
        entry.markdown_range.start_codepoint0 : entry.markdown_range.end_codepoint0
    ]
    assert selected == "매출은 10% 증가했다."
    assert "\r" not in artifact.markdown


def test_export_and_zip_are_deterministic(canonical_document) -> None:
    artifact_a = export_markdown(
        canonical_document,
        options(ExportProfile.PORTABLE_STRUCTURED),
    )
    artifact_b = export_markdown(
        canonical_document,
        options(ExportProfile.PORTABLE_STRUCTURED),
    )
    assert artifact_a == artifact_b
    quality = QualityReport(
        document_id=canonical_document.document_id,
        overall_score=0.95,
        status="PASS",
        component_scores={"text": 0.95},
    )
    vault = compile_vault(canonical_document, artifact_a, quality_report=quality)
    assert deterministic_zip(vault) == deterministic_zip(dict(reversed(tuple(vault.items()))))


def test_package_manifest_is_written_last_after_inventory_files() -> None:
    payload = deterministic_zip(
        {
            "manifest.json": b'{"schemaVersion":"export-manifest-1.0.0"}',
            "z.txt": b"z",
            "a.txt": b"a",
        }
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["a.txt", "z.txt", "manifest.json"]


def test_adaptive_chunks_keep_provenance_and_links(canonical_document) -> None:
    chunks = adaptive_chunks(canonical_document, language="ko")
    assert len(chunks) == 1
    assert chunks[0].source_refs
    assert chunks[0].content_hash.startswith("sha256:")
    assert chunks[0].previous_chunk_id is None
    assert chunks[0].next_chunk_id is None


def test_vault_merge_never_silently_overwrites() -> None:
    existing = {"10-Documents/a.md": b"old"}
    incoming = {"10-documents/A.md": b"new"}
    blocked = plan_vault_merge(existing, incoming)
    assert not blocked.safe_to_apply
    assert blocked.files["10-Documents/a.md"] == b"old"
    renamed = plan_vault_merge(existing, incoming, policy=MergePolicy.RENAME_INCOMING)
    assert renamed.safe_to_apply
    assert len(renamed.files) == 2
