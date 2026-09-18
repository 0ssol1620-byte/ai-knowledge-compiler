"""Source-bound recovery candidate tests; synthetic evidence, no quality claim."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

import pytest
from akc_cir import CanonicalDocument
from akc_router.document_execution import DocumentSourceBinding, DocumentTextExecutionResult
from akc_router.evidence_execution import (
    EvidenceDisposition,
    RegionExecutionResult,
    TextObservation,
    text_digest,
)
from akc_router.region_recovery import (
    build_region_recovery_candidate,
    project_source_bound_text_regions,
)

SHA = "sha256:" + "a" * 64
REP = "sha256:" + "b" * 64


def document(*, refs: list[dict] | None = None, second: bool = False) -> CanonicalDocument:
    default_ref = {
        "documentId": "source-a",
        "documentVersionId": "revision-a",
        "pageIndex0": 0,
        "pageNumber1": 1,
        "bbox1000": [10, 10, 400, 100],
    }
    blocks = [
        {
            "id": "block-a",
            "order": 0,
            "type": "paragraph",
            "contentLayer": "extracted",
            "origin": "native_extracted",
            "rawText": "Revenue was -12.5 million USD.",
            "sourceRefs": refs if refs is not None else [default_ref],
            "contentHash": SHA,
        }
    ]
    if second:
        blocks.append(
            {
                "id": "block-b",
                "order": 1,
                "type": "paragraph",
                "contentLayer": "extracted",
                "origin": "native_extracted",
                "rawText": "Operating income was 9 million USD.",
                "sourceRefs": [
                    {**default_ref, "bbox1000": [450, 10, 900, 100]}
                ],
                "contentHash": "sha256:" + "c" * 64,
            }
        )
    return CanonicalDocument.model_validate(
        {
            "tenantId": "tenant-a",
            "documentId": "source-a",
            "documentVersionId": "revision-a",
            "title": "Region fixture",
            "sourceFilename": "fixture.pdf",
            "sourceSha256": SHA,
            "contentLayer": "extracted",
            "blocks": blocks,
            "metadata": {"pages": [{}]},
            "createdAt": datetime(2026, 9, 10, tzinfo=UTC),
        }
    )


def result(doc: CanonicalDocument, *, disposition=EvidenceDisposition.VERIFIED_TEXT_REGION):
    inventory = project_source_bound_text_regions(
        doc, expected_source_sha256=SHA, representation_sha256=REP
    )
    regions = {}
    for region in inventory.regions:
        text = region.witness.observation.text
        accepted = TextObservation(
            region.binding, "visual.region-specialist", text, text_digest(text)
        )
        regions[region.binding.region_id] = RegionExecutionResult(
            region.binding,
            disposition,
            accepted if disposition is EvidenceDisposition.VERIFIED_TEXT_REGION else None,
            (),
            (),
            0.2,
        )
    execution = DocumentTextExecutionResult(
        "plan-a",
        DocumentSourceBinding(doc.document_version_id, SHA, REP),
        MappingProxyType(regions),
        0.2,
        0.1,
        "verified_text_scope"
        if disposition is EvidenceDisposition.VERIFIED_TEXT_REGION
        else "unresolved",
        (),
    )
    return inventory, execution


def test_exact_source_ref_becomes_a_crop_binding_and_native_witness() -> None:
    inventory, _ = result(document())
    region = inventory.regions[0]
    assert inventory.complete
    assert inventory.eligible_text_block_count == 1
    assert region.binding.page_index0 == 0
    assert region.binding.bbox1000 == (10, 10, 400, 100)
    assert region.block_id == "block-a"
    assert region.witness.observation.producer_id == "native.source"
    assert region.witness.covers_declared_text_region is True


def test_missing_or_multi_source_geometry_is_visible_and_never_invented() -> None:
    no_box = [{
        "documentId": "source-a",
        "documentVersionId": "revision-a",
        "pageIndex0": 0,
        "pageNumber1": 1,
        "bbox1000": None,
    }]
    inventory = project_source_bound_text_regions(
        document(refs=no_box), expected_source_sha256=SHA, representation_sha256=REP
    )
    assert not inventory.complete and not inventory.regions
    assert inventory.unresolved[0].reason == "REGION_GEOMETRY_UNMEASURED"
    two_refs = [
        {**no_box[0], "bbox1000": [10, 10, 400, 100]},
        {
            **no_box[0],
            "pageIndex0": 1,
            "pageNumber1": 2,
            "bbox1000": [10, 10, 400, 100],
        },
    ]
    inventory = project_source_bound_text_regions(
        document(refs=two_refs), expected_source_sha256=SHA, representation_sha256=REP
    )
    assert inventory.unresolved[0].reason == "REGION_SINGLE_SOURCE_REF_REQUIRED"


def test_foreign_reference_or_representation_fails_before_projection() -> None:
    foreign = [{
        "documentId": "foreign",
        "documentVersionId": "revision-a",
        "pageIndex0": 0,
        "pageNumber1": 1,
        "bbox1000": [10, 10, 400, 100],
    }]
    with pytest.raises(ValueError, match="REFERENCE_IDENTITY"):
        project_source_bound_text_regions(
            document(refs=foreign), expected_source_sha256=SHA, representation_sha256=REP
        )
    with pytest.raises(ValueError, match="REPRESENTATION_DIGEST"):
        project_source_bound_text_regions(
            document(), expected_source_sha256=SHA, representation_sha256="latest"
        )


def test_verified_outputs_form_an_immutable_non_promotable_candidate() -> None:
    doc = document(second=True)
    inventory, execution = result(doc)
    candidate = build_region_recovery_candidate(doc, inventory=inventory, execution=execution)
    assert candidate.disposition == "verified_candidate"
    assert set(candidate.replacements) == {"block-a", "block-b"}
    assert candidate.production_promotion is False
    assert candidate.verification_scope == "declared_text_regions_only"
    with pytest.raises(TypeError):
        candidate.replacements["block-c"] = candidate.replacements["block-a"]


def test_partial_or_changed_base_never_yields_a_replacement() -> None:
    doc = document()
    inventory, execution = result(doc, disposition=EvidenceDisposition.UNRESOLVED)
    candidate = build_region_recovery_candidate(doc, inventory=inventory, execution=execution)
    assert candidate.disposition == "unresolved"
    assert not candidate.replacements
    changed = doc.model_copy(
        update={"blocks": [doc.blocks[0].model_copy(update={"revision": 2})]}
    )
    verified_inventory, verified_execution = result(doc)
    with pytest.raises(ValueError, match="BASE_BLOCK_CHANGED"):
        build_region_recovery_candidate(
            changed, inventory=verified_inventory, execution=verified_execution
        )


def test_a_localized_target_is_not_blocked_by_an_unrelated_unlocated_block() -> None:
    doc = document(second=True)
    unlocated = doc.blocks[1].source_refs[0].model_copy(update={"bbox1000": None})
    doc = doc.model_copy(
        update={
            "blocks": [
                doc.blocks[0],
                doc.blocks[1].model_copy(update={"source_refs": [unlocated]}),
            ]
        }
    )
    inventory = project_source_bound_text_regions(
        doc, expected_source_sha256=SHA, representation_sha256=REP
    )
    target = inventory.regions[0]
    text = target.witness.observation.text
    accepted = TextObservation(
        target.binding, "visual.region-specialist", text, text_digest(text)
    )
    execution = DocumentTextExecutionResult(
        "plan-a",
        DocumentSourceBinding(doc.document_version_id, SHA, REP),
        MappingProxyType(
            {
                target.binding.region_id: RegionExecutionResult(
                    target.binding,
                    EvidenceDisposition.VERIFIED_TEXT_REGION,
                    accepted,
                    (),
                    (),
                    0.2,
                )
            }
        ),
        0.2,
        0.1,
        "verified_text_scope",
        (),
    )
    candidate = build_region_recovery_candidate(
        doc,
        inventory=inventory,
        execution=execution,
        target_region_ids=frozenset({target.binding.region_id}),
    )
    assert candidate.disposition == "verified_candidate"
    assert set(candidate.replacements) == {"block-a"}


def test_overlapping_replacements_refuse_the_entire_candidate() -> None:
    doc = document(second=True)
    second = doc.blocks[1]
    overlapping_ref = second.source_refs[0].model_copy(
        update={"bbox1000": second.source_refs[0].bbox1000.model_copy(
            update={"root": (300, 10, 700, 100)}
        )}
    )
    doc = doc.model_copy(
        update={
            "blocks": [
                doc.blocks[0],
                second.model_copy(update={"source_refs": [overlapping_ref]}),
            ]
        }
    )
    inventory, execution = result(doc)
    candidate = build_region_recovery_candidate(doc, inventory=inventory, execution=execution)
    assert candidate.disposition == "unresolved"
    assert candidate.reasons == ("RECOVERY_REGION_OVERLAP",)
    assert not candidate.replacements
