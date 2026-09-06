"""Product-Core v2 candidate compilation contract."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime

import pytest
from akc_cir.identity import document_version_id, source_id
from akc_cir.models import BBox1000, BlockType
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)

TENANT = "tenant-foundation-pilot"
WORKSPACE = "workspace-foundation-pilot"
COLLECTION = "collection-mixed-corpus"
RELEASE = "sha256:" + "a" * 64


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _document(native_id: str, text: str, *, page: int = 1) -> ProductCoreDocument:
    source = source_id(
        tenant_id=TENANT,
        connector_type="foundation-r2",
        native_id=native_id,
    )
    digest = _sha(text)
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
        page_count=page,
        regions=(
            ProductCoreRegion(
                region_id=f"region-{native_id}",
                page_index0=page - 1,
                page_number1=page,
                order=0,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=BBox1000((100, 120, 900, 240)),
                confidence=0.99,
                authority="regulatory_filing",
            ),
        ),
    )


def _request(
    documents: tuple[ProductCoreDocument, ...],
    *,
    request_id: str,
    previous: PreviousWorldSnapshot | None = None,
) -> ProductCoreCompileRequest:
    return ProductCoreCompileRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        collection_id=COLLECTION,
        requested_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        route=ProductCoreRoute(
            operation_class="incremental_recompile" if previous else "initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=10,
            max_latency_ms=90_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=documents,
        previous_active_world=previous,
    )


def _fragmented_document(native_id: str) -> ProductCoreDocument:
    fragments = tuple(
        f"Section {index}: TAVONEL reported verified revenue evidence for fiscal year 2025."
        for index in range(30)
    )
    document = _document(native_id, "\n".join(fragments))
    regions = tuple(
        ProductCoreRegion(
            region_id=f"region-{native_id}-{index}",
            page_index0=0,
            page_number1=1,
            order=index,
            block_type=BlockType.PARAGRAPH,
            text=text,
            bbox1000=BBox1000((100, 100 + index * 20, 900, 118 + index * 20)),
            confidence=0.99,
            authority="regulatory_filing",
        )
        for index, text in enumerate(fragments)
    )
    return document.model_copy(update={"regions": regions})


def test_initial_compile_emits_region_bound_candidate_without_promoting() -> None:
    request = _request(
        (
            _document("filing-a", "Revenue is 100 million won."),
            _document("policy-b", "The board approved the policy."),
        ),
        request_id="compile-initial",
    )

    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request,
        input_sha256=_sha("initial-request"),
    )

    assert response.status == "completed"
    assert response.receipt.matching_policy == "legacy"
    assert response.receipt.candidate_promotion is False
    assert response.receipt.equivalence == "not_run"
    assert response.candidate.lifecycle == "candidate"
    assert response.candidate.parent_world_state_id is None
    assert len(response.candidate.canonical_documents) == 2
    first_ref = response.candidate.canonical_documents[0]["blocks"][0]["sourceRefs"][0]
    assert first_ref["pageNumber1"] == 1
    assert first_ref["bbox1000"] == [100, 120, 900, 240]
    assert {artifact.kind for artifact in response.artifacts} == {
        "canonical_ir",
        "knowledge_model",
        "dependency_graph",
        "retrieval_index",
        "candidate_world",
    }
    package_paths = {file.path for file in response.candidate.package.files}
    assert {
        "ontology/knowledge.jsonld",
        "ontology/knowledge.ttl",
        "graph/nodes.csv",
        "graph/relationships.csv",
        "semantics/profile.json",
        "semantics/claims.jsonl",
        "semantics/entities.jsonl",
        "semantics/relations.jsonl",
        "semantics/contradictions.jsonl",
        "rag/documents.jsonl",
        "rag/chunks.jsonl",
        "rag/retrieval-profile.json",
        "ontology/architecture-plan.json",
        "provenance/activities.jsonl",
        "validation/report.json",
    } <= package_paths
    assert all(
        file.size_bytes == len(file.content.encode()) for file in response.candidate.package.files
    )
    chunk_file = next(
        file for file in response.candidate.package.files if file.path == "rag/chunks.jsonl"
    )
    chunks = [json.loads(line) for line in chunk_file.content.splitlines()]
    assert chunks[0]["bbox1000"] == [100, 120, 900, 240]
    assert chunks[0]["authority"] == "regulatory_filing"
    assert chunks[0]["authorityTier"] == "official"
    assert chunks[0]["claimIds"]
    assert chunks[0]["retrievalTerms"]
    architecture_file = next(
        file
        for file in response.candidate.package.files
        if file.path == "ontology/architecture-plan.json"
    )
    architecture = json.loads(architecture_file.content)
    assert architecture["blueprint"] == "corporate-filings"
    assert architecture["module_sha256"].startswith("sha256:")
    assert any(
        row["kind"] == "knowledge_view" and row["blueprint"] == "corporate-filings"
        for row in response.candidate.directory_plan
    )


def test_fragmented_ocr_builds_context_chunks_and_materializes_knowledge_views() -> None:
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request((_fragmented_document("fragmented-filing"),), request_id="compile-fragments"),
        input_sha256=_sha("fragmented-request"),
    )

    assert len(response.candidate.units) == 30
    package = {file.path: file.content for file in response.candidate.package.files}
    chunks = [json.loads(line) for line in package["rag/chunks.jsonl"].splitlines()]
    assert 1 < len(chunks) < len(response.candidate.units)
    assert all(len(chunk["text"]) >= 180 for chunk in chunks)
    assert all(chunk["logicalIds"] and chunk["evidenceIds"] for chunk in chunks)
    assert all(len(chunk["evidenceRefs"]) == len(chunk["evidenceIds"]) for chunk in chunks)
    assert all(chunk["retrievalTerms"] for chunk in chunks)

    relationships = list(csv.DictReader(package["graph/relationships.csv"].splitlines()))
    predicates = {row["predicate"] for row in relationships}
    assert {"contains", "supported_by"} <= predicates
    assert predicates != {"links_to"}

    architecture = json.loads(package["ontology/architecture-plan.json"])
    assert all(f"obsidian/{view}.md" in package for view in architecture["root_views"])
    assert all(f"obsidian/MOCs/{moc}.md" in package for moc in architecture["mocs"])
    validation = json.loads(package["validation/report.json"])
    assert validation["retrievalChunkCount"] == len(chunks)
    assert validation["retrievalTinyChunkCount"] == 0
    assert validation["retrievalEvidenceCoverage"] == 1.0


def test_incremental_compile_abstains_on_ambiguous_identity_and_proves_equivalence() -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    initial = compiler.compile(
        _request(
            (
                _document("filing-a", "Revenue is 100 million won."),
                _document("policy-b", "The board approved the policy."),
            ),
            request_id="compile-v1",
        ),
        input_sha256=_sha("request-v1"),
    )
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    before_ids = {unit.source_id: unit.logical_id for unit in initial.candidate.units}

    incremental = compiler.compile(
        _request(
            (
                _document("filing-a", "Revenue is 120 million won."),
                _document("policy-b", "The board approved the policy."),
            ),
            request_id="compile-v2",
            previous=previous,
        ),
        input_sha256=_sha("request-v2"),
    )

    assert incremental.status == "review_required"
    assert incremental.receipt.equivalence == "passed"
    assert incremental.receipt.work_avoided_artifacts > 0
    assert incremental.candidate.parent_world_state_id == initial.candidate.world_state_id
    after_units = {unit.source_id: unit for unit in incremental.candidate.units}
    filing_source = _document("filing-a", "unused").source_id
    policy_source = _document("policy-b", "unused").source_id
    assert after_units[filing_source].logical_id != before_ids[filing_source]
    assert after_units[filing_source].identity_state == "unresolved"
    assert after_units[policy_source].logical_id == before_ids[policy_source]
    assert after_units[policy_source].identity_state == "matched"
    assert incremental.candidate.review_reasons[0].startswith("IDENTITY_AMBIGUOUS:")
    assert incremental.candidate.diff["contentChanged"] is True
    assert incremental.candidate.recompilation["rebuild_count"] > 0


def test_core_rejects_product_supplied_identity_that_does_not_match_derivation() -> None:
    document = _document("filing-a", "Revenue is 100 million won.").model_copy(
        update={"source_id": "src_tampered"}
    )
    request = _request((document,), request_id="compile-tampered")

    with pytest.raises(ValueError, match="sourceId does not match"):
        ProductCoreCompiler(core_release_digest=RELEASE).compile(
            request,
            input_sha256=_sha("tampered-request"),
        )


def test_core_is_the_identity_authority_when_product_omits_derived_ids() -> None:
    document = _document("filing-a", "Revenue is 100 million won.").model_copy(
        update={"source_id": None, "source_version_id": None}
    )

    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request((document,), request_id="compile-core-derived-identity"),
        input_sha256=_sha("core-derived-identity"),
    )

    expected_source = source_id(
        tenant_id=TENANT,
        connector_type="foundation-r2",
        native_id="filing-a",
    )
    assert response.candidate.units[0].source_id == expected_source
    assert response.candidate.units[0].source_version_id.startswith("dv_")


def test_missing_region_geometry_and_authority_require_review() -> None:
    document = _document("scan-a", "Scanned text without layout evidence.")
    region = document.regions[0].model_copy(update={"bbox1000": None, "authority": "unclassified"})
    document = document.model_copy(update={"regions": (region,)})

    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request((document,), request_id="compile-review-required"),
        input_sha256=_sha("review-required"),
    )

    assert response.status == "review_required"
    assert response.candidate.lifecycle == "review_required"
    assert any(
        reason.startswith("REGION_CITATION_UNAVAILABLE:")
        for reason in response.candidate.review_reasons
    )
    assert any(
        reason.startswith("AUTHORITY_UNCLASSIFIED:") for reason in response.candidate.review_reasons
    )


def test_multilingual_semantics_and_numeric_conflicts_stay_evidence_bound_for_review() -> None:
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request(
            (
                _document(
                    "filing-en",
                    "2025 revenue was 100 million won. "
                    "TAVONEL Research Institute reported the result.",
                ),
                _document("filing-ko", "2025 revenue was 120 million won. 한국은행은 공시했다."),
            ),
            request_id="compile-semantic-review",
        ),
        input_sha256=_sha("semantic-review"),
    )

    assert response.status == "review_required"
    assert any(
        reason.startswith("CONTRADICTION_CANDIDATE:")
        for reason in response.candidate.review_reasons
    )
    objects = response.candidate.canonical_knowledge_model["objects"]
    claims = [item for item in objects if item["kind"] == "claim"]
    entities = [item for item in objects if item["kind"] == "entity"]
    validations = [item for item in objects if item["kind"] == "validation_record"]
    assert claims and entities and validations
    assert all(item["sourceRefs"][0]["bbox1000"] == [100, 120, 900, 240] for item in claims)
    assert all(item["verificationState"] == "unresolved" for item in validations)
    semantic_profile = json.loads(
        next(
            file.content
            for file in response.candidate.package.files
            if file.path == "semantics/profile.json"
        )
    )
    assert set(semantic_profile["languages"]) == {"en", "ko"}
    assert semantic_profile["contradictionCandidateCount"] == 1
