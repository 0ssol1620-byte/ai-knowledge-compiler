"""Local file-server agent for the TAVONEL Foundation control plane.

The API key comes only from ``TAVONEL_API_KEY``. Source bytes travel directly
to a short-lived R2 PUT URL; the application server receives bounded metadata.
The local cursor advances only after the remote cursor batch commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from akc_source_adapters.envelope import Cursor, canonical_json, stable_hash
from akc_source_adapters.file_server_adapter import FileServerAdapter
from akc_source_adapters.s3_adapter import S3Adapter

STATE_SCHEMA = "tavonel.foundation-source-agent.v1"
DEFAULT_BASE_URL = "https://tavonel.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
QUALIFIED_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
}


class FoundationAgentError(RuntimeError):
    """The agent cannot safely complete and commit one polling cycle."""


class FoundationClient(Protocol):
    def create_upload(
        self, *, filename: str, mime_type: str, size: int, idempotency_key: str
    ) -> Mapping[str, Any]: ...

    def upload_file(self, *, upload_url: str, path: Path, mime_type: str, size: int) -> None: ...

    def apply_batch(self, connection_id: str, batch: Mapping[str, Any]) -> Mapping[str, Any]: ...


class S3ObjectClient(Protocol):
    def list_objects_v2(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: object) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AgentState:
    connection_id: str
    cursor_token: str | None
    server_cursor_sha256: str | None


class HttpFoundationClient:
    """Bounded stdlib HTTP client; key values are never logged or persisted."""

    def __init__(self, base_url: str, api_key: str, *, timeout_seconds: float = 60.0) -> None:
        if not base_url.startswith("https://") and not base_url.startswith("http://localhost"):
            raise ValueError("Foundation base URL must use HTTPS (or localhost for tests)")
        if not api_key.startswith("tvnl_live_"):
            raise ValueError("TAVONEL_API_KEY is missing or malformed")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _json(
        self,
        path: str,
        *,
        body: Mapping[str, Any],
        extra_headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        encoded = canonical_json(body).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - base URL scheme is validated in __init__.
            f"{self.base_url}{path}",
            data=encoded,
            method="POST",
            headers={
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
                **dict(extra_headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise FoundationAgentError(f"Foundation HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise FoundationAgentError(f"Foundation request failed: {exc.reason}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise FoundationAgentError("Foundation response exceeded the bounded client limit")
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FoundationAgentError("Foundation returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise FoundationAgentError("Foundation response must be an object")
        return value

    def create_upload(
        self, *, filename: str, mime_type: str, size: int, idempotency_key: str
    ) -> Mapping[str, Any]:
        return self._json(
            "/api/v1/uploads/capability",
            body={
                "originalFilename": filename,
                "declaredMimeType": mime_type,
                "requestedBytes": size,
            },
            extra_headers={"x-tavonel-source-idempotency-key": idempotency_key},
        )

    def upload_file(self, *, upload_url: str, path: Path, mime_type: str, size: int) -> None:
        if not upload_url.startswith("https://") and not upload_url.startswith("http://localhost"):
            raise FoundationAgentError("upload capability URL is not HTTPS")
        before = path.stat()
        if before.st_size != size:
            raise FoundationAgentError(f"{path.name!r} changed after its scan")
        with path.open("rb") as source:
            request = urllib.request.Request(  # noqa: S310 - capability scheme is validated above.
                upload_url,
                data=source,
                method="PUT",
                headers={"content-type": mime_type, "content-length": str(size)},
            )
            try:
                with urllib.request.urlopen(  # noqa: S310 - request URL is validated above.
                    request, timeout=self.timeout_seconds
                ) as response:
                    if response.status not in {200, 201, 204}:
                        raise FoundationAgentError(f"direct upload returned HTTP {response.status}")
            except urllib.error.HTTPError as exc:
                raise FoundationAgentError(f"direct upload returned HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                raise FoundationAgentError(f"direct upload failed: {exc.reason}") from exc
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise FoundationAgentError(f"{path.name!r} changed during direct upload")

    def apply_batch(self, connection_id: str, batch: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._json(f"/api/v1/connections/{connection_id}/sync", body=batch)


def _semantic_cursor_digest(cursor: Cursor) -> str:
    state = {key: value for key, value in cursor.state.items() if key != "last_polled_at"}
    return stable_hash({"provider": cursor.provider, "source_id": cursor.source_id, "state": state})


def _source_idempotency_key(connection_id: str, native_id: str, revision: str) -> str:
    raw = "\x1f".join((connection_id, native_id, revision)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_state(path: Path, connection_id: str) -> AgentState:
    if not path.exists():
        return AgentState(connection_id=connection_id, cursor_token=None, server_cursor_sha256=None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationAgentError(f"agent state is not readable: {path}") from exc
    if (
        not isinstance(raw, Mapping)
        or raw.get("schemaVersion") != STATE_SCHEMA
        or raw.get("connectionId") != connection_id
        or (raw.get("cursorToken") is not None and not isinstance(raw.get("cursorToken"), str))
        or (
            raw.get("serverCursorSha256") is not None
            and (
                not isinstance(raw.get("serverCursorSha256"), str)
                or not str(raw.get("serverCursorSha256")).startswith("sha256:")
            )
        )
    ):
        raise FoundationAgentError("agent state binding is invalid")
    return AgentState(
        connection_id=connection_id,
        cursor_token=raw.get("cursorToken"),
        server_cursor_sha256=raw.get("serverCursorSha256"),
    )


def save_state(path: Path, state: AgentState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(
        {
            "schemaVersion": STATE_SCHEMA,
            "connectionId": state.connection_id,
            "cursorToken": state.cursor_token,
            "serverCursorSha256": state.server_cursor_sha256,
        }
    )
    temp_name: str | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def sync_file_server(
    *,
    root: Path,
    connection_id: str,
    state_path: Path,
    client: FoundationClient,
    source_name: str | None = None,
    max_file_bytes: int = 512 * 1024 * 1024,
) -> Mapping[str, Any]:
    state = load_state(state_path, connection_id)
    previous = Cursor.decode(state.cursor_token) if state.cursor_token else None
    adapter = FileServerAdapter(
        root,
        source_name=source_name or connection_id,
        max_file_bytes=max_file_bytes,
    )
    fetched = adapter.fetch_changes(previous)
    next_cursor_sha256 = _semantic_cursor_digest(fetched.cursor)
    if not fetched.events and next_cursor_sha256 == state.server_cursor_sha256:
        save_state(
            state_path,
            AgentState(connection_id, fetched.cursor.encoded(), state.server_cursor_sha256),
        )
        return {"status": "unchanged", "eventCount": 0}

    events: list[dict[str, Any]] = []
    for event in fetched.events:
        native_id = str(event.payload["path"])
        deleted = event.kind == "file_deleted"
        document_id: str | None = None
        raw_size = event.payload.get("size")
        size: int | None = None
        if not deleted:
            if not isinstance(raw_size, int):
                raise FoundationAgentError("file-server event omitted its integer size")
            size = raw_size
        content_sha256 = None if deleted else str(event.payload["sha256"])
        mime_type = (
            None if deleted else QUALIFIED_MIME_BY_SUFFIX.get(Path(native_id).suffix.lower())
        )
        if not deleted and mime_type is not None and size is not None:
            source_path = (root / Path(native_id)).resolve()
            if not source_path.is_relative_to(root.resolve()):
                raise FoundationAgentError("source path escaped the mounted root")
            idempotency_key = _source_idempotency_key(connection_id, native_id, event.revision)
            capability = client.create_upload(
                filename=Path(native_id).name,
                mime_type=mime_type,
                size=size,
                idempotency_key=idempotency_key,
            )
            upload_url = capability.get("uploadUrl")
            document_id_value = capability.get("documentId")
            if not isinstance(upload_url, str) or not isinstance(document_id_value, str):
                raise FoundationAgentError("upload capability omitted its immutable binding")
            client.upload_file(
                upload_url=upload_url,
                path=source_path,
                mime_type=mime_type,
                size=size,
            )
            document_id = document_id_value
        events.append(
            {
                "kind": "deleted"
                if deleted
                else "changed"
                if event.kind == "file_changed"
                else "added",
                "nativeId": native_id,
                "revision": event.revision,
                "contentSha256": content_sha256,
                "sizeBytes": size,
                "mimeType": mime_type,
                "documentId": document_id,
            }
        )

    batch = {
        "batchId": str(uuid.uuid4()),
        "previousCursorSha256": state.server_cursor_sha256,
        "nextCursorSha256": next_cursor_sha256,
        "manifestSha256": stable_hash(events),
        "events": events,
    }
    result = client.apply_batch(connection_id, batch)
    if result.get("status") not in {"applied", "replayed"}:
        raise FoundationAgentError("Foundation did not commit the cursor batch")
    save_state(
        state_path,
        AgentState(connection_id, fetched.cursor.encoded(), next_cursor_sha256),
    )
    return {"status": result["status"], "eventCount": len(events), "batchId": batch["batchId"]}


def _download_s3_object(
    client: S3ObjectClient,
    *,
    bucket: str,
    key: str,
    revision: str,
    etag: str,
    expected_size: int,
) -> tuple[Path, str]:
    request: dict[str, object] = {"Bucket": bucket, "Key": key}
    if revision.startswith("version:"):
        request["VersionId"] = revision.removeprefix("version:")
    else:
        request["IfMatch"] = f'"{etag}"'
    response = client.get_object(**request)
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise FoundationAgentError("S3 GetObject omitted its streaming body")
    descriptor, temp_name = tempfile.mkstemp(prefix="tavonel-s3-", suffix=Path(key).suffix)
    digest = hashlib.sha256()
    written = 0
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "wb") as target:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise FoundationAgentError("S3 body returned a non-byte chunk")
                written += len(chunk)
                if written > expected_size:
                    raise FoundationAgentError("S3 object exceeded its listed size")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    if written != expected_size:
        Path(temp_name).unlink(missing_ok=True)
        raise FoundationAgentError("S3 object size changed after listing")
    return Path(temp_name), digest.hexdigest()


def sync_s3_source(
    *,
    s3_client: S3ObjectClient,
    bucket: str,
    prefix: str,
    connection_id: str,
    state_path: Path,
    client: FoundationClient,
    endpoint_label: str = "aws-s3",
) -> Mapping[str, Any]:
    state = load_state(state_path, connection_id)
    previous = Cursor.decode(state.cursor_token) if state.cursor_token else None
    adapter = S3Adapter(
        s3_client,
        bucket=bucket,
        prefix=prefix,
        source_name=connection_id,
        endpoint_label=endpoint_label,
    )
    fetched = adapter.fetch_changes(previous)
    next_cursor_sha256 = _semantic_cursor_digest(fetched.cursor)
    if not fetched.events and next_cursor_sha256 == state.server_cursor_sha256:
        save_state(
            state_path,
            AgentState(connection_id, fetched.cursor.encoded(), state.server_cursor_sha256),
        )
        return {"status": "unchanged", "eventCount": 0}

    events: list[dict[str, Any]] = []
    for event in fetched.events:
        native_id = str(event.payload["key"])
        deleted = event.kind == "object_deleted"
        raw_size = event.payload.get("size")
        size: int | None = None
        if not deleted:
            if not isinstance(raw_size, int):
                raise FoundationAgentError("S3 event omitted its integer size")
            size = raw_size
        mime_type = (
            None if deleted else QUALIFIED_MIME_BY_SUFFIX.get(Path(native_id).suffix.lower())
        )
        content_sha256: str | None = None
        document_id: str | None = None
        if not deleted and mime_type is not None and size is not None and size > 0:
            etag = event.payload.get("etag")
            if not isinstance(etag, str) or not etag:
                raise FoundationAgentError("S3 event omitted its ETag")
            temp_path, content_sha256 = _download_s3_object(
                s3_client,
                bucket=bucket,
                key=native_id,
                revision=event.revision,
                etag=etag,
                expected_size=size,
            )
            try:
                idempotency_key = _source_idempotency_key(connection_id, native_id, event.revision)
                capability = client.create_upload(
                    filename=Path(native_id).name,
                    mime_type=mime_type,
                    size=size,
                    idempotency_key=idempotency_key,
                )
                upload_url = capability.get("uploadUrl")
                document_id_value = capability.get("documentId")
                if not isinstance(upload_url, str) or not isinstance(document_id_value, str):
                    raise FoundationAgentError("upload capability omitted its immutable binding")
                client.upload_file(
                    upload_url=upload_url,
                    path=temp_path,
                    mime_type=mime_type,
                    size=size,
                )
                document_id = document_id_value
            finally:
                temp_path.unlink(missing_ok=True)
        events.append(
            {
                "kind": "deleted"
                if deleted
                else "changed"
                if event.kind == "object_changed"
                else "added",
                "nativeId": native_id,
                "revision": event.revision,
                "contentSha256": content_sha256,
                "sizeBytes": size,
                "mimeType": mime_type,
                "documentId": document_id,
            }
        )

    batch = {
        "batchId": str(uuid.uuid4()),
        "previousCursorSha256": state.server_cursor_sha256,
        "nextCursorSha256": next_cursor_sha256,
        "manifestSha256": stable_hash(events),
        "events": events,
    }
    result = client.apply_batch(connection_id, batch)
    if result.get("status") not in {"applied", "replayed"}:
        raise FoundationAgentError("Foundation did not commit the cursor batch")
    save_state(
        state_path,
        AgentState(connection_id, fetched.cursor.encoded(), next_cursor_sha256),
    )
    return {"status": result["status"], "eventCount": len(events), "batchId": batch["batchId"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync an OS-mounted file server to TAVONEL")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path, help="Mounted read-only source directory")
    source.add_argument("--s3-bucket", help="AWS S3, R2, or MinIO bucket")
    parser.add_argument(
        "--connection-id", required=True, help="Connection UUID from Workspace > Connections"
    )
    parser.add_argument("--state", type=Path, required=True, help="Local cursor state path")
    parser.add_argument(
        "--source-name", help="Stable local source label (defaults to connection UUID)"
    )
    parser.add_argument("--base-url", default=os.environ.get("TAVONEL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--max-file-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--s3-prefix", default="")
    parser.add_argument("--s3-region")
    parser.add_argument("--s3-endpoint-url")
    parser.add_argument("--s3-endpoint-label", default="aws-s3")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("TAVONEL_API_KEY", "")
    client = HttpFoundationClient(args.base_url, api_key)
    if args.root is not None:
        result = sync_file_server(
            root=args.root,
            connection_id=args.connection_id,
            state_path=args.state,
            client=client,
            source_name=args.source_name,
            max_file_bytes=args.max_file_bytes,
        )
    else:
        import boto3

        s3_client = cast(
            S3ObjectClient,
            boto3.client(
                "s3",
                region_name=args.s3_region,
                endpoint_url=args.s3_endpoint_url,
            ),
        )
        result = sync_s3_source(
            s3_client=s3_client,
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            connection_id=args.connection_id,
            state_path=args.state,
            client=client,
            endpoint_label=args.s3_endpoint_label,
        )
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
