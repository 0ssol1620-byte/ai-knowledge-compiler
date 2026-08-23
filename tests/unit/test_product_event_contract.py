"""Conformance tests for the canonical ProductEvent envelope.

Spec: TAVONEL Cinematic Compilation Replay Master Spec v2.0 §9.4 (envelope),
§9.3 A/B (event_type enum), §9.5.1 (example payloads), Phase 1 (Event
contract). The Python twin under test is the stdlib-only mirror of
``packages/contracts/product-event.schema.json``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from akc_contracts.product_event import (
    PRODUCT_EVENT_SCHEMA_VERSION,
    PRODUCT_EVENT_TYPES,
    CollectionScope,
    DemoScope,
    JobScope,
    ProductEvent,
    ProductEventValidationError,
    canonical_json,
    parse_envelope,
    validate_envelope,
)

# §9.5.1 — schema examples (explicitly NOT production fixture literals).
SPEC_IMPACT_EXAMPLE: dict[str, Any] = {
    "schema_version": "1.0",
    "event_id": "evt-impact-0001",
    "event_type": "impact.detected.v1",
    "sequence": 1842,
    "occurred_at": "2026-08-23T10:00:00Z",
    "mode": "demo",
    "scope": {"kind": "demo", "fixture_id": "showcase-world-v1"},
    "payload": {
        "change_id": "chg-0002",
        "sources_changed": 1,
        "knowledge_units_affected": 7,
        "agent_contexts_stale": 2,
        "retrieval_packages_invalidated": 1,
        "reason_paths": [["source:approved-plan", "claim:launch-date", "artifact:roadmap"]],
    },
}

SPEC_RECOMPILE_EXAMPLE: dict[str, Any] = {
    "schema_version": "1.0",
    "event_id": "evt-recompile-0007",
    "event_type": "recompile.completed.v1",
    "sequence": 1850,
    "occurred_at": "2026-08-23T10:00:02Z",
    "mode": "demo",
    "scope": {"kind": "demo", "fixture_id": "showcase-world-v1"},
    "payload": {
        "recompiled": 7,
        "world_units_total": 12841,
        "candidate_world_state_id": "WS-0002",
        "equivalence_receipt_id": "receipt-eq-0002",
    },
}


def _base(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": "evt-test-0001",
        "event_type": "impact.detected.v1",
        "sequence": 1842,
        "occurred_at": "2026-08-23T10:00:00Z",
        "mode": "demo",
        "scope": {"kind": "demo", "fixture_id": "showcase-world-v1"},
        "payload": {"change_id": "chg-0002", "sources_changed": 1},
    }
    envelope.update(overrides)
    return envelope


def _rejects(envelope: Any, *fragments: str) -> ProductEventValidationError:
    with pytest.raises(ProductEventValidationError) as excinfo:
        validate_envelope(envelope)
    message = str(excinfo.value)
    for fragment in fragments:
        assert fragment in message, f"expected {fragment!r} in:\n{message}"
    return excinfo.value


def test_spec_impact_example_passes() -> None:
    parsed = parse_envelope(SPEC_IMPACT_EXAMPLE)
    assert isinstance(parsed.scope, DemoScope)
    assert parsed.scope.fixture_id == "showcase-world-v1"
    assert parsed.payload["reason_paths"] == SPEC_IMPACT_EXAMPLE["payload"]["reason_paths"]


def test_spec_recompile_example_passes() -> None:
    parsed = parse_envelope(SPEC_RECOMPILE_EXAMPLE)
    # The spec payload carries no change_id; the envelope must not demand one.
    assert parsed.event_type == "recompile.completed.v1"
    assert parsed.payload["candidate_world_state_id"] == "WS-0002"


def test_valid_envelope_returns_normalized_copy_without_mutating_input() -> None:
    raw = _base(monotonic_offset_ms=1500)
    frozen = json.dumps(raw)
    normalized = validate_envelope(raw)
    assert normalized["monotonic_offset_ms"] == 1500.0
    assert set(normalized) == {
        "schema_version",
        "event_id",
        "event_type",
        "sequence",
        "occurred_at",
        "mode",
        "scope",
        "payload",
        "monotonic_offset_ms",
    }
    assert json.dumps(raw) == frozen


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            {"kind": "job", "job_id": "job-abc", "document_id": "doc-9", "page_number": 3},
            JobScope(job_id="job-abc", document_id="doc-9", page_number=3),
        ),
        (
            {"kind": "collection", "collection_id": "coll-xyz", "job_id": "job-abc"},
            CollectionScope(collection_id="coll-xyz", job_id="job-abc"),
        ),
        ({"kind": "demo"}, DemoScope(fixture_id=None)),
    ],
)
def test_scope_variants_pass(scope: dict[str, Any], expected: Any) -> None:
    parsed = parse_envelope(_base(scope=scope))
    assert parsed.scope == expected


@pytest.mark.parametrize("bad_sequence", [1842.0, "1842", True, None, [1842]])
def test_non_integer_sequence_rejected(bad_sequence: Any) -> None:
    _rejects(_base(sequence=bad_sequence), "sequence")


@pytest.mark.parametrize("bad_sequence", [0, -1])
def test_sequence_below_one_rejected(bad_sequence: int) -> None:
    _rejects(_base(sequence=bad_sequence), "sequence")


@pytest.mark.parametrize("bad_mode", ["Demo", "sample", "live ", "", None, 1])
def test_invalid_mode_rejected(bad_mode: Any) -> None:
    _rejects(_base(mode=bad_mode), "mode")


def test_missing_mode_rejected() -> None:
    envelope = _base()
    del envelope["mode"]
    _rejects(envelope, "missing required field")


@pytest.mark.parametrize(
    "unregistered",
    [
        "file.security.passed.v1",  # §9.3 C candidate — deliberately not registered
        "collection.created.v1",  # real backend type outside the cinematic vocabulary
        "impact.detected",  # missing version suffix
        "",
    ],
)
def test_unregistered_event_type_rejected(unregistered: str) -> None:
    _rejects(_base(event_type=unregistered), "event_type")


@pytest.mark.parametrize(
    "event_type", PRODUCT_EVENT_TYPES, ids=lambda event_type: event_type.removesuffix(".v1")
)
def test_every_registered_event_type_accepts_a_minimal_frame(event_type: str) -> None:
    parsed = parse_envelope(_base(event_type=event_type))
    assert parsed.event_type == event_type


def test_roundtrip_through_canonical_json() -> None:
    original = parse_envelope(SPEC_IMPACT_EXAMPLE)
    text = canonical_json(original)
    reparsed = parse_envelope(json.loads(text))
    assert reparsed == original
    # Determinism: key order in the source mapping must not matter.
    shuffled = parse_envelope(json.loads(text))
    assert canonical_json(shuffled) == text


def test_canonical_json_is_key_order_independent() -> None:
    a = canonical_json(parse_envelope(_base()))
    reversed_raw = dict(reversed(list(_base().items())))
    b = canonical_json(validate_envelope(reversed_raw))
    assert a == b


def test_unknown_top_level_key_rejected() -> None:
    # Legacy top-level collection_id is exactly what canonical removes.
    _rejects(_base(collection_id="coll-legacy"), "unexpected key")


def test_schema_version_mismatch_rejected() -> None:
    _rejects(_base(schema_version="1.1"), "schema_version")
    _rejects(_base(schema_version=1.0), "schema_version")


@pytest.mark.parametrize("field", ["event_id", "occurred_at", "payload", "scope"])
def test_missing_required_field_rejected(field: str) -> None:
    envelope = _base()
    del envelope[field]
    _rejects(envelope, field)


def test_empty_event_id_rejected() -> None:
    _rejects(_base(event_id=""), "event_id")


@pytest.mark.parametrize("offset", [0, 250, 17.5])
def test_monotonic_offset_ms_accepts_finite_numbers(offset: float) -> None:
    parsed = parse_envelope(_base(monotonic_offset_ms=offset))
    assert parsed.monotonic_offset_ms == float(offset)


@pytest.mark.parametrize("bad_offset", ["250ms", True, None, float("nan")])
def test_monotonic_offset_ms_rejects_non_numbers(bad_offset: Any) -> None:
    _rejects(_base(monotonic_offset_ms=bad_offset), "monotonic_offset_ms")


def test_job_scope_requires_job_id_and_positive_page_number() -> None:
    _rejects(_base(scope={"kind": "job"}), "scope.job_id")
    _rejects(_base(scope={"kind": "job", "job_id": "j", "page_number": 0}), "page_number")
    _rejects(_base(scope={"kind": "job", "job_id": "j", "extra": 1}), "unexpected key")


def test_scope_kind_must_be_known() -> None:
    _rejects(_base(scope={"kind": "tenant", "tenant_id": "t"}), "scope.kind")


def test_payload_may_be_any_json_value() -> None:
    # Envelope-level contract is opaque ('unknown' in §9.4); per-type payload
    # contracts are validated by the producer/parser conformance layer.
    for value in [{"any": "shape"}, [], "text", 42, None]:
        parsed = parse_envelope(_base(payload=value))
        assert parsed.payload == value


def test_validation_error_collects_all_problems() -> None:
    error = _rejects(
        _base(sequence="nope", mode="Demo"),
        "sequence",
        "mode",
    )
    assert len(error.errors) >= 2


def test_non_object_envelope_rejected() -> None:
    for bad in ["not-an-object", 42, None, [SPEC_IMPACT_EXAMPLE]]:
        with pytest.raises(ProductEventValidationError):
            validate_envelope(bad)


def test_parse_envelope_returns_product_event_dataclass() -> None:
    parsed = parse_envelope(_base())
    assert isinstance(parsed, ProductEvent)
    assert parsed.schema_version == PRODUCT_EVENT_SCHEMA_VERSION
    assert parsed.to_dict()["sequence"] == 1842
