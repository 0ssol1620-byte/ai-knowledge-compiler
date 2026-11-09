"""Read-only S3-compatible metadata adapter for AWS S3, R2 and MinIO."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult

PROVIDER = "s3"
FRESHNESS_TIER = "F1"


class S3ListClient(Protocol):
    """The boto3-compatible read surface used by :class:`S3Adapter`."""

    def list_objects_v2(self, **kwargs: object) -> Mapping[str, Any]: ...


class S3AdapterError(RuntimeError):
    """An S3 listing cannot be represented safely or within configured bounds."""


class S3Adapter:
    """Poll current object metadata without reading customer object bytes."""

    provider = PROVIDER

    def __init__(
        self,
        client: S3ListClient,
        *,
        bucket: str,
        source_name: str | None = None,
        prefix: str = "",
        endpoint_label: str = "aws-s3",
        max_objects: int = 100_000,
        max_pages: int = 100,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not bucket or any(character.isspace() for character in bucket):
            raise ValueError("bucket must be a non-empty S3 bucket name")
        if prefix.startswith("/") or ".." in prefix.split("/"):
            raise ValueError("prefix must be a relative object-key prefix")
        if max_objects < 1 or max_pages < 1:
            raise ValueError("S3 listing limits must be positive")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_label = endpoint_label
        self.source_id = f"{PROVIDER}:{source_name or bucket}"
        self.max_objects = max_objects
        self.max_pages = max_pages
        self._clock = clock or (lambda: datetime.now(UTC))

    def discover(self) -> Mapping[str, object]:
        return {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "endpoint": self.endpoint_label,
            "bucket": self.bucket,
            "prefix": self.prefix,
            "freshness_tier": FRESHNESS_TIER,
            "permission_snapshot": {
                "read_only": True,
                "operations": ["ListBucket"],
                "customer_bytes_read": False,
            },
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        self._assert_compatible(cursor)
        previous = _cursor_objects(cursor)
        current = self._list_snapshot()
        observed_at = self._clock()
        events: list[ChangeEvent] = []

        for key in sorted(current):
            state = current[key]
            prior = previous.get(key)
            if prior == state:
                continue
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind="object_changed" if prior is not None else "object_added",
                    revision=str(state["revision"]),
                    observed_at=observed_at,
                    payload={
                        "key": key,
                        "size": state["size"],
                        "etag": state["etag"],
                        "last_modified": state["last_modified"],
                        "previous_revision": prior.get("revision") if prior else None,
                        "customer_bytes_read": False,
                    },
                )
            )

        for key in sorted(set(previous) - set(current)):
            prior = previous[key]
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind="object_deleted",
                    revision=str(prior["revision"]),
                    observed_at=observed_at,
                    payload={
                        "key": key,
                        "previous_revision": prior["revision"],
                        "previous_size": prior["size"],
                        "customer_bytes_read": False,
                    },
                )
            )

        return FetchResult(
            events=tuple(events),
            cursor=Cursor(
                provider=PROVIDER,
                source_id=self.source_id,
                state={"objects": current, "last_polled_at": observed_at.isoformat()},
            ),
        )

    def checkpoint(self) -> Cursor:
        return Cursor(
            provider=PROVIDER,
            source_id=self.source_id,
            state={"objects": self._list_snapshot()},
        )

    def _list_snapshot(self) -> dict[str, dict[str, object]]:
        snapshot: dict[str, dict[str, object]] = {}
        continuation: str | None = None
        for _page in range(self.max_pages):
            request: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": self.prefix,
                "MaxKeys": 1000,
            }
            if continuation:
                request["ContinuationToken"] = continuation
            response = self.client.list_objects_v2(**request)
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise S3AdapterError("S3 Contents must be a list")
            for item in contents:
                if not isinstance(item, Mapping):
                    raise S3AdapterError("S3 object metadata must be an object")
                key = str(item.get("Key") or "")
                if not key or (self.prefix and not key.startswith(self.prefix)):
                    raise S3AdapterError("S3 returned an object outside the configured prefix")
                if key in snapshot:
                    raise S3AdapterError(f"S3 returned duplicate object key {key!r}")
                if len(snapshot) >= self.max_objects:
                    raise S3AdapterError(
                        f"source exceeds max_objects={self.max_objects}; narrow the prefix"
                    )
                snapshot[key] = _object_state(item)
            truncated = bool(response.get("IsTruncated"))
            next_token = response.get("NextContinuationToken")
            if not truncated:
                return snapshot
            if not isinstance(next_token, str) or not next_token:
                raise S3AdapterError("truncated S3 listing omitted its continuation token")
            continuation = next_token
        raise S3AdapterError(f"S3 listing exceeded max_pages={self.max_pages}")

    def _assert_compatible(self, cursor: Cursor | None) -> None:
        if cursor is None:
            return
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor belongs to source {cursor.source_id!r}, adapter serves {self.source_id!r}"
            )


def _object_state(item: Mapping[str, object]) -> dict[str, object]:
    etag = str(item.get("ETag") or "").strip('"')
    size = item.get("Size")
    if not etag or not isinstance(size, int) or size < 0:
        raise S3AdapterError("S3 object metadata requires ETag and non-negative Size")
    modified = item.get("LastModified")
    if isinstance(modified, datetime):
        normalized_modified = (
            modified.astimezone(UTC) if modified.tzinfo else modified.replace(tzinfo=UTC)
        ).isoformat()
    elif isinstance(modified, str) and modified:
        normalized_modified = modified
    else:
        raise S3AdapterError("S3 object metadata requires LastModified")
    version = item.get("VersionId")
    revision = (
        f"version:{version}"
        if isinstance(version, str) and version
        else f"etag:{etag}:size:{size}:modified:{normalized_modified}"
    )
    return {
        "etag": etag,
        "size": size,
        "last_modified": normalized_modified,
        "revision": revision,
    }


def _cursor_objects(cursor: Cursor | None) -> dict[str, dict[str, object]]:
    raw = cursor.state.get("objects", {}) if cursor is not None else {}
    if not isinstance(raw, Mapping):
        raise ValueError("S3 cursor objects must be an object")
    objects: dict[str, dict[str, object]] = {}
    for key, state in raw.items():
        if not isinstance(key, str) or not isinstance(state, Mapping):
            raise ValueError("S3 cursor contains an invalid object state")
        normalized = dict(state)
        if not isinstance(normalized.get("revision"), str):
            raise ValueError("S3 cursor contains an invalid object revision")
        objects[key] = normalized
    return objects
