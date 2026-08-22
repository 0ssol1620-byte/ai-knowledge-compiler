"""Shared fixtures/helpers for desktop-watcher tests."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from akc_desktop_watcher.config import WatcherConfig
from akc_desktop_watcher.sink import CallbackEventSink, CompositeEventSink, JsonlFileSink

COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID: str | None = None
SOURCE_ROOT_ID = "22222222-2222-4222-8222-222222222222"
STABILITY_WINDOW = 0.5
POLL_INTERVAL = 0.05


def make_config(inbox: Path, state: Path, **overrides: Any) -> WatcherConfig:
    root_patch = {
        key: overrides.pop(key) for key in ("source_root_id", "exclude_globs") if key in overrides
    }
    data: dict[str, Any] = {
        "collection_id": COLLECTION_ID,
        "job_id": JOB_ID,
        "stability_window_seconds": STABILITY_WINDOW,
        "poll_interval_seconds": POLL_INTERVAL,
        "journal_path": str(state / "journal.jsonl"),
        "event_sink_path": str(state / "events.jsonl"),
        "reconcile_on_start": True,
    }
    root: dict[str, Any] = {
        "path": str(inbox),
        "source_root_id": SOURCE_ROOT_ID,
        "exclude_globs": [],
    }
    root.update(root_patch)
    data["roots"] = [root]
    data.update(overrides)
    return WatcherConfig.from_dict(data)


def wait_until(
    predicate: Callable[[], bool], timeout: float = 15.0, interval: float = 0.05
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def settle(window: float = STABILITY_WINDOW) -> None:
    """Sleep long enough for one stability window plus scheduling slack."""
    time.sleep(window + 0.75)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Session:
    """One running watcher session wired to an in-memory + JSONL sink pair."""

    inbox: Path
    state: Path
    config: WatcherConfig
    watcher: Any
    records: list[dict]
    sink: CompositeEventSink

    def stop(self) -> None:
        self.watcher.stop()
        self.sink.close()


@pytest.fixture()
def watch_env(tmp_path: Path) -> tuple[Path, Path]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    return inbox, state


@pytest.fixture()
def start_session(watch_env: tuple[Path, Path]) -> Callable[..., Session]:
    sessions: list[Session] = []

    def factory(**overrides: Any) -> Session:
        inbox, state = watch_env
        config = make_config(inbox, state, **overrides)
        session = open_session(config, inbox, state)
        sessions.append(session)
        return session

    yield factory
    for session in sessions:
        session.stop()


def open_session(config: WatcherConfig, inbox: Path, state: Path) -> Session:
    """Start one watcher wired to a recording callback + persistent JSONL sink."""
    from akc_desktop_watcher import DesktopWatcher

    records: list[dict] = []
    jsonl_sink = JsonlFileSink(config.event_sink_path)
    sink = CompositeEventSink(CallbackEventSink(records.append), jsonl_sink)
    watcher = DesktopWatcher(config, sink=sink)
    watcher.start()
    return Session(
        inbox=inbox,
        state=state,
        config=config,
        watcher=watcher,
        records=records,
        sink=sink,
    )


def wait_watch_live(session: Session) -> None:
    """Block until the Observer is demonstrably delivering events.

    Writes a probe file and waits until it shows up in the pending map, then
    deletes it and waits for the removal to drain. The probe never reaches the
    stability window, so it never emits an event.
    """
    probe = session.inbox / "__probe.txt"
    probe.write_text("probe", encoding="utf-8")
    appeared = wait_until(
        lambda: any(p.endswith("__probe.txt") for p in session.watcher.pending_paths())
    )
    assert appeared
    probe.unlink()
    assert wait_until(lambda: not session.watcher.pending_paths())
