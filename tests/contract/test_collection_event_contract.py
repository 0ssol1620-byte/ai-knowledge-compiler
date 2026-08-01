from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from akc_cir import (
    COLLECTION_EVENT_ENUM_FIELDS,
    COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS,
    COLLECTION_EVENT_PAYLOAD_CONTRACTS,
    COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS,
    COLLECTION_EVENT_TYPES,
    CollectionEventEnvelope,
    json_schema,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
COLLECTION_ID = "00000000-0000-4000-8000-000000000001"
JOB_ID = "00000000-0000-4000-8000-000000000002"
UUID_FIELDS = {
    "collection_id",
    "project_id",
    "source_root_id",
    "upload_session_id",
    "preflight_id",
    "estimate_run_id",
    "processing_job_id",
    "architecture_plan_id",
    "analysis_task_id",
    "billing_owner_job_id",
    "repair_id",
    "target_id",
    "decision_id",
    "execution_id",
    "registry_model_id",
    "export_id",
    "package_manifest_id",
    "package_validation_id",
    "document_id",
    "shard_id",
    "attempt_id",
    "validation_id",
    "source_attempt_id",
    "hedge_attempt_id",
    "worker_health_id",
    "recovery_task_id",
    "result_attempt_id",
}


def _field_value(event_type: str, key: str, expected: object) -> object:
    enum_values = COLLECTION_EVENT_ENUM_FIELDS.get(event_type, {}).get(key)
    if enum_values:
        return sorted(enum_values)[0]
    if key == "status":
        return "CREATED"
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    selected = next(item for item in expected_types if item is not type(None))
    if key == "collection_id":
        return COLLECTION_ID
    if key in UUID_FIELDS:
        return JOB_ID if key == "processing_job_id" else "00000000-0000-4000-8000-000000000003"
    if key.endswith("_sha256"):
        return "a" * 64
    if key in {
        "credits",
        "hard_cap",
        "credit_p50",
        "credit_p95",
        "reserve_ceiling",
        "confidence",
        "credits_consumed",
        "cost_usd",
        "semantic_score",
        "billable_credits",
    } and selected is str:
        return "0"
    if selected is str:
        return "fixture"
    if selected is int:
        return 0
    if selected is bool:
        return True
    if selected is dict:
        return {"verified": 1}
    if selected is list:
        return [0] if key == "sample_tiers" else ["fixture"]
    raise AssertionError(f"unsupported event field type: {event_type}.{key}={expected}")


def _valid_payload(event_type: str, *, include_optional: bool = False) -> dict[str, object]:
    contract = COLLECTION_EVENT_PAYLOAD_CONTRACTS[event_type]
    fields = dict(contract.required)
    if include_optional:
        fields.update(contract.optional)
    return {
        key: _field_value(event_type, key, expected) for key, expected in fields.items()
    }


def _envelope(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    payload_job_id = payload.get("processing_job_id")
    return {
        "event_id": "00000000-0000-4000-8000-000000000004",
        "collection_id": COLLECTION_ID,
        "job_id": payload_job_id if isinstance(payload_job_id, str) else None,
        "sequence": 1,
        "event_type": event_type,
        "timestamp": datetime.now(UTC),
        "payload": payload,
        "schema_version": "1.0",
    }


def _wrong_type(expected: object) -> object:
    expected_types = expected if isinstance(expected, tuple) else (expected,)
    selected = next(item for item in expected_types if item is not type(None))
    if selected is str:
        return 1
    if selected is int:
        return True
    if selected is bool:
        return "true"
    if selected is dict:
        return []
    if selected is list:
        return {}
    raise AssertionError(f"unsupported event field type: {expected}")


def test_checked_in_collection_event_schema_is_canonical() -> None:
    checked_in = json.loads(
        (ROOT / "packages/contracts/schemas/collection-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_in == json_schema("collection-event")


def test_collection_event_envelope_rejects_unknown_event_names() -> None:
    payload = {
        "event_id": uuid4(),
        "collection_id": uuid4(),
        "job_id": None,
        "sequence": 1,
        "event_type": "collection.unregistered.v1",
        "timestamp": datetime.now(UTC),
        "payload": {"collection_id": str(uuid4())},
        "schema_version": "1.0",
    }
    with pytest.raises(ValidationError):
        CollectionEventEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("collection.created.v1", {}),
        ("processing.started.v1", {"collection_id": "wrong"}),
        (
            "processing.started.v1",
            {
                "collection_id": "00000000-0000-4000-8000-000000000001",
                "processing_job_id": "00000000-0000-4000-8000-000000000002",
                "architecture_plan_id": "00000000-0000-4000-8000-000000000003",
                "task_count": True,
            },
        ),
    ],
)
def test_collection_event_envelope_rejects_payload_contract_drift(
    event_type: str, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        CollectionEventEnvelope.model_validate(
            {
                "event_id": "00000000-0000-4000-8000-000000000004",
                "collection_id": "00000000-0000-4000-8000-000000000001",
                "job_id": "00000000-0000-4000-8000-000000000002",
                "sequence": 1,
                "event_type": event_type,
                "timestamp": datetime.now(UTC),
                "payload": payload,
                "schema_version": "1.0",
            }
        )


def test_every_collection_event_has_a_required_payload_contract() -> None:
    assert set(COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS) == set(COLLECTION_EVENT_TYPES)
    assert set(COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS) == set(COLLECTION_EVENT_TYPES)
    assert all(
        fields.get("collection_id") is str
        for fields in COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS.values()
    )


@pytest.mark.parametrize("event_type", COLLECTION_EVENT_TYPES)
@pytest.mark.parametrize("include_optional", [False, True])
def test_every_collection_event_accepts_its_typed_contract(
    event_type: str,
    include_optional: bool,
) -> None:
    payload = _valid_payload(event_type, include_optional=include_optional)
    envelope = CollectionEventEnvelope.model_validate(_envelope(event_type, payload))
    assert envelope.payload == payload


@pytest.mark.parametrize("event_type", COLLECTION_EVENT_TYPES)
def test_every_collection_event_rejects_a_missing_required_field(event_type: str) -> None:
    payload = _valid_payload(event_type)
    removed = next(reversed(COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[event_type]))
    del payload[removed]
    with pytest.raises(ValidationError, match="missing required keys"):
        CollectionEventEnvelope.model_validate(_envelope(event_type, payload))


@pytest.mark.parametrize("event_type", COLLECTION_EVENT_TYPES)
def test_every_collection_event_rejects_required_type_drift(event_type: str) -> None:
    payload = _valid_payload(event_type)
    key = next(reversed(COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[event_type]))
    payload[key] = _wrong_type(COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[event_type][key])
    with pytest.raises(ValidationError):
        CollectionEventEnvelope.model_validate(_envelope(event_type, payload))


@pytest.mark.parametrize(
    ("event_type", "key", "invalid"),
    [
        ("collection.created.v1", "project_id", "not-a-uuid"),
        ("collection.files.planned.v1", "manifest_sha256", "A" * 64),
        ("file.discovered.v1", "discovered_files", -1),
        ("estimate.fast.ready.v1", "confidence", "1.1"),
        ("collection.source.created.v1", "source_type", "ftp"),
        ("collection.completed.v1", "status", "PARTIAL"),
        ("page.route.selected.v1", "route_counts", {"native": -1}),
        ("verification.failed.v1", "reason_codes", ["contains spaces"]),
    ],
)
def test_collection_event_rejects_identifier_hash_bound_and_enum_drift(
    event_type: str,
    key: str,
    invalid: object,
) -> None:
    payload = _valid_payload(event_type, include_optional=True)
    payload[key] = invalid
    with pytest.raises(ValidationError):
        CollectionEventEnvelope.model_validate(_envelope(event_type, payload))


@pytest.mark.parametrize("forbidden_key", ["email", "raw_text", "document_path"])
def test_collection_event_rejects_pii_and_raw_payload_fields(forbidden_key: str) -> None:
    payload = _valid_payload("collection.created.v1")
    payload[forbidden_key] = "forbidden"
    with pytest.raises(ValidationError):
        CollectionEventEnvelope.model_validate(_envelope("collection.created.v1", payload))


def test_collection_event_allows_additive_safe_fields() -> None:
    payload = _valid_payload("collection.created.v1")
    payload["producer_revision_2"] = "revision-2"
    envelope = CollectionEventEnvelope.model_validate(
        _envelope("collection.created.v1", payload)
    )
    assert envelope.payload["producer_revision_2"] == "revision-2"


def test_generated_web_contract_contains_every_canonical_event() -> None:
    generated = (ROOT / "packages/contracts/src/generated-contracts.ts").read_text(encoding="utf-8")
    for event_type in COLLECTION_EVENT_TYPES:
        assert f'  "{event_type}",' in generated

    web_client = (ROOT / "apps/web/src/lib/collection-runtime-client.ts").read_text(
        encoding="utf-8"
    )
    assert 'from "@akc/contracts"' in web_client
    assert "z.enum(COLLECTION_EVENT_TYPES)" in web_client


def test_legacy_processing_event_registry_matches_its_canonical_enum() -> None:
    canonical = json_schema("processing-event")
    canonical_types = set(canonical["$defs"]["EventType"]["enum"])  # type: ignore[index]
    checked_in = json.loads(
        (ROOT / "packages/contracts/schemas/processing-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(checked_in["properties"]["event_type"]["enum"]) == canonical_types

    manual_types = (ROOT / "packages/contracts/src/index.ts").read_text(encoding="utf-8")
    for event_type in canonical_types:
        assert f'  | "{event_type}"' in manual_types
