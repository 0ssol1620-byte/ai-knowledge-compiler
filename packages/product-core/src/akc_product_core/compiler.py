"""Candidate-only Product-Core compiler built on the verified CIR primitives."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

from akc_cir.base import canonical_json, sha256_digest
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.identity import (
    LogicalMatch,
    LogicalUnitFingerprint,
    assign_one_to_one,
    document_version_id,
    evidence_id,
    logical_id_seed,
    normalize_text_for_identity,
    source_id,
)
from akc_cir.knowledge_model import (
    CanonicalKnowledgeModel,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    build_knowledge_object,
)
from akc_cir.models import (
    BlockOrigin,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    SourceRef,
)
from akc_cir.recompilation import (
    ArtifactState,
    content_hash,
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    SemanticChange,
    SemanticDiff,
    UnitSnapshot,
    diff_documents,
)
from akc_domain_packs import ArchitecturePlan, ArchitectureProfile, plan_architecture

from .contracts import (
    CandidateArtifact,
    CandidatePackage,
    CandidatePackageFile,
    CandidateWorld,
    PreviousUnit,
    ProductCoreCompileRequest,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreReceipt,
)
from .semantics import SemanticClaim, SemanticCompilation, SemanticSource, compile_semantics


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(f"{len(part)}:{part}" for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _shape(units: Iterable[UnitSnapshot]) -> DocumentShape:
    rows = tuple(units)
    return DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in rows),
        block_count=len(rows),
    )


def _snapshot(unit: PreviousUnit) -> UnitSnapshot:
    return UnitSnapshot(
        logical_id=unit.logical_id,
        text=unit.text,
        document_path=unit.document_path,
        anchor=unit.anchor,
        neighbour_anchors=unit.neighbour_anchors,
        evidence_id=unit.evidence_id,
        page_number1=unit.page_number1,
        authority=unit.authority,
    )


def _fingerprint(unit: UnitSnapshot, source_lineage: str) -> LogicalUnitFingerprint:
    return unit.fingerprint(source_lineage=source_lineage)


def _diff_input_digest(source_sha256: str, units: Iterable[UnitSnapshot]) -> str:
    """Bind diff's binary fast path to supplied extraction and trust inputs too.

    Source bytes can stay fixed while OCR, citation geometry or authority changes.
    These are compilation inputs, not a claim that the source bytes changed.
    Keep this digest internal; source/version identities retain the source hash.
    """
    return content_hash(
        {
            "sourceSha256": source_sha256,
            "units": [
                {
                    "logicalId": unit.logical_id,
                    "text": unit.text,
                    "documentPath": unit.document_path,
                    "anchor": unit.anchor,
                    "evidenceId": unit.evidence_id,
                    "pageNumber1": unit.page_number1,
                    "authority": unit.authority,
                }
                for unit in sorted(units, key=lambda item: item.logical_id)
            ],
        }
    )


@dataclass(frozen=True)
class DocumentFragment:
    """Document extraction result bound to one immutable collection revision context."""

    connector_type: str
    native_id: str
    scope_digest: str
    document_digest: str
    canonical_document: CanonicalDocument
    units: tuple[PreviousUnit, ...]
    changes: tuple[SemanticChange, ...]
    review_reasons: tuple[str, ...]
    output_digest: str = ""

    def content_digest(self) -> str:
        return sha256_digest(
            _json_bytes(
                {
                    "canonicalDocument": self.canonical_document.model_dump(
                        mode="json", by_alias=True
                    ),
                    "units": [unit.model_dump(mode="json", by_alias=True) for unit in self.units],
                    "changes": [change.as_record() for change in self.changes],
                    "reviewReasons": self.review_reasons,
                }
            )
        )


class ProductCoreCompiler:
    """Compile an immutable OCR collection into a non-promoted candidate world."""

    def __init__(self, *, core_release_digest: str) -> None:
        if not core_release_digest.startswith("sha256:") or len(core_release_digest) != 71:
            raise ValueError("core release digest must be sha256:")
        self.core_release_digest = core_release_digest

    def compile(
        self,
        request: ProductCoreCompileRequest,
        *,
        input_sha256: str,
    ) -> ProductCoreCompileResponse:
        return self.reduce_fragments(
            request, self.compile_fragments(request), input_sha256=input_sha256
        )

    def _fragment_scope(self, request: ProductCoreCompileRequest) -> str:
        return sha256_digest(
            _json_bytes(
                {
                    "tenantId": request.tenant_id,
                    "workspaceId": request.workspace_id,
                    "collectionId": request.collection_id,
                    "previous": request.previous_active_world.model_dump(mode="json", by_alias=True)
                    if request.previous_active_world
                    else None,
                    "coreReleaseDigest": self.core_release_digest,
                }
            )
        )

    def compile_fragments(
        self,
        request: ProductCoreCompileRequest,
        document_keys: tuple[tuple[str, str], ...] | None = None,
    ) -> tuple[DocumentFragment, ...]:
        """Extract a bounded document shard without making shard-local semantic decisions."""
        selected = set(document_keys) if document_keys is not None else None
        available = {(doc.connector_type, doc.native_id) for doc in request.documents}
        if selected is not None and (
            len(selected) != len(document_keys or ()) or not selected <= available
        ):
            raise ValueError("fragment selection is duplicated or outside the collection")
        prior_by_source: defaultdict[str, list[PreviousUnit]] = defaultdict(list)
        if request.previous_active_world:
            for unit in request.previous_active_world.units:
                prior_by_source[unit.source_id].append(unit)
        fragments = []
        scope = self._fragment_scope(request)
        for document in sorted(
            request.documents, key=lambda item: (item.connector_type, item.native_id)
        ):
            if (
                selected is not None
                and (document.connector_type, document.native_id) not in selected
            ):
                continue
            derived_source = source_id(
                tenant_id=request.tenant_id,
                connector_type=document.connector_type,
                native_id=document.native_id,
            )
            compiled, units, changes, reviews = self._compile_document(
                request=request,
                document=document,
                previous=tuple(prior_by_source.get(derived_source, ())),
            )
            fragments.append(
                DocumentFragment(
                    connector_type=document.connector_type,
                    native_id=document.native_id,
                    scope_digest=scope,
                    document_digest=sha256_digest(
                        _json_bytes(document.model_dump(mode="json", by_alias=True))
                    ),
                    canonical_document=compiled,
                    units=tuple(units),
                    changes=changes,
                    review_reasons=tuple(reviews),
                )
            )
        return tuple(
            replace(fragment, output_digest=fragment.content_digest()) for fragment in fragments
        )

    def reduce_fragments(
        self,
        request: ProductCoreCompileRequest,
        fragments: Iterable[DocumentFragment],
        *,
        input_sha256: str,
    ) -> ProductCoreCompileResponse:
        """One collection-wide semantic/dependency reduction, independent of shard boundaries."""
        inventory = tuple(fragments)
        if any(not isinstance(item, DocumentFragment) for item in inventory):
            raise ValueError("malformed document fragment")
        ordered = sorted(inventory, key=lambda item: (item.connector_type, item.native_id))
        expected = {(doc.connector_type, doc.native_id): doc for doc in request.documents}
        keys = [(item.connector_type, item.native_id) for item in ordered]
        if len(set(keys)) != len(keys) or set(keys) != set(expected):
            raise ValueError("collection fragments must cover every document exactly once")
        scope = self._fragment_scope(request)
        for fragment in ordered:
            document = expected[(fragment.connector_type, fragment.native_id)]
            digest = sha256_digest(_json_bytes(document.model_dump(mode="json", by_alias=True)))
            if (
                fragment.scope_digest != scope
                or fragment.document_digest != digest
                or fragment.output_digest != fragment.content_digest()
            ):
                raise ValueError("fragment does not belong to this immutable collection revision")
        previous = request.previous_active_world
        prior_by_source: defaultdict[str, list[PreviousUnit]] = defaultdict(list)
        if previous:
            for unit in previous.units:
                prior_by_source[unit.source_id].append(unit)
        canonical_documents = [fragment.canonical_document for fragment in ordered]
        current_units = [unit for fragment in ordered for unit in fragment.units]
        all_changes = [change for fragment in ordered for change in fragment.changes]
        review_reasons = [reason for fragment in ordered for reason in fragment.review_reasons]
        immutable_inputs_only = self._immutable_inputs_only(request)
        if not immutable_inputs_only:
            review_reasons.append("IMMUTABLE_INPUT_BINDING_INVALID")

        if previous is not None:
            current_sources = {
                source_id(
                    tenant_id=request.tenant_id,
                    connector_type=document.connector_type,
                    native_id=document.native_id,
                )
                for document in request.documents
            }
            for removed in sorted(set(prior_by_source) - current_sources):
                for unit in prior_by_source[removed]:
                    all_changes.append(
                        SemanticChange(
                            kind=ChangeKind.UNIT_REMOVED,
                            logical_id=unit.logical_id,
                            before=unit.text,
                            detail="source removed from collection",
                        )
                    )

        diff = self._aggregate_diff(all_changes, initial=previous is None)
        semantics = compile_semantics(
            tuple(
                SemanticSource(
                    logical_id=unit.logical_id,
                    source_id=unit.source_id,
                    source_version_id=unit.source_version_id,
                    evidence_id=unit.evidence_id,
                    text=unit.text,
                    authority=unit.authority or "unclassified",
                )
                for unit in current_units
            )
        )
        architecture = plan_architecture(
            ArchitectureProfile(
                domain=semantics.domain,
                object_types=semantics.object_types,
                user_goal="Build an evidence-bound living knowledge world",
                corpus_size=len(canonical_documents),
                temporal_structure=semantics.temporal_structure,
                requested_blueprint=request.requested_blueprint,
            )
        )
        if not semantics.claims:
            review_reasons.append("SEMANTIC_CLAIMS_EMPTY")
        review_reasons.extend(
            f"CONTRADICTION_CANDIDATE:{item.contradiction_id}" for item in semantics.contradictions
        )
        knowledge_model = self._knowledge_model(
            request,
            canonical_documents,
            current_units,
            semantics,
            architecture,
        )
        graph, artifacts = self._dependency_graph_and_artifacts(
            canonical_documents,
            knowledge_model,
            current_units,
            semantics,
        )
        plan = plan_recompilation(diff=diff, graph=graph, artifacts=artifacts)
        if previous is not None:
            # Collection aggregates include attempt provenance (creation time,
            # activity IDs and identity-resolution state). The previous snapshot
            # supplies no provenance dependency inputs, so semantic impact alone
            # cannot establish that these byte-level artifacts are reusable.
            # Rebuild them conservatively while retaining per-unit selectivity.
            aggregates = {
                "canonical/model",
                "knowledge/model",
                "retrieval/global",
                "export/package",
            }
            plan = replace(
                plan,
                targets=tuple(
                    replace(
                        target,
                        state=ArtifactState.STALE,
                        reason="collection aggregate includes compilation attempt provenance",
                    )
                    if target.artifact_id in aggregates
                    else target
                    for target in plan.targets
                ),
            )
        full_hashes = self._artifact_hashes(
            canonical_documents=canonical_documents,
            knowledge_model=knowledge_model,
            units=current_units,
            semantics=semantics,
            architecture=architecture,
            artifacts=artifacts,
        )

        if previous is None:
            equivalence = "not_run"
            rebuilt = dict(full_hashes)
            carried: dict[str, str] = {}
        else:
            rebuild_ids = set(plan.to_rebuild)
            rebuilt = {key: value for key, value in full_hashes.items() if key in rebuild_ids}
            carried = {
                key: value
                for key, value in previous.artifact_hashes.items()
                if key in full_hashes and key not in rebuild_ids
            }
            report = verify_equivalence(
                full_rebuild=full_hashes,
                selective_rebuild=rebuilt,
                carried_over=carried,
                plan=plan,
            )
            equivalence = "passed" if report.equivalent else "failed"
            if not report.equivalent:
                review_reasons.append("FULL_REBUILD_EQUIVALENCE_FAILED")

        lifecycle = "candidate"
        status = "completed"
        if review_reasons:
            lifecycle = "review_required"
            status = "review_required"
        if equivalence == "failed":
            lifecycle = "rejected"
            status = "rejected"

        parent_id = previous.world_state_id if previous else None
        world_state_id = _stable_id(
            "ws",
            request.tenant_id,
            request.workspace_id,
            request.collection_id,
            parent_id or "root",
            sha256_digest(_json_bytes(full_hashes)),
        )
        manifest_digest = sha256_digest(
            _json_bytes(
                {
                    "worldStateId": world_state_id,
                    "parentWorldStateId": parent_id,
                    "coreReleaseDigest": self.core_release_digest,
                    "artifactHashes": full_hashes,
                }
            )
        )
        impact = graph.impact_of(diff.changed_logical_ids)
        package, directory_plan = self._package_projection(
            request=request,
            canonical_documents=canonical_documents,
            knowledge_model=knowledge_model,
            units=current_units,
            semantics=semantics,
            architecture=architecture,
            lifecycle=lifecycle,
            review_reasons=review_reasons,
            immutable_inputs_only=immutable_inputs_only,
        )
        candidate = CandidateWorld(
            world_state_id=world_state_id,
            parent_world_state_id=parent_id,
            manifest_digest=manifest_digest,
            lifecycle=lifecycle,
            canonical_documents=tuple(
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in canonical_documents
            ),
            canonical_knowledge_model=knowledge_model.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            units=tuple(current_units),
            artifact_hashes=full_hashes,
            directory_plan=directory_plan,
            package=package,
            validation={
                "status": "passed" if lifecycle == "candidate" else lifecycle,
                "immutableInputsOnly": immutable_inputs_only,
                "deterministicMaterialization": True,
                "sourceCoverage": True,
                "evidenceCoverage": True,
                "fullRebuildEquivalence": equivalence,
                "matchingPolicy": "legacy",
            },
            diff={
                "level": diff.level.value,
                "changeId": diff.change_id,
                "contentChanged": diff.content_changed,
                "changes": [change.as_record() for change in diff.changes],
            },
            impact={
                "changed": list(impact.changed),
                "affected": [
                    {
                        "nodeId": item.node_id,
                        "depth": item.depth,
                        "path": item.describe(),
                    }
                    for item in impact.affected
                ],
                "cycles": [list(cycle) for cycle in impact.cycles_detected],
                "unknownNodes": list(impact.unknown_nodes),
            },
            recompilation=plan.as_record(),
            review_reasons=tuple(sorted(set(review_reasons))),
        )
        candidate_bytes = _json_bytes(
            candidate.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        artifact_rows = self._candidate_artifacts(
            canonical_documents,
            knowledge_model,
            graph,
            candidate,
            candidate_bytes,
            semantics,
            architecture,
        )
        receipt = ProductCoreReceipt(
            request_id=request.request_id,
            input_sha256=input_sha256,
            output_sha256=sha256_digest(candidate_bytes),
            core_release_digest=self.core_release_digest,
            equivalence=equivalence,
            total_artifacts=len(full_hashes),
            rebuilt_artifacts=len(rebuilt),
            work_avoided_artifacts=max(0, len(full_hashes) - len(rebuilt)),
        )
        return ProductCoreCompileResponse(
            status=status,
            candidate=candidate,
            artifacts=artifact_rows,
            receipt=receipt,
        )

    @staticmethod
    def _immutable_inputs_only(request: ProductCoreCompileRequest) -> bool:
        """Check immutable input references, not backend retention or fetched byte integrity.

        The Foundation boundary supplies inline OCR and digest-addressed source/OCR
        references. Both references must bind to this tenant, workspace, document
        and source digest; mutable aliases and cross-scope paths cannot pass.
        Object storage enforcement and source-byte verification belong to intake.
        """
        for document in request.documents:
            keys = (document.immutable_object_key, document.ocr_object_key)
            if keys[0] == keys[1]:
                return False
            parts = [key.split("/") for key in keys]
            # The upload/revision object ID can differ from native_id, which is
            # the stable logical source ID across successive uploads.
            if any(len(row) != 6 for row in parts) or parts[0][:-1] != parts[1][:-1]:
                return False
            for row in parts:
                if row[:3] != ["immutable", request.tenant_id, request.workspace_id]:
                    return False
                if row[4] != document.content_sha256[7:]:
                    return False
                if any(
                    not part
                    or part in {".", ".."}
                    or "\\" in part
                    or any(ord(char) < 32 or ord(char) == 127 for char in part)
                    for part in row
                ):
                    return False
        return True

    def _compile_document(
        self,
        *,
        request: ProductCoreCompileRequest,
        document: ProductCoreDocument,
        previous: tuple[PreviousUnit, ...],
    ) -> tuple[CanonicalDocument, list[PreviousUnit], tuple[SemanticChange, ...], list[str]]:
        derived_source_id = source_id(
            tenant_id=request.tenant_id,
            connector_type=document.connector_type,
            native_id=document.native_id,
        )
        if document.source_id is not None and document.source_id != derived_source_id:
            raise ValueError("sourceId does not match Core stable identity")
        derived_version_id = document_version_id(
            source=derived_source_id,
            content_sha256=document.content_sha256,
        )
        if (
            document.source_version_id is not None
            and document.source_version_id != derived_version_id
        ):
            raise ValueError("sourceVersionId does not match Core stable identity")

        previous_snapshots = [_snapshot(unit) for unit in previous]
        reviews: list[str] = []
        seeds: list[UnitSnapshot] = []
        for region in sorted(document.regions, key=lambda item: item.order):
            if region.bbox1000 is None:
                reviews.append(
                    f"REGION_CITATION_UNAVAILABLE:{derived_source_id}:{region.region_id}"
                )
            if region.authority == "unclassified":
                reviews.append(f"AUTHORITY_UNCLASSIFIED:{derived_source_id}:{region.region_id}")
            path = (document.title, f"page-{region.page_number1}", region.block_type.value)
            anchor = region.native_object_id or region.region_id
            seeds.append(
                UnitSnapshot(
                    logical_id=logical_id_seed(
                        source=derived_source_id,
                        document_path=path,
                        anchor=anchor,
                    ),
                    text=region.text,
                    document_path=path,
                    anchor=anchor,
                    evidence_id=evidence_id(
                        document_version=derived_version_id,
                        page_number1=region.page_number1,
                        bbox1000=(region.bbox1000.as_tuple() if region.bbox1000 else None),
                        span_text=region.text,
                    ),
                    page_number1=region.page_number1,
                    authority=region.authority,
                )
            )

        resolved = list(seeds)
        identity_states = ["new"] * len(seeds)
        if previous_snapshots:
            decisions = assign_one_to_one(
                [_fingerprint(item, derived_source_id) for item in seeds],
                [_fingerprint(item, derived_source_id) for item in previous_snapshots],
            )
            resolved = []
            identity_states = []
            for seed, decision in zip(seeds, decisions, strict=True):
                if decision.match is LogicalMatch.MATCHED and decision.logical_id:
                    resolved.append(replace(seed, logical_id=decision.logical_id))
                    identity_states.append("matched")
                elif decision.match is LogicalMatch.AMBIGUOUS:
                    resolved.append(
                        replace(
                            seed,
                            logical_id=_stable_id("ku_unresolved", derived_version_id, seed.anchor),
                        )
                    )
                    identity_states.append("unresolved")
                else:
                    resolved.append(seed)
                    identity_states.append("new")
                if decision.match is LogicalMatch.AMBIGUOUS:
                    reviews.append(f"IDENTITY_AMBIGUOUS:{derived_source_id}:{seed.anchor}")

        before_sha = previous[0].source_content_sha256 if previous else content_hash("absent")
        document_diff = diff_documents(
            before_sha256=_diff_input_digest(before_sha, previous_snapshots),
            after_sha256=_diff_input_digest(document.content_sha256, resolved),
            level=DiffLevel.GRAPH,
            before_shape=_shape(previous_snapshots),
            after_shape=_shape(resolved),
            before_units=previous_snapshots,
            after_units=resolved,
            source=derived_source_id,
        )
        document_changes = list(document_diff.changes)
        for unit, identity_state in zip(resolved, identity_states, strict=True):
            if identity_state == "unresolved":
                document_changes.append(
                    SemanticChange(
                        kind=ChangeKind.UNIT_ADDED,
                        logical_id=unit.logical_id,
                        after=unit.text,
                        detail="quarantined unresolved identity candidate",
                    )
                )
        regions_by_anchor = {
            region.native_object_id or region.region_id: region for region in document.regions
        }
        blocks: list[CanonicalBlock] = []
        units: list[PreviousUnit] = []
        for unit, identity_state in zip(resolved, identity_states, strict=True):
            region = regions_by_anchor[unit.anchor]
            ref = SourceRef(
                document_id=derived_source_id,
                document_version_id=derived_version_id,
                page_index0=region.page_index0,
                page_number1=region.page_number1,
                bbox1000=region.bbox1000,
                native_object_id=region.native_object_id or region.region_id,
            )
            block_id = _stable_id("block", derived_version_id, region.region_id)
            blocks.append(
                CanonicalBlock(
                    id=block_id,
                    order=region.order,
                    type=region.block_type,
                    content_layer=ContentLayer.EXTRACTED,
                    raw_text=region.text,
                    normalized_text=normalize_text_for_identity(region.text),
                    origin=BlockOrigin.OCR_EXTRACTED,
                    source_refs=(ref,),
                    confidence=region.confidence,
                    content_hash=content_hash(
                        {
                            "text": region.text,
                            "type": region.block_type.value,
                            "sourceRef": ref.model_dump(mode="json", by_alias=True),
                        }
                    ),
                )
            )
            units.append(
                PreviousUnit(
                    logical_id=unit.logical_id,
                    source_id=derived_source_id,
                    source_version_id=derived_version_id,
                    source_content_sha256=document.content_sha256,
                    text=unit.text,
                    document_path=unit.document_path,
                    anchor=unit.anchor,
                    neighbour_anchors=unit.neighbour_anchors,
                    evidence_id=unit.evidence_id or "",
                    page_number1=unit.page_number1 or 1,
                    authority=unit.authority,
                    identity_state=identity_state,
                )
            )
        canonical = CanonicalDocument(
            tenant_id=request.tenant_id,
            document_id=derived_source_id,
            document_version_id=derived_version_id,
            title=document.title,
            source_filename=document.source_filename,
            source_sha256=document.content_sha256,
            content_layer=ContentLayer.EXTRACTED,
            blocks=tuple(blocks),
            metadata={
                "immutableObjectKey": document.immutable_object_key,
                "ocrObjectKey": document.ocr_object_key,
                "pageCount": document.page_count,
                "matchingPolicy": "legacy",
            },
            created_at=request.requested_at,
        )
        return canonical, units, tuple(document_changes), reviews

    def _aggregate_diff(self, changes: list[SemanticChange], *, initial: bool) -> SemanticDiff:
        if initial and not changes:
            raise ValueError("initial compile produced no knowledge units")
        payload = [change.as_record() for change in changes]
        change_id = "chg_" + hashlib.sha256(_json_bytes(payload)).hexdigest()
        return SemanticDiff(
            level=DiffLevel.GRAPH,
            content_changed=bool(changes),
            changes=tuple(changes),
            change_id=change_id,
        )

    def _knowledge_model(
        self,
        request: ProductCoreCompileRequest,
        documents: list[CanonicalDocument],
        units: list[PreviousUnit],
        semantics: SemanticCompilation,
        architecture: ArchitecturePlan,
    ) -> CanonicalKnowledgeModel:
        activity = _stable_id("activity", request.request_id, self.core_release_digest)
        refs_by_version = {
            document.document_version_id: tuple(
                ref for block in document.blocks for ref in block.source_refs
            )
            for document in documents
        }
        objects = []
        document_ids = [_stable_id("ko_document", item.document_id) for item in documents]
        objects.append(
            build_knowledge_object(
                stable_id=_stable_id("ko_collection", request.collection_id),
                tenant_id=request.tenant_id,
                collection_id=request.collection_id,
                kind=KnowledgeObjectKind.COLLECTION,
                source_refs=tuple(ref for refs in refs_by_version.values() for ref in refs),
                origin=KnowledgeOrigin.STRUCTURED_DERIVED,
                verification_state=KnowledgeVerificationState.VERIFIED,
                created_by_activity=activity,
                version=1,
                links=document_ids,
                payload={"workspaceId": request.workspace_id},
            )
        )
        for document, object_id in zip(documents, document_ids, strict=True):
            block_ids = [_stable_id("ko_block", block.id) for block in document.blocks]
            objects.append(
                build_knowledge_object(
                    stable_id=object_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.DOCUMENT,
                    source_refs=refs_by_version[document.document_version_id],
                    origin=KnowledgeOrigin.NATIVE_EXTRACTED,
                    verification_state=KnowledgeVerificationState.VERIFIED,
                    created_by_activity=activity,
                    version=1,
                    links=block_ids,
                    payload={
                        "title": document.title,
                        "documentVersionId": document.document_version_id,
                    },
                )
            )
            for block, block_object_id in zip(document.blocks, block_ids, strict=True):
                objects.append(
                    build_knowledge_object(
                        stable_id=block_object_id,
                        tenant_id=request.tenant_id,
                        collection_id=request.collection_id,
                        kind=KnowledgeObjectKind.BLOCK,
                        source_refs=block.source_refs,
                        origin=KnowledgeOrigin.VISUAL_EXTRACTED,
                        verification_state=KnowledgeVerificationState.VERIFIED_WITH_WARNING,
                        created_by_activity=activity,
                        version=1,
                        payload={"text": block.raw_text, "blockType": block.type.value},
                    )
                )
        block_by_anchor = {
            (document.document_version_id, ref.native_object_id): block
            for document in documents
            for block in document.blocks
            for ref in block.source_refs[:1]
        }
        unit_by_logical = {unit.logical_id: unit for unit in units}
        refs_by_logical: dict[str, tuple[SourceRef, ...]] = {}
        refs_by_evidence: dict[str, tuple[SourceRef, ...]] = {}
        evidence_object_by_id: dict[str, str] = {}
        evidence_units: defaultdict[str, list[PreviousUnit]] = defaultdict(list)
        for unit in units:
            block = block_by_anchor[(unit.source_version_id, unit.anchor)]
            refs_by_logical[unit.logical_id] = block.source_refs
            evidence_units[unit.evidence_id].append(unit)
            combined = (*refs_by_evidence.get(unit.evidence_id, ()), *block.source_refs)
            refs_by_evidence[unit.evidence_id] = tuple(
                {
                    canonical_json(ref.model_dump(mode="json", by_alias=True)): ref
                    for ref in combined
                }.values()
            )
        for evidence_key, supporting_units in evidence_units.items():
            verification_state = (
                KnowledgeVerificationState.UNRESOLVED
                if any(unit.identity_state == "unresolved" for unit in supporting_units)
                else KnowledgeVerificationState.VERIFIED_WITH_WARNING
            )
            evidence_object_id = _stable_id("ko_evidence", evidence_key)
            evidence_object_by_id[evidence_key] = evidence_object_id
            objects.append(
                build_knowledge_object(
                    stable_id=evidence_object_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.EVIDENCE,
                    source_refs=refs_by_evidence[evidence_key],
                    origin=KnowledgeOrigin.VISUAL_EXTRACTED,
                    verification_state=verification_state,
                    created_by_activity=activity,
                    version=1,
                    payload={"evidenceId": evidence_key},
                )
            )

        for claim in semantics.claims:
            unit = unit_by_logical[claim.logical_id]
            verification_state = (
                KnowledgeVerificationState.UNRESOLVED
                if unit.identity_state == "unresolved"
                else KnowledgeVerificationState.VERIFIED_WITH_WARNING
            )
            objects.append(
                build_knowledge_object(
                    stable_id=claim.claim_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.CLAIM,
                    source_refs=refs_by_logical[claim.logical_id],
                    origin=KnowledgeOrigin.RULE_DERIVED,
                    verification_state=verification_state,
                    created_by_activity=activity,
                    version=1,
                    links=(evidence_object_by_id[claim.evidence_id], *claim.entity_ids),
                    payload=claim.as_record(),
                )
            )

        claim_by_id = {claim.claim_id: claim for claim in semantics.claims}
        for entity in semantics.entities:
            entity_refs = tuple(
                {
                    canonical_json(ref.model_dump(mode="json", by_alias=True)): ref
                    for claim_id in entity.claim_ids
                    for ref in refs_by_logical[claim_by_id[claim_id].logical_id]
                }.values()
            )
            objects.append(
                build_knowledge_object(
                    stable_id=entity.entity_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.ENTITY,
                    source_refs=entity_refs,
                    origin=KnowledgeOrigin.RULE_DERIVED,
                    verification_state=KnowledgeVerificationState.VERIFIED_WITH_WARNING,
                    created_by_activity=activity,
                    version=1,
                    payload=entity.as_record(),
                )
            )

        for relation in semantics.relations:
            objects.append(
                build_knowledge_object(
                    stable_id=relation.relation_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.RELATION,
                    source_refs=refs_by_logical[claim_by_id[relation.subject_id].logical_id],
                    origin=KnowledgeOrigin.RULE_DERIVED,
                    verification_state=KnowledgeVerificationState.VERIFIED_WITH_WARNING,
                    created_by_activity=activity,
                    version=1,
                    links=(relation.subject_id, relation.object_id),
                    payload=relation.as_record(),
                )
            )

        for contradiction in semantics.contradictions:
            left = claim_by_id[contradiction.claim_ids[0]]
            right = claim_by_id[contradiction.claim_ids[1]]
            objects.append(
                build_knowledge_object(
                    stable_id=contradiction.contradiction_id,
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.VALIDATION_RECORD,
                    source_refs=(
                        *refs_by_evidence[left.evidence_id],
                        *refs_by_evidence[right.evidence_id],
                    ),
                    origin=KnowledgeOrigin.RULE_DERIVED,
                    verification_state=KnowledgeVerificationState.UNRESOLVED,
                    created_by_activity=activity,
                    version=1,
                    links=contradiction.claim_ids,
                    payload=contradiction.as_record(),
                )
            )

        first_ref = next(ref for refs in refs_by_version.values() for ref in refs)
        for object_type in semantics.object_types:
            objects.append(
                build_knowledge_object(
                    stable_id=_stable_id(
                        "ontology_term", architecture.blueprint, object_type.casefold()
                    ),
                    tenant_id=request.tenant_id,
                    collection_id=request.collection_id,
                    kind=KnowledgeObjectKind.ONTOLOGY_TERM,
                    source_refs=(first_ref,),
                    origin=KnowledgeOrigin.STRUCTURED_DERIVED,
                    verification_state=KnowledgeVerificationState.VERIFIED,
                    created_by_activity=activity,
                    version=1,
                    payload={
                        "term": object_type,
                        "blueprint": architecture.blueprint,
                        "blueprintVersion": architecture.blueprint_version,
                        "moduleSha256": architecture.module_sha256,
                    },
                )
            )
        return CanonicalKnowledgeModel(
            tenant_id=request.tenant_id,
            collection_id=request.collection_id,
            objects=tuple(objects),
        )

    def _dependency_graph_and_artifacts(
        self,
        documents: list[CanonicalDocument],
        model: CanonicalKnowledgeModel,
        units: list[PreviousUnit],
        semantics: SemanticCompilation,
    ) -> tuple[DependencyGraph, tuple[str, ...]]:
        edges: list[DependencyEdge] = []
        artifacts = ["canonical/model", "knowledge/model", "retrieval/global", "export/package"]
        for unit in units:
            claim_id = unit.logical_id
            evidence_node = f"evidence/{unit.evidence_id}"
            edges.append(DependencyEdge(evidence_node, claim_id, EdgeType.SUPPORTS))
            for suffix in ("rag", "answer", "export"):
                artifact = f"artifact/{suffix}/{claim_id}"
                artifacts.append(artifact)
                edges.append(DependencyEdge(claim_id, artifact, EdgeType.CONSUMED_BY))
            for artifact in (
                "canonical/model",
                "knowledge/model",
                "retrieval/global",
                "export/package",
            ):
                edges.append(DependencyEdge(claim_id, artifact, EdgeType.CONSUMED_BY))
        for claim in semantics.claims:
            edges.append(DependencyEdge(claim.claim_id, claim.logical_id, EdgeType.DERIVED_FROM))
            for entity_id in claim.entity_ids:
                edges.append(DependencyEdge(entity_id, claim.claim_id, EdgeType.DERIVED_FROM))
        for contradiction in semantics.contradictions:
            for claim_id in contradiction.claim_ids:
                edges.append(
                    DependencyEdge(
                        contradiction.contradiction_id,
                        claim_id,
                        EdgeType.DERIVED_FROM,
                    )
                )
        _ = documents, model
        return DependencyGraph(edges), tuple(dict.fromkeys(artifacts))

    def _artifact_hashes(
        self,
        *,
        canonical_documents: list[CanonicalDocument],
        knowledge_model: CanonicalKnowledgeModel,
        units: list[PreviousUnit],
        semantics: SemanticCompilation,
        architecture: ArchitecturePlan,
        artifacts: tuple[str, ...],
    ) -> dict[str, str]:
        unit_by_id = {unit.logical_id: unit for unit in units}
        claims_by_logical: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for claim in semantics.claims:
            claims_by_logical[claim.logical_id].append(claim.as_record())
        canonical_payload = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in canonical_documents
        ]
        knowledge_payload = knowledge_model.model_dump(mode="json", by_alias=True)
        semantic_payload = {
            "profile": semantics.profile_record(),
            "claims": [claim.as_record() for claim in semantics.claims],
            "entities": [entity.as_record() for entity in semantics.entities],
            "relations": [relation.as_record() for relation in semantics.relations],
            "contradictions": [
                contradiction.as_record() for contradiction in semantics.contradictions
            ],
            "architecture": architecture.model_dump(mode="json", by_alias=True),
        }
        hashes: dict[str, str] = {
            "canonical/model": sha256_digest(_json_bytes(canonical_payload)),
            "knowledge/model": sha256_digest(_json_bytes(knowledge_payload)),
            "retrieval/global": sha256_digest(
                _json_bytes(
                    {
                        "units": [unit.model_dump(mode="json", by_alias=True) for unit in units],
                        "semantics": semantic_payload,
                    }
                )
            ),
            "export/package": sha256_digest(
                _json_bytes(
                    {
                        "canonical": canonical_payload,
                        "knowledge": knowledge_payload,
                        "semantics": semantic_payload,
                    }
                )
            ),
        }
        for artifact in artifacts:
            if not artifact.startswith("artifact/"):
                continue
            logical_id = artifact.rsplit("/", 1)[-1]
            unit = unit_by_id[logical_id]
            hashes[artifact] = content_hash(
                {
                    "profile": artifact.split("/", 2)[1],
                    "unit": {
                        "logicalId": unit.logical_id,
                        "sourceVersionId": unit.source_version_id,
                        "text": unit.text,
                        "evidenceId": unit.evidence_id,
                        "authority": unit.authority,
                        "semanticClaims": claims_by_logical[unit.logical_id],
                    },
                }
            )
        return dict(sorted(hashes.items()))

    @staticmethod
    def _csv(value: object) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    @staticmethod
    def _package_media_type(path: str) -> str:
        if path.endswith(".md"):
            return "text/markdown; charset=utf-8"
        if path.endswith(".ttl"):
            return "text/turtle; charset=utf-8"
        if path.endswith(".csv"):
            return "text/csv; charset=utf-8"
        if path.endswith(".jsonld"):
            return "application/ld+json"
        if path.endswith(".jsonl"):
            return "application/x-ndjson"
        return "application/json"

    def _package_projection(
        self,
        *,
        request: ProductCoreCompileRequest,
        canonical_documents: list[CanonicalDocument],
        knowledge_model: CanonicalKnowledgeModel,
        units: list[PreviousUnit],
        semantics: SemanticCompilation,
        architecture: ArchitecturePlan,
        lifecycle: str,
        review_reasons: list[str],
        immutable_inputs_only: bool,
    ) -> tuple[CandidatePackage, tuple[dict[str, object], ...]]:
        model_payload = knowledge_model.model_dump(mode="json", by_alias=True)
        objects = list(model_payload["objects"])
        jsonld = {
            "@context": {
                "@vocab": "urn:tavonel:",
                "evidence": "http://www.w3.org/ns/prov#wasDerivedFrom",
            },
            "@graph": [
                {
                    "@id": f"urn:tavonel:{item['stableId']}",
                    "@type": item["kind"],
                    "evidence": [
                        {
                            "documentId": ref["documentId"],
                            "documentVersionId": ref["documentVersionId"],
                            "pageNumber1": ref["pageNumber1"],
                            "bbox1000": ref.get("bbox1000"),
                        }
                        for ref in item["sourceRefs"]
                    ],
                    **item["payload"],
                }
                for item in objects
            ],
        }
        ttl_lines = [
            "@prefix tav: <urn:tavonel:> .",
            "@prefix prov: <http://www.w3.org/ns/prov#> .",
            "",
        ]
        for item in objects:
            ttl_lines.append(f"<urn:tavonel:{item['stableId']}> a tav:{item['kind']} .")
            for link in item["links"]:
                ttl_lines.append(
                    f"<urn:tavonel:{item['stableId']}> tav:linksTo <urn:tavonel:{link}> ."
                )
        node_csv = (
            "id,kind,payload,verification_state\n"
            + "\n".join(
                ",".join(
                    (
                        self._csv(item["stableId"]),
                        self._csv(item["kind"]),
                        self._csv(canonical_json(item["payload"])),
                        self._csv(item["verificationState"]),
                    )
                )
                for item in objects
            )
            + "\n"
        )
        relation_rows = [
            ",".join(
                (
                    self._csv(_stable_id("edge", item["stableId"], link)),
                    self._csv(item["stableId"]),
                    self._csv("links_to"),
                    self._csv(link),
                )
            )
            for item in objects
            for link in item["links"]
        ]
        relation_csv = "id,subject_id,predicate,object_id\n" + "\n".join(relation_rows) + "\n"
        document_jsonl = "".join(
            canonical_json(
                {
                    "documentId": item.document_id,
                    "documentVersionId": item.document_version_id,
                    "title": item.title,
                    "sourceSha256": item.source_sha256,
                }
            )
            + "\n"
            for item in canonical_documents
        )
        evidence_refs = {
            item["payload"]["evidenceId"]: item["sourceRefs"][0]
            for item in objects
            if item["kind"] == "evidence"
            and item["sourceRefs"]
            and isinstance(item["payload"].get("evidenceId"), str)
        }
        claims_by_logical: defaultdict[str, list[SemanticClaim]] = defaultdict(list)
        for claim in semantics.claims:
            claims_by_logical[claim.logical_id].append(claim)
        entity_names = {entity.entity_id: entity.canonical_name for entity in semantics.entities}
        chunk_jsonl = "".join(
            canonical_json(
                {
                    "chunkId": _stable_id("chunk", unit.logical_id),
                    "logicalId": unit.logical_id,
                    "text": unit.text,
                    "sourceId": unit.source_id,
                    "sourceVersionId": unit.source_version_id,
                    "evidenceId": unit.evidence_id,
                    "pageNumber1": unit.page_number1,
                    "bbox1000": evidence_refs[unit.evidence_id].get("bbox1000"),
                    "authority": unit.authority,
                    "authorityTier": (
                        claims_by_logical[unit.logical_id][0].authority_tier
                        if claims_by_logical[unit.logical_id]
                        else "unclassified"
                    ),
                    "authorityScore": (
                        claims_by_logical[unit.logical_id][0].authority_score
                        if claims_by_logical[unit.logical_id]
                        else 0.0
                    ),
                    "claimIds": [claim.claim_id for claim in claims_by_logical[unit.logical_id]],
                    "entityIds": list(
                        dict.fromkeys(
                            entity_id
                            for claim in claims_by_logical[unit.logical_id]
                            for entity_id in claim.entity_ids
                        )
                    ),
                    "entityNames": list(
                        dict.fromkeys(
                            entity_names[entity_id]
                            for claim in claims_by_logical[unit.logical_id]
                            for entity_id in claim.entity_ids
                        )
                    ),
                    "languages": list(
                        dict.fromkeys(
                            claim.language for claim in claims_by_logical[unit.logical_id]
                        )
                    ),
                    "temporalRefs": list(
                        dict.fromkeys(
                            temporal_ref
                            for claim in claims_by_logical[unit.logical_id]
                            for temporal_ref in claim.temporal_refs
                        )
                    ),
                    "retrievalTerms": list(
                        dict.fromkeys(
                            term
                            for claim in claims_by_logical[unit.logical_id]
                            for term in claim.retrieval_terms
                        )
                    ),
                }
            )
            + "\n"
            for unit in units
        )
        provenance_jsonl = "".join(
            canonical_json(
                {
                    "type": "core.region.compiled.v2",
                    "requestId": request.request_id,
                    "logicalId": unit.logical_id,
                    "evidenceId": unit.evidence_id,
                    "identityState": unit.identity_state,
                }
            )
            + "\n"
            for unit in units
        )
        home = (
            "# TAVONEL Candidate Knowledge Package\n\n"
            + f"Blueprint: `{architecture.blueprint}` v{architecture.blueprint_version}\n\n"
            + "## Knowledge views\n\n"
            + "\n".join(f"- [[{view}]]" for view in architecture.root_views)
            + "\n\n## Sources\n\n"
            + "\n".join(
                f"- [[Sources/{item.document_id}|{item.title}]]" for item in canonical_documents
            )
            + "\n"
        )
        claims_jsonl = "".join(
            canonical_json(claim.as_record()) + "\n" for claim in semantics.claims
        )
        entities_jsonl = "".join(
            canonical_json(entity.as_record()) + "\n" for entity in semantics.entities
        )
        relations_jsonl = "".join(
            canonical_json(relation.as_record()) + "\n" for relation in semantics.relations
        )
        contradictions_jsonl = "".join(
            canonical_json(contradiction.as_record()) + "\n"
            for contradiction in semantics.contradictions
        )
        contents: dict[str, str] = {
            "source/collection-files.json": canonical_json(
                [
                    {
                        "documentId": item.document_id,
                        "documentVersionId": item.document_version_id,
                        "sourceSha256": item.source_sha256,
                    }
                    for item in canonical_documents
                ]
            )
            + "\n",
            "canonical/model.json": canonical_json(model_payload) + "\n",
            "obsidian/Home.md": home,
            "ontology/architecture-plan.json": canonical_json(
                architecture.model_dump(mode="json", by_alias=True)
            )
            + "\n",
            "ontology/knowledge.jsonld": canonical_json(jsonld) + "\n",
            "ontology/knowledge.ttl": "\n".join(ttl_lines) + "\n",
            "graph/nodes.csv": node_csv,
            "graph/relationships.csv": relation_csv,
            "semantics/profile.json": canonical_json(semantics.profile_record()) + "\n",
            "semantics/claims.jsonl": claims_jsonl,
            "semantics/entities.jsonl": entities_jsonl,
            "semantics/relations.jsonl": relations_jsonl,
            "semantics/contradictions.jsonl": contradictions_jsonl,
            "rag/documents.jsonl": document_jsonl,
            "rag/chunks.jsonl": chunk_jsonl,
            "rag/retrieval-profile.json": canonical_json(semantics.retrieval_profile) + "\n",
            "provenance/activities.jsonl": provenance_jsonl,
            "validation/report.json": canonical_json(
                {
                    "status": "passed" if lifecycle == "candidate" else lifecycle,
                    "matchingPolicy": "legacy",
                    "candidatePromotion": False,
                    "immutableInputsOnly": immutable_inputs_only,
                    "reviewReasons": sorted(set(review_reasons)),
                    "documentCount": len(canonical_documents),
                    "knowledgeObjectCount": len(objects),
                    "unitCount": len(units),
                    "claimCount": len(semantics.claims),
                    "entityCount": len(semantics.entities),
                    "relationCount": len(semantics.relations),
                    "contradictionCandidateCount": len(semantics.contradictions),
                    "languages": dict(semantics.languages),
                    "blueprint": architecture.blueprint,
                    "architecturePlanSha256": architecture.plan_sha256,
                    "semanticEvidenceCoverage": (
                        sum(1 for claim in semantics.claims if claim.evidence_id)
                        / max(1, len(semantics.claims))
                    ),
                }
            )
            + "\n",
        }
        for item in canonical_documents:
            contents[f"obsidian/Sources/{item.document_id}.md"] = (
                f"---\ndocument_id: {item.document_id}\n"
                f"document_version_id: {item.document_version_id}\n---\n\n"
                f"# {item.title}\n\n"
                + "\n\n".join(block.raw_text or "" for block in item.blocks)
                + "\n"
            )
        files = tuple(
            CandidatePackageFile(
                path=path,
                media_type=self._package_media_type(path),
                size_bytes=len(content.encode("utf-8")),
                sha256=sha256_digest(content),
                content=content,
            )
            for path, content in sorted(contents.items())
        )
        roots = (
            "source",
            "canonical",
            "obsidian",
            "ontology",
            "graph",
            "semantics",
            "rag",
            "provenance",
            "validation",
        )
        directory_plan_rows: list[dict[str, object]] = [
            {"path": root, "kind": "root", "sourceIds": []} for root in roots
        ]
        directory_plan_rows.extend(
            {
                "path": path,
                "kind": "knowledge_view",
                "sourceIds": [],
                "blueprint": architecture.blueprint,
            }
            for path in architecture.folder_paths
        )
        directory_plan_rows.extend(
            {
                "path": file.path,
                "kind": "artifact",
                "sourceIds": [unit.source_id for unit in units],
            }
            for file in files
        )
        directory_plan = tuple(directory_plan_rows)
        return CandidatePackage(roots=roots, files=files), directory_plan

    def _candidate_artifacts(
        self,
        documents: list[CanonicalDocument],
        model: CanonicalKnowledgeModel,
        graph: DependencyGraph,
        candidate: CandidateWorld,
        candidate_bytes: bytes,
        semantics: SemanticCompilation,
        architecture: ArchitecturePlan,
    ) -> tuple[CandidateArtifact, ...]:
        rows = (
            (
                "cir",
                "canonical_ir",
                [item.model_dump(mode="json", by_alias=True) for item in documents],
            ),
            ("knowledge", "knowledge_model", model.model_dump(mode="json", by_alias=True)),
            ("dependency", "dependency_graph", {"nodes": sorted(graph.nodes)}),
            (
                "retrieval",
                "retrieval_index",
                {
                    "units": [
                        item.model_dump(mode="json", by_alias=True) for item in candidate.units
                    ],
                    "claims": [claim.as_record() for claim in semantics.claims],
                    "entities": [entity.as_record() for entity in semantics.entities],
                    "profile": semantics.retrieval_profile,
                    "architecturePlanSha256": architecture.plan_sha256,
                },
            ),
        )
        artifacts = [
            CandidateArtifact(
                artifact_id=_stable_id("artifact", candidate.world_state_id, name),
                kind=kind,
                content_sha256=sha256_digest(_json_bytes(payload)),
                byte_length=len(_json_bytes(payload)),
            )
            for name, kind, payload in rows
        ]
        artifacts.append(
            CandidateArtifact(
                artifact_id=_stable_id("artifact", candidate.world_state_id, "candidate"),
                kind="candidate_world",
                content_sha256=sha256_digest(candidate_bytes),
                byte_length=len(candidate_bytes),
            )
        )
        return tuple(artifacts)
