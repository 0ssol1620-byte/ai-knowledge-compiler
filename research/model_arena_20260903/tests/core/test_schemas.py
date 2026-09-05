"""The JSON Schemas and the pydantic models are two views of one contract."""

from __future__ import annotations

import json
from typing import Any

import pytest
from arena.core.receipts import (
    SCHEMA_NAMES,
    SCHEMAS_DIR,
    ReceiptError,
    load_schema,
    model_for_schema,
    schema_name_for_id,
    validate,
)
from examples import EXAMPLE_NAMES, example
from jsonschema import Draft202012Validator

# Schema names whose 'schema' field is optional because the artifact is a
# config file or an HTTP wire object rather than a persisted campaign record.
DOCUMENT_NAMES = frozenset(
    {"runtime", "worker-run-request", "worker-run-response", "ready-response", "heartbeat"}
)

# ARENA_CONTRACT 11.1 D4 and 11.5 D26. These records travel between lanes that
# each know something the core does not - the Opus subscription columns, a
# worker's own gauges, the canary driver's per-stage detail, the controller's
# gate and upload blocks - so they accept unknown keys. Required core keys stay
# required and no consumer may depend on a non-core key.
EXTENSION_OPEN_NAMES = frozenset(
    {
        "page-receipt",
        "heartbeat",
        "model-registry-record",
        "evaluator-registry-record",
        "canary-receipt",
        "provision_gate",
        "bundle-publish",
    }
)


def _file_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_every_contract_schema_has_a_file_and_a_model() -> None:
    on_disk = {path.name.removesuffix(".schema.json") for path in SCHEMAS_DIR.glob("*.schema.json")}
    assert on_disk == set(SCHEMA_NAMES)
    assert set(EXAMPLE_NAMES) == set(SCHEMA_NAMES)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_file_is_a_valid_draft_2020_12_document(name: str) -> None:
    schema = _file_schema(name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"urn:tavonel:arena:{name}:v1"
    assert schema["additionalProperties"] is (name in EXTENSION_OPEN_NAMES)
    assert schema.get("description", "").strip(), f"{name} has no description"


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_and_model_agree_on_properties_and_required(name: str) -> None:
    """Drift between the two views is a test failure, not a runtime surprise."""

    generated = model_for_schema(name).model_json_schema(by_alias=True)
    on_disk = _file_schema(name)
    assert set(on_disk["properties"]) == set(generated["properties"]), name
    assert set(on_disk.get("required", ())) == set(generated.get("required", ())), name


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_the_schema_field_is_required_exactly_for_persisted_records(name: str) -> None:
    required = set(_file_schema(name).get("required", ()))
    if name in DOCUMENT_NAMES:
        assert "schema" not in required
    else:
        assert "schema" in required


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_the_example_validates_against_the_file_and_the_model(name: str) -> None:
    record = example(name)
    validate(record, name)
    parsed = model_for_schema(name).model_validate(record)
    round_tripped = parsed.to_record()
    validate(round_tripped, name)
    assert round_tripped == record


@pytest.mark.parametrize("name", sorted(set(SCHEMA_NAMES) - EXTENSION_OPEN_NAMES))
def test_an_unknown_field_is_rejected_by_a_closed_schema(name: str) -> None:
    from arena.core.receipts import SchemaValidationError

    with pytest.raises(SchemaValidationError):
        validate(dict(example(name), unexpected_field="x"), name)


@pytest.mark.parametrize("name", sorted(EXTENSION_OPEN_NAMES))
def test_an_extension_open_schema_accepts_an_unknown_field(name: str) -> None:
    """D4: a lane may add a column; the record still round-trips through the model."""

    record = dict(example(name), lane_specific_column="x")
    validate(record, name)
    round_tripped = model_for_schema(name).model_validate(record).to_record()
    assert round_tripped["lane_specific_column"] == "x"
    assert round_tripped == record


@pytest.mark.parametrize("name", sorted(EXTENSION_OPEN_NAMES))
def test_an_extension_open_schema_still_requires_its_core_keys(name: str) -> None:
    from arena.core.receipts import SchemaValidationError

    required = sorted(_file_schema(name).get("required", ()))
    assert required
    for field in required:
        record = example(name)
        record.pop(field, None)
        with pytest.raises(SchemaValidationError):
            validate(record, name)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_dropping_any_required_field_fails_validation(name: str) -> None:
    from arena.core.receipts import SchemaValidationError

    required = sorted(_file_schema(name).get("required", ()))
    assert required, f"{name} requires nothing at all"
    for field in required:
        record = example(name)
        record.pop(field, None)
        with pytest.raises(SchemaValidationError):
            validate(record, name)


def test_schema_ids_map_back_to_their_names() -> None:
    for name in SCHEMA_NAMES:
        schema_id = model_for_schema(name).SCHEMA_ID
        assert schema_id == f"tavonel.arena.{name}.v1"
        assert schema_name_for_id(schema_id) == name


def test_load_schema_refuses_an_unknown_name() -> None:
    with pytest.raises(ReceiptError, match="unknown schema name"):
        load_schema("not-a-schema")


def test_loaded_schema_matches_the_file_on_disk() -> None:
    assert dict(load_schema("event")) == _file_schema("event")
