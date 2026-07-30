"""Pinned-context JSON-LD and deterministic JSONL exporters."""

from __future__ import annotations

import json

from akc_cir import CanonicalDocument, KnowledgeBundle, RagChunk, canonical_json

AKMP_CONTEXT = {
    "@version": 1.1,
    "akmp": "https://schemas.aiknowledgecompiler.dev/akmp/v1#",
    "dcterms": "http://purl.org/dc/terms/",
    "schema": "https://schema.org/",
    "KnowledgeNote": "akmp:KnowledgeNote",
    "RelationAssertion": "akmp:RelationAssertion",
    "title": "dcterms:title",
    "noteType": "akmp:noteType",
    "origin": "akmp:origin",
    "reviewStatus": "akmp:reviewStatus",
    "assertionStatus": "akmp:assertionStatus",
    "confidence": "akmp:confidence",
    "source": {"@id": "dcterms:source", "@type": "@id"},
    "supportedBy": {
        "@id": "akmp:supportedBy",
        "@type": "@id",
        "@container": "@set",
    },
    "subject": {"@id": "akmp:subject", "@type": "@id"},
    "predicate": {"@id": "akmp:predicate", "@type": "@id"},
    "object": {"@id": "akmp:object", "@type": "@id"},
    "appliesTo": {"@id": "akmp:appliesTo", "@type": "@id"},
    "created": {
        "@id": "dcterms:created",
        "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
    },
}

KNOWLEDGE_NOTE_SHACL = """@prefix akmp: <https://schemas.aiknowledgecompiler.dev/akmp/v1#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

akmp:KnowledgeNoteShape
  a sh:NodeShape ;
  sh:targetClass akmp:KnowledgeNote ;
  sh:closed false ;
  sh:property [
    sh:path dcterms:title ;
    sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:datatype xsd:string ;
    sh:minLength 1
  ] ;
  sh:property [
    sh:path akmp:noteType ;
    sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:datatype xsd:string
  ] ;
  sh:property [
    sh:path dcterms:source ;
    sh:minCount 1 ;
    sh:nodeKind sh:IRI
  ] ;
  sh:property [
    sh:path akmp:supportedBy ;
    sh:minCount 1 ;
    sh:nodeKind sh:IRI
  ] ;
  sh:property [
    sh:path akmp:origin ;
    sh:minCount 1 ;
    sh:maxCount 1 ;
    sh:in (
      "native_extracted"
      "ocr_extracted"
      "rule_reconstructed"
      "ai_reconstructed"
      "ai_summarized"
      "ai_inferred"
      "user_edited"
    )
  ] .
"""


def context_jsonld() -> str:
    return (
        json.dumps(
            {"@context": AKMP_CONTEXT},
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def knowledge_jsonld(document: CanonicalDocument, bundle: KnowledgeBundle) -> str:
    available_block_ids = {block.id for block in document.blocks}
    graph: list[dict[str, object]] = []
    for note in sorted(bundle.notes, key=lambda item: item.note_id):
        evidence = sorted(
            {
                *note.evidence_block_ids,
                *(block_id for claim in note.claims for block_id in claim.source_block_ids),
            }
        )
        missing = sorted(set(evidence) - available_block_ids)
        if missing:
            raise ValueError(f"knowledge note references unknown blocks: {missing}")
        graph.append(
            {
                "@id": note.note_id,
                "@type": "akmp:KnowledgeNote",
                "title": note.title,
                "noteType": note.note_type.value,
                "origin": note.content_origin.value,
                "source": (
                    document.document_id
                    if document.document_id.startswith("urn:")
                    else f"urn:akmp:doc:{document.document_id}"
                ),
                "supportedBy": [
                    block_id if block_id.startswith("urn:") else f"urn:akmp:block:{block_id}"
                    for block_id in evidence
                ],
                "reviewStatus": note.review_status.value,
            }
        )
    for relation in sorted(bundle.relations, key=lambda item: item.id):
        missing = sorted(set(relation.evidence_block_ids) - available_block_ids)
        if missing:
            raise ValueError(f"relation references unknown blocks: {missing}")
        graph.append(
            {
                "@id": relation.id,
                "@type": "akmp:RelationAssertion",
                "subject": relation.subject,
                "predicate": relation.predicate,
                "object": relation.object,
                "assertionStatus": relation.assertion_status.value,
                "confidence": relation.confidence,
                "supportedBy": [
                    block_id if block_id.startswith("urn:") else f"urn:akmp:block:{block_id}"
                    for block_id in relation.evidence_block_ids
                ],
                "reviewStatus": relation.review_status.value,
            }
        )
    return (
        json.dumps(
            {"@context": AKMP_CONTEXT, "@graph": graph},
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def chunks_jsonl(chunks: tuple[RagChunk, ...]) -> str:
    return "\n".join(canonical_json(chunk) for chunk in chunks) + ("\n" if chunks else "")


def documents_jsonl(document: CanonicalDocument) -> str:
    payload = {
        "documentId": document.document_id,
        "documentVersion": document.document_version_id,
        "title": document.title,
        "sourceSha256": document.source_sha256,
        "contentLayer": document.content_layer.value,
        "contentHash": document.source_sha256,
    }
    return canonical_json(payload) + "\n"
