"""Contract tests for the source adapters in ``packages/source-adapters``.

The adapters are the compiler's intake surface, so what gets pinned here is
the contract the rest of the tree leans on: a full pull followed by an empty
incremental pull (nothing is re-emitted), a resume that survives a cursor
round-trip through its encoded string, change detection driven by content
rather than mtimes, and hashes that do not depend on dict order or timezone.
The migration graph guard closes the loop: the new cursor table must join the
chain as its single head, not fork it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from akc_source_adapters import (
    EVENT_HASH_PREFIX,
    ChangeEvent,
    Cursor,
    Freshness,
    GitAdapter,
    GitCursorInvalid,
    ObsidianVaultAdapter,
    SourceAdapter,
    canonical_json,
    classify_lag,
    evaluate_freshness,
)

# -- helpers ---------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603 -- fixed executable, scratch repo paths only
        ["git", "-C", str(repo), *args],  # noqa: S607 -- git resolves on PATH by design
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, f"git {' '.join(args)} failed: {completed.stderr.strip()}"
    return completed.stdout


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A scratch repository holding two commits on one branch."""
    repo = tmp_path / "notes-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "adapter-test@example.com")
    _git(repo, "config", "user.name", "Adapter Test")
    (repo / "a.md").write_text("# alpha\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "first commit")
    (repo / "b.md").write_text("# beta\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "second commit")
    return repo


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """A scratch Obsidian vault: frontmatter title, H1 title, subfolder."""
    vault_dir = tmp_path / "vault"
    (vault_dir / "ideas").mkdir(parents=True)
    (vault_dir / "ideas" / "titled.md").write_text(
        "---\ntitle: Frontmatter Title\nstatus: draft\n---\nbody text\n",
        encoding="utf-8",
    )
    (vault_dir / "heading.md").write_text(
        "intro line\n\n# Heading Title\n\nmore text\n",
        encoding="utf-8",
    )
    return vault_dir


# -- git adapter ------------------------------------------------------------


def test_git_adapter_satisfies_the_protocol(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)
    assert isinstance(adapter, SourceAdapter)
    assert adapter.provider == "git"


def test_git_discover_reports_shape_without_emitting_events(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)
    info = adapter.discover()
    assert info["provider"] == "git"
    assert info["commit_count"] == 2
    assert isinstance(info["head_commit"], str) and len(info["head_commit"]) == 40


def test_git_full_pull_then_incremental_resume(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)

    # Full pull (no cursor): every commit, oldest first.
    first = adapter.fetch_changes(None)
    subjects = [event.payload["subject"] for event in first.events]
    assert subjects == ["first commit", "second commit"]
    assert all(event.kind == "commit" for event in first.events)
    revisions = [event.revision for event in first.events]
    assert len(set(revisions)) == 2  # each commit identified by its own sha

    # Resuming from the returned cursor immediately: nothing new.
    replay = adapter.fetch_changes(first.cursor)
    assert replay.events == ()
    assert replay.cursor.state["head"] == first.cursor.state["head"]

    # A new commit lands; the incremental pull reports only it.
    (git_repo / "c.md").write_text("# gamma\n", encoding="utf-8")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "third commit")

    incremental = adapter.fetch_changes(first.cursor)
    assert [event.payload["subject"] for event in incremental.events] == ["third commit"]
    assert incremental.cursor.state["head"] == incremental.events[0].revision

    # And the cursor survives a round-trip through its encoded string.
    resumed = adapter.fetch_changes(Cursor.decode(incremental.cursor.encoded()))
    assert resumed.events == ()


def test_git_checkpoint_parks_the_head_without_fetching(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)
    parked = adapter.checkpoint()
    assert parked.provider == "git"
    assert parked.state["head"] == adapter.discover()["head_commit"]
    # A fetch against the parked checkpoint sees nothing older than it.
    assert adapter.fetch_changes(parked).events == ()


def test_git_rejects_a_cursor_from_a_rewritten_history(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)
    bogus = Cursor(provider="git", source_id=adapter.source_id, state={"head": "0" * 40})
    with pytest.raises(GitCursorInvalid):
        adapter.fetch_changes(bogus)


def test_git_rejects_a_foreign_cursor(git_repo: Path) -> None:
    adapter = GitAdapter(git_repo)
    foreign = Cursor(provider="obsidian", source_id="obsidian:somewhere", state={})
    with pytest.raises(ValueError, match="does not match"):
        adapter.fetch_changes(foreign)


# -- obsidian adapter --------------------------------------------------------


def test_obsidian_first_poll_sees_every_note_with_titles(vault: Path) -> None:
    adapter = ObsidianVaultAdapter(vault)
    assert adapter.provider == "obsidian"

    result = adapter.fetch_changes(None)
    by_path = {event.payload["path"]: event for event in result.events}
    assert set(by_path) == {"heading.md", "ideas/titled.md"}
    assert all(event.kind == "note_added" for event in result.events)

    # Frontmatter title wins over headings/stems; H1 wins over the stem.
    assert by_path["ideas/titled.md"].payload["title"] == "Frontmatter Title"
    assert by_path["heading.md"].payload["title"] == "Heading Title"
    assert by_path["heading.md"].payload["previous_sha256"] is None


def test_obsidian_poll_detects_edits_adds_and_deletes_once(vault: Path) -> None:
    adapter = ObsidianVaultAdapter(vault)
    baseline = adapter.fetch_changes(None)
    assert len(baseline) == 2

    # Touched but byte-identical: no event, even though mtime moved.
    note = vault / "heading.md"
    stat = note.stat()
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))
    quiet = adapter.fetch_changes(baseline.cursor)
    assert quiet.events == ()

    # Edit one note, add another, delete one: exactly those three events.
    (vault / "heading.md").write_text("intro line\n\n# Renamed Heading\n", encoding="utf-8")
    (vault / "new.md").write_text("---\ntitle: Brand New\n---\n", encoding="utf-8")
    (vault / "ideas" / "titled.md").unlink()

    followup = adapter.fetch_changes(baseline.cursor)
    observed = {(event.kind, event.payload["path"]) for event in followup.events}
    assert observed == {
        ("note_changed", "heading.md"),
        ("note_added", "new.md"),
        ("note_deleted", "ideas/titled.md"),
    }

    edited = next(e for e in followup.events if e.payload.get("path") == "heading.md")
    old_revision = next(e.revision for e in baseline.events if e.payload["path"] == "heading.md")
    # The revision is the content hash, and the edit names what it replaced.
    assert old_revision.startswith("sha256:")
    assert edited.payload["previous_sha256"] == old_revision.removeprefix("sha256:")
    assert edited.revision.startswith("sha256:")
    assert edited.revision != old_revision

    # The deletion is reported exactly once: a further poll stays silent.
    settled = adapter.fetch_changes(followup.cursor)
    assert settled.events == ()


def test_obsidian_checkpoint_matches_a_fresh_poll_cursor(vault: Path) -> None:
    adapter = ObsidianVaultAdapter(vault)
    parked = adapter.checkpoint()
    assert adapter.fetch_changes(parked).events == ()


def test_obsidian_requires_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        ObsidianVaultAdapter(tmp_path / "does-not-exist")


# -- envelope: determinism and hashing ---------------------------------------


def test_canonical_json_is_sorted_compact_and_order_free() -> None:
    nested = {"b": 1, "a": [{"z": 0, "y": None}, 2]}
    assert canonical_json(nested) == '{"a":[{"y":null,"z":0},2],"b":1}'
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_event_hash_ignores_key_order_and_timezone() -> None:
    utc_morning = datetime(2026, 8, 23, 9, 30, tzinfo=UTC)
    seoul = timezone(timedelta(hours=9))
    base = dict(source_id="src-1", provider="git", kind="commit", revision="abc123")

    first = ChangeEvent(observed_at=utc_morning, payload={"x": 1, "y": {"p": True, "q": 7}}, **base)
    second = ChangeEvent(
        observed_at=datetime(2026, 8, 23, 18, 30, tzinfo=seoul),  # same instant
        payload={"y": {"q": 7, "p": True}, "x": 1},
        **base,
    )

    assert first.canonical() == second.canonical()
    assert first.event_hash == second.event_hash
    assert first.event_hash.startswith(EVENT_HASH_PREFIX)
    digest = hashlib.sha256(first.canonical().encode("utf-8")).hexdigest()
    assert first.event_hash == f"{EVENT_HASH_PREFIX}{digest}"


def test_event_hash_changes_when_content_changes() -> None:
    moment = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    base = dict(source_id="src-1", provider="obsidian", kind="note_changed", observed_at=moment)
    before = ChangeEvent(revision="sha256:aa", payload={"path": "n.md"}, **base)
    after = ChangeEvent(revision="sha256:bb", payload={"path": "n.md"}, **base)
    assert before.event_hash != after.event_hash


def test_cursor_encoding_is_deterministic_and_round_trips() -> None:
    cursor = Cursor(provider="git", source_id="git:repo", state={"head": "abc", "count": 3})
    reordered = Cursor(provider="git", source_id="git:repo", state={"count": 3, "head": "abc"})
    assert cursor.encoded() == reordered.encoded()
    assert Cursor.decode(cursor.encoded()) == cursor
    with pytest.raises(ValueError):
        Cursor.decode("not-a-token")


# -- freshness tiers ----------------------------------------------------------


def test_freshness_tiers_cover_f0_through_f3() -> None:
    assert [tier.name for tier in Freshness] == ["F0", "F1", "F2", "F3"]
    assert Freshness.F0.slo_seconds == 60
    assert Freshness.F1.slo_seconds == 3_600
    assert Freshness.F2.slo_seconds == 86_400
    assert Freshness.F3.slo_seconds == 604_800


def test_evaluate_freshness_passes_within_slo_and_breaches_beyond_it() -> None:
    changed = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)

    within = evaluate_freshness(Freshness.F1, changed, now=changed + timedelta(minutes=30))
    assert within.within_slo
    assert within.lag_seconds == 1_800
    assert within.breach_seconds == 0

    breached = evaluate_freshness(Freshness.F1, changed, now=changed + timedelta(hours=2))
    assert not breached.within_slo
    assert breached.breach_seconds == 3_600


def test_classify_lag_names_the_tightest_covering_tier() -> None:
    assert classify_lag(30) is Freshness.F0
    assert classify_lag(60) is Freshness.F0
    assert classify_lag(61) is Freshness.F1
    assert classify_lag(50_000) is Freshness.F2
    assert classify_lag(86_400) is Freshness.F2
    assert classify_lag(10**9) is Freshness.F3


# -- migration graph -----------------------------------------------------------


def test_source_cursor_migration_is_the_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    repository = Path(__file__).resolve().parents[2]
    script = ScriptDirectory.from_config(Config(str(repository / "alembic.ini")))
    assert script.get_heads() == ["0041_source_cursor_plane_boundary"]
