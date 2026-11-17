"""Keyed identity for connector-declared fact keys (WO-D12-12, ADR-010) and F-D12-5.

F-D12-5, the class: two regions of one document that share an anchor (the native object id,
else the region id) name one region; they are refused by name when the document is built,
not at block construction with an unnamed error.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from akc_product_core.contracts import (
    ProductCoreCompileRequest,
    ProductCoreDocument,
    ProductCoreRegion,
)
from pydantic import ValidationError

from benchmark.u06_equivalence.harness import _request

AT = datetime(2026, 1, 1, tzinfo=UTC)
ANCHOR_REFUSAL = "region anchors .*must be unique within a document"


def _region(order: int, region_id: str, native: str | None, text: str) -> ProductCoreRegion:
    return ProductCoreRegion(
        region_id=region_id,
        page_index0=0,
        page_number1=1,
        order=order,
        text=text,
        native_object_id=native,
        authority="official",
    )


def _document(regions: tuple[ProductCoreRegion, ...]) -> ProductCoreDocument:
    body = "\n".join(region.text for region in regions)
    return ProductCoreDocument(
        native_id="doc-1",
        connector_type="synthetic",
        immutable_object_key="syn/v1/doc-1.json",
        ocr_object_key="syn/v1/doc-1.txt",
        content_sha256="sha256:" + hashlib.sha256(body.encode()).hexdigest(),
        title="Synthetic statement",
        source_filename="doc-1.json",
        page_count=1,
        regions=regions,
    )


# --------------------------------------------------------------------------- F-D12-5


def test_two_regions_with_one_native_id_are_refused_by_name() -> None:
    # Before: the document was accepted and the compile failed at CanonicalDocument with an
    # unnamed "block IDs must be unique".
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL) as raised:
        _document(
            (
                _region(0, "r-1", "Fact-1", "Net income was 100."),
                _region(1, "r-2", "Fact-1", "Revenue was 900."),
            )
        )
    assert "Net income" not in str(raised.value) and "Revenue" not in str(raised.value)


def test_a_native_id_equal_to_another_regions_region_id_is_refused() -> None:
    # The same class: the anchor is native_object_id or region_id, so these two collide too.
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL):
        _document(
            (
                _region(0, "r-1", None, "Net income was 100."),
                _region(1, "r-2", "r-1", "Revenue was 900."),
            )
        )


def test_the_served_request_contract_refuses_it_too() -> None:
    document = _document((_region(0, "r-1", "Fact-1", "Net income was 100."),))
    payload = _request(
        [document],
        request_id="req-dup",
        requested_at=AT,
        tenant_id="tenant-foundation-pilot",
        workspace_id="workspace-foundation-pilot",
        collection_id="collection-dup",
    ).model_dump(mode="json", by_alias=True)
    region = dict(payload["documents"][0]["regions"][0])
    payload["documents"][0]["regions"] = [
        region,
        {**region, "regionId": "r-2", "order": 1, "text": "Revenue was 900."},
    ]
    with pytest.raises(ValidationError, match=ANCHOR_REFUSAL):
        ProductCoreCompileRequest.model_validate(payload)


def test_distinct_anchors_still_build() -> None:
    document = _document(
        (
            _region(0, "r-1", "Fact-1", "Net income was 100."),
            _region(1, "r-2", None, "Revenue was 900."),
        )
    )
    assert [r.native_object_id or r.region_id for r in document.regions] == ["Fact-1", "r-2"]
