"""Single-host durable fragment checkpoints and candidate replay; never publication."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from akc_cir.base import ContractModel, Sha256, canonical_json, sha256_digest
from akc_cir.models import CanonicalDocument
from akc_cir.semantic_diff import ChangeKind, SemanticChange
from pydantic import ValidationError

from .compiler import DocumentFragment, ProductCoreCompiler
from .contracts import PreviousUnit, ProductCoreCompileRequest, ProductCoreCompileResponse


class JournalConflict(Exception):
    """A durable key was already bound to different work or compiler release."""


class JournalCorrupt(Exception):
    """A persisted record failed integrity or schema validation."""


def compile_work_digest(request: ProductCoreCompileRequest) -> str:
    """Hash immutable work independently of authenticated transport attempts."""
    semantic = request.model_dump(mode="json", by_alias=True)
    semantic.pop("requestId", None)
    semantic.pop("requestedAt", None)
    semantic["route"].pop("maxLatencyMs", None)
    semantic["documents"].sort(key=lambda doc: (doc["connectorType"], doc["nativeId"]))
    for document in semantic["documents"]:
        document["regions"].sort(key=lambda region: region["order"])
    return sha256_digest(canonical_json(semantic))


class _AcceptedWork(ContractModel):
    request: ProductCoreCompileRequest
    input_sha256: Sha256


class _Change(ContractModel):
    kind: ChangeKind
    logical_id: str | None = None
    before: str | None = None
    after: str | None = None
    detail: str = ""
    candidates: tuple[str, ...] = ()


class _Fragment(ContractModel):
    connector_type: str
    native_id: str
    scope_digest: str
    document_digest: str
    canonical_document: CanonicalDocument
    units: tuple[PreviousUnit, ...]
    changes: tuple[_Change, ...]
    review_reasons: tuple[str, ...]
    output_digest: str

    @classmethod
    def encode(cls, fragment: DocumentFragment) -> str:
        return cls(
            connector_type=fragment.connector_type,
            native_id=fragment.native_id,
            scope_digest=fragment.scope_digest,
            document_digest=fragment.document_digest,
            canonical_document=fragment.canonical_document,
            units=fragment.units,
            changes=tuple(
                _Change.model_validate(change.as_record()) for change in fragment.changes
            ),
            review_reasons=fragment.review_reasons,
            output_digest=fragment.output_digest,
        ).model_dump_json(by_alias=True)

    def decode(self) -> DocumentFragment:
        return DocumentFragment(
            connector_type=self.connector_type,
            native_id=self.native_id,
            scope_digest=self.scope_digest,
            document_digest=self.document_digest,
            canonical_document=self.canonical_document,
            units=self.units,
            changes=tuple(
                SemanticChange(**change.model_dump(by_alias=False)) for change in self.changes
            ),
            review_reasons=self.review_reasons,
            output_digest=self.output_digest,
        )


class SQLiteCompileJournal:
    """Serialize each checkpoint with SQLite's writer lock across local processes.

    An immutable key binding commits before extraction. Each document commits
    separately, so a killed worker resumes completed documents. The reducer and
    response commit together; an HTTP success is returned only after that commit.
    No pending or partial response can be read as a completed candidate.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("compile journal requires a durable filesystem path")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS compile_jobs ("
                "job_key TEXT PRIMARY KEY, work_digest TEXT NOT NULL, "
                "release_digest TEXT NOT NULL, "
                "accepted_work TEXT NOT NULL, accepted_digest TEXT NOT NULL, "
                "payload TEXT, payload_digest TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS compile_fragments ("
                "job_key TEXT NOT NULL, connector TEXT NOT NULL, native_id TEXT NOT NULL, "
                "payload TEXT NOT NULL, payload_digest TEXT NOT NULL, "
                "PRIMARY KEY(job_key, connector, native_id), "
                "FOREIGN KEY(job_key) REFERENCES compile_jobs(job_key))"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _verified(payload: str, digest: str) -> str:
        if sha256_digest(payload) != digest:
            raise JournalCorrupt("checkpoint digest mismatch")
        return payload

    @classmethod
    def _response(cls, payload: str, digest: str, *, accepted: _AcceptedWork, release: str) -> str:
        value = cls._verified(payload, digest)
        try:
            response = ProductCoreCompileResponse.model_validate_json(value)
        except ValidationError as exc:
            raise JournalCorrupt("candidate schema mismatch") from exc
        receipt = response.receipt
        if (
            receipt.request_id != accepted.request.request_id
            or receipt.input_sha256 != accepted.input_sha256
            or receipt.core_release_digest != release
            or receipt.output_sha256
            != sha256_digest(
                canonical_json(
                    response.candidate.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
            )
        ):
            raise JournalCorrupt("candidate receipt binding mismatch")
        return value

    def compile(
        self,
        request: ProductCoreCompileRequest,
        *,
        compiler: ProductCoreCompiler,
        work_digest: str,
        input_sha256: str,
    ) -> dict[str, object]:
        key = canonical_json([request.tenant_id, request.workspace_id, request.idempotency_key])
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT work_digest, release_digest, payload, payload_digest, "
                "accepted_work, accepted_digest "
                "FROM compile_jobs WHERE job_key=?",
                (key,),
            ).fetchone()
            if row is None:
                accepted = _AcceptedWork(request=request, input_sha256=input_sha256)
                accepted_payload = accepted.model_dump_json(by_alias=True)
                connection.execute(
                    "INSERT INTO compile_jobs(job_key, work_digest, release_digest, "
                    "accepted_work, accepted_digest) VALUES(?,?,?,?,?)",
                    (
                        key,
                        work_digest,
                        compiler.core_release_digest,
                        accepted_payload,
                        sha256_digest(accepted_payload),
                    ),
                )
            else:
                if row[:2] != (work_digest, compiler.core_release_digest):
                    raise JournalConflict
                try:
                    accepted = _AcceptedWork.model_validate_json(self._verified(row[4], row[5]))
                except ValidationError as exc:
                    raise JournalCorrupt("accepted work schema mismatch") from exc
                if compile_work_digest(accepted.request) != work_digest:
                    raise JournalCorrupt("accepted work binding mismatch")
                if row[2] is not None:
                    payload = self._response(
                        row[2], row[3], accepted=accepted, release=compiler.core_release_digest
                    )
                    connection.commit()
                    return cast(dict[str, object], json.loads(payload))
            connection.commit()
            # Resume using the first accepted attempt's provenance for all fragments
            # and reduction. A retry only rebinds the outgoing authenticated receipt.
            request = accepted.request
            input_sha256 = accepted.input_sha256
            fragments = []
            for document in sorted(
                request.documents, key=lambda doc: (doc.connector_type, doc.native_id)
            ):
                connection.execute("BEGIN IMMEDIATE")
                fragment_key = (key, document.connector_type, document.native_id)
                row = connection.execute(
                    "SELECT payload, payload_digest FROM compile_fragments "
                    "WHERE job_key=? AND connector=? AND native_id=?",
                    fragment_key,
                ).fetchone()
                if row is None:
                    (fragment,) = compiler.compile_fragments(
                        request, ((document.connector_type, document.native_id),)
                    )
                    payload = _Fragment.encode(fragment)
                    connection.execute(
                        "INSERT INTO compile_fragments VALUES(?,?,?,?,?)",
                        (*fragment_key, payload, sha256_digest(payload)),
                    )
                else:
                    try:
                        fragment = _Fragment.model_validate_json(self._verified(*row)).decode()
                    except ValidationError as exc:
                        raise JournalCorrupt("fragment schema mismatch") from exc
                    if fragment.content_digest() != fragment.output_digest:
                        raise JournalCorrupt("fragment content mismatch")
                fragments.append(fragment)
                connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, payload_digest FROM compile_jobs WHERE job_key=?", (key,)
            ).fetchone()
            if row[0] is not None:
                payload = self._response(
                    *row, accepted=accepted, release=compiler.core_release_digest
                )
            else:
                response = compiler.reduce_fragments(request, fragments, input_sha256=input_sha256)
                payload = response.model_dump_json(by_alias=True, exclude_none=True)
                connection.execute(
                    "UPDATE compile_jobs SET payload=?, payload_digest=? WHERE job_key=?",
                    (payload, sha256_digest(payload), key),
                )
            connection.commit()
            return cast(dict[str, object], json.loads(payload))
        except (json.JSONDecodeError, TypeError) as exc:
            raise JournalCorrupt("checkpoint cannot be decoded") from exc
        finally:
            # Closing an interrupted transaction rolls it back; committed fragments survive.
            connection.close()
