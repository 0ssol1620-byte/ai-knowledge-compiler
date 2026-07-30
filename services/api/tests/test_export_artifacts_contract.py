from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from akc_api.artifacts import _build_figure_assets, _export_model_provenance, _quality_html
from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    ModelRunRecord,
    QualityReport,
    SourceRef,
    sha256_digest,
)
from PIL import Image


class _ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _FigureSession:
    def __init__(self, pages: list[object], assets: list[object]) -> None:
        self._results = iter((pages, assets))

    async def scalars(self, _statement: object) -> _ScalarRows:
        return _ScalarRows(next(self._results))


class _FigureStore:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.reads: list[str] = []

    async def read_derived(self, object_key: str) -> bytes:
        self.reads.append(object_key)
        return self.payload


def test_export_model_provenance_preserves_all_attested_layers() -> None:
    document = CanonicalDocument(
        tenant_id="tenant-1",
        document_id="document-1",
        document_version_id="document-1:v1",
        title="Attested",
        source_filename="source.pdf",
        source_sha256=sha256_digest("source"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=(
            CanonicalBlock(
                id="block-1",
                order=0,
                type=BlockType.PARAGRAPH,
                content_layer=ContentLayer.STRUCTURED,
                normalized_text="Bounded evidence",
                origin=BlockOrigin.OCR_EXTRACTED,
                source_refs=(
                    SourceRef(
                        document_id="document-1",
                        document_version_id="document-1:v1",
                        page_index0=0,
                        page_number1=1,
                    ),
                ),
                model_run_ids=("run-1",),
                content_hash=sha256_digest("bounded-evidence"),
            ),
        ),
        model_runs=(
            ModelRunRecord(
                id="run-1",
                provider="bounded-provider",
                model="visual-parser",
                revision="a" * 40,
                runtime="container",
                runtime_version="sha256:" + "b" * 64,
                prompt_sha256=sha256_digest("prompt"),
                hardware="test-cpu",
                container_digest="sha256:" + "c" * 64,
                route_profile="parse_balanced_v1",
                started_at=datetime(2026, 7, 29, tzinfo=UTC),
                completed_at=datetime(2026, 7, 29, tzinfo=UTC),
            ),
        ),
        metadata={
            "knowledgeCompileProvenance": {"pipeline_revision": "pipeline-1"},
            "semanticClassification": {
                "attestation": {"model_revision": "d" * 40},
                "provenance": {"evidence_block_ids": ["block-1"]},
            },
        },
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    provenance = _export_model_provenance(document)

    assert set(provenance) == {
        "knowledge_compile",
        "semantic_classification",
        "model_runs",
    }
    assert provenance["model_runs"][0]["id"] == "run-1"
    assert provenance["semantic_classification"]["provenance"]["evidence_block_ids"] == ["block-1"]


def test_quality_report_html_is_static_escaped_and_self_contained() -> None:
    report = QualityReport(
        document_id="doc-1",
        overall_score=0.75,
        status="REVIEW_REQUIRED",
        component_scores={
            "provenance_coverage": 1.0,
            "text_confidence": 0.75,
        },
        findings=(
            {
                "severity": "high",
                "category": "<script>alert(1)</script>",
            },
        ),
        review_item_count=1,
    )

    html = _quality_html(report)

    assert "default-src 'none'" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "REVIEW_REQUIRED" in html
    assert "0.7500" in html


@pytest.mark.asyncio
async def test_figure_asset_is_integrity_checked_cropped_and_attested() -> None:
    source = Image.new("RGB", (100, 80), (220, 20, 20))
    for x in range(50, 100):
        for y in range(80):
            source.putpixel((x, y), (10, 40, 220))
    encoded = io.BytesIO()
    source.save(encoded, format="PNG")
    payload = encoded.getvalue()

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    page_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    source_ref = SourceRef(
        document_id=str(document_id),
        document_version_id=f"{document_id}:v1",
        page_index0=0,
        page_number1=1,
        bbox1000=BBox1000((500, 0, 1000, 1000)),
    )
    figure = CanonicalBlock(
        id="figure-blue-half",
        order=0,
        type=BlockType.FIGURE,
        content_layer=ContentLayer.STRUCTURED,
        normalized_text="Blue half",
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest("blue-half"),
    )
    document = CanonicalDocument(
        tenant_id=str(tenant_id),
        document_id=str(document_id),
        document_version_id=f"{document_id}:v1",
        title="Figure evidence",
        source_filename="source.pdf",
        source_sha256=sha256_digest("source"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=(figure,),
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    page = SimpleNamespace(id=page_id, page_number=1)
    asset = SimpleNamespace(
        id=asset_id,
        page_id=page_id,
        asset_type="preview",
        storage_key="tenants/t/derived/page-1.png",
        sha256=hashlib.sha256(payload).hexdigest(),
        metadata_json={
            "content_type": "image/png",
            "size_bytes": len(payload),
            "width": 100,
            "height": 80,
        },
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    session = _FigureSession([page], [asset])
    store = _FigureStore(payload)

    files, paths = await _build_figure_assets(
        session,  # type: ignore[arg-type]
        SimpleNamespace(tenant_id=tenant_id, document_id=document_id),  # type: ignore[arg-type]
        document,
        store,  # type: ignore[arg-type]
    )

    figure_path = "assets/figures/figure-blue-half.png"
    assert paths == {"figure-blue-half": f"../{figure_path}"}
    with Image.open(io.BytesIO(files[figure_path])) as crop:
        assert crop.size == (50, 80)
        assert crop.getpixel((25, 40)) == (10, 40, 220)
    manifest = json.loads(files["assets/figures/manifest.json"])
    assert manifest["figures"][0]["source_asset_sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["figures"][0]["bbox1000"] == [500, 0, 1000, 1000]
    assert manifest["figures"][0]["sha256"] == hashlib.sha256(files[figure_path]).hexdigest()
    assert store.reads == ["tenants/t/derived/page-1.png"]


@pytest.mark.asyncio
async def test_figure_asset_tamper_fails_closed() -> None:
    payload = b"not-the-attested-payload"
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    page_id = uuid.uuid4()
    source_ref = SourceRef(
        document_id=str(document_id),
        document_version_id=f"{document_id}:v1",
        page_index0=0,
        page_number1=1,
        bbox1000=BBox1000((1, 1, 999, 999)),
    )
    document = CanonicalDocument(
        tenant_id=str(tenant_id),
        document_id=str(document_id),
        document_version_id=f"{document_id}:v1",
        title="Tamper evidence",
        source_filename="source.pdf",
        source_sha256=sha256_digest("source"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=(
            CanonicalBlock(
                id="tampered-figure",
                order=0,
                type=BlockType.FIGURE,
                content_layer=ContentLayer.STRUCTURED,
                normalized_text="Tampered",
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(source_ref,),
                content_hash=sha256_digest("tampered"),
            ),
        ),
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    asset = SimpleNamespace(
        id=uuid.uuid4(),
        page_id=page_id,
        asset_type="preview",
        storage_key="tampered.png",
        sha256="0" * 64,
        metadata_json={
            "content_type": "image/png",
            "size_bytes": len(payload),
            "width": 1,
            "height": 1,
        },
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="integrity mismatch"):
        await _build_figure_assets(
            _FigureSession([SimpleNamespace(id=page_id, page_number=1)], [asset]),  # type: ignore[arg-type]
            SimpleNamespace(tenant_id=tenant_id, document_id=document_id),  # type: ignore[arg-type]
            document,
            _FigureStore(payload),  # type: ignore[arg-type]
        )
