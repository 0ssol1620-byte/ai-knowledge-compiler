"""JSON Schema registry generated from the canonical Pydantic contracts."""

from __future__ import annotations

from pydantic import BaseModel

from .errors import ErrorEnvelope
from .events import ProcessingEvent
from .exports import ExportManifest, QualityReport, RagChunk, SourceMap
from .knowledge import DocumentClassification, KnowledgeBundle, KnowledgeNote, RelationAssertion
from .models import CanonicalDocument, CanonicalTable

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "canonical-document": CanonicalDocument,
    "canonical-table": CanonicalTable,
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
    return schema


def all_json_schemas() -> dict[str, dict[str, object]]:
    return {name: json_schema(name) for name in sorted(SCHEMA_MODELS)}
