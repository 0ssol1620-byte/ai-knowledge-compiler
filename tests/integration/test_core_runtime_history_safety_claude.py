"""Core runtime history-safety regressions -- authored by Claude Opus 5.5.

Provenance: every test in this file was written by Claude Opus 5.5 alongside
the runtime fix. It is deliberately separate from the frozen, independently
authored Codex reproduction in ``test_core_runtime_history_safety.py``, which
is neither edited nor relied on here.

Every scenario drives the production ``Pipeline`` over local synthetic
Markdown with the rule-based runtime only. Each incremental publish is judged
against a forced full re-resolution started from a copy of that exact prior
store, and the comparison keeps every history and safety field --
``invalidated_by``, ``moved_from``, ``doc_node``, evidence, the review queue
and the tombstones -- rather than normalising any of them away. Each publish
is also re-read from disk so the state proven equal is the state a restarted
Pipeline sees.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
from akc_compiler_runtime import OracleRefused, Pipeline, WorldResult, WorldStore

SOURCE_TEXT = """\
# Source

The current launch date for Project Beacon is October 15, 2026.
"""

DEPENDENT_TEXT = """\
# Dependent plan

## Dependencies

Depends on: source.md - launch date.

## Plan

The project launch checklist is due before the confirmed launch date.
"""

POLICY_TEXT = "# Policy\n\nThe warranty covers water damage.\n"
AMBIGUOUS_POLICY_TEXT = "# Policy\n\nThe warranty does not cover water damage.\n"
STABLE_TEXT = "# Stable\n\nThe office opens at eight each morning.\n"

CHECKLIST_QUESTION = "When is the project launch checklist due?"


def _write(source: Path, rel_path: str, text: str) -> None:
    path = source / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_unrelated(source: Path, number: int) -> None:
    """A fresh file each time, so no unrelated edit can raise its own review."""
    text = f"# Notes\n\nRoom {number} is booked for the review.\n"
    _write(source, f"unrelated-{number}.md", text)


def _rows(result: WorldResult, rel_path: str) -> list[Mapping[str, object]]:
    return [row for row in result.claims.values() if row["rel_path"] == rel_path]


def _only_row(result: WorldResult, rel_path: str) -> Mapping[str, object]:
    rows = _rows(result, rel_path)
    assert len(rows) == 1, f"expected exactly one claim for {rel_path}, got {len(rows)}"
    return rows[0]


def _snapshot(result: WorldResult) -> dict[str, object]:
    """Everything that serves, reviews, evidences or traces a world -- no normalising."""
    return {
        "world_state_id": result.world_state_id,
        "manifest_hash": result.manifest_hash,
        "claims": json.dumps(result.claims, sort_keys=True, ensure_ascii=False),
        "evidence_index": json.dumps(result.evidence_index, sort_keys=True, ensure_ascii=False),
        "review_queue": [item.as_record() for item in result.review_queue],
        "invalidated": sorted(result.invalidated),
        "renames": list(result.renames),
        "tombstones": list(result.tombstones),
    }


def _step(pipeline: Pipeline, source: Path, store: Path, prior_copy: Path) -> WorldResult:
    """Recompile incrementally and prove it equals a full rebuild from the same prior state."""
    shutil.copytree(store, prior_copy)
    incremental = pipeline.recompile(source)
    assert incremental.published and not incremental.no_op
    assert incremental.equivalence is not None and incremental.equivalence.equivalent

    full = Pipeline(prior_copy).compile_workspace(source)
    assert _snapshot(incremental) == _snapshot(full)

    persisted = WorldStore(store, workspace_id="personal").load_world()
    assert persisted is not None
    assert persisted.world_state_id == incremental.world_state_id
    assert persisted.claims == dict(incremental.claims)
    assert list(persisted.review_queue) == [item.as_record() for item in incremental.review_queue]
    assert [
        (str(record["logical_id"]), str(record["lineage_path"]))
        for record in persisted.tombstones
    ] == list(incremental.tombstones)
    return incremental


def _dependency_rows(result: WorldResult, target_ref: str) -> list[Mapping[str, object]]:
    """The dependent's own ``Depends on: <target_ref>`` claim(s), not its prose rows."""
    return [row for row in _rows(result, "dependent.md") if target_ref in row["dep_refs"]]


def _drafted_ids(result: WorldResult, question: str) -> set[str]:
    return {draft.claim.claim_id for draft in result.draft_claims(question)}


def _assert_dependent_invalidated(result: WorldResult, cause: str) -> None:
    dependent_rows = _rows(result, "dependent.md")
    assert dependent_rows
    for row in dependent_rows:
        assert row["invalidated_by"] == [cause]
        assert str(row["logical_id"]) not in result.active_claim_ids
    assert not _drafted_ids(result, CHECKLIST_QUESTION) & {
        str(row["logical_id"]) for row in dependent_rows
    }


def _compile_source_and_dependent(tmp_path: Path) -> tuple[Path, Path, Pipeline, WorldResult]:
    source = tmp_path / "source"
    _write(source, "source.md", SOURCE_TEXT)
    _write(source, "dependent.md", DEPENDENT_TEXT)
    store = tmp_path / "store"
    pipeline = Pipeline(store)
    return source, store, pipeline, pipeline.compile_workspace(source)


# ---------------------------------------------------------------------------
# delete -> unrelated edit -> Pipeline restart
# ---------------------------------------------------------------------------


def test_claude_deleted_dependency_stays_invalidated_across_publishes_and_restart(
    tmp_path: Path,
) -> None:
    source, store, pipeline, initial = _compile_source_and_dependent(tmp_path)
    source_claim = str(_only_row(initial, "source.md")["logical_id"])
    assert initial.tombstones == ()

    (source / "source.md").unlink()
    deleted = _step(pipeline, source, store, tmp_path / "prior-delete")
    _assert_dependent_invalidated(deleted, source_claim)
    assert deleted.tombstones == ((source_claim, "source.md"),)

    _write_unrelated(source, 1)
    unrelated = _step(pipeline, source, store, tmp_path / "prior-unrelated-1")
    _assert_dependent_invalidated(unrelated, source_claim)
    assert unrelated.tombstones == ((source_claim, "source.md"),)

    # A fresh process sees the same fail-closed state, untouched by a no-op ...
    restarted = Pipeline(store)
    idle = restarted.recompile(source)
    assert idle.no_op and not idle.published
    _assert_dependent_invalidated(idle, source_claim)
    assert idle.tombstones == ((source_claim, "source.md"),)

    # ... and keeps it through the next real publish.
    _write_unrelated(source, 2)
    after_restart = _step(restarted, source, store, tmp_path / "prior-unrelated-2")
    _assert_dependent_invalidated(after_restart, source_claim)
    assert after_restart.tombstones == ((source_claim, "source.md"),)


# ---------------------------------------------------------------------------
# source restoration semantics
# ---------------------------------------------------------------------------


def test_claude_restoring_the_source_at_its_lineage_lifts_the_invalidation(
    tmp_path: Path,
) -> None:
    source, store, pipeline, initial = _compile_source_and_dependent(tmp_path)
    source_claim = str(_only_row(initial, "source.md")["logical_id"])
    dependent_ids = {str(row["logical_id"]) for row in _rows(initial, "dependent.md")}

    (source / "source.md").unlink()
    _step(pipeline, source, store, tmp_path / "prior-delete")
    _write_unrelated(source, 1)
    _step(pipeline, source, store, tmp_path / "prior-unrelated")

    # The same bytes at a different path, in a later run, are a new document:
    # the dependent still names source.md, so nothing is restored.
    _write(source, "elsewhere.md", SOURCE_TEXT)
    elsewhere = _step(pipeline, source, store, tmp_path / "prior-elsewhere")
    _assert_dependent_invalidated(elsewhere, source_claim)
    assert elsewhere.tombstones == ((source_claim, "source.md"),)
    assert str(_only_row(elsewhere, "elsewhere.md")["logical_id"]) != source_claim

    # Recreating source.md is the deliberate resolution: the tombstone is lifted,
    # the dependent serves again, and identical content keeps its identity.
    restarted = Pipeline(store)
    _write(source, "source.md", SOURCE_TEXT)
    restored = _step(restarted, source, store, tmp_path / "prior-restore")
    assert restored.tombstones == ()
    assert str(_only_row(restored, "source.md")["logical_id"]) == source_claim
    for row in _rows(restored, "dependent.md"):
        assert row["invalidated_by"] == []
    assert dependent_ids <= set(restored.active_claim_ids)
    assert _drafted_ids(restored, CHECKLIST_QUESTION) & dependent_ids


# ---------------------------------------------------------------------------
# rename -> edit -> repeated rename -> delete
# ---------------------------------------------------------------------------


def test_claude_lineage_survives_rename_edit_repeated_rename_and_delete(tmp_path: Path) -> None:
    source, store, pipeline, initial = _compile_source_and_dependent(tmp_path)
    original = _only_row(initial, "source.md")
    source_claim = str(original["logical_id"])
    original_doc_node = str(original["doc_node"])
    assert original["moved_from"] == ""

    # Only the dependent's ``Depends on: source.md`` claim carries the edge;
    # its plan prose names no document. Pin the edge before anything moves.
    initial_edges = _dependency_rows(initial, "source.md")
    assert initial_edges
    for edge in initial_edges:
        assert edge["dependencies"] == [original_doc_node]
    edge_ids = {str(edge["logical_id"]) for edge in initial_edges}

    def assert_edge(result: WorldResult) -> None:
        """The dependent's semantic edge still names the original document node."""
        edges = _dependency_rows(result, "source.md")
        assert edges
        assert {str(edge["logical_id"]) for edge in edges} == edge_ids
        for edge in edges:
            assert edge["dep_refs"] == ["source.md"]
            assert original_doc_node in edge["dependencies"]

    def assert_lineage(result: WorldResult, rel_path: str) -> None:
        row = _only_row(result, rel_path)
        assert row["logical_id"] == source_claim
        assert row["moved_from"] == "source.md"
        assert row["doc_node"] == original_doc_node
        assert_edge(result)
        # A move or an edit is not a removal: nothing is invalidated.
        assert result.invalidated == ()
        assert result.tombstones == ()
        for dependent in _rows(result, "dependent.md"):
            assert dependent["invalidated_by"] == []
            assert str(dependent["logical_id"]) in result.active_claim_ids

    def assert_idle_after_restart(rel_path: str) -> None:
        """A fresh process sees the same lineage and publishes nothing new."""
        idle = Pipeline(store).recompile(source)
        assert idle.no_op and not idle.published
        assert_lineage(idle, rel_path)

    # rename (same process)
    first = source / "moved" / "source.md"
    first.parent.mkdir(parents=True)
    (source / "source.md").rename(first)
    renamed = _step(pipeline, source, store, tmp_path / "prior-rename")
    assert renamed.renames == (("source.md", "moved/source.md"),)
    assert _rows(renamed, "source.md") == []
    assert_lineage(renamed, "moved/source.md")
    assert_idle_after_restart("moved/source.md")

    # edit after rename (restarted process)
    _write(source, "moved/source.md", SOURCE_TEXT.replace("October 15", "November 3"))
    edited = _step(Pipeline(store), source, store, tmp_path / "prior-edit")
    assert edited.renames == ()
    assert edited.review_queue == ()
    assert_lineage(edited, "moved/source.md")
    assert "November 3" in str(_only_row(edited, "moved/source.md")["value"])
    assert_idle_after_restart("moved/source.md")

    # repeated rename (restarted process)
    second = source / "archive" / "2026" / "source.md"
    second.parent.mkdir(parents=True)
    first.rename(second)
    renamed_again = _step(Pipeline(store), source, store, tmp_path / "prior-rename-again")
    assert renamed_again.renames == (("moved/source.md", "archive/2026/source.md"),)
    assert _rows(renamed_again, "moved/source.md") == []
    assert_lineage(renamed_again, "archive/2026/source.md")
    assert "November 3" in str(_only_row(renamed_again, "archive/2026/source.md")["value"])
    assert_idle_after_restart("archive/2026/source.md")

    # delete after repeated rename (restarted process): the tombstone is
    # recorded at the original lineage path, and the dependent's edge still
    # names the original document node, so the impact reaches it.
    second.unlink()
    deleted = _step(Pipeline(store), source, store, tmp_path / "prior-delete")
    assert _rows(deleted, "archive/2026/source.md") == []
    assert_edge(deleted)
    _assert_dependent_invalidated(deleted, source_claim)
    assert deleted.tombstones == ((source_claim, "source.md"),)

    idle = Pipeline(store).recompile(source)
    assert idle.no_op and not idle.published
    assert_edge(idle)
    _assert_dependent_invalidated(idle, source_claim)
    assert idle.tombstones == ((source_claim, "source.md"),)

    # unrelated publish after restart keeps the deletion fail-closed
    restarted = Pipeline(store)
    _write_unrelated(source, 1)
    after_restart = _step(restarted, source, store, tmp_path / "prior-unrelated")
    assert_edge(after_restart)
    _assert_dependent_invalidated(after_restart, source_claim)
    assert after_restart.tombstones == ((source_claim, "source.md"),)


# ---------------------------------------------------------------------------
# review hold: oracle refusal until deliberate source resolution, then recovery
#
# Observed behaviour, asserted as-is: while a review item is held, an
# unrelated edit is refused by the unchanged full-rebuild oracle
# (``OracleRefused``) and nothing is published. Publishing an unrelated edit
# *while preserving* the held review queue is out of scope here and is not
# claimed.
# ---------------------------------------------------------------------------


def test_claude_review_hold_refuses_publication_until_the_source_is_resolved(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write(source, "policy.md", POLICY_TEXT)
    _write(source, "stable.md", STABLE_TEXT)
    store = tmp_path / "store"
    pipeline = Pipeline(store)
    initial = pipeline.compile_workspace(source)
    policy_claim = str(_only_row(initial, "policy.md")["logical_id"])

    _write(source, "policy.md", AMBIGUOUS_POLICY_TEXT)
    reviewed = _step(pipeline, source, store, tmp_path / "prior-ambiguous")
    held = [item.as_record() for item in reviewed.review_queue]
    assert len(held) == 1 and held[0]["rel_path"] == "policy.md"
    assert _rows(reviewed, "policy.md") == []
    assert WorldStore(store, workspace_id="personal").sequence == 2

    def assert_held_world_intact() -> None:
        """The last successful publish -- the review world -- is still the active one."""
        reader = WorldStore(store, workspace_id="personal")
        assert reader.active_world_state_id() == reviewed.world_state_id
        assert reader.sequence == 2
        # The refused edit never reached the store: no next world was written.
        assert reader.load_world(reader.next_world_state_id) is None
        persisted = reader.load_world()
        assert persisted is not None
        assert persisted.world_state_id == reviewed.world_state_id
        assert list(persisted.review_queue) == held
        assert persisted.claims == dict(reviewed.claims)
        assert not [
            row for row in persisted.claims.values() if row["rel_path"] == "unrelated-1.md"
        ]

    # The unrelated edit is refused by the unchanged full oracle; the review
    # world stays active with its queue untouched.
    _write_unrelated(source, 1)
    with pytest.raises(OracleRefused):
        pipeline.recompile(source)
    assert_held_world_intact()

    # The refusal is a property of the stored state, not of one process.
    restarted = Pipeline(store)
    with pytest.raises(OracleRefused):
        restarted.recompile(source)
    assert_held_world_intact()

    # Deliberately resolving the held source re-resolves it on both paths; the
    # publish goes through the unweakened oracle and the hold is released.
    _write(source, "policy.md", POLICY_TEXT)
    recovered = _step(restarted, source, store, tmp_path / "prior-resolution")
    assert recovered.review_queue == ()
    assert _only_row(recovered, "policy.md")["logical_id"] == policy_claim
    assert _rows(recovered, "unrelated-1.md")
    assert recovered.invalidated == ()
