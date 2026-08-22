"""Schema-compatible collection event envelopes for desktop watch records.

Contract authority (do not drift from these, they are the wire truth):

- ``packages/contracts/schemas/collection-event.schema.json`` — strict
  ``CollectionEventEnvelope``: ``event_id``, ``collection_id``, ``job_id``,
  ``sequence`` (>=1), ``event_type``, timezone-aware ``timestamp``,
  ``payload`` object, ``schema_version == "1.0"``, ``additionalProperties:
  false``.
- ``packages/cir-python/src/akc_cir/collection_events.py`` —
  ``COLLECTION_EVENT_PAYLOAD_CONTRACTS["file.discovered.v1"]`` requires
  exactly ``collection_id``, ``source_root_id``, ``discovered_files``,
  ``discovered_bytes``, ``manifest_revision``. The count field is spelled
  **discovered_files** (``files_discovered`` was a historical bug; the
  frontend mismatch is documented in
  ``docs/integration/M2_1_MINIMAL_COLLECTION_BOUNDARY.md``).

Payload hygiene mirrors akc_cir: keys such as ``path``, ``filename``,
``name`` and anything ending in ``_path``/``_url`` are forbidden inside
envelope payloads. Local filesystem detail therefore lives ONLY in the
watcher's journal/sink records (see journal.py / watcher.py); envelopes
carry aggregate counters only.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

EVENT_TYPE_FILE_DISCOVERED = "file.discovered.v1"
SCHEMA_VERSION = "1.0"

ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "event_id",
        "collection_id",
        "job_id",
        "sequence",
        "event_type",
        "timestamp",
        "payload",
        "schema_version",
    }
)

# Mirrors COLLECTION_EVENT_PAYLOAD_CONTRACTS["file.discovered.v1"] (required only).
_FILE_DISCOVERED_REQUIRED: dict[str, type] = {
    "collection_id": str,
    "source_root_id": str,
    "discovered_files": int,
    "discovered_bytes": int,
    "manifest_revision": int,
}

_INT64_MAX = 2**63 - 1

# Mirrors akc_cir.collection_events._FORBIDDEN_COLLECTION_KEYS plus the
# recursive *_path/*_url suffix rule enforced by _validate_collection_payload_shape.
_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "body",
        "content",
        "document",
        "document_text",
        "email",
        "filename",
        "name",
        "path",
        "presigned_url",
        "prompt",
        "raw_output",
        "raw_text",
        "source_text",
        "token",
        "url",
    }
)

_UUID36 = re.compile(r"^[0-9a-f-]{36}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# Deterministic UUID namespace for watcher-generated identities.
EVENT_NAMESPACE: uuid.UUID = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://schemas.aiknowledgecompiler.dev/desktop-watcher/1",
)


def source_root_id_for(root_key: str) -> str:
    """Deterministic source_root_id for a watch root without explicit config."""
    return str(uuid.uuid5(EVENT_NAMESPACE, f"source-root|{root_key.casefold()}"))


def build_event_key(*parts: object) -> str:
    """Stable dedup/replay identity for one emission.

    Callers must include enough components (root, path, action, content hash,
    revision/generation) that two distinct emissions never collide while any
    single emission always maps to the same key across restarts.
    """
    joined = "|".join(str(part) for part in parts)
    return joined


def deterministic_event_id(event_key: str) -> str:
    return str(uuid.uuid5(EVENT_NAMESPACE, f"collection-event|{event_key}"))


def build_discovery_envelope(
    *,
    collection_id: str,
    job_id: str | None,
    source_root_id: str,
    discovered_bytes: int,
    manifest_revision: int,
    sequence: int,
    occurred_at: datetime,
    event_key: str,
) -> dict:
    """Build and self-validate one ``file.discovered.v1`` envelope."""
    envelope = {
        "event_id": deterministic_event_id(event_key),
        "collection_id": collection_id,
        "job_id": job_id,
        "sequence": sequence,
        "event_type": EVENT_TYPE_FILE_DISCOVERED,
        "timestamp": occurred_at.astimezone(UTC).isoformat(),
        "payload": {
            "collection_id": collection_id,
            "source_root_id": source_root_id,
            # Contract spelling: discovered_files — NOT files_discovered.
            "discovered_files": 1,
            "discovered_bytes": discovered_bytes,
            "manifest_revision": manifest_revision,
        },
        "schema_version": SCHEMA_VERSION,
    }
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope: object) -> None:
    """Fail-closed validation against the collection-event contract.

    Structural rules mirror ``CollectionEventEnvelope`` (pydantic) and the
    JSON Schema; payload rules mirror ``validate_collection_event_payload``
    restricted to the single event type this watcher emits.
    """
    if not isinstance(envelope, dict):
        raise ValueError("envelope must be an object")
    if set(envelope) != ENVELOPE_FIELDS:
        extra = sorted(set(envelope) - ENVELOPE_FIELDS)
        missing = sorted(ENVELOPE_FIELDS - set(envelope))
        raise ValueError(f"envelope field mismatch: extra={extra} missing={missing}")
    if envelope["event_type"] != EVENT_TYPE_FILE_DISCOVERED:
        raise ValueError(f"unsupported event_type: {envelope['event_type']!r}")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema_version must be '1.0'")
    for key in ("event_id", "collection_id"):
        value = envelope[key]
        if not isinstance(value, str) or not _UUID36.match(value):
            raise ValueError(f"envelope.{key} must be a lowercase uuid string")
    job_id = envelope["job_id"]
    if job_id is not None and (not isinstance(job_id, str) or not _UUID36.match(job_id)):
        raise ValueError("envelope.job_id must be null or a lowercase uuid string")
    sequence = envelope["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("envelope.sequence must be an integer >= 1")
    timestamp = envelope["timestamp"]
    if not isinstance(timestamp, str):
        raise ValueError("envelope.timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("envelope.timestamp must be timezone-aware")

    _validate_payload(envelope["payload"], envelope["collection_id"])


def _validate_payload(payload: object, envelope_collection_id: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    _reject_forbidden_keys(payload, "$")
    missing = [key for key in _FILE_DISCOVERED_REQUIRED if key not in payload]
    if missing:
        raise ValueError(f"payload missing required keys: {sorted(missing)}")
    for key, expected in _FILE_DISCOVERED_REQUIRED.items():
        value = payload[key]
        if expected is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"payload.{key} must be an integer")
            if not 0 <= value <= _INT64_MAX:
                raise ValueError(f"payload.{key} out of range")
        elif not isinstance(value, str):
            raise ValueError(f"payload.{key} must be a string")
    if not _UUID36.match(payload["collection_id"]):
        raise ValueError("payload.collection_id must be a lowercase uuid string")
    if not _UUID36.match(payload["source_root_id"]):
        raise ValueError("payload.source_root_id must be a lowercase uuid string")
    if payload["collection_id"] != envelope_collection_id:
        raise ValueError("payload identity mismatch with envelope.collection_id")


def _reject_forbidden_keys(node: object, path: str) -> None:
    if isinstance(node, dict):
        if len(node) > 256:
            raise ValueError(f"mapping too large at {path}")
        for key, item in node.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_PAYLOAD_KEYS or normalized.endswith(("_path", "_url")):
                raise ValueError(f"forbidden payload key at {path}.{key}")
            _reject_forbidden_keys(item, f"{path}.{normalized}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_forbidden_keys(item, f"{path}[{index}]")
    elif isinstance(node, str):
        if len(node) > 2048:
            raise ValueError(f"string too long at {path}")
