"""Integration tests: real watchdog Observer against pytest tmp directories.

Covered behaviors:
- create -> file.discovered.v1 envelope, contract-spelled (discovered_files)
- rename/move -> event follows the destination path
- rapid consecutive writes -> exactly one event after the stability window
- sha256 dedup -> same-content rewrite and unchanged restart emit nothing
- delete + recreate -> emits again (generation bumps)
- journal replay idempotency across a full watcher restart
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import (
    COLLECTION_ID,
    POLL_INTERVAL,
    SOURCE_ROOT_ID,
    STABILITY_WINDOW,
    Session,
    make_config,
    open_session,
    settle,
    sha256_of,
    wait_until,
    wait_watch_live,
)
from jsonschema import Draft202012Validator

from akc_desktop_watcher import DesktopWatcher
from akc_desktop_watcher.events import validate_envelope
from akc_desktop_watcher.journal import Journal
from akc_desktop_watcher.sink import CallbackEventSink, CompositeEventSink

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "collection-event.schema.json"
)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_create_emits_contract_valid_discovery_event(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session()
    wait_watch_live(session)

    (session.inbox / "hello.txt").write_text("v1", encoding="utf-8")

    assert wait_until(lambda: len(session.records) == 1)
    record = session.records[0]
    envelope = record["envelope"]

    # Watcher-side validation plus the authoritative JSON Schema.
    validate_envelope(envelope)
    Draft202012Validator(_load_schema()).validate(envelope)

    assert envelope["event_type"] == "file.discovered.v1"
    assert envelope["collection_id"] == COLLECTION_ID
    assert envelope["sequence"] == 1
    payload = envelope["payload"]
    assert payload["collection_id"] == COLLECTION_ID
    assert payload["source_root_id"] == SOURCE_ROOT_ID
    # Contract spelling regression guard: discovered_files, NOT files_discovered.
    assert payload["discovered_files"] == 1
    assert "files_discovered" not in payload
    assert payload["discovered_bytes"] == len(b"v1")
    assert payload["manifest_revision"] == 1

    assert record["relative_path"] == "hello.txt"
    assert record["content_sha256"] == sha256_of("v1")
    assert record["sequence"] == 1
    assert record["action"] == "created"

    # The JSONL sink persisted exactly one line for this event_key.
    lines = (session.state / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_key"] == record["event_key"]

    # Journal is fully acknowledged after successful delivery.
    with Journal(session.config.journal_path) as journal:
        assert journal.replay().unprocessed == []


def test_rapid_consecutive_writes_collapse_into_one_stable_event(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session()
    wait_watch_live(session)

    target = session.inbox / "rapid.txt"
    for i in range(6):
        target.write_text(f"chunk-{i}", encoding="utf-8")
        time.sleep(POLL_INTERVAL)  # writes stay well inside the stability window

    assert wait_until(lambda: len(session.records) >= 1)
    settle()
    assert len(session.records) == 1
    record = session.records[0]
    assert record["relative_path"] == "rapid.txt"
    assert record["content_sha256"] == sha256_of("chunk-5")


def test_rename_emits_for_destination_and_clears_source(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session()
    wait_watch_live(session)

    source = session.inbox / "a.txt"
    source.write_text("same-bytes", encoding="utf-8")
    assert wait_until(lambda: len(session.records) == 1)

    sub = session.inbox / "sub"
    sub.mkdir()
    source.rename(sub / "b.txt")

    assert wait_until(lambda: len(session.records) == 2)
    by_rel = {record["relative_path"]: record for record in session.records}
    assert set(by_rel) == {"a.txt", "sub/b.txt"}
    moved = by_rel["sub/b.txt"]
    assert moved["content_sha256"] == sha256_of("same-bytes")
    assert moved["sequence"] == 2
    assert moved["manifest_revision"] == 2

    # The source slot is cleared: recreating a.txt emits again.
    (session.inbox / "a.txt").write_text("same-bytes", encoding="utf-8")
    assert wait_until(lambda: len(session.records) == 3)
    recreated = session.records[-1]
    assert recreated["relative_path"] == "a.txt"
    assert recreated["generation"] == 2


def test_delete_then_recreate_emits_again_with_bumped_generation(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session()
    wait_watch_live(session)

    target = session.inbox / "f.txt"
    target.write_text("payload", encoding="utf-8")
    assert wait_until(lambda: len(session.records) == 1)

    target.unlink()
    assert wait_until(lambda: session.watcher.stats()["removals_cleared"] == 1)

    target.write_text("payload", encoding="utf-8")
    assert wait_until(lambda: len(session.records) == 2)
    second = session.records[1]
    assert second["generation"] == 2
    assert second["sequence"] == 2
    assert second["content_sha256"] == sha256_of("payload")


def test_same_content_rewrite_is_suppressed_by_sha256_dedup(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session()
    wait_watch_live(session)

    target = session.inbox / "stable.txt"
    target.write_text("identical", encoding="utf-8")
    assert wait_until(lambda: len(session.records) == 1)

    target.write_text("identical", encoding="utf-8")  # new mtime, same bytes
    settle(STABILITY_WINDOW)
    assert len(session.records) == 1
    stats = session.watcher.stats()
    assert stats["suppressed_unchanged"] >= 1


def test_exclude_globs_keep_noise_out(start_session) -> None:  # type: ignore[no-untyped-def]
    session: Session = start_session(exclude_globs=["*.tmp"])
    wait_watch_live(session)

    (session.inbox / "notes.tmp").write_text("noise", encoding="utf-8")
    (session.inbox / "keep.txt").write_text("real", encoding="utf-8")

    assert wait_until(lambda: len(session.records) == 1)
    settle()
    assert len(session.records) == 1
    assert session.records[0]["relative_path"] == "keep.txt"


def test_reconcile_on_start_picks_up_preexisting_files(watch_env) -> None:  # type: ignore[no-untyped-def]
    inbox, state = watch_env
    (inbox / "pre.txt").write_text("seeded-before-start", encoding="utf-8")

    config = make_config(inbox, state)
    records: list[dict] = []
    watcher = DesktopWatcher(
        config,
        sink=CompositeEventSink(CallbackEventSink(records.append)),
    )
    watcher.start()
    try:
        assert wait_until(lambda: len(records) == 1)
        assert records[0]["relative_path"] == "pre.txt"
        assert records[0]["content_sha256"] == sha256_of("seeded-before-start")
    finally:
        watcher.stop()


def test_restart_resumes_without_duplicate_events(watch_env) -> None:  # type: ignore[no-untyped-def]
    inbox, state = watch_env
    config = make_config(inbox, state)
    events_file = state / "events.jsonl"
    target = inbox / "resume.txt"

    # --- session 1: discover one file, then stop -------------------------
    session1 = open_session(config, inbox, state)
    try:
        target.write_text("payload-1", encoding="utf-8")
        assert wait_until(lambda: len(session1.records) == 1)
        # The sink callback records the event before the watcher increments its counter.
        assert wait_until(lambda: session1.watcher.stats()["emitted"] == 1)
    finally:
        session1.stop()
    assert len(events_file.read_text(encoding="utf-8").splitlines()) == 1

    # --- session 2: unchanged file must not re-emit ----------------------
    session2 = open_session(config, inbox, state)
    try:
        settle()  # replay + reconcile pass; dedup suppresses resume.txt
        assert session2.records == []
        # The persistent JSONL sink was not re-written for the unchanged file.
        assert len(events_file.read_text(encoding="utf-8").splitlines()) == 1

        # Counters continue where session 1 left off.
        target.write_text("payload-2", encoding="utf-8")
        assert wait_until(lambda: len(session2.records) == 1)
        record = session2.records[0]
        assert record["sequence"] == 2
        assert record["manifest_revision"] == 2
        assert record["envelope"]["sequence"] == 2
        assert record["content_sha256"] == sha256_of("payload-2")
        settle()
        assert len(session2.records) == 1
        assert len(events_file.read_text(encoding="utf-8").splitlines()) == 2
    finally:
        session2.stop()

    with Journal(config.journal_path) as journal:
        result = journal.replay()
    assert result.unprocessed == []
    assert (result.manifest_revision, result.sequence) == (2, 2)


@pytest.mark.parametrize(
    ("pattern", "filename"),
    [("~$*", "~$lock.docx"), ("**/__pycache__/**", "__pycache__/x.pyc")],
)
def test_common_exclude_patterns(pattern: str, filename: str) -> None:
    from akc_desktop_watcher.watcher import _ExcludeMatcher

    matcher = _ExcludeMatcher([pattern])
    assert matcher.matches(filename)
    assert not matcher.matches("keep.txt")
