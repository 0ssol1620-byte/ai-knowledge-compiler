from __future__ import annotations

import json
from pathlib import Path

import pytest
from akc_cir import (
    CanonicalDocument,
    ErrorEnvelope,
    ExportManifest,
    KnowledgeBundle,
    ProcessingEvent,
)
from akc_exporters import AKMP_CONTEXT, KNOWLEDGE_NOTE_SHACL
from akc_router import RouteDecision
from jsonschema import Draft202012Validator, FormatChecker

from scripts.generate_contract_types import OUTPUT, generate_types

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "packages" / "contracts" / "schemas"
EXAMPLES = ROOT / "packages" / "contracts" / "examples"

CASES = (
    ("canonical-document", CanonicalDocument),
    ("processing-event", ProcessingEvent),
    ("error-envelope", ErrorEnvelope),
    ("knowledge-bundle", KnowledgeBundle),
    ("export-manifest", ExportManifest),
    ("route-decision", RouteDecision),
)


@pytest.mark.parametrize(("name", "model"), CASES)
def test_static_schema_and_python_contract_accept_example(name, model) -> None:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    example = json.loads((EXAMPLES / f"{name}.example.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    parsed = model.model_validate(example)
    assert parsed.model_dump(mode="json", by_alias=True, exclude_none=True) == example


def test_all_static_schemas_are_valid_draft_2020_12() -> None:
    for path in SCHEMAS.glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_pinned_jsonld_context_and_shacl_runtime_assets_match_specification() -> None:
    akmp = ROOT / "docs" / "akmp"
    assert json.loads((akmp / "context-v1.jsonld").read_text(encoding="utf-8")) == {
        "@context": AKMP_CONTEXT
    }
    assert (akmp / "knowledge-note.shacl.ttl").read_text(encoding="utf-8") == KNOWLEDGE_NOTE_SHACL


def test_pydantic_generated_typescript_contracts_are_current() -> None:
    assert OUTPUT.read_text(encoding="utf-8") == generate_types()
