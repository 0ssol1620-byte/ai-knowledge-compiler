from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    SourceRef,
    sha256_digest,
)


@pytest.fixture
def source_ref() -> SourceRef:
    return SourceRef(
        document_id="doc_001",
        document_version_id="docver_001",
        page_index0=0,
        page_number1=1,
        bbox1000=BBox1000([100, 100, 900, 300]),
    )


@pytest.fixture
def canonical_document(source_ref: SourceRef) -> CanonicalDocument:
    blocks = (
        CanonicalBlock(
            id="blk_001",
            order=0,
            type=BlockType.PARAGRAPH,
            content_layer=ContentLayer.STRUCTURED,
            raw_text="매출은 10% 증가했다.",
            normalized_text="매출은 10% 증가했다.",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("매출은 10% 증가했다."),
            confidence=0.99,
        ),
        CanonicalBlock(
            id="blk_002",
            order=1,
            type=BlockType.PARAGRAPH,
            content_layer=ContentLayer.KNOWLEDGE,
            normalized_text="AI 요약 문장",
            origin=BlockOrigin.AI_SUMMARIZED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("AI 요약 문장"),
            confidence=0.90,
        ),
    )
    return CanonicalDocument(
        tenant_id="tenant_001",
        document_id="doc_001",
        document_version_id="docver_001",
        title="검증 가능한 문서",
        source_filename="source.pdf",
        source_sha256=sha256_digest(b"source"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=blocks,
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
