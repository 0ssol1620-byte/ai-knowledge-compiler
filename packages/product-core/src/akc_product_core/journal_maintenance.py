"""Explicit offline maintenance of synthetic single-host journals."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from akc_cir.base import canonical_json, sha256_digest

from .compiler import ProductCoreCompiler
from .journal import (
    JournalConflict,
    JournalCorrupt,
    SQLiteCompileJournal,
    _AcceptedWork,
    _Fragment,
    compile_work_digest,
)


def _accepted(row: tuple[Any, ...]) -> _AcceptedWork:
    key, work, release, payload, digest = row
    try:
        accepted = _AcceptedWork.model_validate_json(
            SQLiteCompileJournal._verified(payload, digest)
        )
        request = accepted.request
        if (
            key
            != canonical_json([request.tenant_id, request.workspace_id, request.idempotency_key])
            or compile_work_digest(request) != work
            or not isinstance(release, str)
            or len(release) != 71
        ):
            raise JournalCorrupt("accepted work scope mismatch")
        return accepted
    except (ValueError, TypeError) as exc:
        raise JournalCorrupt("invalid accepted work") from exc


def validate_journal(connection: sqlite3.Connection) -> None:
    """Validate one coherent read snapshot; never regenerate corrupt candidates."""
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise JournalCorrupt("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise JournalCorrupt("orphan checkpoint")
    for row in connection.execute(
        "SELECT job_key, work_digest, release_digest, accepted_work, accepted_digest, "
        "payload, payload_digest FROM compile_jobs ORDER BY job_key"
    ):
        accepted = _accepted(row[:5])
        if (row[5] is None) != (row[6] is None):
            raise JournalCorrupt("incomplete candidate record")
        if row[5] is not None:
            SQLiteCompileJournal._response(row[5], row[6], accepted=accepted, release=row[2])
        documents = {(doc.connector_type, doc.native_id): doc for doc in accepted.request.documents}
        scope = ProductCoreCompiler(core_release_digest=row[2])._fragment_scope(accepted.request)
        for connector, native, payload, digest in connection.execute(
            "SELECT connector, native_id, payload, payload_digest FROM compile_fragments "
            "WHERE job_key=? ORDER BY connector, native_id",
            (row[0],),
        ):
            try:
                fragment = _Fragment.model_validate_json(
                    SQLiteCompileJournal._verified(payload, digest)
                ).decode()
                document = documents[(connector, native)]
                if (
                    (fragment.connector_type, fragment.native_id) != (connector, native)
                    or fragment.scope_digest != scope
                    or fragment.document_digest
                    != sha256_digest(
                        canonical_json(document.model_dump(mode="json", by_alias=True))
                    )
                    or fragment.output_digest != fragment.content_digest()
                ):
                    raise JournalCorrupt("fragment binding mismatch")
            except (ValueError, TypeError, KeyError) as exc:
                raise JournalCorrupt("invalid fragment") from exc


def compact_completed(journal: SQLiteCompileJournal, *, limit: int = 100) -> tuple[str, ...]:
    """Drop redundant completed fragments, retaining replay and key bindings forever.

    No request/candidate TTL is guessed. Pending work is excluded. One bounded,
    deterministic batch is validated and deleted atomically under the writer lock.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("maintenance batch must be between 1 and 1000")
    with closing(journal._connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT job_key, work_digest, release_digest, accepted_work, accepted_digest, "
            "payload, payload_digest FROM compile_jobs WHERE payload IS NOT NULL "
            "AND EXISTS(SELECT 1 FROM compile_fragments f WHERE f.job_key=compile_jobs.job_key) "
            "ORDER BY job_key LIMIT ?",
            (limit,),
        ).fetchall()
        for row in rows:
            accepted = _accepted(row[:5])
            journal._response(row[5], row[6], accepted=accepted, release=row[2])
        for row in rows:
            connection.execute("DELETE FROM compile_fragments WHERE job_key=?", (row[0],))
        return tuple(row[0] for row in rows)


def reset_pending_fragments(
    journal: SQLiteCompileJournal,
    *,
    tenant: str,
    workspace: str,
    idempotency_key: str,
    expected_work_digest: str,
    expected_release_digest: str,
) -> int:
    """Explicit recovery of derived fragments only; preserve immutable accepted work."""
    key = canonical_json([tenant, workspace, idempotency_key])
    with closing(journal._connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT job_key, work_digest, release_digest, accepted_work, accepted_digest, "
            "payload FROM compile_jobs WHERE job_key=?",
            (key,),
        ).fetchone()
        if row is None or row[1:3] != (expected_work_digest, expected_release_digest):
            raise JournalConflict
        _accepted(row[:5])
        if row[5] is not None:
            raise JournalConflict("completed candidates cannot be reset")
        cursor = connection.execute("DELETE FROM compile_fragments WHERE job_key=?", (key,))
        return cursor.rowcount


def copy_verified_journal(
    source: str | Path, destination: str | Path, *, timeout_seconds: float = 30
) -> None:
    """SQLite online backup or offline restore to a NEW path, never overwrite live state.

    A restore cannot recover acknowledged work committed after its snapshot.
    Callers must quiesce deployment and reconcile that recovery-point gap separately.
    """
    if not 0 < timeout_seconds <= 60:
        raise ValueError("copy deadline must be between 0 and 60 seconds")
    deadline = time.monotonic() + timeout_seconds
    source_path = Path(source).resolve(strict=True)
    target_path = Path(destination).absolute()
    # Exclusive creation prevents replacing an existing database or symlink.
    with target_path.open("xb"):
        pass
    try:
        with (
            closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(target_path)) as copied,
        ):

            def progress(status: int, remaining: int, total: int) -> None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("journal copy deadline exceeded")

            original.backup(copied, pages=128, progress=progress)
            copied.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            copied.execute("BEGIN")
            validate_journal(copied)
            copied.rollback()
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise
