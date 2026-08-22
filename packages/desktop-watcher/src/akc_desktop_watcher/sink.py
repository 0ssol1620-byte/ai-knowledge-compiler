"""Structured event sinks. Events never go to stdout; they go here."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class EventSink(Protocol):
    def deliver(self, record: dict) -> None:
        """Consume one watcher record.

        Delivery is at-least-once: a sink that raises leaves the journal entry
        unacknowledged, so the record will be replayed on restart. Sinks must
        therefore be idempotent by ``record["event_key"]`` (JsonlFileSink is).
        """
        ...


class CallbackEventSink:
    def __init__(self, callback: Callable[[dict], None]) -> None:
        self._callback = callback

    def deliver(self, record: dict) -> None:
        self._callback(record)


class SinkDeliveryError(RuntimeError):
    def __init__(self, failures: list[tuple[str, str]]) -> None:
        joined = "; ".join(f"{name}: {message}" for name, message in failures)
        super().__init__(f"all sinks attempted, {len(failures)} failed: {joined}")


class CompositeEventSink:
    """Deliver to every sink; raise only after all were attempted."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = list(sinks)

    def add(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def close(self) -> None:
        for sink in self._sinks:
            closer = getattr(sink, "close", None)
            if callable(closer):
                closer()

    def deliver(self, record: dict) -> None:
        failures: list[tuple[str, str]] = []
        for index, sink in enumerate(self._sinks):
            try:
                sink.deliver(record)
            except Exception as exc:  # noqa: BLE001 - report after full fan-out
                failures.append((f"sink[{index}]", repr(exc)))
        if failures:
            raise SinkDeliveryError(failures)


class JsonlFileSink:
    """Append records as JSONL; skips event_keys already present in the file.

    Idempotent across restarts: existing lines are scanned on init so a
    replayed record is not written twice.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_event_keys = self._load_seen()
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")

    def _load_seen(self) -> set[str]:
        seen: set[str] = set()
        if not self.path.exists():
            return seen
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("event_key"), str):
                    seen.add(obj["event_key"])
        return seen

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> JsonlFileSink:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def deliver(self, record: dict) -> None:
        key = record.get("event_key")
        if isinstance(key, str) and key in self.seen_event_keys:
            return
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        self._fh.write(payload + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        if isinstance(key, str):
            self.seen_event_keys.add(key)
