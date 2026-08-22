"""Append-only, hash-chained evidence ledger for resumable v6 provider runs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_sha256,
    require_sha256,
)

_GENESIS_SHA256 = "sha256:" + ("0" * 64)
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,95}\.v1$")
_RUN_TAG_RE = re.compile(r"^v6-[a-z0-9][a-z0-9._-]{2,127}$")
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "sequence",
        "cohort_id",
        "run_tag",
        "event_type",
        "occurred_at",
        "previous_sha256",
        "payload",
        "event_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    sequence: int
    cohort_id: str
    run_tag: str
    event_type: str
    occurred_at: str
    previous_sha256: str
    payload: Mapping[str, object]
    event_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "6.0.0",
            "sequence": self.sequence,
            "cohort_id": self.cohort_id,
            "run_tag": self.run_tag,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "previous_sha256": self.previous_sha256,
            "payload": dict(self.payload),
            "event_sha256": self.event_sha256,
        }


class EvidenceLedger:
    """One immutable cohort ledger.

    A separate exclusive lock file prevents two processes from appending based
    on the same tail.  A stale lock is not broken automatically: uncertain
    writer state must be reconciled explicitly rather than risk duplicate work.
    """

    def __init__(self, path: Path, *, cohort_id: str, run_tag: str) -> None:
        if not cohort_id.strip():
            raise ContractError("ledger cohort_id is required")
        if not _RUN_TAG_RE.fullmatch(run_tag):
            raise ContractError("ledger run_tag must be an immutable v6 tag")
        if path.suffix.casefold() not in {".jsonl", ".ndjson"}:
            raise ContractError("evidence ledger must use .jsonl or .ndjson")
        self.path = path.resolve(strict=False)
        self.cohort_id = cohort_id
        self.run_tag = run_tag
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def replay(self) -> tuple[LedgerEvent, ...]:
        if not self.path.exists():
            return ()
        try:
            content = self.path.read_bytes()
        except OSError as exc:
            raise ContractError(f"cannot read evidence ledger: {exc}") from exc
        if not content:
            return ()
        if not content.endswith(b"\n"):
            raise ContractError("evidence ledger has a truncated final record")
        events: list[LedgerEvent] = []
        previous = _GENESIS_SHA256
        for sequence, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                raise ContractError("evidence ledger contains a blank record")
            try:
                raw = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ContractError(f"invalid evidence ledger JSON at sequence {sequence}") from exc
            event = self._parse_event(raw, expected_sequence=sequence, previous=previous)
            events.append(event)
            previous = event.event_sha256
        self._validate_semantics(events)
        return tuple(events)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> LedgerEvent:
        if not _EVENT_TYPE_RE.fullmatch(event_type):
            raise ContractError("ledger event_type must be a namespaced *.v1 identifier")
        if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
            raise ContractError("ledger payload must be an object with string keys")
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ContractError("ledger occurred_at must be timezone-aware")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = self._acquire_lock()
        try:
            existing = self.replay()
            previous = existing[-1].event_sha256 if existing else _GENESIS_SHA256
            body: dict[str, object] = {
                "schema_version": "6.0.0",
                "sequence": len(existing) + 1,
                "cohort_id": self.cohort_id,
                "run_tag": self.run_tag,
                "event_type": event_type,
                "occurred_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "previous_sha256": previous,
                "payload": dict(payload),
            }
            body["event_sha256"] = canonical_sha256(body)
            event = self._parse_event(
                body,
                expected_sequence=len(existing) + 1,
                previous=previous,
            )
            self._validate_semantics([*existing, event])
            encoded = canonical_json_bytes(body) + b"\n"
            try:
                with self.path.open("ab", buffering=0) as handle:
                    handle.write(encoded)
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise ContractError(f"cannot append evidence ledger: {exc}") from exc
            return event
        finally:
            self._release_lock(lock_fd)

    def iter_type(self, event_type: str) -> Iterator[LedgerEvent]:
        return (event for event in self.replay() if event.event_type == event_type)

    def latest(self, event_type: str) -> LedgerEvent | None:
        matches = tuple(self.iter_type(event_type))
        return matches[-1] if matches else None

    def terminal_sha256(self) -> str:
        events = self.replay()
        return events[-1].event_sha256 if events else _GENESIS_SHA256

    def _acquire_lock(self) -> int:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            lock_fd = os.open(self.lock_path, flags, 0o600)
        except FileExistsError as exc:
            raise ContractError(
                "evidence ledger is locked; reconcile the writer before resuming"
            ) from exc
        try:
            os.write(lock_fd, f"pid={os.getpid()}\n".encode())
            os.fsync(lock_fd)
        except OSError:
            os.close(lock_fd)
            self.lock_path.unlink(missing_ok=True)
            raise
        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        os.close(lock_fd)
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            raise ContractError("evidence ledger lock disappeared during append") from None

    def _parse_event(
        self, value: object, *, expected_sequence: int, previous: str
    ) -> LedgerEvent:
        if not isinstance(value, Mapping):
            raise ContractError("evidence ledger record must be an object")
        keys = set(value)
        if keys != _RECORD_KEYS:
            raise ContractError(
                "evidence ledger record shape drift "
                f"(missing={sorted(_RECORD_KEYS - keys)}, unknown={sorted(keys - _RECORD_KEYS)})"
            )
        if value["schema_version"] != "6.0.0":
            raise ContractError("evidence ledger schema_version must be 6.0.0")
        if value["sequence"] != expected_sequence:
            raise ContractError("evidence ledger sequence is not contiguous")
        if value["cohort_id"] != self.cohort_id or value["run_tag"] != self.run_tag:
            raise ContractError("evidence ledger cohort/run tag changed")
        event_type = value["event_type"]
        if not isinstance(event_type, str) or not _EVENT_TYPE_RE.fullmatch(event_type):
            raise ContractError("evidence ledger event_type is invalid")
        occurred_at = value["occurred_at"]
        if not isinstance(occurred_at, str):
            raise ContractError("evidence ledger occurred_at must be a string")
        _parse_timestamp(occurred_at)
        if value["previous_sha256"] != previous:
            raise ContractError("evidence ledger hash chain is broken")
        if not isinstance(value["payload"], Mapping) or any(
            not isinstance(key, str) for key in value["payload"]
        ):
            raise ContractError("evidence ledger payload must be an object")
        event_sha = value["event_sha256"]
        if not isinstance(event_sha, str):
            raise ContractError("evidence ledger event_sha256 must be a string")
        require_sha256(event_sha, "event_sha256")
        unhashed = {key: item for key, item in value.items() if key != "event_sha256"}
        if canonical_sha256(unhashed) != event_sha:
            raise ContractError("evidence ledger event hash mismatch")
        return LedgerEvent(
            sequence=expected_sequence,
            cohort_id=self.cohort_id,
            run_tag=self.run_tag,
            event_type=event_type,
            occurred_at=occurred_at,
            previous_sha256=previous,
            payload=dict(value["payload"]),
            event_sha256=event_sha,
        )

    def _validate_semantics(self, events: list[LedgerEvent]) -> None:
        plan_count = 0
        intents: dict[str, tuple[str, str]] = {}
        dispatches: dict[str, str] = {}
        provider_jobs: dict[str, str] = {}
        accepted: set[str] = set()
        charged: set[str] = set()
        nonbillable: set[str] = set()
        absence: set[str] = set()
        for event in events:
            payload = event.payload
            if event.event_type == "cohort.plan.frozen.v1":
                plan_count += 1
                if plan_count > 1:
                    raise ContractError("cohort plan may be frozen only once")
            elif event.event_type == "job.dispatch.intent.v1":
                key = _payload_string(payload, "idempotency_key", event.event_type)
                logical = _payload_string(payload, "logical_work_id", event.event_type)
                input_sha = _payload_sha(payload, "input_sha256", event.event_type)
                if key in intents:
                    raise ContractError("duplicate dispatch intent idempotency key")
                intents[key] = (logical, input_sha)
            elif event.event_type == "job.dispatched.v1":
                key = _payload_string(payload, "idempotency_key", event.event_type)
                logical = _payload_string(payload, "logical_work_id", event.event_type)
                provider_job = _payload_string(payload, "provider_job_id", event.event_type)
                input_sha = _payload_sha(payload, "input_sha256", event.event_type)
                if key not in intents or intents[key] != (logical, input_sha):
                    raise ContractError("dispatch acknowledgement has no matching immutable intent")
                if key in dispatches:
                    raise ContractError("idempotency key has multiple dispatch acknowledgements")
                if provider_job in provider_jobs:
                    raise ContractError("provider job ID is bound to multiple dispatches")
                dispatches[key] = provider_job
                provider_jobs[provider_job] = key
            elif event.event_type == "job.accepted.v1":
                logical = _payload_string(payload, "logical_work_id", event.event_type)
                provider_job = _payload_string(payload, "provider_job_id", event.event_type)
                if provider_job not in provider_jobs:
                    raise ContractError("accepted job was not dispatched by this ledger")
                if logical in accepted:
                    raise ContractError("logical work has multiple accepted results")
                accepted.add(logical)
            elif event.event_type == "user.charge.settled.v1":
                logical = _payload_string(payload, "logical_work_id", event.event_type)
                if logical not in accepted:
                    raise ContractError("user charge requires an accepted result")
                if logical in charged or logical in nonbillable:
                    raise ContractError("logical work has multiple user charges")
                charged.add(logical)
            elif event.event_type == "user.nonbillable.finalized.v1":
                logical = _payload_string(payload, "logical_work_id", event.event_type)
                if logical in charged or logical in nonbillable:
                    raise ContractError("logical work has multiple billing finalizations")
                if payload.get("amount_usd") != "0":
                    raise ContractError("nonbillable finalization amount must be zero")
                nonbillable.add(logical)
            elif event.event_type == "endpoint.provider_absent.v1":
                endpoint = _payload_string(payload, "endpoint_id", event.event_type)
                if endpoint in absence:
                    raise ContractError("endpoint has multiple terminal absence receipts")
                absence.add(endpoint)


def _payload_string(payload: Mapping[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"{context}.{key} must be a non-empty string")
    return value


def _payload_sha(payload: Mapping[str, object], key: str, context: str) -> str:
    value = _payload_string(payload, key, context)
    return require_sha256(value, f"{context}.{key}")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("evidence ledger occurred_at must be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ContractError("evidence ledger occurred_at must include a timezone")
    return parsed
