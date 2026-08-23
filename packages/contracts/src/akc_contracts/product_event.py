"""Canonical ``ProductEvent`` wire contract — ``ProductEventEnvelopeV1``.

Generated counterpart of ``packages/contracts/product-event.schema.json``
(TAVONEL Cinematic Compilation Replay Master Spec v2.0, §9.4). The envelope is
the one vocabulary the cinematic landing and the real product both speak;
per-type payload shapes stay out of scope here and arrive with the producer /
parser conformance work (spec Phase 1, steps 4-6).

Validation is deliberately dependency-free: the JSON Schema is mirrored by
hand with the stdlib only, so importing this module never pulls ``jsonschema``
into a client bundle or a worker image.

Wire guarantees enforced here:

* ``schema_version`` is pinned to ``"1.0"``; a mismatch fails loudly.
* ``event_type`` must be one of the 22 registered types (spec §9.3 lists A +
  B). The §9.3 "C" candidates are deliberately absent until a backend
  producer or a DERIVED beat exists for them.
* ``sequence`` is an integer >= 1 and monotonic per scope (§9.6). Sequences
  from different scopes are different counter spaces and are never
  comparable, so no cross-scope ordering is implied anywhere here.
* ``mode`` distinguishes replayed fixture data (``"demo"``) from live backend
  frames (``"live"``).
* ``scope`` is a discriminated union on ``kind`` carrying exactly the identity
  fields the corresponding backend plane has — a job-scope event has no
  ``collection_id`` because the job plane structurally has none.
* Unknown keys are rejected at every level (``additionalProperties: false``),
  so a drifted producer fails validation instead of rendering half a frame.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

PRODUCT_EVENT_SCHEMA_VERSION = "1.0"

#: §9.3 A — event names already produced by ``akc_cir.collection_events``.
REUSED_EVENT_TYPES: tuple[str, ...] = (
    "collection.discovery.progress.v1",
    "file.discovered.v1",
    "file.duplicate.detected.v1",
    "page.route.selected.v1",
    "verification.failed.v1",
    "recovery.completed.v1",
    "entity.resolved.v1",
    "relation.created.v1",
)

#: §9.3 B — client proposal types; fixture-only until a producer exists.
PROPOSED_EVENT_TYPES: tuple[str, ...] = (
    "revision.family.detected.v1",
    "document.profiled.v1",
    "document.rerouted.v1",
    "knowledge.unit.created.v1",
    "conflict.detected.v1",
    "authority.resolved.v1",
    "source.revision.created.v1",
    "world_state.activated.v1",
    "impact.detected.v1",
    "recompile.progress.v1",
    "recompile.completed.v1",
    "answer.resolution.started.v1",
    "answer.source.resolved.v1",
    "answer.emitted.v1",
)

PRODUCT_EVENT_TYPES: tuple[str, ...] = REUSED_EVENT_TYPES + PROPOSED_EVENT_TYPES

REGISTERED_EVENT_TYPES: frozenset[str] = frozenset(PRODUCT_EVENT_TYPES)

_MODES: frozenset[str] = frozenset({"demo", "live"})


class ProductEventValidationError(ValueError):
    """Raised when a frame does not satisfy the canonical envelope.

    ``errors`` carries one human-readable message per violation, each with the
    dotted path of the offending field (``scope.job_id``, ``sequence``, ...),
    so a producer sees every problem with one parse instead of one per retry.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        joined = "\n  - ".join(self.errors)
        super().__init__(
            f"invalid ProductEventEnvelopeV1 ({len(self.errors)} error(s)):\n  - {joined}"
        )


@dataclass(frozen=True)
class JobScope:
    """Job-plane identity. ``page_number`` narrows the event to one page."""

    kind: Literal["job"] = "job"
    job_id: str = ""
    document_id: str | None = None
    page_number: int | None = None


@dataclass(frozen=True)
class CollectionScope:
    """Collection-plane identity. ``job_id`` is optional context, not identity."""

    kind: Literal["collection"] = "collection"
    collection_id: str = ""
    job_id: str | None = None


@dataclass(frozen=True)
class DemoScope:
    """Fixture-originated display events that impersonate neither real plane."""

    kind: Literal["demo"] = "demo"
    fixture_id: str | None = None


EventScope = JobScope | CollectionScope | DemoScope


@dataclass(frozen=True)
class ProductEvent:
    """Typed view of one canonical frame (§9.4)."""

    schema_version: str
    event_id: str
    event_type: str
    sequence: int
    occurred_at: str
    mode: str
    scope: EventScope
    payload: Any
    monotonic_offset_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Wire-form dict; ``monotonic_offset_ms`` appears only when set."""
        document: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "mode": self.mode,
            "scope": _scope_to_dict(self.scope),
            "payload": self.payload,
        }
        if self.monotonic_offset_ms is not None:
            document["monotonic_offset_ms"] = self.monotonic_offset_ms
        return document


def _scope_to_dict(scope: EventScope) -> dict[str, Any]:
    document: dict[str, Any]
    if isinstance(scope, JobScope):
        document = {"kind": scope.kind, "job_id": scope.job_id}
        if scope.document_id is not None:
            document["document_id"] = scope.document_id
        if scope.page_number is not None:
            document["page_number"] = scope.page_number
        return document
    if isinstance(scope, CollectionScope):
        document = {"kind": scope.kind, "collection_id": scope.collection_id}
        if scope.job_id is not None:
            document["job_id"] = scope.job_id
        return document
    document = {"kind": scope.kind}
    if scope.fixture_id is not None:
        document["fixture_id"] = scope.fixture_id
    return document


_ALLOWED_TOP_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "event_id",
        "event_type",
        "sequence",
        "occurred_at",
        "monotonic_offset_ms",
        "mode",
        "scope",
        "payload",
    }
)

_REQUIRED_TOP_KEYS: frozenset[str] = _ALLOWED_TOP_KEYS - {"monotonic_offset_ms"}

_SCOPE_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "job": frozenset({"kind", "job_id", "document_id", "page_number"}),
    "collection": frozenset({"kind", "collection_id", "job_id"}),
    "demo": frozenset({"kind", "fixture_id"}),
}


def _is_int(value: Any) -> bool:
    # bool subclasses int; a bare True/False must not pass as 1/0.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _unexpected_keys(where: str, value: Mapping[str, Any], allowed: frozenset[str]) -> list[str]:
    extra = sorted(set(value) - allowed)
    if not extra:
        return []
    listed = ", ".join(repr(key) for key in extra)
    return [f"{where}: unexpected key(s) {listed}"]


def _validate_scope(scope_value: Any, errors: list[str]) -> dict[str, Any]:
    if not isinstance(scope_value, Mapping):
        errors.append("scope: expected an object")
        return {}

    kind = scope_value.get("kind")
    if not _is_nonempty_str(kind):
        errors.append("scope.kind: expected 'job' | 'collection' | 'demo'")
        return {}
    if kind not in _SCOPE_ALLOWED_KEYS:
        errors.append(f"scope.kind: unknown kind {kind!r}")
        return {}

    errors.extend(_unexpected_keys("scope", scope_value, _SCOPE_ALLOWED_KEYS[kind]))

    normalized: dict[str, Any] = {"kind": kind}

    def require(field: str) -> None:
        value = scope_value.get(field)
        if not _is_nonempty_str(value):
            errors.append(f"scope.{field}: expected a non-empty string")
            return
        normalized[field] = value

    def optional_str(field: str) -> None:
        if field in scope_value and scope_value[field] is not None:
            value = scope_value[field]
            if not _is_nonempty_str(value):
                errors.append(f"scope.{field}: expected a non-empty string")
                return
            normalized[field] = value

    if kind == "job":
        require("job_id")
        optional_str("document_id")
        page_number = scope_value.get("page_number")
        if page_number is not None:
            if not _is_int(page_number) or page_number < 1:
                errors.append("scope.page_number: expected an integer >= 1")
            else:
                normalized["page_number"] = page_number
    elif kind == "collection":
        require("collection_id")
        optional_str("job_id")
    else:
        optional_str("fixture_id")

    return normalized


def validate_envelope(value: Any) -> dict[str, Any]:
    """Validate one raw frame against the canonical envelope.

    Returns a normalized dict containing exactly the canonical keys. Raises
    :class:`ProductEventValidationError` with every violation it found.
    """
    if not isinstance(value, Mapping):
        raise ProductEventValidationError(
            [f"envelope: expected an object, got {type(value).__name__}"]
        )

    errors: list[str] = []
    errors.extend(_unexpected_keys("envelope", value, _ALLOWED_TOP_KEYS))

    missing = sorted(_REQUIRED_TOP_KEYS - set(value))
    if missing:
        listed = ", ".join(repr(key) for key in missing)
        errors.append(f"envelope: missing required field(s) {listed}")

    # A present-but-null required key is a violation, not an absence: JSON
    # null must never masquerade as a default. `payload` is exempt — it is
    # opaque ('unknown' in §9.4) and may legitimately be null.
    for key in sorted((_REQUIRED_TOP_KEYS - {"payload"}) & set(value)):
        if value[key] is None:
            errors.append(f"{key}: expected a value, got null")

    schema_version = value.get("schema_version")
    if schema_version is not None and schema_version != PRODUCT_EVENT_SCHEMA_VERSION:
        errors.append(
            f"schema_version: expected {PRODUCT_EVENT_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    event_id = value.get("event_id")
    if event_id is not None and not _is_nonempty_str(event_id):
        errors.append("event_id: expected a non-empty string")

    event_type = value.get("event_type")
    if event_type is not None and event_type not in REGISTERED_EVENT_TYPES:
        registered = len(PRODUCT_EVENT_TYPES)
        errors.append(
            f"event_type: unregistered type {event_type!r} ({registered} types registered)"
        )

    sequence = value.get("sequence")
    if sequence is not None and (not _is_int(sequence) or sequence < 1):
        errors.append("sequence: expected an integer >= 1")

    occurred_at = value.get("occurred_at")
    if occurred_at is not None and not _is_nonempty_str(occurred_at):
        errors.append("occurred_at: expected a non-empty string")

    if "monotonic_offset_ms" in value and not _is_number(value["monotonic_offset_ms"]):
        errors.append("monotonic_offset_ms: expected a finite number")

    mode = value.get("mode")
    if mode is not None and mode not in _MODES:
        errors.append(f"mode: expected 'demo' | 'live', got {mode!r}")

    scope = _validate_scope(value.get("scope"), errors)

    if errors:
        raise ProductEventValidationError(errors)

    normalized: dict[str, Any] = {
        "schema_version": schema_version,
        "event_id": event_id,
        "event_type": event_type,
        "sequence": sequence,
        "occurred_at": occurred_at,
        "mode": mode,
        "scope": scope,
        "payload": value["payload"],
    }
    if "monotonic_offset_ms" in value:
        normalized["monotonic_offset_ms"] = float(value["monotonic_offset_ms"])
    return normalized


def _scope_from_dict(data: Mapping[str, Any]) -> EventScope:
    kind = data["kind"]
    if kind == "job":
        return JobScope(
            job_id=data["job_id"],
            document_id=data.get("document_id"),
            page_number=data.get("page_number"),
        )
    if kind == "collection":
        return CollectionScope(collection_id=data["collection_id"], job_id=data.get("job_id"))
    return DemoScope(fixture_id=data.get("fixture_id"))


def parse_envelope(value: Any) -> ProductEvent:
    """Validate and type one raw frame into a :class:`ProductEvent`."""
    document = validate_envelope(value)
    return ProductEvent(
        schema_version=document["schema_version"],
        event_id=document["event_id"],
        event_type=document["event_type"],
        sequence=document["sequence"],
        occurred_at=document["occurred_at"],
        mode=document["mode"],
        scope=_scope_from_dict(document["scope"]),
        payload=document["payload"],
        monotonic_offset_ms=document.get("monotonic_offset_ms"),
    )


def canonical_json(source: ProductEvent | Mapping[str, Any]) -> str:
    """Deterministic JSON form used by replay hashing and fixture manifests."""
    document = source.to_dict() if isinstance(source, ProductEvent) else validate_envelope(source)
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "PRODUCT_EVENT_SCHEMA_VERSION",
    "PRODUCT_EVENT_TYPES",
    "PROPOSED_EVENT_TYPES",
    "REUSED_EVENT_TYPES",
    "CollectionScope",
    "DemoScope",
    "EventScope",
    "JobScope",
    "ProductEvent",
    "ProductEventValidationError",
    "canonical_json",
    "parse_envelope",
    "validate_envelope",
]
