"""Offline native artifact manifest and compact, source-bound CKO projection."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from akc_cir.base import ContractModel, Sha256, StableId, canonical_json, sha256_digest
from akc_cir.knowledge_model import (
    CanonicalKnowledgeModel,
    CanonicalKnowledgeObject,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    build_knowledge_object,
)
from akc_cir.models import CanonicalCell, SourceRef
from pydantic import BaseModel, Field, TypeAdapter, model_validator

from .contracts import CandidatePackage, Identifier
from .native_cir import (
    MAX_NATIVE_CELLS,
    MAX_NATIVE_CIR_BYTES,
    MAX_NATIVE_PACKAGE_BYTES,
    NativeCIRRequest,
    _preflight,
    parse_native_request,
    serialize_native_draft,
)
from .native_facts import (
    MAX_NATIVE_FACTS_OUTPUT_BYTES,
    NativeCellEvidence,
    NativeCellFact,
    NativeFactsDraft,
)

MANIFEST_SCHEMA: Literal["tavonel.product_core.native_world_artifact_manifest.v1"] = (
    "tavonel.product_core.native_world_artifact_manifest.v1"
)
REFERENCE_PROFILE: Literal["tavonel.native_cell_observation_world.refs.v1"] = (
    "tavonel.native_cell_observation_world.refs.v1"
)
MAX_NATIVE_MANIFEST_BYTES = 32 * 1024
MAX_NATIVE_MODEL_BYTES = MAX_NATIVE_PACKAGE_BYTES
ArtifactKind = Literal["native_facts", "full_cir_package", "canonical_knowledge_model"]


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _chunks(value: Any) -> Iterator[str]:
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )
    return encoder.iterencode(_json_value(value))


def _json_length(value: Any, limit: int) -> int:
    size = 0
    for chunk in _chunks(value):
        size += len(chunk.encode("utf-8"))
        if size > limit:
            raise ValueError("native compact projected byte limit")
    return size


def _bytes(value: Any, limit: int) -> bytes:
    result = bytearray()
    for chunk in _chunks(value):
        raw = chunk.encode("utf-8")
        if len(result) + len(raw) + 1 > limit:
            raise ValueError("native artifact serialization byte limit")
        result.extend(raw)
    result.extend(b"\n")
    return bytes(result)


def _load(body: bytes, limit: int) -> Any:
    if len(body) > limit:
        raise ValueError("native artifact input byte limit")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON property")
            result[key] = value
        return result

    def finite(value: str) -> None:
        raise ValueError("non-finite JSON constant")

    try:
        return json.loads(
            body.decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=finite
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid native artifact JSON") from exc


def _id(prefix: str, *parts: str) -> str:
    return prefix + "_" + sha256_digest(canonical_json(parts))[7:]


class NativeArtifactReference(ContractModel):
    artifact_id: Identifier
    kind: ArtifactKind
    media_type: Literal["application/json"] = "application/json"
    byte_length: Annotated[int, Field(ge=1, le=32 * 1024 * 1024)]
    sha256: Sha256

    @model_validator(mode="after")
    def bind_identity(self) -> NativeArtifactReference:
        if self.artifact_id != f"{self.kind}_{self.sha256[7:]}":
            raise ValueError("native artifact reference identity mismatch")
        return self


def _reference(kind: ArtifactKind, body: bytes) -> NativeArtifactReference:
    digest = sha256_digest(body)
    return NativeArtifactReference(
        artifact_id=f"{kind}_{digest[7:]}", kind=kind, byte_length=len(body), sha256=digest
    )


class NativeManifestSource(ContractModel):
    native_id: Identifier
    source_id: Identifier
    source_version_id: Identifier
    content_sha256: Sha256
    cir_sha256: Sha256
    processing_receipt_id: Identifier


class NativeFactReferencePayload(ContractModel):
    profile_version: Literal["tavonel.native_cell_observation_world.refs.v1"] = REFERENCE_PROFILE
    facts_artifact_sha256: Sha256
    fact_id: Identifier
    evidence_id: Identifier
    observation_kind: Literal["source_cell_value", "formula_expression", "source_error"] | None = (
        None
    )


class NativeWorldArtifactManifest(ContractModel):
    schema_version: Literal["tavonel.product_core.native_world_artifact_manifest.v1"] = (
        MANIFEST_SCHEMA
    )
    projection_version: Literal["tavonel.native_cell_observation_world.refs.v1"] = REFERENCE_PROFILE
    kind: Literal["native_world_artifact_manifest"] = "native_world_artifact_manifest"
    operation_class: Literal["initial_compile"] = "initial_compile"
    status: Literal["review_required"] = "review_required"
    approval_status: Literal["unbound"] = "unbound"
    candidate_promotion: Literal[False] = False
    signature_status: Literal["external_signer_required"] = "external_signer_required"
    tenant_id: Identifier
    workspace_id: Identifier
    collection_id: StableId
    core_release_digest: Sha256
    canonical_request_sha256: Sha256
    world_state_id: Identifier
    parent_world_state_id: None = None
    manifest_digest: Sha256
    sources: Annotated[tuple[NativeManifestSource, ...], Field(min_length=1, max_length=16)]
    artifacts: Annotated[tuple[NativeArtifactReference, ...], Field(min_length=3, max_length=3)]
    cell_count: Annotated[int, Field(ge=0, le=100_000)]
    knowledge_object_count: Annotated[int, Field(ge=1)]
    validation: dict[str, Any]
    review_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def bind_manifest(self) -> NativeWorldArtifactManifest:
        if tuple(a.kind for a in self.artifacts) != (
            "native_facts",
            "full_cir_package",
            "canonical_knowledge_model",
        ):
            raise ValueError("native manifest artifact set/order mismatch")
        source_keys = [s.source_id for s in self.sources]
        if source_keys != sorted(set(source_keys)) or len(
            {s.source_version_id for s in self.sources}
        ) != len(self.sources):
            raise ValueError("native manifest source set/order mismatch")
        work = self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude={"world_state_id", "manifest_digest"},
        )
        if self.world_state_id != _id("native_refs_ws", canonical_json(work)):
            raise ValueError("native manifest World identity mismatch")
        body = self.model_dump(
            mode="json", by_alias=True, exclude_none=True, exclude={"manifest_digest"}
        )
        if self.manifest_digest != sha256_digest(_bytes(body, MAX_NATIVE_MANIFEST_BYTES)):
            raise ValueError("native manifest digest mismatch")
        _bytes(self, MAX_NATIVE_MANIFEST_BYTES)
        return self


@dataclass(frozen=True, slots=True)
class NativeManifestReduction:
    """Offline return value: manifest and ONE new blob, not a wire package."""

    manifest: NativeWorldArtifactManifest
    canonical_model: bytes


@dataclass(frozen=True, slots=True)
class VerifiedNativeManifest:
    manifest: NativeWorldArtifactManifest
    facts: NativeFactsDraft
    knowledge_model: CanonicalKnowledgeModel


@dataclass(frozen=True, slots=True)
class ResolvedNativeCell:
    fact: NativeCellFact
    evidence: NativeCellEvidence
    cell: CanonicalCell
    sheet: dict[str, Any]


def _facts(body: bytes) -> NativeFactsDraft:
    value = _load(body, MAX_NATIVE_FACTS_OUTPUT_BYTES)
    if not isinstance(value, dict):
        raise ValueError("native facts object required")
    TypeAdapter(StableId).validate_python(value.get("collectionId"))
    documents = value.get("canonicalDocuments")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 16:
        raise ValueError("native canonical document count limit")
    total_bytes = total_cells = 0
    for doc in documents:
        _preflight(doc)
        total_bytes += _json_length(doc, MAX_NATIVE_CIR_BYTES)
        total_cells += sum(
            len(b["table"]["cells"]) for b in doc["blocks"] if b.get("table") is not None
        )
        if total_bytes > MAX_NATIVE_CIR_BYTES or total_cells > MAX_NATIVE_CELLS:
            raise ValueError("aggregate native CIR limit")
    return NativeFactsDraft.model_validate(value)


def _request(facts: NativeFactsDraft) -> NativeCIRRequest:
    cir = {d.document_version_id: d for d in facts.canonical_documents}
    envelopes = {
        d.source_version_id: {
            **d.model_dump(mode="json", by_alias=True, exclude={"tables"}),
            "canonicalDocument": cir[d.source_version_id].model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
        }
        for d in facts.documents
    }
    return parse_native_request(
        _bytes(
            {
                "schemaVersion": "tavonel.product_core.native_cir_request.v1",
                "requestId": facts.request_id,
                "idempotencyKey": facts.idempotency_key,
                "requestedAt": facts.requested_at.isoformat(),
                "tenantId": facts.tenant_id,
                "workspaceId": facts.workspace_id,
                "collectionId": facts.collection_id,
                "documents": [envelopes[v] for v in facts.input_document_order],
            },
            MAX_NATIVE_FACTS_OUTPUT_BYTES,
        )
    )


def _check_cir_package(body: bytes, facts: NativeFactsDraft) -> None:
    supplied = CandidatePackage.model_validate(_load(body, MAX_NATIVE_PACKAGE_BYTES))
    expected = serialize_native_draft(_request(facts)).package
    if supplied != expected:
        raise ValueError("native full CIR package binding mismatch")
    for file in supplied.files:
        raw = file.content.encode("utf-8")
        if len(raw) != file.size_bytes or sha256_digest(raw) != file.sha256:
            raise ValueError("native full CIR file byte binding mismatch")


def _project(
    facts: NativeFactsDraft,
    facts_ref: NativeArtifactReference,
    cir_ref: NativeArtifactReference,
    release: str,
) -> tuple[CanonicalKnowledgeModel, bytes]:
    scope = (facts.tenant_id, facts.workspace_id, facts.collection_id)
    activity = _id(
        "native_refs_activity", *scope, REFERENCE_PROFILE, release, facts_ref.sha256, cir_ref.sha256
    )
    pending: list[
        tuple[str, KnowledgeObjectKind, tuple[SourceRef, ...], dict[str, Any], tuple[str, ...]]
    ] = []
    header = {
        "schemaVersion": "canonical-knowledge-1.0.0",
        "tenantId": facts.tenant_id,
        "collectionId": facts.collection_id,
        "objects": [],
    }
    projected = _json_length(header, MAX_NATIVE_MODEL_BYTES) + 1  # Exact final LF.

    def emit(
        key: str,
        kind: KnowledgeObjectKind,
        refs: tuple[SourceRef, ...],
        payload: dict[str, Any],
        links: tuple[str, ...] = (),
    ) -> None:
        nonlocal projected
        primitive = {
            "stableId": key,
            "tenantId": facts.tenant_id,
            "collectionId": facts.collection_id,
            "kind": kind.value,
            "sourceRefs": [
                r.model_dump(mode="json", by_alias=True, exclude_none=True) for r in refs
            ],
            "origin": "native_extracted",
            "verificationState": "unresolved",
            "createdByActivity": activity,
            "version": 1,
            "links": list(links),
            "payload": payload,
            "hash": "sha256:" + "0" * 64,
        }
        projected += _json_length(primitive, MAX_NATIVE_MODEL_BYTES - projected) + bool(pending)
        if projected > MAX_NATIVE_MODEL_BYTES:
            raise ValueError("native compact projected byte limit")
        # Retain compact construction arguments; admit the COMPLETE model before
        # constructing any typed CKO or computing any of its content hashes.
        pending.append((key, kind, refs, payload, links))

    documents = {d.source_version_id: d for d in facts.documents}
    doc_keys = {v: _id("native_document", *scope, v) for v in documents}
    emit(
        _id("native_collection", *scope),
        KnowledgeObjectKind.COLLECTION,
        tuple(d.blocks[0].source_refs[0] for d in facts.canonical_documents),
        {"profileVersion": REFERENCE_PROFILE, "workspaceId": facts.workspace_id},
        tuple(doc_keys.values()),
    )
    evidence = {e.fact_id: e for e in facts.evidence}
    for cir in facts.canonical_documents:
        document = documents[cir.document_version_id]
        block_keys = {
            b.id: _id("native_block", *scope, cir.document_version_id, b.id) for b in cir.blocks
        }
        emit(
            doc_keys[cir.document_version_id],
            KnowledgeObjectKind.DOCUMENT,
            tuple(b.source_refs[0] for b in cir.blocks),
            {"documentVersionId": cir.document_version_id, "cirArtifactId": cir_ref.artifact_id},
            tuple(block_keys.values()),
        )
        tables = {t.block_id: t for t in document.tables}
        for block in cir.blocks:
            table_key = (
                _id("native_table", *scope, cir.document_version_id, block.table.id)
                if block.table
                else None
            )
            emit(
                block_keys[block.id],
                KnowledgeObjectKind.BLOCK,
                block.source_refs,
                {
                    "blockId": block.id,
                    "blockType": block.type.value,
                    "contentSha256": block.content_hash,
                    "cirArtifactId": cir_ref.artifact_id,
                },
                (table_key,) if table_key else (),
            )
            if block.table is None:
                continue
            assert table_key is not None
            table = tables[block.id]
            cells = [f for row in table.rows for f in row.cells]
            emit(
                table_key,
                KnowledgeObjectKind.TABLE,
                table.source_refs,
                {
                    "tableId": table.table_id,
                    "headerStatus": table.header_status,
                    "headerBindings": [],
                    "reviewReasons": list(table.review_reasons),
                },
                tuple(_id("native_observation", f.fact_id) for f in cells),
            )
            for fact in cells:
                ev = evidence[fact.fact_id]
                evidence_key = _id("native_evidence_object", ev.evidence_id)
                base = NativeFactReferencePayload(
                    facts_artifact_sha256=facts_ref.sha256,
                    fact_id=fact.fact_id,
                    evidence_id=ev.evidence_id,
                )
                emit(
                    evidence_key,
                    KnowledgeObjectKind.EVIDENCE,
                    ev.source_refs,
                    base.model_dump(mode="json", by_alias=True, exclude_none=True),
                )
                kind: Literal["source_cell_value", "formula_expression", "source_error"] = (
                    fact.observation.kind
                )
                if kind == "source_cell_value" and fact.value_type == "error":
                    kind = "source_error"
                reference = base.model_copy(update={"observation_kind": kind})
                emit(
                    _id("native_observation", fact.fact_id),
                    KnowledgeObjectKind.CLAIM
                    if kind == "source_cell_value"
                    else KnowledgeObjectKind.NOTE,
                    ev.source_refs,
                    reference.model_dump(mode="json", by_alias=True, exclude_none=True),
                    (evidence_key,),
                )
    objects: list[CanonicalKnowledgeObject] = [
        build_knowledge_object(
            stable_id=key,
            tenant_id=facts.tenant_id,
            collection_id=facts.collection_id,
            kind=kind,
            source_refs=refs,
            origin=KnowledgeOrigin.NATIVE_EXTRACTED,
            verification_state=KnowledgeVerificationState.UNRESOLVED,
            created_by_activity=activity,
            version=1,
            links=links,
            payload=payload,
        )
        for key, kind, refs, payload, links in pending
    ]
    model = CanonicalKnowledgeModel(
        tenant_id=facts.tenant_id,
        collection_id=facts.collection_id,
        objects=tuple(sorted(objects, key=lambda o: o.stable_id)),
    )
    body = _bytes(model, MAX_NATIVE_MODEL_BYTES)
    if len(body) != projected:
        raise ValueError("native compact projected/serialized byte mismatch")
    return model, body


def _reduce(
    facts: NativeFactsDraft,
    facts_ref: NativeArtifactReference,
    cir_ref: NativeArtifactReference,
    release: str,
) -> NativeManifestReduction:
    model, body = _project(facts, facts_ref, cir_ref, release)
    model_ref = _reference("canonical_knowledge_model", body)
    sources = tuple(
        NativeManifestSource(
            **d.model_dump(
                mode="python",
                by_alias=False,
                include={
                    "native_id",
                    "source_id",
                    "source_version_id",
                    "content_sha256",
                    "cir_sha256",
                    "processing_receipt_id",
                },
            )
        )
        for d in facts.documents
    )
    fields = {
        "schemaVersion": MANIFEST_SCHEMA,
        "projectionVersion": REFERENCE_PROFILE,
        "kind": "native_world_artifact_manifest",
        "operationClass": "initial_compile",
        "status": "review_required",
        "approvalStatus": "unbound",
        "candidatePromotion": False,
        "signatureStatus": "external_signer_required",
        "tenantId": facts.tenant_id,
        "workspaceId": facts.workspace_id,
        "collectionId": facts.collection_id,
        "coreReleaseDigest": release,
        "canonicalRequestSha256": facts.input_sha256,
        "sources": [_json_value(s) for s in sources],
        "artifacts": [_json_value(r) for r in (facts_ref, cir_ref, model_ref)],
        "cellCount": len(facts.evidence),
        "knowledgeObjectCount": len(model.objects),
        "validation": {
            "sourceBinding": "passed",
            "completeCellCoverage": "passed",
            "canonicalModelIntegrity": "passed",
            "semanticBinding": "unbound",
            "equivalence": "not_run",
            "workAvoidedArtifacts": 0,
            "retrieval": "exact_source_version_locator_or_evidence_id",
        },
        "reviewReasons": sorted(set(facts.review_reasons) | {"NATIVE_WORLD_SEMANTICS_UNBOUND"}),
    }
    fields["worldStateId"] = _id("native_refs_ws", canonical_json(fields))
    fields["manifestDigest"] = sha256_digest(_bytes(fields, MAX_NATIVE_MANIFEST_BYTES))
    manifest = NativeWorldArtifactManifest.model_validate(fields)
    return NativeManifestReduction(manifest=manifest, canonical_model=body)


def reduce_native_manifest(
    facts_body: bytes, cir_package_body: bytes, *, core_release_digest: str
) -> NativeManifestReduction:
    """One compact output blob and references to complete authoritative inputs."""
    release = TypeAdapter(Sha256).validate_python(core_release_digest)
    facts = _facts(facts_body)
    _check_cir_package(cir_package_body, facts)
    return _reduce(
        facts,
        _reference("native_facts", facts_body),
        _reference("full_cir_package", cir_package_body),
        release,
    )


def manifest_bytes(manifest: NativeWorldArtifactManifest) -> bytes:
    return _bytes(manifest, MAX_NATIVE_MANIFEST_BYTES)


def verify_native_manifest(
    manifest_body: bytes, artifacts: Mapping[str, bytes]
) -> VerifiedNativeManifest:
    """Verify all bytes AND reproject; references alone are not evidence."""
    manifest = NativeWorldArtifactManifest.model_validate(
        _load(manifest_body, MAX_NATIVE_MANIFEST_BYTES)
    )
    if set(artifacts) != {r.artifact_id for r in manifest.artifacts}:
        raise ValueError("native manifest missing or unexpected artifacts")
    by_kind: dict[ArtifactKind, bytes] = {}
    for ref in manifest.artifacts:
        body = artifacts[ref.artifact_id]
        if (
            len(body) != ref.byte_length
            or len(body) > MAX_NATIVE_PACKAGE_BYTES
            or sha256_digest(body) != ref.sha256
        ):
            raise ValueError("native referenced artifact byte binding mismatch")
        by_kind[ref.kind] = body
    facts = _facts(by_kind["native_facts"])
    _check_cir_package(by_kind["full_cir_package"], facts)
    expected = _reduce(
        facts, manifest.artifacts[0], manifest.artifacts[1], manifest.core_release_digest
    )
    if (
        manifest_bytes(expected.manifest) != manifest_body
        or expected.canonical_model != by_kind["canonical_knowledge_model"]
    ):
        raise ValueError("native manifest projection binding mismatch")
    model = CanonicalKnowledgeModel.model_validate(
        _load(expected.canonical_model, MAX_NATIVE_MODEL_BYTES)
    )
    return VerifiedNativeManifest(manifest=manifest, facts=facts, knowledge_model=model)


def resolve_native_cell(
    manifest_body: bytes, artifacts: Mapping[str, bytes], *, evidence_id: str
) -> ResolvedNativeCell:
    verified = verify_native_manifest(manifest_body, artifacts)
    ev = next((e for e in verified.facts.evidence if e.evidence_id == evidence_id), None)
    if ev is None:
        raise ValueError("native evidence not in this manifest")
    document = next(
        d for d in verified.facts.documents if d.source_version_id == ev.document_version_id
    )
    fact = next(
        f for t in document.tables for row in t.rows for f in row.cells if f.fact_id == ev.fact_id
    )
    cir = next(
        d
        for d in verified.facts.canonical_documents
        if d.document_version_id == ev.document_version_id
    )
    cell = next(c for b in cir.blocks if b.table for c in b.table.cells if c.id == ev.cell_id)
    return ResolvedNativeCell(
        fact=fact,
        evidence=ev,
        cell=cell,
        sheet=cir.metadata["sheets"][ev.source_refs[0].page_index0],
    )
