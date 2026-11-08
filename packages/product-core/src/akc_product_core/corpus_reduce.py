"""`corpus_reduce`: N part compile outputs -> one corpus World (live product-core semantics).

Foundation compiles a corpus larger than one compile in parts. This folds the parts' candidate
Worlds into the World one compile over the whole corpus would have produced. It is the live
Core's merge, not Protected Core's: nothing here replaces or reimplements `akc_cir`, which is
only called (ADR-008).

Rules (PROGRAM-2026-11-04 §4.B, B3):

1. Documents, blocks, evidence, claims and relations have content-derived IDs. They are a
   union; an ID seen in two parts must be byte-identical (attempt fields aside) or the reduce
   refuses with REDUCE_ID_COLLISION.
2. Entities merge across parts only on the compiler's own exact key (the casefolded label is
   the entity ID). Names that only *look* alike are returned as review candidates, never merged.
3. Contradiction candidates, the semantic profile, the architecture plan, ontology terms and
   the collection root are recomputed over the union, so nothing across a part seam is lost.
4. Review reasons: per-document and validation reasons are a union; the rest is recomputed.
   A reason the reduce does not know refuses rather than being dropped.
5. The output is a candidate. Nothing here promotes it; a person activates a World.

Every refusal is a `CorpusReduceError` with a stable code. There is no partial result.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from akc_cir.base import canonical_json, sha256_digest
from akc_cir.identity import source_id
from akc_cir.knowledge_model import (
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    build_knowledge_object,
)
from akc_cir.models import SourceRef
from akc_domain_packs import ArchitectureProfile, plan_architecture

from .compiler import (
    ARCHITECTURE_USER_GOAL,
    VALIDATION_CHECK_REVIEW_REASON,
    _stable_id,
    _wire_numbers,
)
from .contracts import ProductCoreCompileRequest
from .semantics import (
    _DOMAIN_OBJECT_TYPES,
    SemanticClaim,
    SemanticCompilation,
    SemanticEntity,
    SemanticRelation,
    SemanticSource,
    _domain,
    _retrieval_profile,
    contradiction_candidates,
)

REDUCE_VERSION = "tavonel.corpus_reduce.v1"
CORPUS_WORLD_SCHEMA = "tavonel.product_core.corpus_world.v1"
REDUCE_RECEIPT_SCHEMA = "tavonel.product_core.corpus_reduce_receipt.v1"
CANONICAL_FORM_SCHEMA = "tavonel.product_core.world_canonical_form.v1"

_COPIED_KINDS = frozenset({"document", "block", "evidence", "claim", "relation"})
_RECOMPUTED_KINDS = frozenset({"collection", "entity", "validation_record", "ontology_term"})
_PER_DOCUMENT_REASONS = (
    "REGION_CITATION_UNAVAILABLE:",
    "AUTHORITY_UNCLASSIFIED:",
    "IDENTITY_AMBIGUOUS:",
)
_VALIDATION_REASONS = frozenset(VALIDATION_CHECK_REVIEW_REASON.values())
# Attempt provenance, not knowledge: the request time and the activity (a hash of the request
# ID). They differ between any two compiles of the same documents and are left out of every
# byte comparison here. The object `hash` covers the activity, so it goes with it.
_DOCUMENT_ATTEMPT_FIELDS = frozenset({"createdAt"})
_OBJECT_ATTEMPT_FIELDS = frozenset({"createdByActivity", "hash"})


class CorpusReduceError(ValueError):
    """The parts cannot be folded into one World. Nothing is returned."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ReducePart:
    """One part: what was asked (scope and document keys) and the candidate Core answered."""

    corpus_id: str
    part_index: int
    part_count: int
    request_id: str
    input_sha256: str
    tenant_id: str
    workspace_id: str
    collection_id: str
    operation_class: str
    requested_blueprint: str | None
    document_keys: tuple[tuple[str, str], ...]
    response: Mapping[str, Any]

    @classmethod
    def from_compile(
        cls,
        *,
        corpus_id: str,
        part_index: int,
        part_count: int,
        request: ProductCoreCompileRequest,
        input_sha256: str,
        response: Mapping[str, Any],
    ) -> ReducePart:
        """`response` is the `/v2/compile` wire payload; `input_sha256` the digest of the body."""
        return cls(
            corpus_id=corpus_id,
            part_index=part_index,
            part_count=part_count,
            request_id=request.request_id,
            input_sha256=input_sha256,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            collection_id=request.collection_id,
            operation_class=request.route.operation_class,
            requested_blueprint=request.requested_blueprint,
            document_keys=tuple(
                (document.connector_type, document.native_id) for document in request.documents
            ),
            response=response,
        )


def _without(record: Mapping[str, Any], fields: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in fields}


def world_canonical_form(
    *,
    tenant_id: str,
    collection_id: str,
    documents: Sequence[Mapping[str, Any]],
    units: Sequence[Mapping[str, Any]],
    objects: Sequence[Mapping[str, Any]],
    semantic_profile: Mapping[str, Any],
    architecture: Mapping[str, Any],
    review_reasons: Sequence[str],
    lifecycle: str,
) -> dict[str, Any]:
    """The knowledge a World holds, without the attempt that produced it.

    Ordered lists, not sets: the order is part of what a compile emits, so a reduce that gets
    every object right in the wrong order still fails the comparison.
    """
    form: dict[str, Any] = _wire_numbers(
        {
            "schemaVersion": CANONICAL_FORM_SCHEMA,
            "tenantId": tenant_id,
            "collectionId": collection_id,
            "documents": [_without(item, _DOCUMENT_ATTEMPT_FIELDS) for item in documents],
            "units": [dict(item) for item in units],
            "objects": [_without(item, _OBJECT_ATTEMPT_FIELDS) for item in objects],
            "semanticProfile": dict(semantic_profile),
            "architecture": dict(architecture),
            "reviewReasons": sorted(set(review_reasons)),
            "lifecycle": lifecycle,
        }
    )
    return form


def canonical_form_of_compile(response: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical form of one `/v2/compile` wire payload (a whole-corpus or a part World)."""
    candidate = response["candidate"]
    model = candidate["canonicalKnowledgeModel"]
    files = {item["path"]: item["content"] for item in candidate["package"]["files"]}
    return world_canonical_form(
        tenant_id=model["tenantId"],
        collection_id=model["collectionId"],
        documents=candidate["canonicalDocuments"],
        units=candidate["units"],
        objects=model["objects"],
        semantic_profile=json.loads(files["semantics/profile.json"]),
        architecture=json.loads(files["ontology/architecture-plan.json"]),
        review_reasons=candidate.get("reviewReasons", ()),
        lifecycle=candidate["lifecycle"],
    )


def canonical_form_of_corpus_world(world: Mapping[str, Any]) -> dict[str, Any]:
    model = world["canonicalKnowledgeModel"]
    return world_canonical_form(
        tenant_id=model["tenantId"],
        collection_id=model["collectionId"],
        documents=world["canonicalDocuments"],
        units=world["units"],
        objects=model["objects"],
        semantic_profile=world["semanticProfile"],
        architecture=world["architecture"],
        review_reasons=world["reviewReasons"],
        lifecycle=world["lifecycle"],
    )


def _validated(parts: Sequence[ReducePart]) -> list[ReducePart]:
    if not parts:
        raise CorpusReduceError("REDUCE_NO_PARTS", "no parts were supplied")
    counts = {part.part_count for part in parts}
    if len(counts) != 1:
        raise CorpusReduceError("REDUCE_PART_COUNT_MISMATCH", f"parts disagree: {sorted(counts)}")
    count = counts.pop()
    indexes = [part.part_index for part in parts]
    if len(indexes) != len(set(indexes)):
        raise CorpusReduceError("REDUCE_PART_DUPLICATED", f"part indexes {sorted(indexes)}")
    missing = sorted(set(range(count)) - set(indexes))
    extra = sorted(set(indexes) - set(range(count)))
    if missing or extra:
        raise CorpusReduceError(
            "REDUCE_PART_MISSING",
            f"expected {count} parts; missing {missing}, out of range {extra}",
        )
    ordered = sorted(parts, key=lambda part: part.part_index)
    first = ordered[0]

    def scope(part: ReducePart) -> tuple[object, ...]:
        receipt = part.response.get("receipt", {})
        return (
            part.corpus_id,
            part.tenant_id,
            part.workspace_id,
            part.collection_id,
            part.requested_blueprint,
            receipt.get("coreReleaseDigest"),
        )

    for part in ordered:
        if scope(part) != scope(first):
            raise CorpusReduceError(
                "REDUCE_PART_SCOPE_MISMATCH",
                f"part {part.part_index} differs from part {first.part_index} in corpus, tenant, "
                "workspace, collection, blueprint or Core release",
            )
        if part.operation_class != "initial_compile":
            raise CorpusReduceError(
                "REDUCE_PART_NOT_INITIAL",
                f"part {part.part_index} is {part.operation_class}; revisions are B5, not reduce",
            )
        response = part.response
        if response.get("status") == "rejected":
            raise CorpusReduceError("REDUCE_PART_REJECTED", f"part {part.part_index} was rejected")
        receipt = response.get("receipt", {})
        candidate = response.get("candidate")
        if not isinstance(candidate, Mapping):
            raise CorpusReduceError("REDUCE_RECEIPT_INVALID", f"part {part.part_index}: no World")
        output = sha256_digest(canonical_json(candidate).encode("utf-8"))
        if (
            receipt.get("requestId") != part.request_id
            or receipt.get("inputSha256") != part.input_sha256
            or receipt.get("outputSha256") != output
        ):
            raise CorpusReduceError(
                "REDUCE_RECEIPT_INVALID",
                f"part {part.part_index}: the receipt does not bind this request and World",
            )
        model = candidate["canonicalKnowledgeModel"]
        if model.get("tenantId") != part.tenant_id or model.get("collectionId") != (
            part.collection_id
        ):
            raise CorpusReduceError(
                "REDUCE_PART_SCOPE_MISMATCH", f"part {part.part_index}: World scope differs"
            )
    return ordered


def _union(
    store: dict[str, dict[str, Any]],
    owner: dict[str, int],
    key: str,
    value: Mapping[str, Any],
    attempt_fields: frozenset[str],
    part_index: int,
) -> None:
    held = store.get(key)
    if held is None:
        store[key] = dict(value)
        owner[key] = part_index
        return
    if canonical_json(_without(held, attempt_fields)) != canonical_json(
        _without(value, attempt_fields)
    ):
        raise CorpusReduceError(
            "REDUCE_ID_COLLISION",
            f"{key} differs between part {owner[key]} and part {part_index}",
        )


def _claim(payload: Mapping[str, Any]) -> SemanticClaim:
    return SemanticClaim(
        claim_id=payload["claimId"],
        logical_id=payload["logicalId"],
        source_id=payload["sourceId"],
        source_version_id=payload["sourceVersionId"],
        evidence_id=payload["evidenceId"],
        text=payload["text"],
        language=payload["language"],
        polarity=payload["polarity"],
        modality=payload["modality"],
        authority=payload["authority"],
        authority_tier=payload["authorityTier"],
        authority_score=float(payload["authorityScore"]),
        temporal_refs=tuple(payload["temporalRefs"]),
        numeric_values=tuple(payload["numericValues"]),
        entity_ids=tuple(payload["entityIds"]),
        topic_key=payload["topicKey"],
        retrieval_terms=tuple(payload["retrievalTerms"]),
    )


def _review_candidates(entities: Sequence[SemanticEntity]) -> list[dict[str, Any]]:
    """Entities whose names agree once case, spacing and punctuation are ignored.

    "Globex-Corp" and "Globex Corp" are two IDs to the compiler. They may be one company; they may
    not. A false merge rewrites history that cannot be unwritten, so they are listed for a
    person and never merged.
    """
    groups: dict[str, list[SemanticEntity]] = {}
    for entity in entities:
        key = "".join(
            character for character in entity.canonical_name.casefold() if character.isalnum()
        )
        if key:
            groups.setdefault(key, []).append(entity)
    return [
        {
            "kind": "entity_identity",
            "rule": "alnum_casefold_equal",
            "entityIds": [item.entity_id for item in group],
            "canonicalNames": [item.canonical_name for item in group],
            "decision": "human_review_required",
        }
        for _, group in sorted(groups.items())
        if len(group) > 1
    ]


def corpus_reduce(parts: Sequence[ReducePart]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold verified part Worlds into one corpus World. Returns (world, receipt)."""
    ordered = _validated(parts)
    first = ordered[0]
    tenant, workspace, collection = first.tenant_id, first.workspace_id, first.collection_id

    documents: dict[str, dict[str, Any]] = {}
    document_owner: dict[str, int] = {}
    document_key: dict[str, tuple[str, str]] = {}
    units: dict[str, dict[str, Any]] = {}
    unit_owner: dict[str, int] = {}
    objects: dict[str, dict[str, Any]] = {}
    object_owner: dict[str, int] = {}
    entity_records: dict[tuple[int, str], Mapping[str, Any]] = {}
    reasons: set[str] = set()
    part_rows: list[dict[str, Any]] = []

    for part in ordered:
        candidate = part.response["candidate"]
        keys = {
            source_id(tenant_id=tenant, connector_type=connector, native_id=native): (
                connector,
                native,
            )
            for connector, native in part.document_keys
        }
        part_documents = [item["documentId"] for item in candidate["canonicalDocuments"]]
        if set(part_documents) != set(keys) or len(part_documents) != len(keys):
            raise CorpusReduceError(
                "REDUCE_DOCUMENT_UNKNOWN",
                f"part {part.part_index}: the World's documents are not the documents requested",
            )
        for item in candidate["canonicalDocuments"]:
            document_key[item["documentId"]] = keys[item["documentId"]]
            _union(
                documents,
                document_owner,
                item["documentId"],
                item,
                _DOCUMENT_ATTEMPT_FIELDS,
                part.part_index,
            )
        for unit in candidate["units"]:
            _union(units, unit_owner, unit["logicalId"], unit, frozenset(), part.part_index)
        for item in candidate["canonicalKnowledgeModel"]["objects"]:
            kind = item["kind"]
            if kind == "entity":
                entity_records[(part.part_index, item["stableId"])] = item["payload"]
            elif kind in _COPIED_KINDS:
                _union(
                    objects,
                    object_owner,
                    item["stableId"],
                    item,
                    _OBJECT_ATTEMPT_FIELDS,
                    part.part_index,
                )
            elif kind not in _RECOMPUTED_KINDS:
                raise CorpusReduceError(
                    "REDUCE_OBJECT_KIND_UNKNOWN", f"part {part.part_index}: kind {kind!r}"
                )
        for reason in candidate.get("reviewReasons", ()):
            if reason.startswith(_PER_DOCUMENT_REASONS) or reason in _VALIDATION_REASONS:
                reasons.add(reason)
            elif reason != "SEMANTIC_CLAIMS_EMPTY" and not reason.startswith(
                "CONTRADICTION_CANDIDATE:"
            ):
                raise CorpusReduceError(
                    "REDUCE_REVIEW_REASON_UNKNOWN",
                    f"part {part.part_index}: {reason.split(':', 1)[0]} has no reduce rule",
                )
        part_rows.append(
            {
                "partIndex": part.part_index,
                "requestId": part.request_id,
                "inputSha256": part.input_sha256,
                "outputSha256": part.response["receipt"]["outputSha256"],
                "worldStateId": candidate["worldStateId"],
                "manifestDigest": candidate["manifestDigest"],
                "documentIds": part_documents,
            }
        )

    order = sorted(documents, key=lambda item: document_key[item])
    ordered_documents = [documents[item] for item in order]
    units_by_source: dict[str, list[dict[str, Any]]] = {}
    for unit in units.values():
        units_by_source.setdefault(unit["sourceId"], []).append(unit)
    ordered_units = [unit for item in order for unit in units_by_source.get(item, [])]
    if len(ordered_units) != len(units):
        raise CorpusReduceError("REDUCE_GRAPH_INVALID", "a part unit names no part document")
    claims_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in objects.values():
        if item["kind"] == "claim":
            claims_by_source.setdefault(item["payload"]["sourceId"], []).append(item)
    claims = [claim for item in order for claim in claims_by_source.get(item, [])]

    placed: list[dict[str, Any]] = []

    def take(object_id: str) -> dict[str, Any]:
        found = objects.get(object_id)
        if found is None:
            raise CorpusReduceError("REDUCE_GRAPH_INVALID", f"{object_id} is referenced, absent")
        placed.append(found)
        return found

    for item in order:
        document_object = take(_stable_id("ko_document", item))
        for block_id in document_object["links"]:
            take(block_id)
    for unit in ordered_units:
        take(_stable_id("ko_evidence", unit["evidenceId"]))
    documents_and_evidence = list(placed)
    placed.extend(claims)
    relations = [
        take(_stable_id("relation", claim["stableId"], "mentions", entity_id))
        for claim in claims
        for entity_id in claim["payload"]["entityIds"]
    ]
    if len(placed) != len(objects) or {item["stableId"] for item in placed} != set(objects):
        unplaced = sorted(set(objects) - {item["stableId"] for item in placed})
        raise CorpusReduceError(
            "REDUCE_GRAPH_INVALID",
            f"{len(unplaced)} part objects have no place, e.g. {unplaced[:3]}",
        )

    def refs(evidence: str) -> tuple[SourceRef, ...]:
        found = objects[_stable_id("ko_evidence", evidence)]["sourceRefs"]
        return tuple(SourceRef.model_validate(ref) for ref in found)

    # The activity names this reduce: the corpus and the exact part Worlds it read.
    activity = _stable_id(
        "activity", REDUCE_VERSION, first.corpus_id, *(row["outputSha256"] for row in part_rows)
    )

    def build(**fields: Any) -> dict[str, Any]:
        built = build_knowledge_object(
            tenant_id=tenant,
            collection_id=collection,
            created_by_activity=activity,
            version=1,
            **fields,
        )
        record: dict[str, Any] = _wire_numbers(
            built.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        return record

    mentions: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        for entity_id in claim["payload"]["entityIds"]:
            mentions.setdefault(entity_id, []).append(claim)
    entities: list[SemanticEntity] = []
    cross_part_entities = 0
    for entity_id in sorted(mentions):
        rows = mentions[entity_id]
        record = entity_records.get((object_owner[rows[0]["stableId"]], entity_id))
        if record is None:
            raise CorpusReduceError("REDUCE_GRAPH_INVALID", f"{entity_id} has no part record")
        entities.append(
            SemanticEntity(
                entity_id=entity_id,
                canonical_name=record["canonicalName"],
                entity_type=record["entityType"],
                claim_ids=tuple(dict.fromkeys(row["stableId"] for row in rows)),
                evidence_ids=tuple(dict.fromkeys(row["payload"]["evidenceId"] for row in rows)),
            )
        )
        if len({object_owner[row["stableId"]] for row in rows}) > 1:
            cross_part_entities += 1
    if {entity_id for _, entity_id in entity_records} != set(mentions):
        raise CorpusReduceError("REDUCE_GRAPH_INVALID", "part entities and claim mentions differ")

    semantic_claims = tuple(_claim(item["payload"]) for item in claims)
    claim_by_id = {claim.claim_id: claim for claim in semantic_claims}
    contradictions = contradiction_candidates(semantic_claims)
    languages: Counter[str] = Counter(claim.language for claim in semantic_claims)
    domain = _domain(
        tuple(
            SemanticSource(
                logical_id=unit["logicalId"],
                source_id=unit["sourceId"],
                source_version_id=unit["sourceVersionId"],
                evidence_id=unit["evidenceId"],
                text=unit["text"],
                authority=unit.get("authority") or "unclassified",
            )
            for unit in ordered_units
        )
    )
    semantics = SemanticCompilation(
        domain=domain,
        object_types=_DOMAIN_OBJECT_TYPES[domain],
        languages=tuple(sorted(languages.items())),
        temporal_structure=(
            "explicit" if any(claim.temporal_refs for claim in semantic_claims) else "undated"
        ),
        claims=semantic_claims,
        entities=tuple(entities),
        relations=tuple(
            SemanticRelation(
                relation_id=item["payload"]["relationId"],
                subject_id=item["payload"]["subjectId"],
                predicate="mentions",
                object_id=item["payload"]["objectId"],
                evidence_id=item["payload"]["evidenceId"],
            )
            for item in relations
        ),
        contradictions=contradictions,
        retrieval_profile=_retrieval_profile(
            claims=semantic_claims, entities=tuple(entities), languages=languages
        ),
    )
    architecture = plan_architecture(
        ArchitectureProfile(
            domain=semantics.domain,
            object_types=semantics.object_types,
            user_goal=ARCHITECTURE_USER_GOAL,
            corpus_size=len(order),
            temporal_structure=semantics.temporal_structure,
            requested_blueprint=first.requested_blueprint,
        )
    )

    all_refs = tuple(
        SourceRef.model_validate(ref)
        for document in ordered_documents
        for block in document["blocks"]
        for ref in block["sourceRefs"]
    )
    collection_object = build(
        stable_id=_stable_id("ko_collection", collection),
        kind=KnowledgeObjectKind.COLLECTION,
        source_refs=all_refs,
        origin=KnowledgeOrigin.STRUCTURED_DERIVED,
        verification_state=KnowledgeVerificationState.VERIFIED,
        links=[_stable_id("ko_document", item) for item in order],
        payload={"workspaceId": workspace},
    )
    entity_objects = [
        build(
            stable_id=entity.entity_id,
            kind=KnowledgeObjectKind.ENTITY,
            source_refs=refs(claim_by_id[entity.claim_ids[0]].evidence_id),
            origin=KnowledgeOrigin.RULE_DERIVED,
            verification_state=KnowledgeVerificationState.VERIFIED_WITH_WARNING,
            payload=entity.as_record(),
        )
        for entity in entities
    ]
    contradiction_objects = [
        build(
            stable_id=item.contradiction_id,
            kind=KnowledgeObjectKind.VALIDATION_RECORD,
            source_refs=(
                *refs(claim_by_id[item.claim_ids[0]].evidence_id),
                *refs(claim_by_id[item.claim_ids[1]].evidence_id),
            ),
            origin=KnowledgeOrigin.RULE_DERIVED,
            verification_state=KnowledgeVerificationState.UNRESOLVED,
            links=item.claim_ids,
            payload=item.as_record(),
        )
        for item in contradictions
    ]
    first_ref = all_refs[0]
    ontology_objects = [
        build(
            stable_id=_stable_id("ontology_term", architecture.blueprint, term.casefold()),
            kind=KnowledgeObjectKind.ONTOLOGY_TERM,
            source_refs=(first_ref,),
            origin=KnowledgeOrigin.STRUCTURED_DERIVED,
            verification_state=KnowledgeVerificationState.VERIFIED,
            payload={
                "term": term,
                "blueprint": architecture.blueprint,
                "blueprintVersion": architecture.blueprint_version,
                "moduleSha256": architecture.module_sha256,
            },
        )
        for term in semantics.object_types
    ]
    model_objects = [
        collection_object,
        *documents_and_evidence,
        *claims,
        *entity_objects,
        *relations,
        *contradiction_objects,
        *ontology_objects,
    ]
    identifiers = [item["stableId"] for item in model_objects]
    known = set(identifiers)
    if len(known) != len(identifiers) or any(
        link not in known for item in model_objects for link in item.get("links", ())
    ):
        raise CorpusReduceError(
            "REDUCE_GRAPH_INVALID", "merged graph has duplicate or dangling IDs"
        )

    review_reasons = set(reasons)
    if not semantic_claims:
        review_reasons.add("SEMANTIC_CLAIMS_EMPTY")
    review_reasons.update(
        f"CONTRADICTION_CANDIDATE:{item.contradiction_id}" for item in contradictions
    )
    lifecycle = "review_required" if review_reasons else "candidate"
    claim_owner = {claim["stableId"]: object_owner[claim["stableId"]] for claim in claims}
    cross_part_contradictions = sum(
        1
        for item in contradictions
        if claim_owner[item.claim_ids[0]] != claim_owner[item.claim_ids[1]]
    )
    candidates = _review_candidates(entities)

    knowledge_model = {
        "schemaVersion": "canonical-knowledge-1.0.0",
        "tenantId": tenant,
        "collectionId": collection,
        "objects": model_objects,
    }
    profile: dict[str, Any] = _wire_numbers(semantics.profile_record())
    plan: dict[str, Any] = _wire_numbers(architecture.model_dump(mode="json", by_alias=True))
    form = world_canonical_form(
        tenant_id=tenant,
        collection_id=collection,
        documents=ordered_documents,
        units=ordered_units,
        objects=model_objects,
        semantic_profile=profile,
        architecture=plan,
        review_reasons=sorted(review_reasons),
        lifecycle=lifecycle,
    )
    canonical_sha256 = sha256_digest(canonical_json(form).encode("utf-8"))
    world: dict[str, Any] = {
        "schemaVersion": CORPUS_WORLD_SCHEMA,
        "reduceVersion": REDUCE_VERSION,
        "corpusWorldId": _stable_id("cws", tenant, workspace, collection, canonical_sha256),
        "corpusId": first.corpus_id,
        "tenantId": tenant,
        "workspaceId": workspace,
        "collectionId": collection,
        "coreReleaseDigest": first.response["receipt"]["coreReleaseDigest"],
        "lifecycle": lifecycle,
        "candidatePromotion": False,
        "canonicalDocuments": ordered_documents,
        "units": ordered_units,
        "canonicalKnowledgeModel": knowledge_model,
        "semanticProfile": profile,
        "architecture": plan,
        "reviewReasons": sorted(review_reasons),
        "reviewCandidates": candidates,
        "parts": part_rows,
    }
    receipt = {
        "schemaVersion": REDUCE_RECEIPT_SCHEMA,
        "reduceVersion": REDUCE_VERSION,
        "corpusId": first.corpus_id,
        "corpusWorldId": world["corpusWorldId"],
        "coreReleaseDigest": world["coreReleaseDigest"],
        "partCount": len(ordered),
        "inputs": [
            {key: row[key] for key in ("partIndex", "requestId", "inputSha256", "outputSha256")}
            for row in part_rows
        ],
        "outputSha256": sha256_digest(canonical_json(world).encode("utf-8")),
        "canonicalSha256": canonical_sha256,
        "documentCount": len(order),
        "objectCount": len(model_objects),
        "crossPartEntityCount": cross_part_entities,
        "crossPartContradictionCount": cross_part_contradictions,
        "reviewCandidateCount": len(candidates),
        "lifecycle": lifecycle,
        "candidatePromotion": False,
    }
    return world, receipt


__all__ = [
    "CANONICAL_FORM_SCHEMA",
    "CORPUS_WORLD_SCHEMA",
    "REDUCE_RECEIPT_SCHEMA",
    "REDUCE_VERSION",
    "CorpusReduceError",
    "ReducePart",
    "canonical_form_of_compile",
    "canonical_form_of_corpus_world",
    "corpus_reduce",
    "world_canonical_form",
]
