"""JSON Schema registry generated from the canonical Pydantic contracts."""

from __future__ import annotations

from pydantic import BaseModel

from .collection_events import (
    COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS,
    COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS,
    CollectionEventEnvelope,
    collection_event_payload_field_schema,
)
from .errors import ErrorEnvelope
from .events import ProcessingEvent
from .exports import ExportManifest, QualityReport, RagChunk, SourceMap
from .knowledge import DocumentClassification, KnowledgeBundle, KnowledgeNote, RelationAssertion
from .knowledge_model import CanonicalKnowledgeModel, CanonicalKnowledgeObject
from .models import CanonicalDocument, CanonicalTable

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "canonical-document": CanonicalDocument,
    "canonical-table": CanonicalTable,
    "canonical-knowledge-model": CanonicalKnowledgeModel,
    "canonical-knowledge-object": CanonicalKnowledgeObject,
    "collection-event": CollectionEventEnvelope,
    "processing-event": ProcessingEvent,
    "error-envelope": ErrorEnvelope,
    "document-classification": DocumentClassification,
    "knowledge-note": KnowledgeNote,
    "knowledge-bundle": KnowledgeBundle,
    "relation-assertion": RelationAssertion,
    "source-map": SourceMap,
    "rag-chunk": RagChunk,
    "quality-report": QualityReport,
    "export-manifest": ExportManifest,
}


def json_schema(name: str) -> dict[str, object]:
    try:
        model = SCHEMA_MODELS[name]
    except KeyError as exc:
        raise KeyError(f"unknown schema {name!r}") from exc
    schema = model.model_json_schema(by_alias=True, mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://schemas.aiknowledgecompiler.dev/{name}/1.0.0"
    if name == "collection-event":
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"event_type": {"const": event_type}},
                    "required": ["event_type"],
                },
                "then": {
                    "properties": {
                        "payload": {
                            "properties": {
                                key: collection_event_payload_field_schema(
                                    event_type,
                                    key,
                                    expected,
                                )
                                for key, expected in {
                                    **required,
                                    **COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS[event_type],
                                }.items()
                            },
                            "required": sorted(required),
                        }
                    }
                },
            }
            for event_type, required in COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS.items()
        ]
    return schema


def all_json_schemas() -> dict[str, dict[str, object]]:
    return {name: json_schema(name) for name in sorted(SCHEMA_MODELS)}
