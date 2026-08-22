from __future__ import annotations

import pytest
from akc_cir import (
    CanonicalKnowledgeModel,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    SourceRef,
    build_knowledge_object,
)


def _source_ref() -> SourceRef:
    return SourceRef(
        document_id="doc-001",
        document_version_id="docv-001",
        page_index0=0,
        page_number1=1,
    )


def _object(
    stable_id: str,
    kind: KnowledgeObjectKind,
    *,
    links: tuple[str, ...] = (),
    origin: KnowledgeOrigin = KnowledgeOrigin.SOURCE_EXPLICIT,
    state: KnowledgeVerificationState = KnowledgeVerificationState.VERIFIED,
):
    return build_knowledge_object(
        stable_id=stable_id,
        tenant_id="tenant-001",
        collection_id="collection-001",
        kind=kind,
        source_refs=(_source_ref(),),
        origin=origin,
        verification_state=state,
        created_by_activity="activity-001",
        version=1,
        links=links,
        payload={"title": stable_id},
    )


def test_canonical_model_is_renderer_neutral_and_source_bound() -> None:
    root = _object("collection-001", KnowledgeObjectKind.COLLECTION, links=("note-001",))
    note = _object("note-001", KnowledgeObjectKind.NOTE)
    model = CanonicalKnowledgeModel(
        tenant_id="tenant-001",
        collection_id="collection-001",
        objects=(root, note),
    )
    assert {item.kind for item in model.objects} == {
        KnowledgeObjectKind.COLLECTION,
        KnowledgeObjectKind.NOTE,
    }
    assert all(item.source_refs and item.hash.startswith("sha256:") for item in model.objects)
    assert "folder" not in {kind.value for kind in KnowledgeObjectKind}


def test_canonical_object_kind_registry_matches_every_v4_model_object() -> None:
    assert {kind.value for kind in KnowledgeObjectKind} == {
        "collection",
        "document",
        "document_version",
        "page",
        "region",
        "block",
        "table",
        "figure",
        "note",
        "entity",
        "relation",
        "claim",
        "evidence",
        "asset",
        "ontology_term",
        "export_artifact",
        "validation_record",
    }


def test_model_inferred_relation_cannot_be_promoted_without_objective_verification() -> None:
    with pytest.raises(ValueError, match="verified graph"):
        _object(
            "relation-001",
            KnowledgeObjectKind.RELATION,
            origin=KnowledgeOrigin.MODEL_INFERRED,
        )
    isolated = _object(
        "relation-001",
        KnowledgeObjectKind.RELATION,
        origin=KnowledgeOrigin.MODEL_INFERRED,
        state=KnowledgeVerificationState.UNRESOLVED,
    )
    assert isolated.verification_state is KnowledgeVerificationState.UNRESOLVED


def test_canonical_model_rejects_unknown_links_and_digest_tampering() -> None:
    root = _object("collection-001", KnowledgeObjectKind.COLLECTION, links=("missing",))
    with pytest.raises(ValueError, match="unknown objects"):
        CanonicalKnowledgeModel(
            tenant_id="tenant-001",
            collection_id="collection-001",
            objects=(root,),
        )
    with pytest.raises(ValueError, match="hash is not reproducible"):
        root.model_copy(update={"hash": "sha256:" + "0" * 64}, deep=True).__class__(
            **root.model_copy(update={"hash": "sha256:" + "0" * 64}).model_dump()
        )
