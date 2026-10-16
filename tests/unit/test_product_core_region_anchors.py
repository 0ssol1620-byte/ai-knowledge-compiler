"""Region identity must preserve a one-to-one evidence and source binding."""

from datetime import UTC, datetime

import pytest
from akc_cir.models import BBox1000
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import ProductCoreDocument, ProductCoreRegion, ProductCoreRoute
from pydantic import ValidationError


def _region(region_id: str, order: int, native_object_id: str | None) -> ProductCoreRegion:
    return ProductCoreRegion(
        region_id=region_id,
        native_object_id=native_object_id,
        order=order,
        page_index0=order,
        page_number1=order + 1,
        text=f"The board approved policy {order}.",
        bbox1000=BBox1000((100, 100, 900, 200)),
        authority="regulatory_filing",
    )


def _document(regions: tuple[ProductCoreRegion, ...]) -> ProductCoreDocument:
    return ProductCoreDocument(
        native_id="anchor-fixture",
        connector_type="synthetic",
        immutable_object_key="synthetic/source.pdf",
        ocr_object_key="synthetic/ocr.json",
        content_sha256="sha256:" + "a" * 64,
        title="Anchor fixture",
        source_filename="source.pdf",
        page_count=2,
        regions=regions,
    )


@pytest.mark.parametrize(
    "regions",
    [
        (_region("region-a", 0, "shared"), _region("region-b", 1, "shared")),
        (_region("region-a", 0, "region-b"), _region("region-b", 1, None)),
    ],
    ids=["duplicate-native-anchor", "native-and-fallback-anchor-collision"],
)
def test_colliding_effective_anchors_are_rejected(regions: tuple[ProductCoreRegion, ...]) -> None:
    # Different pages, region IDs and orders must not mask an anchor collision.
    with pytest.raises(ValidationError, match="effective region anchors must be unique"):
        _document(regions)


def test_distinct_effective_anchors_preserve_text_page_and_citation_binding() -> None:
    regions = (_region("region-a", 0, "native-a"), _region("region-b", 1, None))
    document = _document(regions)
    request = ProductCoreCompileRequest(
        request_id="anchor-request",
        idempotency_key="anchor-idempotency",
        tenant_id="synthetic-tenant",
        workspace_id="synthetic-workspace",
        collection_id="synthetic-collection",
        requested_at=datetime(2026, 9, 30, tzinfo=UTC),
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=0,
            max_latency_ms=1000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=(document,),
    )
    compiler = ProductCoreCompiler(core_release_digest="sha256:" + "b" * 64)
    fragment = compiler.compile_fragments(request)[0]
    assert len({unit.logical_id for unit in fragment.units}) == 2
    assert len({unit.evidence_id for unit in fragment.units}) == 2
    for region, unit, block in zip(
        regions, fragment.units, fragment.canonical_document.blocks, strict=True
    ):
        assert unit.text == block.raw_text == region.text
        assert unit.page_number1 == region.page_number1
        assert block.source_refs[0].page_number1 == region.page_number1
        assert unit.anchor == block.source_refs[0].native_object_id
        assert unit.anchor == (region.native_object_id or region.region_id)
