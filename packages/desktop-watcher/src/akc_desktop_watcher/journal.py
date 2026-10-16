"""Append-only JSONL write-ahead journal with crash-safe replay.

Line kinds (one JSON object per newline-terminated line):

- ``{"kind":"event","event_key":...,"record":{...}}`` — written BEFORE the
  record is handed to sinks. A crash between append and delivery leaves an
  unacknowledged event that replay re-delivers on next start.
- ``{"kind":"ack","event_key":...}`` — written AFTER all sinks accepted the
  record; replay treats acknowledged events as done.
- ``{"kind":"state","root":...,"rel":...,"content_sha256":...,"generation":...,
  "manifest_revision":...,"sequence":...}`` — dedup map entries and monotonic
  counters, appended whenever they change.

Replay folds the log into: unprocessed records (ordered), latest dedup state
per ``(root, rel)``, and max counters. A torn trailing line (hard kill during
append) is truncated at open; corrupt middle lines are skipped and counted.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("akc_desktop_watcher.journal")


@dataclass(frozen=True)
class DedupEntry:
    content_sha256: str | None  # None after removal; suppression requires equality
    generation: int


@dataclass(frozen=True)
class ReplayResult:
    unprocessed: list[dict[str, Any]]
    dedup: dict[tuple[str, str], DedupEntry]
    manifest_revision: int
    sequence: int
    skipped_lines: int


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._repair_partial_tail()
        # Serializes append+flush+fsync so handler threads and the scheduler
        # thread can share one Journal instance without interleaved lines.
        self._write_lock = threading.Lock()
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def append_event(self, record: dict[str, Any]) -> None:
        self._append_line(
            {"kind": "event", "event_key": record["event_key"], "record": record}
        )

    def append_ack(self, event_key: str) -> None:
        self._append_line({"kind": "ack", "event_key": event_key})

    def append_state(
        self,
        *,
        root: str,
        rel: str,
        content_sha256: str | None,
        generation: int,
        manifest_revision: int,
        sequence: int,
    ) -> None:
        self._append_line(
            {
                "kind": "state",
                "root": root,
                "rel": rel,
                "content_sha256": content_sha256,
                "generation": generation,
                "manifest_revision": manifest_revision,
                "sequence": sequence,
            }
        )

    def replay(self) -> ReplayResult:
        unprocessed: dict[str, dict[str, Any]] = {}
        dedup: dict[tuple[str, str], DedupEntry] = {}
        manifest_revision = 0
        sequence = 0
        skipped = 0
        for line in self._iter_lines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            kind = obj.get("kind") if isinstance(obj, dict) else None
            if kind == "event":
                key = obj.get("event_key")
                record = obj.get("record")
                if isinstance(key, str) and isinstance(record, dict):
                    unprocessed[key] = record
                else:
                    skipped += 1
            elif kind == "ack":
                key = obj.get("event_key")
                if isinstance(key, str):
                    unprocessed.pop(key, None)
                else:
                    skipped += 1
            elif kind == "state":
                root, rel = obj.get("root"), obj.get("rel")
                if not isinstance(root, str) or not isinstance(rel, str):
                    skipped += 1
                    continue
                # Windows paths are case-insensitive: fold both components so
                # replay produces the same dedup keys the writer used.
                dedup[(root.casefold(), rel.casefold())] = DedupEntry(
                    content_sha256=obj.get("content_sha256"),
                    generation=int(obj.get("generation", 0)),
                )
                manifest_revision = max(manifest_revision, int(obj.get("manifest_revision", 0)))
                sequence = max(sequence, int(obj.get("sequence", 0)))
            else:
                skipped += 1
        return ReplayResult(
            unprocessed=list(unprocessed.values()),
            dedup=dedup,
            manifest_revision=manifest_revision,
            sequence=sequence,
            skipped_lines=skipped,
        )

    def _iter_lines(self) -> Iterator[str]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    yield stripped

    def _append_line(self, obj: dict[str, Any]) -> None:
        payload = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        with self._write_lock:
            self._fh.write(payload + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())

    def _repair_partial_tail(self) -> None:
        """Drop a torn trailing write so future appends stay line-aligned."""
        if not self.path.exists():
            return
        size = self.path.stat().st_size
        if size == 0:
            return
        with self.path.open("rb") as fh:
            fh.seek(max(0, size - 1))
            tail_byte = fh.read(1)
            if tail_byte == b"\n":
                return
            # Find the last complete line boundary.
            window_start = max(0, size - 65536)
            with self.path.open("rb") as scan:
                scan.seek(window_start)
                chunk = scan.read()
        last_newline = chunk.rfind(b"\n")
        keep = window_start + last_newline + 1 if last_newline != -1 else 0
        logger.warning(
            "journal %s: truncating torn trailing bytes (%d -> %d)",
            self.path,
            size,
            keep,
        )
        with self.path.open("r+b") as fh:
            fh.truncate(keep)
