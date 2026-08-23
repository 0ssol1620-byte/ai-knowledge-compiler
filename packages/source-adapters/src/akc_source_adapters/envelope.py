"""Change events, cursors, and the adapter protocol every source connector shares.

A source adapter turns one upstream system (a git remote, an Obsidian vault) into
an ordered stream of :class:`ChangeEvent` envelopes that the compiler can hash,
store, and resume from. Two invariants hold across every adapter:

* **Determinism.** The same logical change always serializes to the same bytes.
  Payload mappings are normalized (sorted keys, UTC timestamps, no whitespace
  variance), so ``stable_hash`` of an event is stable across processes, hosts,
  and dict insertion order. Downstream deduplication and provenance chains
  depend on this; it is why the hash exists at all.
* **Resumability.** A poll never has to start from scratch. Every fetch returns
  a :class:`Cursor`, and ``fetch_changes(cursor)`` emits exactly the changes the
  previous cursor cannot see. Cursors encode to a single opaque string so a
  scheduler can persist them between runs — which is what migration
  ``0039_source_adapter_cursors`` stores.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

EVENT_HASH_PREFIX = "sha256:"
CANONICAL_JSON_SEPARATORS = (",", ":")


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def _normalize(value: object) -> Any:
    """Reduce ``value`` to plain JSON types with deterministic forms.

    Mappings lose their insertion order (re-added sorted later by ``json.dumps``),
    datetimes and dates become ISO-8601 strings, tuples become lists. Anything
    else raises ``TypeError``, so a payload that only *looks* serializable fails
    here rather than corrupting a stored hash.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TypeError(f"non-finite float is not JSON-serializable: {value!r}")
        return value
    if isinstance(value, datetime):
        return _isoformat_utc(value)
    if isinstance(value, (bytes, bytearray)):
        raise TypeError("bytes are not JSON-serializable; hex- or base64-encode first")
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_normalize(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    raise TypeError(f"value of type {type(value).__name__} is not JSON-serializable")


def _isoformat_utc(value: datetime) -> str:
    """RFC 3339 string in UTC; naive inputs are interpreted as UTC."""
    moment = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return moment.isoformat().replace("+00:00", "Z")


def canonical_json(payload: object) -> str:
    """Deterministic JSON text: sorted keys, compact separators, UTF-8 text."""
    return json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=CANONICAL_JSON_SEPARATORS,
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_hash(payload: object) -> str:
    """Content hash of ``payload``'s canonical form, prefixed for provenance."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{EVENT_HASH_PREFIX}{digest}"


def _require_non_empty(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """One observed change from one source, wrapped in a hashable envelope.

    ``revision`` identifies the upstream state the change moves to (a commit
    sha, a content hash); ``observed_at`` is when *this adapter* saw it, not
    when the source changed — the payload carries upstream timestamps where
    they exist. Naive datetimes are treated as UTC; other offsets are converted.
    """

    source_id: str
    provider: str
    kind: str
    revision: str
    observed_at: datetime
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("source_id", "provider", "kind", "revision"):
            _require_non_empty(attr, getattr(self, attr))
        if not isinstance(self.observed_at, datetime):
            raise ValueError(
                f"observed_at must be a datetime, got {type(self.observed_at).__name__}"
            )
        try:
            canonical_json(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload must be JSON-serializable: {exc}") from exc

    def as_dict(self) -> dict[str, Any]:
        """Canonical field order, timestamps normalized, payload normalized."""
        return {
            "kind": self.kind,
            "observed_at": _isoformat_utc(self.observed_at),
            "payload": _normalize(self.payload),
            "provider": self.provider,
            "revision": self.revision,
            "source_id": self.source_id,
        }

    def canonical(self) -> str:
        """The exact byte sequence the event hash commits to."""
        return canonical_json(self.as_dict())

    @property
    def event_hash(self) -> str:
        """Stable identity of this change; equal changes hash equally."""
        return stable_hash(self.as_dict())


@dataclass(frozen=True, slots=True)
class Cursor:
    """Opaque resume token for one source's poll position.

    ``state`` holds adapter-defined, JSON-native values only (dicts, lists,
    strings, ints). :meth:`encode` / :meth:`decode` carry it across process
    boundaries as one base64 string, deterministically: encoding is canonical
    JSON underneath, so the same state always yields the same token.
    """

    provider: str
    source_id: str
    state: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("provider", "source_id"):
            _require_non_empty(attr, getattr(self, attr))
        try:
            canonical_json(self.state)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"cursor state must be JSON-serializable: {exc}") from exc

    def encoded(self) -> str:
        envelope = {
            "provider": self.provider,
            "source_id": self.source_id,
            "state": _normalize(self.state),
        }
        raw = canonical_json(envelope).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        """Parse a token from :meth:`encoded`; raises ValueError on tampering."""
        if not isinstance(token, str) or not token:
            raise ValueError("cursor token must be a non-empty string")
        try:
            envelope = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
        except (binascii.Error, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cursor token is not decodable: {exc}") from exc
        required = {"provider", "source_id", "state"}
        if not isinstance(envelope, dict) or not required <= set(envelope):
            raise ValueError("cursor token payload is missing required fields")
        return cls(
            provider=envelope["provider"],
            source_id=envelope["source_id"],
            state=envelope["state"],
        )


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What one poll produced: ordered events plus the position after them."""

    events: tuple[ChangeEvent, ...]
    cursor: Cursor

    def __len__(self) -> int:
        return len(self.events)


@runtime_checkable
class SourceAdapter(Protocol):
    """Structural interface every connector implements.

    ``discover`` reports the source's current shape without emitting change
    events (head revision, note count, paths). ``fetch_changes`` returns the
    changes since ``cursor`` — pass ``None`` for the initial full pull — each
    result carrying the cursor to resume from next time. ``checkpoint``
    snapshots the current position without fetching anything, so a scheduler
    can park a source mid-stream.
    """

    provider: str

    def discover(self) -> Mapping[str, object]: ...

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult: ...

    def checkpoint(self) -> Cursor: ...
