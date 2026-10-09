"""Bounded cleanup and recovery preserve synthetic immutable journal bindings."""

import sqlite3
from unittest.mock import patch

import pytest
from akc_product_core.journal import JournalConflict, JournalCorrupt, compile_work_digest
from akc_product_core.journal_maintenance import (
    compact_completed,
    copy_verified_journal,
    reset_pending_fragments,
)

from .test_product_core_fragments import RELEASE
from .test_product_core_journal import _compile, _input, _service


def test_compaction_is_bounded_deterministic_and_retains_replay(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    requests = [_input().model_copy(update={"idempotency_key": f"retention-{i}"}) for i in range(3)]
    results = [_compile(service, request) for request in requests]
    first = compact_completed(service.journal, limit=1)
    assert len(first) == 1
    rest = compact_completed(service.journal, limit=10)
    assert len(rest) == 2
    assert (*first, *rest) == tuple(sorted((*first, *rest)))
    assert compact_completed(service.journal) == ()
    with patch.object(service.compiler, "compile_fragments", side_effect=AssertionError):
        assert [_compile(service, request) for request in requests] == results
    changed = requests[0].model_copy(update={"collection_id": "changed-collection"})
    assert _compile(service, changed)[0] == 409


def _pending(service, request):
    with (
        patch.object(service.compiler, "reduce_fragments", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        _compile(service, request)


def test_compaction_preserves_pending_and_corruption_rolls_back_batch(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    request = _input()
    _pending(service, request)
    assert compact_completed(service.journal) == ()
    assert _compile(service, request)[0] == 200
    other = request.model_copy(update={"idempotency_key": "z-other"})
    assert _compile(service, other)[0] == 200
    with sqlite3.connect(service.journal.path) as connection:
        connection.execute("UPDATE compile_jobs SET payload='{}' WHERE job_key LIKE '%z-other%'")
    with pytest.raises(JournalCorrupt):
        compact_completed(service.journal)
    with sqlite3.connect(service.journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM compile_fragments").fetchone() == (6,)


def test_verified_backup_restore_replays_and_resumes(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    request = _input()
    completed = _compile(service, request)
    pending = request.model_copy(update={"idempotency_key": "pending"})
    _pending(service, pending)
    backup = tmp_path / "backup.sqlite"
    restored = tmp_path / "restored.sqlite"
    copy_verified_journal(service.journal.path, backup)
    copy_verified_journal(backup, restored)
    recovered = _service(restored)
    with patch.object(recovered.compiler, "compile_fragments", side_effect=AssertionError):
        assert _compile(recovered, request) == completed
        assert _compile(recovered, pending)[0] == 200
    with pytest.raises(FileExistsError):
        copy_verified_journal(backup, restored)
    assert _compile(recovered, request) == completed


@pytest.mark.parametrize("damage", ["response", "accepted", "orphan", "scope"])
def test_corrupt_snapshot_is_refused_and_destination_removed(tmp_path, damage):
    service = _service(tmp_path / "journal.sqlite")
    assert _compile(service, _input())[0] == 200
    with sqlite3.connect(service.journal.path) as connection:
        if damage == "response":
            connection.execute("UPDATE compile_jobs SET payload='{}'")
        elif damage == "accepted":
            connection.execute("UPDATE compile_jobs SET accepted_work='{}'")
        elif damage == "orphan":
            connection.execute("UPDATE compile_fragments SET job_key='orphan'")
        else:
            connection.execute("UPDATE compile_jobs SET job_key='wrong-scope'")
    destination = tmp_path / "copy.sqlite"
    with pytest.raises(JournalCorrupt):
        copy_verified_journal(service.journal.path, destination)
    assert not destination.exists()


def test_pending_reset_requires_exact_binding_and_cannot_reset_completed(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    request = _input()
    _pending(service, request)
    options = dict(
        tenant=request.tenant_id,
        workspace=request.workspace_id,
        idempotency_key=request.idempotency_key,
        expected_work_digest=compile_work_digest(request),
        expected_release_digest=RELEASE,
    )
    with pytest.raises(JournalConflict):
        reset_pending_fragments(service.journal, **{**options, "expected_release_digest": "wrong"})
    with sqlite3.connect(service.journal.path) as connection:
        connection.execute("UPDATE compile_fragments SET payload='{}'")
    assert reset_pending_fragments(service.journal, **options) == 3
    assert reset_pending_fragments(service.journal, **options) == 0
    assert _compile(service, request)[0] == 200
    with pytest.raises(JournalConflict):
        reset_pending_fragments(service.journal, **options)


def test_corrupt_accepted_work_is_never_reset(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    request = _input()
    _pending(service, request)
    with sqlite3.connect(service.journal.path) as connection:
        connection.execute("UPDATE compile_jobs SET accepted_work='{}'")
    with pytest.raises(JournalCorrupt):
        reset_pending_fragments(
            service.journal,
            tenant=request.tenant_id,
            workspace=request.workspace_id,
            idempotency_key=request.idempotency_key,
            expected_work_digest=compile_work_digest(request),
            expected_release_digest=RELEASE,
        )


@pytest.mark.parametrize("limit", [0, 1001])
def test_unbounded_cleanup_refused(tmp_path, limit):
    with pytest.raises(ValueError):
        compact_completed(_service(tmp_path / "journal.sqlite").journal, limit=limit)


def test_lost_live_journal_fails_closed_without_recreating_file(tmp_path):
    path = tmp_path / "journal.sqlite"
    service = _service(path)
    assert _compile(service, _input())[0] == 200
    path.unlink()
    assert _compile(service, _input()) == (503, {"code": "CORE_JOURNAL_UNAVAILABLE"})
    assert not path.exists()


def test_copy_deadline_removes_new_destination(tmp_path):
    service = _service(tmp_path / "journal.sqlite")
    assert _compile(service, _input())[0] == 200
    destination = tmp_path / "copy.sqlite"
    with (
        patch("akc_product_core.journal_maintenance.time.monotonic", side_effect=[0, 31]),
        pytest.raises(TimeoutError),
    ):
        copy_verified_journal(service.journal.path, destination)
    assert not destination.exists()
