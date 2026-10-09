"""Filesystem watch loop: watchdog Observer + stability window + sha256 dedup.

Architecture (single-writer):

- watchdog Observer threads only translate FS events into pending-map updates:
  create/modify schedule stabilization of the path; delete/move-away schedule
  a removal (dedup slot cleared so recreation re-emits).
- one scheduler thread promotes pending paths that have been quiet for
  ``stability_window_seconds`` — hash (sha256) -> dedup check -> journal ->
  sink -> ack -> journal state. All journal writes happen on that thread
  (plus replay on start), so appends never race.
- rapid consecutive writes keep bumping ``changed_at``; only when the path has
  been quiet for a full window is it hashed, collapsing bursts into one event
  carrying the final content.

Crash-safety contract (see journal.py): events are journaled before delivery
and acknowledged after every sink accepted them; unacknowledged records are
redelivered on next start. Sinks must be idempotent by ``record["event_key"]``
(JsonlFileSink is). The sha256 dedup map is journaled as state lines, so a
restart neither re-emits unchanged files nor loses counter progress
(``manifest_revision``/``sequence`` continue where the previous run stopped).

Envelopes carry aggregate counters only; local paths/hashes live in the
watcher record (journal/sink), never inside the contract envelope payload.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

# watchdog is this package's dependency; import stubs vary by environment.
from watchdog.events import (  # type: ignore[import-not-found,unused-ignore]
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import (  # type: ignore[import-not-found,unused-ignore]
    Observer as BaseObserver,
)

from .config import RootConfig, WatcherConfig
from .events import (
    build_discovery_envelope,
    build_event_key,
    source_root_id_for,
)
from .journal import DedupEntry, Journal
from .sink import CompositeEventSink, EventSink, JsonlFileSink

logger = logging.getLogger("akc_desktop_watcher.watcher")


@dataclass(frozen=True)
class _Root:
    config: RootConfig
    key: str  # source_root_id used in journal state lines and event keys


@dataclass
class WatcherStats:
    emitted: int = 0
    suppressed_unchanged: int = 0
    removals_cleared: int = 0
    redelivered: int = 0
    delivery_failures: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "emitted": self.emitted,
            "suppressed_unchanged": self.suppressed_unchanged,
            "removals_cleared": self.removals_cleared,
            "redelivered": self.redelivered,
            "delivery_failures": self.delivery_failures,
        }


@dataclass(frozen=True)
class _Pending:
    root: _Root
    changed_at: float
    deleted: bool = False


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a slash-aware glob ('**', '*', '?') into an anchored regex."""
    parts = [part for part in pattern.replace("\\", "/").split("/") if part not in ("", ".")]
    out: list[str] = ["^"]
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            segment: list[str] = []
            for char in part:
                if char == "*":
                    segment.append("[^/]*")
                elif char == "?":
                    segment.append("[^/]")
                else:
                    segment.append(re.escape(char))
            out.append("".join(segment) + ("" if last else "/"))
    out.append("$")
    return re.compile("".join(out))


class _ExcludeMatcher:
    """Slash-aware exclude matcher with gitignore-style bare patterns.

    A pattern without '/' also matches against the basename at any depth
    (e.g. ``*.tmp`` excludes ``sub/report.tmp``).
    """

    def __init__(self, globs: tuple[str, ...] | list[str]) -> None:
        self._compiled: list[tuple[re.Pattern[str], bool]] = [
            (_glob_to_regex(pattern), "/" not in pattern.strip()) for pattern in globs
        ]

    def matches(self, rel_posix: str) -> bool:
        for regex, basename_only in self._compiled:
            if regex.match(rel_posix):
                return True
            if basename_only:
                base = rel_posix.rsplit("/", 1)[-1]
                if regex.match(base):
                    return True
        return False


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DesktopWatcher:
    """Crash-safe local-folder watcher emitting contract-valid discovery events."""

    def __init__(
        self,
        config: WatcherConfig,
        *,
        sink: EventSink | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._clock = clock
        if sink is None:
            fallback = CompositeEventSink()
            if config.event_sink_path:
                fallback.add(JsonlFileSink(config.event_sink_path))
            sink = fallback
        self._sink = sink
        self._roots = tuple(
            _Root(
                config=root,
                key=root.source_root_id or source_root_id_for(str(root.path)),
            )
            for root in config.roots
        )
        self._matchers = {
            root.key: _ExcludeMatcher(root.config.exclude_globs) for root in self._roots
        }
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._dedup: dict[tuple[str, str], DedupEntry] = {}
        self._manifest_revision = config.initial_manifest_revision
        self._sequence = 0
        self._stats = WatcherStats()
        self._journal: Journal | None = None
        # watchdog.observers.Observer is a platform-selected runtime alias,
        # not a static type, so the attribute is intentionally loosely typed.
        self._observer: Any = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._started:
            raise RuntimeError("watcher already started")
        journal = Journal(Path(self._config.journal_path))
        self._journal = journal

        replayed = journal.replay()
        with self._lock:
            self._dedup = dict(replayed.dedup)
            self._manifest_revision = max(
                self._config.initial_manifest_revision, replayed.manifest_revision
            )
            self._sequence = replayed.sequence

        # Redeliver records whose sinks were never acknowledged (at-least-once).
        for record in replayed.unprocessed:
            try:
                self._sink.deliver(record)
            except Exception:
                self._stats.delivery_failures += 1
                logger.exception(
                    "redelivery failed for %s; left unacknowledged", record.get("event_key")
                )
            else:
                journal.append_ack(record["event_key"])
                self._stats.redelivered += 1

        observer = BaseObserver()
        for root in self._roots:
            observer.schedule(_RootHandler(self, root), str(root.config.path), recursive=True)
        observer.start()
        self._observer = observer

        if self._config.reconcile_on_start:
            for root in self._roots:
                self._schedule_tree(root.config.path, root)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="akc-desktop-watcher", daemon=True
        )
        self._thread.start()
        self._started = True
        logger.info(
            "watching %d root(s); replay redelivered=%d skipped_lines=%d",
            len(self._roots),
            self._stats.redelivered,
            replayed.skipped_lines,
        )

    def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._started = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout)
            self._observer = None
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def __enter__(self) -> DesktopWatcher:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # -- introspection -----------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            return self._stats.snapshot()

    def pending_paths(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._pending)

    @property
    def manifest_revision(self) -> int:
        with self._lock:
            return self._manifest_revision

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    # -- event intake (Observer threads; pending map only) ------------------

    def _resolve(self, raw: str | bytes | Path) -> Path | None:
        try:
            return Path(os.fsdecode(raw)).resolve()
        except OSError:
            return None

    def _relative(self, resolved: Path, root: _Root) -> Path | None:
        try:
            rel = resolved.relative_to(root.config.path)
        except ValueError:
            return None
        return rel if rel.parts else None

    def _schedule_file(self, raw: str | bytes | Path, root: _Root) -> None:
        resolved = self._resolve(raw)
        if resolved is None:
            return
        rel = self._relative(resolved, root)
        if rel is None:
            return
        if self._matchers[root.key].matches(rel.as_posix()):
            return
        with self._lock:
            self._pending[str(resolved)] = _Pending(root=root, changed_at=self._clock())

    def _schedule_tree(self, raw: str | bytes | Path, root: _Root) -> None:
        base = self._resolve(raw)
        if base is None or not base.is_dir():
            return
        try:
            children = list(base.rglob("*"))
        except OSError:
            return
        for child in children:
            try:
                if child.is_file():
                    self._schedule_file(child, root)
            except OSError:
                continue

    def _forget(self, raw: str | bytes | Path, root: _Root) -> None:
        """Schedule removal processing for a deleted/moved-away path."""
        resolved = self._resolve(raw)
        if resolved is None:
            return
        if self._relative(resolved, root) is None:
            return
        with self._lock:
            self._pending[str(resolved)] = _Pending(
                root=root, changed_at=self._clock(), deleted=True
            )

    # -- scheduler thread (single writer) -----------------------------------

    def _run(self) -> None:
        poll = self._config.poll_interval_seconds
        window = self._config.stability_window_seconds
        while not self._stop_event.wait(poll):
            now = self._clock()
            due: list[tuple[str, _Pending]] = []
            with self._lock:
                for path_str, item in list(self._pending.items()):
                    if item.deleted or now - item.changed_at >= window:
                        due.append((path_str, item))
                        del self._pending[path_str]
            for path_str, item in due:
                try:
                    if item.deleted:
                        self._apply_removal(Path(path_str), item)
                    else:
                        self._process_stable(Path(path_str), item.root)
                except Exception:
                    logger.exception("failed processing pending path %s", path_str)

    def _under(self, path_str: str, directory: Path) -> bool:
        candidate = Path(path_str)
        return candidate == directory or directory in candidate.parents

    def _apply_removal(self, resolved: Path, item: _Pending) -> None:
        rel = self._relative(resolved, item.root)
        if rel is None:
            return
        rel_cf = rel.as_posix().casefold()
        prefix = f"{rel_cf}/"
        with self._lock:
            affected = [
                key
                for key in self._dedup
                if key[0] == item.root.key and (key[1] == rel_cf or key[1].startswith(prefix))
            ]
            # Keep the slot with content_sha256=None (journal contract: None
            # means "cleared"; suppression requires equality with a real
            # digest) so recreation re-emits while generation continuity and
            # per-path history survive.
            cleared: list[tuple[tuple[str, str], DedupEntry]] = []
            for key in affected:
                entry = self._dedup[key]
                if entry.content_sha256 is None:
                    continue  # already cleared; do not spam more state lines
                cleared.append((key, entry))
                self._dedup[key] = DedupEntry(
                    content_sha256=None, generation=entry.generation
                )
            for pending_path in [p for p in self._pending if self._under(p, resolved)]:
                del self._pending[pending_path]
            revision, sequence = self._manifest_revision, self._sequence
        if not cleared:
            return
        assert self._journal is not None
        for key, entry in cleared:
            self._journal.append_state(
                root=key[0],
                rel=key[1],
                content_sha256=None,
                generation=entry.generation,
                manifest_revision=revision,
                sequence=sequence,
            )
        self._stats.removals_cleared += len(cleared)

    def _process_stable(self, resolved: Path, root: _Root) -> None:
        try:
            size = resolved.stat().st_size
            digest = _sha256_file(resolved)
        except OSError:
            return  # vanished while pending; nothing to emit
        rel = self._relative(resolved, root)
        if rel is None:
            return
        rel_posix = rel.as_posix()
        if self._matchers[root.key].matches(rel_posix):
            return
        rel_cf = rel_posix.casefold()
        key = (root.key, rel_cf)

        with self._lock:
            previous = self._dedup.get(key)
            if previous is not None and previous.content_sha256 == digest:
                self._stats.suppressed_unchanged += 1
                return
            generation = (previous.generation if previous is not None else 0) + 1
            self._manifest_revision += 1
            self._sequence += 1
            revision, sequence = self._manifest_revision, self._sequence

        event_key = build_event_key("discovery", root.key, rel_cf, digest, generation)
        envelope = build_discovery_envelope(
            collection_id=self._config.collection_id,
            job_id=self._config.job_id,
            source_root_id=root.key,
            discovered_bytes=size,
            manifest_revision=revision,
            sequence=sequence,
            occurred_at=datetime.now(UTC),
            event_key=event_key,
        )
        record = {
            "event_key": event_key,
            "event_id": envelope["event_id"],
            "event_type": envelope["event_type"],
            "collection_id": self._config.collection_id,
            "job_id": self._config.job_id,
            "source_root_id": root.key,
            "sequence": sequence,
            "manifest_revision": revision,
            "timestamp": envelope["timestamp"],
            "relative_path": rel_posix,
            "content_sha256": digest,
            "size_bytes": size,
            "generation": generation,
            "action": "modified" if previous is not None else "created",
            "envelope": envelope,
        }

        assert self._journal is not None
        self._journal.append_event(record)
        try:
            self._sink.deliver(record)
        except Exception:
            # Leave unacknowledged: replay redelivers on next start, and the
            # dedup slot stays unset so the scheduler retries in-process too.
            self._stats.delivery_failures += 1
            logger.exception("sink delivery failed for %s; left unacknowledged", event_key)
            return
        self._journal.append_ack(event_key)
        with self._lock:
            self._dedup[key] = DedupEntry(content_sha256=digest, generation=generation)
            self._stats.emitted += 1
        # Persist the new dedup slot + counters so a restart neither re-emits
        # this file nor resets manifest_revision/sequence progress.
        self._journal.append_state(
            root=key[0],
            rel=key[1],
            content_sha256=digest,
            generation=generation,
            manifest_revision=revision,
            sequence=sequence,
        )


class _RootHandler(FileSystemEventHandler):  # type: ignore[misc,unused-ignore]
    """Translates watchdog events into pending-map updates. No I/O here."""

    def __init__(self, watcher: DesktopWatcher, root: _Root) -> None:
        super().__init__()
        self._watcher = watcher
        self._root = root

    def on_created(self, event: FileSystemEvent) -> None:
        if isinstance(event, DirCreatedEvent):
            self._watcher._schedule_tree(event.src_path, self._root)
        elif isinstance(event, FileCreatedEvent):
            self._watcher._schedule_file(event.src_path, self._root)

    def on_modified(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileModifiedEvent):
            self._watcher._schedule_file(event.src_path, self._root)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if isinstance(event, (FileDeletedEvent, DirDeletedEvent)):
            self._watcher._forget(event.src_path, self._root)

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, (FileMovedEvent, DirMovedEvent)):
            self._watcher._forget(event.src_path, self._root)
            if isinstance(event, DirMovedEvent):
                self._watcher._schedule_tree(event.dest_path, self._root)
            else:
                self._watcher._schedule_file(event.dest_path, self._root)
