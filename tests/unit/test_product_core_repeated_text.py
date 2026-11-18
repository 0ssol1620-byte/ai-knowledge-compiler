"""Repeated text inside one document (WO-D12-8, decision D12-D8).

`akc_cir.identity.evidence_id` hashes (version, page, bbox, normalised text) and no anchor, so two
regions with the same text on the same page and no bbox share one evidence id. The compiler must
emit one evidence object carrying both regions' references, and every claim, entity, relation and
retrieval chunk must cite its own region, never the other one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from akc_cir.identity import document_version_id, source_id
from akc_cir.models import BBox1000, BlockType
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)

TENANT = "tenant-foundation-pilot"
WORKSPACE = "workspace-foundation-pilot"
RELEASE = "sha256:" + "a" * 64
REPEATED = "Mercury Systems reported revenue of 100 million won in 2025."
OTHER = "Venus Labs acquired the Orion plant in 2024."


def _document(*texts: str, box_step: int | None = None) -> ProductCoreDocument:
    source = source_id(tenant_id=TENANT, connector_type="foundation-r2", native_id="statement")
    digest = "sha256:" + hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
    return ProductCoreDocument(
        native_id="statement",
        connector_type="foundation-r2",
        source_id=source,
        source_version_id=document_version_id(source=source, content_sha256=digest),
        immutable_object_key=f"immutable/{TENANT}/{WORKSPACE}/statement/{digest[7:]}/source.pdf",
        ocr_object_key=f"immutable/{TENANT}/{WORKSPACE}/statement/{digest[7:]}/ocr.json",
        content_sha256=digest,
        title="Statement",
        source_filename="statement.pdf",
        page_count=1,
        regions=tuple(
            ProductCoreRegion(
                region_id=f"region-{index}",
                page_index0=0,
                page_number1=1,
                order=index,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=(
                    None
                    if box_step is None
                    else BBox1000((100, 100 + box_step * index, 900, 152 + box_step * index))
                ),
                confidence=0.99,
                authority="regulatory_filing",
            )
            for index, text in enumerate(texts)
        ),
    )


def _compile(
    document: ProductCoreDocument, previous: ProductCoreCompileResponse | None = None
) -> ProductCoreCompileResponse:
    snapshot = (
        None
        if previous is None
        else PreviousWorldSnapshot(
            world_state_id=previous.candidate.world_state_id,
            manifest_digest=previous.candidate.manifest_digest,
            units=previous.candidate.units,
            artifact_hashes=previous.candidate.artifact_hashes,
        )
    )
    request = ProductCoreCompileRequest(
        request_id="req-repeated",
        idempotency_key="idem-repeated",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        collection_id="collection-repeated",
        requested_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC),
        route=ProductCoreRoute(
            operation_class="incremental_recompile" if snapshot else "initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=10,
            max_latency_ms=90_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=(document,),
        previous_active_world=snapshot,
    )
    return ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256="sha256:" + hashlib.sha256(b"repeated").hexdigest()
    )


def _objects(response: ProductCoreCompileResponse, kind: str) -> list[dict[str, Any]]:
    objects = response.candidate.canonical_knowledge_model["objects"]
    return [item for item in objects if item["kind"] == kind]


def _anchors(item: dict[str, Any]) -> list[str]:
    return [ref["nativeObjectId"] for ref in item["sourceRefs"]]


def _assert_every_region_cites_itself(response: ProductCoreCompileResponse) -> None:
    anchor_by_logical = {unit.logical_id: unit.anchor for unit in response.candidate.units}
    claims = {item["stableId"]: item for item in _objects(response, "claim")}
    assert len({anchor_by_logical[c["payload"]["logicalId"]] for c in claims.values()}) >= 2
    for claim in claims.values():
        assert _anchors(claim) == [anchor_by_logical[claim["payload"]["logicalId"]]]
    for relation in _objects(response, "relation"):
        subject = claims[relation["payload"]["subjectId"]]
        assert _anchors(relation) == _anchors(subject)
    for entity in _objects(response, "entity"):
        assert _anchors(entity) == _anchors(claims[entity["payload"]["claimIds"][0]])
    files = {item.path: item.content for item in response.candidate.package.files}
    for chunk in map(json.loads, files["rag/chunks.jsonl"].splitlines()):
        expected = [anchor_by_logical[logical] for logical in chunk["logicalIds"]]
        assert [ref["nativeObjectId"] for ref in chunk["evidenceRefs"]] == expected


def _assert_one_evidence_object_for_both_regions(response: ProductCoreCompileResponse) -> None:
    repeated_units = [u for u in response.candidate.units if u.text == REPEATED]
    assert len(repeated_units) == 2
    assert repeated_units[0].evidence_id == repeated_units[1].evidence_id
    shared = [
        item
        for item in _objects(response, "evidence")
        if item["payload"]["evidenceId"] == repeated_units[0].evidence_id
    ]
    assert len(shared) == 1
    assert _anchors(shared[0]) == [repeated_units[0].anchor, repeated_units[1].anchor]


def test_two_regions_with_the_same_text_compile_to_one_evidence_object_citing_both() -> None:
    response = _compile(_document(REPEATED, REPEATED, OTHER))

    assert response.status != "rejected"
    assert len(_objects(response, "evidence")) == 2
    _assert_one_evidence_object_for_both_regions(response)
    _assert_every_region_cites_itself(response)


def test_only_the_after_revision_repeats_a_text_incrementally() -> None:
    before = _compile(_document(REPEATED, OTHER))
    after_document = _document(REPEATED, REPEATED)
    incremental = _compile(after_document, previous=before)
    cold = _compile(after_document)

    for response in (incremental, cold):
        assert response.status != "rejected"
        _assert_one_evidence_object_for_both_regions(response)
        _assert_every_region_cites_itself(response)


def test_boxes_inside_the_identity_quantisation_step_also_share_one_evidence_object() -> None:
    # The class is "same normalised text, same page, same quantised box", and an absent box is
    # one case of it: evidence_id rounds box edges to a step of 2, so boxes 1 apart collide too.
    response = _compile(_document(REPEATED, REPEATED, OTHER, box_step=1))

    _assert_one_evidence_object_for_both_regions(response)
    _assert_every_region_cites_itself(response)


def test_distinct_regions_keep_one_evidence_object_each() -> None:
    # The class boundary: boxes far apart give the same text two evidence ids, two objects.
    response = _compile(_document(REPEATED, REPEATED, OTHER, box_step=200))

    assert len({u.evidence_id for u in response.candidate.units}) == 3
    assert [len(_anchors(item)) for item in _objects(response, "evidence")] == [1, 1, 1]
    _assert_every_region_cites_itself(response)
