"""Product-Core v2 candidate compilation contract."""

from __future__ import annotations

import hashlib
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


@pytest.mark.parametrize("size", [1, 5, 12, 13])
def test_global_reduction_is_invariant_to_shard_size_and_order(size: int) -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    documents = tuple(
        _document(
            f"doc-{i:02}",
            f"TAVONEL Research Institute reported revenue of {100 if i < 12 else 120} "
            "million won in 2025.",
        )
        for i in range(13)
    )
    request = _request(documents, request_id="boundary-13")
    expected = compiler.compile(request, input_sha256=_sha("boundary"))
    keys = [(doc.connector_type, doc.native_id) for doc in documents]
    fragments = tuple(
        fragment
        for start in range(0, len(keys), size)
        for fragment in compiler.compile_fragments(request, tuple(keys[start : start + size]))
    )
    actual = compiler.reduce_fragments(request, reversed(fragments), input_sha256=_sha("boundary"))
    assert actual.model_dump() == expected.model_dump()
    # The thirteenth document participates in a single collection-wide conflict pass.
    assert any(
        reason.startswith("CONTRADICTION_CANDIDATE:") for reason in actual.candidate.review_reasons
    )
    assert len(actual.candidate.canonical_documents) == 13


@pytest.mark.parametrize("defect", ["missing", "duplicate", "foreign", "stale"])
def test_reducer_fails_closed_on_invalid_fragment_inventory(defect: str) -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    request = _request(
        (
            _document("doc-a", "The board approved the policy."),
            _document("doc-b", "Revenue is 100 million won."),
        ),
        request_id="inventory",
    )
    fragments = compiler.compile_fragments(request)
    if defect == "missing":
        fragments = fragments[:-1]
    elif defect == "duplicate":
        fragments = (*fragments, fragments[0])
    elif defect == "foreign":
        request = request.model_copy(update={"tenant_id": "other-tenant"})
    else:
        request = request.model_copy(
            update={
                "documents": (
                    _document("doc-a", "The board rejected the policy."),
                    request.documents[1],
                )
            }
        )
    with pytest.raises(ValueError):
        compiler.reduce_fragments(request, fragments, input_sha256=_sha("invalid"))


def test_incremental_global_reduction_matches_unsharded_reduction() -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    initial_docs = tuple(
        _document(f"doc-{i:02}", "The board approved the policy.") for i in range(13)
    )
    initial = compiler.compile(
        _request(initial_docs, request_id="initial-13"), input_sha256=_sha("initial")
    )
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    # An actual deletion and addition, while keeping a stable logical collection.
    changed = (*initial_docs[1:], _document("doc-new", "The board approved the revised policy."))
    request = _request(changed, request_id="changed-13", previous=previous)
    full = compiler.compile(request, input_sha256=_sha("changed"))
    fragments = compiler.compile_fragments(request)
    incremental = compiler.reduce_fragments(
        request, reversed(fragments), input_sha256=_sha("changed")
    )
    assert incremental.model_dump() == full.model_dump()
    assert incremental.receipt.equivalence == "passed"
    assert incremental.candidate.parent_world_state_id == initial.candidate.world_state_id


def test_independent_full_rebuild_semantic_oracle_and_missing_dependency_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    import akc_product_core.compiler as implementation
    from akc_cir.recompilation import ArtifactState

    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    original = tuple(_document(f"doc-{i:02}", "The board approved the policy.") for i in range(13))
    initial = compiler.compile(
        _request(original, request_id="oracle-initial"), input_sha256=_sha("oracle-initial")
    )
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    mutated = (*original[1:], _document("doc-new", "Revenue is 120 million won."))
    revision = _request(mutated, request_id="oracle-revision", previous=previous)
    incremental = compiler.compile(revision, input_sha256=_sha("oracle-revision"))
    independent = compiler.compile(
        _request(mutated, request_id="oracle-full"), input_sha256=_sha("oracle-full")
    )

    def meaning(response):
        return sorted(
            (
                unit.source_id,
                unit.source_content_sha256,
                unit.text,
                unit.anchor,
                unit.page_number1,
                unit.authority,
            )
            for unit in response.candidate.units
        )

    assert meaning(incremental) == meaning(independent)
    assert incremental.receipt.equivalence == "passed"
    actual_planner = implementation.plan_recompilation

    def omit_dependencies(**kwargs):
        plan = actual_planner(**kwargs)
        return replace(
            plan,
            targets=tuple(replace(target, state=ArtifactState.CURRENT) for target in plan.targets),
        )

    monkeypatch.setattr(implementation, "plan_recompilation", omit_dependencies)
    broken = compiler.compile(revision, input_sha256=_sha("oracle-broken"))
    assert broken.status == "rejected"
    assert broken.receipt.equivalence == "failed"
    assert "FULL_REBUILD_EQUIVALENCE_FAILED" in broken.candidate.review_reasons


def test_fragment_content_corruption_and_malformed_fragment_are_refused() -> None:
    from dataclasses import replace

    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    request = _request(
        (_document("doc-a", "The board approved the policy."),), request_id="corrupt"
    )
    fragment = compiler.compile_fragments(request)[0]
    with pytest.raises(ValueError, match="malformed"):
        compiler.reduce_fragments(request, (None,), input_sha256=_sha("malformed"))
    with pytest.raises(ValueError, match="immutable"):
        compiler.reduce_fragments(
            request, (replace(fragment, units=()),), input_sha256=_sha("corrupt")
        )
