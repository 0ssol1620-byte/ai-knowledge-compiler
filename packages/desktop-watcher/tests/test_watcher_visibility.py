"""WO-D04-3: locked, out-of-root and deleted files become journaled records.

``watcher.file.removed.v1`` / ``watcher.file.skipped.v1`` are watcher-local
record types (envelope None), not collection-event contract types.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import (
    STABILITY_WINDOW,
    make_config,
    open_session,
    settle,
    wait_until,
    wait_watch_live,
)

from akc_desktop_watcher import watcher as watcher_module


def _of(session, event_type: str) -> list[dict]:
    return [r for r in session.records if r["event_type"] == event_type]


REMOVED = "watcher.file.removed.v1"
SKIPPED = "watcher.file.skipped.v1"
DISCOVERED = "file.discovered.v1"


def test_delete_emits_a_removed_record_once_and_replay_does_not_duplicate_it(
    start_session, watch_env
):
    session = start_session()
    wait_watch_live(session)
    target = session.inbox / "a.txt"
    target.write_text("alpha", encoding="utf-8")
    assert wait_until(lambda: len(_of(session, DISCOVERED)) == 1)
    target.unlink()
    assert wait_until(lambda: len(_of(session, REMOVED)) == 1)
    record = _of(session, REMOVED)[0]
    assert record["relative_path"] == "a.txt"
    assert record["previous_content_sha256"] == _of(session, DISCOVERED)[0]["content_sha256"]
    assert record["envelope"] is None
    session.stop()

    # Restart: nothing unacknowledged, nothing re-emitted.
    inbox, state = watch_env
    second = open_session(make_config(inbox, state), inbox, state)
    try:
        settle()
        assert second.records == []
    finally:
        second.stop()


def test_rename_emits_removed_for_source_and_discovered_for_destination(start_session):
    session = start_session()
    wait_watch_live(session)
    src = session.inbox / "old.txt"
    src.write_text("body", encoding="utf-8")
    assert wait_until(lambda: len(_of(session, DISCOVERED)) == 1)
    src.rename(session.inbox / "new.txt")
    assert wait_until(lambda: len(_of(session, REMOVED)) == 1)
    assert wait_until(lambda: len(_of(session, DISCOVERED)) == 2)
    assert _of(session, REMOVED)[0]["relative_path"] == "old.txt"
    assert _of(session, DISCOVERED)[1]["relative_path"] == "new.txt"


def _fail_n_times(monkeypatch, failures: int) -> dict[str, int]:
    real = watcher_module._sha256_file
    calls = {"n": 0}

    def flaky(path: Path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise PermissionError("sharing violation")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(watcher_module, "_sha256_file", flaky)
    return calls


def test_locked_file_emits_skipped_and_is_retried_then_discovered(start_session, monkeypatch):
    _fail_n_times(monkeypatch, 2)
    session = start_session()
    wait_watch_live(session)
    (session.inbox / "locked.txt").write_text("data", encoding="utf-8")
    assert wait_until(lambda: len(_of(session, DISCOVERED)) == 1, timeout=20)
    skipped = _of(session, SKIPPED)
    assert [r["reason"] for r in skipped] == ["unreadable_locked"]
    assert skipped[0]["relative_path"] == "locked.txt"
    assert skipped[0]["generation"] == 0


def test_locked_file_gives_up_visibly_after_bounded_retries(start_session, monkeypatch):
    calls = _fail_n_times(monkeypatch, 10**6)
    session = start_session()
    wait_watch_live(session)
    (session.inbox / "locked.txt").write_text("data", encoding="utf-8")
    assert wait_until(lambda: len(_of(session, SKIPPED)) == 2, timeout=20)
    assert [r["reason"] for r in _of(session, SKIPPED)] == [
        "unreadable_locked",
        "unreadable_gave_up",
    ]
    settle(STABILITY_WINDOW * 8)
    assert calls["n"] == watcher_module.MAX_READ_ATTEMPTS
    assert _of(session, DISCOVERED) == []


def test_vanished_file_stays_silent(start_session, monkeypatch):
    def vanish(path: Path, *args, **kwargs):
        raise FileNotFoundError(str(path))

    monkeypatch.setattr(watcher_module, "_sha256_file", vanish)
    session = start_session()
    wait_watch_live(session)
    (session.inbox / "ghost.txt").write_text("x", encoding="utf-8")
    settle(STABILITY_WINDOW * 3)
    assert session.records == []


def test_symlink_outside_root_is_reported_not_read(start_session, watch_env, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    inbox, _ = watch_env
    try:
        os.symlink(outside, inbox / "link.txt")
    except (OSError, NotImplementedError) as exc:
        print(f"SKIP reason: symlink creation unavailable: {exc!r}")
        pytest.skip(f"symlink creation unavailable: {exc!r}")
    session = start_session()
    assert wait_until(lambda: len(_of(session, SKIPPED)) == 1)
    record = _of(session, SKIPPED)[0]
    assert record["reason"] == "symlink_outside_root"
    assert record["relative_path"] == "link.txt"
    settle()
    assert _of(session, DISCOVERED) == []


def test_same_bytes_under_two_paths_are_two_sources(start_session):
    session = start_session()
    wait_watch_live(session)
    (session.inbox / "one.txt").write_text("same", encoding="utf-8")
    (session.inbox / "two.txt").write_text("same", encoding="utf-8")
    assert wait_until(lambda: len(_of(session, DISCOVERED)) == 2)
    found = _of(session, DISCOVERED)
    assert found[0]["content_sha256"] == found[1]["content_sha256"]
    assert {r["relative_path"] for r in found} == {"one.txt", "two.txt"}
