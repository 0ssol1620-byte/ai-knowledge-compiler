"""Provenance invariant over the real Product-Core compile output (U07).

Every claim, entity, relation and contradiction in a candidate must resolve to an
evidence object that is present in the same candidate.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from akc_cir.identity import document_version_id, source_id
from akc_cir.models import BBox1000, BlockType
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import (
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)

TENANT = "tenant-foundation-pilot"
WORKSPACE = "workspace-foundation-pilot"
COLLECTION = "collection-mixed-corpus"
RELEASE = "sha256:" + "a" * 64


def _document(native_id: str, text: str) -> ProductCoreDocument:
    source = source_id(tenant_id=TENANT, connector_type="foundation-r2", native_id=native_id)
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    version = document_version_id(source=source, content_sha256=digest)
    return ProductCoreDocument(
        native_id=native_id,
        connector_type="foundation-r2",
        source_id=source,
        source_version_id=version,
        immutable_object_key=f"immutable/{TENANT}/{WORKSPACE}/{native_id}/{digest[7:]}/source.pdf",
        ocr_object_key=f"immutable/{TENANT}/{WORKSPACE}/{native_id}/{digest[7:]}/ocr.json",
        content_sha256=digest,
        title=f"Document {native_id}",
        source_filename=f"{native_id}.pdf",
        page_count=1,
        regions=(
            ProductCoreRegion(
                region_id=f"region-{native_id}",
                page_index0=0,
                page_number1=1,
                order=0,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=BBox1000((100, 120, 900, 240)),
                confidence=0.99,
                authority="regulatory_filing",
            ),
        ),
    )


def _compile(documents: tuple[ProductCoreDocument, ...]) -> dict[str, Any]:
    request = ProductCoreCompileRequest(
        request_id="req-provenance",
        idempotency_key="idem-provenance",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        collection_id=COLLECTION,
        requested_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=10,
            max_latency_ms=90_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=documents,
    )
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256="sha256:" + hashlib.sha256(b"provenance").hexdigest()
    )
    assert response.candidate is not None
    model: dict[str, Any] = response.candidate.canonical_knowledge_model
    return model


DOCS = (
    _document(
        "rev-a", "TAVONEL reported verified revenue of 120 million dollars for fiscal year 2025."
    ),
    _document(
        "rev-b", "TAVONEL reported verified revenue of 95 million dollars for fiscal year 2025."
    ),
    _document("note-c", "Mercury Systems published the security review for fiscal year 2025."),
)


def _by_kind(model: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [o for o in model["objects"] if o["kind"] == kind]


def provenance_violations(model: dict[str, Any]) -> list[str]:
    """Every dangling provenance reference in a candidate model, as readable strings."""

    evidence_ids = {o["payload"]["evidenceId"] for o in _by_kind(model, "evidence")}
    claims = {o["stableId"]: o for o in _by_kind(model, "claim")}
    entity_ids = {o["stableId"] for o in _by_kind(model, "entity")}
    bad: list[str] = []
    for claim_id, claim in claims.items():
        if claim["payload"]["evidenceId"] not in evidence_ids:
            bad.append(f"claim {claim_id}: evidence missing")
    for entity in _by_kind(model, "entity"):
        for evidence_id in entity["payload"]["evidenceIds"]:
            if evidence_id not in evidence_ids:
                bad.append(f"entity {entity['stableId']}: evidence {evidence_id} missing")
        for claim_id in entity["payload"]["claimIds"]:
            if claim_id not in claims:
                bad.append(f"entity {entity['stableId']}: claim {claim_id} missing")
    for relation in _by_kind(model, "relation"):
        if relation["payload"]["evidenceId"] not in evidence_ids:
            bad.append(f"relation {relation['stableId']}: evidence missing")
        if relation["payload"]["subjectId"] not in claims | dict.fromkeys(entity_ids):
            bad.append(f"relation {relation['stableId']}: subject missing")
    for record in _by_kind(model, "validation_record"):
        for claim_id in record["payload"].get("claimIds", []):
            if claim_id not in claims:
                bad.append(f"contradiction {record['stableId']}: claim {claim_id} missing")
    return bad


def test_every_claim_entity_relation_and_contradiction_resolves_to_evidence_in_the_candidate() -> (
    None
):
    model = _compile(DOCS)
    assert _by_kind(model, "claim") and _by_kind(model, "entity") and _by_kind(model, "relation")
    assert _by_kind(model, "validation_record"), "fixture must produce a contradiction"
    assert provenance_violations(model) == []


def test_two_disagreeing_sources_both_survive_with_their_own_evidence() -> None:
    model = _compile(DOCS)
    revenue = [c for c in _by_kind(model, "claim") if "revenue" in c["payload"]["text"]]
    assert len(revenue) == 2
    assert revenue[0]["payload"]["evidenceId"] != revenue[1]["payload"]["evidenceId"]
    assert {c["payload"]["sourceId"] for c in revenue} == {d.source_id for d in DOCS[:2]}
    contradictions = [
        r
        for r in _by_kind(model, "validation_record")
        if r["payload"]["reason"] == "numeric_disagreement"
    ]
    assert len(contradictions) == 1
    assert contradictions[0]["payload"]["adjudication"] == "human_review_required"
    assert set(contradictions[0]["payload"]["claimIds"]) == {c["stableId"] for c in revenue}


def test_the_invariant_helper_fails_on_a_dangling_evidence_reference() -> None:
    model = copy.deepcopy(_compile(DOCS))
    claim = _by_kind(model, "claim")[0]
    claim["payload"]["evidenceId"] = "evidence-that-does-not-exist"
    violations = provenance_violations(model)
    assert any("evidence missing" in v for v in violations)
    contradiction = _by_kind(model, "validation_record")[0]
    contradiction["payload"]["claimIds"] = ["claim-that-does-not-exist"]
    assert any("contradiction" in v for v in provenance_violations(model))
    with pytest.raises(AssertionError):
        assert provenance_violations(model) == []
