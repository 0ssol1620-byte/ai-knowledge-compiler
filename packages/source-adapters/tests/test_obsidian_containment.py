"""Symlink containment and the additive ``FetchResult.skipped`` channel."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_source_adapters import ObsidianVaultAdapter, SkippedSource

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        reason = f"symlink creation unavailable here (needs privilege/dev mode): {exc}"
        print("SKIPPED:", reason)
        pytest.skip(reason)


def _adapter(vault: Path) -> ObsidianVaultAdapter:
    return ObsidianVaultAdapter(vault, source_id="obsidian:t", clock=lambda: _NOW)


def test_symlinked_note_outside_vault_is_skipped_and_reported(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n", encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("TOP SECRET", encoding="utf-8")
    _link(vault / "leak.md", secret)

    adapter = _adapter(vault)
    result = adapter.fetch_changes(None)

    assert result.skipped == (SkippedSource("leak.md", "symlink_outside_root"),)
    assert [e.payload["path"] for e in result.events] == ["a.md"]
    assert "leak.md" not in result.cursor.state["notes"]  # type: ignore[operator]
    assert set(adapter.scan()) == {"a.md"}


def test_symlink_inside_vault_is_followed_once(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n", encoding="utf-8")
    _link(vault / "alias.md", vault / "a.md")

    result = _adapter(vault).fetch_changes(None)

    assert result.skipped == ()
    assert [e.payload["path"] for e in result.events] == ["a.md", "alias.md"]
    assert len({e.revision for e in result.events}) == 1  # same content hash
    assert len({e.event_hash for e in result.events}) == 2  # two source instances


def test_skipped_entries_do_not_change_event_hashes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n", encoding="utf-8")
    outside = tmp_path / "o.md"
    outside.write_text("x", encoding="utf-8")
    adapter = _adapter(vault)
    before = adapter.fetch_changes(None)
    _link(vault / "leak.md", outside)
    after = adapter.fetch_changes(None)

    assert before.skipped == () and len(after.skipped) == 1
    assert [e.event_hash for e in before.events] == [e.event_hash for e in after.events]
    assert not hasattr(before.events[0], "skipped")
