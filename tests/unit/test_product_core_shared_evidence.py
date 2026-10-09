"""Native anchors remain distinct when content-addressed evidence coincides."""

from akc_cir.knowledge_model import CanonicalKnowledgeModel
from akc_product_core import ProductCoreCompiler
from akc_product_core.contracts import PreviousWorldSnapshot

from tests.unit.test_product_core_bridge import RELEASE, _document, _request, _sha


def _compile(documents, request_id="shared-evidence", previous=None):
    return ProductCoreCompiler(core_release_digest=RELEASE).compile(
        _request(documents, request_id=request_id, previous=previous),
        input_sha256=_sha(request_id),
    )


def test_shared_span_evidence_preserves_native_claim_and_relation_anchors() -> None:
    document = _document("native", "TAVONEL approved the policy.")
    second = document.regions[0].model_copy(update={"region_id": "second-anchor", "order": 1})
    document = document.model_copy(update={"regions": (*document.regions, second)})
    result = _compile((document,))
    assert result.status == "completed"
    objects = CanonicalKnowledgeModel.model_validate(
        result.candidate.canonical_knowledge_model
    ).objects
    by_id = {obj.stable_id: obj for obj in objects}
    assert len(by_id) == len(objects)
    evidence = [obj for obj in objects if obj.kind.value == "evidence"]
    assert len(evidence) == 1
    anchors = {document.regions[0].region_id, "second-anchor"}
    assert {ref.native_object_id for ref in evidence[0].source_refs} == anchors
    claims = [obj for obj in objects if obj.kind.value == "claim"]
    assert len(claims) == 2
    assert {obj.source_refs[0].native_object_id for obj in claims} == anchors
    for obj in objects:
        assert set(obj.links) <= set(by_id)
        if obj.kind.value == "relation":
            subject = by_id[obj.payload["subjectId"]]
            assert obj.source_refs == subject.source_refs
            assert obj.payload["evidenceId"] == subject.payload["evidenceId"]
    previous = PreviousWorldSnapshot(
        world_state_id=result.candidate.world_state_id,
        manifest_digest=result.candidate.manifest_digest,
        units=result.candidate.units,
        artifact_hashes=result.candidate.artifact_hashes,
    )
    replay = _compile((document,), "shared-revision", previous)
    assert replay.receipt.equivalence == "passed"
    assert replay.receipt.work_avoided_artifacts == 6


def test_entity_retains_all_supporting_source_citations() -> None:
    documents = (
        _document("one", "TAVONEL approved the policy."),
        _document("two", "TAVONEL published the policy."),
    )
    result = _compile(documents, "entity-lineage")
    entity = next(
        obj
        for obj in CanonicalKnowledgeModel.model_validate(
            result.candidate.canonical_knowledge_model
        ).objects
        if obj.kind.value == "entity" and obj.payload["canonicalName"] == "TAVONEL"
    )
    assert {ref.document_id for ref in entity.source_refs} == {
        document.source_id for document in documents
    }
    assert len(entity.payload["evidenceIds"]) == 2
