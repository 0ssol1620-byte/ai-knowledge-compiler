"""Google Drive adapter: changes.list delta tokens, removal tombstones.

Freshness tier F1 (hourly polling is enough for most drives).
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult
from akc_source_adapters.google._common import GoogleTokenProvider, get_json

PROVIDER = "gdrive"
FRESHNESS_TIER = "F1"


def _revision_file_id(revision: str, path: str) -> str:
    return revision.rpartition("@")[0] or path


def _fallback_revision(path: str, file_ids: Mapping[str, Mapping[str, str]]) -> str | None:
    """Revision of a tracked copy at ``path``: latest modifiedTime, ties broken by fileId."""
    candidates = [
        (entry["revision"].rpartition("@")[2], file_id, entry["revision"])
        for file_id, entry in file_ids.items()
        if entry["path"] == path
    ]
    return max(candidates)[2] if candidates else None


def _release_path(
    files: dict[str, str], path: str, file_id: str, file_ids: Mapping[str, Mapping[str, str]]
) -> None:
    """Drop ``file_id``'s claim on ``path``, handing it to a remaining copy if one exists."""
    current = files.get(path)
    if current is None or _revision_file_id(current, path) != file_id:
        return
    fallback = _fallback_revision(path, file_ids)
    if fallback is None:
        del files[path]
    else:
        files[path] = fallback


class DriveAdapter:
    """One Drive (or folder-scoped drive) polled through changes.list."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        source_name: str,
        token_provider: GoogleTokenProvider,
        api_base: str = "https://www.googleapis.com/drive/v3",
        page_size: int = 100,
        sleep: Any = None,
    ) -> None:
        self.source_id = f"gdrive:{source_name}"
        self.api_base = api_base.rstrip("/")
        self.token_provider = token_provider
        self.page_size = page_size
        self._sleep = sleep or (lambda seconds: None)
        self._last_page_token: str | None = None

    # -- SourceAdapter ----------------------------------------------------

    def discover(self) -> Mapping[str, object]:
        about = get_json(
            f"{self.api_base}/about?fields=storageQuota,user&pageSize=1",
            self.token_provider,
        )
        user = about.get("user") or {}
        return {
            "provider": PROVIDER,
            "account": user.get("emailAddress", ""),
            "freshness_tier": FRESHNESS_TIER,
            "page_size": self.page_size,
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        state: dict[str, object] = dict(cursor.state) if cursor is not None else {}
        stored_files = state.get("files", {})
        if not isinstance(stored_files, Mapping):
            raise ValueError("Drive cursor files must be a mapping")
        # Legacy path -> revision projection, carried forward and updated per change; it is
        # never rebuilt from file_ids, whose key order does not survive Cursor encoding.
        files = {str(path): str(revision) for path, revision in stored_files.items()}
        stored_ids = state.get("file_ids")
        if stored_ids is None:
            # Legacy cursors only carry path -> "fileId@modifiedTime"; derive identity from it.
            file_ids: dict[str, dict[str, str]] = {}
            for path, revision in files.items():
                file_id = _revision_file_id(revision, path)
                if file_id in file_ids:
                    # An old rename can leave one fileId under two paths; refuse to guess.
                    raise ValueError(
                        f"Drive cursor files map fileId {file_id!r} to multiple paths"
                    )
                file_ids[file_id] = {"path": path, "revision": revision}
        elif isinstance(stored_ids, Mapping):
            file_ids = {
                str(file_id): {"path": str(entry["path"]), "revision": str(entry["revision"])}
                for file_id, entry in stored_ids.items()
            }
            if "files" not in state:
                for path in sorted({entry["path"] for entry in file_ids.values()}):
                    fallback = _fallback_revision(path, file_ids)
                    if fallback is not None:
                        files[path] = fallback
        else:
            raise ValueError("Drive cursor file_ids must be a mapping")
        tracked = "files" in state or "file_ids" in state
        page_token = str(state.get("delta_token") or "")
        observed_at = datetime.now(UTC)
        events: list[ChangeEvent] = []

        while True:
            params: dict[str, str] = {
                "fields": (
                    "nextPageToken,newStartPageToken,"
                    "changes(fileId,name,mimeType,trashed,modifiedTime)"
                ),
                "pageSize": str(self.page_size),
                "includeRemoved": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            query = urllib.parse.urlencode(params)
            payload = get_json(
                f"{self.api_base}/changes?{query}",
                self.token_provider,
                sleep=self._sleep,
            )

            for change in payload.get("changes", []):
                file_id = str(change.get("fileId"))
                file_meta = change.get("file") or {}
                path = str(file_meta.get("name") or file_id)
                revision = f"{file_id}@{file_meta.get('modifiedTime', '')}"
                removed = bool(change.get("removed")) or bool(file_meta.get("trashed"))
                previous = file_ids.get(file_id)
                emitted: list[tuple[str, dict[str, object]]]
                if removed:
                    # Tombstones usually carry no name; remove the path we last observed.
                    file_ids.pop(file_id, None)
                    if previous is not None:
                        _release_path(files, previous["path"], file_id, file_ids)
                    emitted = [("file_removed", {"path": previous["path"] if previous else path})]
                else:
                    tracked = True
                    file_ids[file_id] = {"path": path, "revision": revision}
                    if previous is not None and previous["path"] != path:
                        _release_path(files, previous["path"], file_id, file_ids)
                    # On a shared name the last-seen fileId wins the projection.
                    files[path] = revision
                    details: dict[str, object] = {
                        "path": path,
                        "mimeType": file_meta.get("mimeType", ""),
                        "modifiedTime": file_meta.get("modifiedTime", ""),
                    }
                    if previous is None:
                        emitted = [("file_added", details)]
                    elif previous["path"] == path:
                        emitted = [("file_changed", details)]
                    else:
                        emitted = [
                            ("file_removed", {"path": previous["path"]}),
                            ("file_added", details),
                        ]
                for kind, event_payload in emitted:
                    events.append(
                        ChangeEvent(
                            source_id=self.source_id,
                            provider=PROVIDER,
                            kind=kind,
                            revision=revision,
                            observed_at=observed_at,
                            payload=event_payload,
                        )
                    )

            new_start = payload.get("newStartPageToken")
            next_page = payload.get("nextPageToken")
            if next_page:
                page_token = str(next_page)
                continue
            if new_start:
                state["delta_token"] = str(new_start)
            break

        if tracked:
            state["file_ids"] = file_ids
            state["files"] = files
        state["last_polled_at"] = observed_at.isoformat()
        cursor_out = Cursor(provider=PROVIDER, source_id=self.source_id, state=state)
        return FetchResult(events=tuple(events), cursor=cursor_out)

    def checkpoint(self) -> Cursor:
        start = get_json(f"{self.api_base}/changes/startPageToken", self.token_provider).get(
            "startPageToken", ""
        )
        return Cursor(
            provider=PROVIDER,
            source_id=self.source_id,
            state={"delta_token": str(start)},
        )
