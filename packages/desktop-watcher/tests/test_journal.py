"""Journal replay idempotency + crash-tail repair tests."""

from __future__ import annotations

import json
from pathlib import Path

from akc_desktop_watcher.journal import DedupEntry, Journal


def test_unacked_event_replays_exactly_once_across_reopens(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    record = {"event_key": "k1", "content_sha256": "ab" * 32}

    # Duplicate event lines for the same key must collapse to one record.
    for _ in range(3):
        with Journal(path) as journal:
            journal.append_event(record)

    with Journal(path) as journal:
        first = journal.replay()
    assert first.unprocessed == [record]

    # Re-reading the same log is stable (idempotent replay).
    with Journal(path) as journal:
        second = journal.replay()
    assert second == first


def test_ack_removes_event_from_replay(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    with Journal(path) as journal:
        journal.append_event({"event_key": "k1", "n": 1})
        journal.append_event({"event_key": "k2", "n": 2})
        journal.append_ack("k1")

    with Journal(path) as journal:
        result = journal.replay()

    assert [record["event_key"] for record in result.unprocessed] == ["k2"]


def test_state_lines_restore_latest_entry_and_max_counters(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    with Journal(path) as journal:
        journal.append_state(
            root="r",
            rel="a.txt",
            content_sha256="h1",
            generation=1,
            manifest_revision=5,
            sequence=3,
        )
        journal.append_state(
            root="r",
            rel="a.txt",
            content_sha256="h2",
            generation=2,
            manifest_revision=2,
            sequence=7,
        )

    with Journal(path) as journal:
        result = journal.replay()

    assert result.dedup[("r", "a.txt")] == DedupEntry(content_sha256="h2", generation=2)
    assert result.manifest_revision == 5  # max across lines, not last line
    assert result.sequence == 7


def test_replay_folds_windows_case_differences(tmp_path: Path) -> None:
    """Windows paths are case-insensitive: one file, one dedup slot."""
    path = tmp_path / "journal.jsonl"
    with Journal(path) as journal:
        journal.append_state(
            root="Root-A",
            rel="Docs/File.TXT",
            content_sha256="h1",
            generation=1,
            manifest_revision=1,
            sequence=1,
        )
        journal.append_state(
            root="root-a",
            rel="docs/file.txt",
            content_sha256="h2",
            generation=2,
            manifest_revision=2,
            sequence=2,
        )

    with Journal(path) as journal:
        result = journal.replay()

    assert list(result.dedup.keys()) == [("root-a", "docs/file.txt")]
    entry = result.dedup[("root-a", "docs/file.txt")]
    assert entry == DedupEntry(content_sha256="h2", generation=2)
    assert (result.manifest_revision, result.sequence) == (2, 2)


def test_torn_tail_is_truncated_on_open_and_appends_stay_aligned(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    good1 = json.dumps({"kind": "ack", "event_key": "k1"}, sort_keys=True)
    good2 = json.dumps({"kind": "ack", "event_key": "k2"}, sort_keys=True)
    path.write_text(f"{good1}\n{good2}\n" + '{"kind":"eve', encoding="utf-8")

    with Journal(path):
        pass  # constructor repairs the torn tail

    assert path.read_text(encoding="utf-8") == f"{good1}\n{good2}\n"

    with Journal(path) as journal:
        journal.append_ack("k3")
    with Journal(path) as journal:
        result = journal.replay()
    assert result.skipped_lines == 0


def test_corrupt_middle_line_is_skipped_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    good1 = json.dumps({"kind": "ack", "event_key": "k1"}, sort_keys=True)
    good2 = json.dumps({"kind": "ack", "event_key": "k2"}, sort_keys=True)
    path.write_text(f"{good1}\nnot-json-at-all\n{good2}\n", encoding="utf-8")

    with Journal(path) as journal:
        result = journal.replay()

    assert result.skipped_lines == 1
