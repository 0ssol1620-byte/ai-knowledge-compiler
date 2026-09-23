"""Google Drive adapter: changes.list delta tokens, removal tombstones.

Freshness tier F1 (hourly polling is enough for most drives).
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult
from akc_source_adapters.google._common import GoogleAdapterError, GoogleTokenProvider, get_json

PROVIDER = "gdrive"
FRESHNESS_TIER = "F1"


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
        page_token = str(state.get("delta_token") or "")
        observed_at = datetime.now(UTC)
        events: list[ChangeEvent] = []
        prior_files = state.get("files") or {}
        if not isinstance(prior_files, Mapping):
            raise GoogleAdapterError("cursor 'files' must be a mapping of path to revision")
        files: dict[str, object] = dict(prior_files)

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
                file_meta = change.get("file") or {}
                path = str(file_meta.get("name") or change.get("fileId"))
                revision = f"{change.get('fileId')}@{file_meta.get('modifiedTime', '')}"
                removed = bool(change.get("removed")) or bool(file_meta.get("trashed"))
                kind = (
                    "file_removed"
                    if removed
                    else ("file_changed" if files.get(path) else "file_added")
                )
                event_payload: dict[str, object] = {"path": path}
                if not removed:
                    event_payload.update(
                        {
                            "mimeType": file_meta.get("mimeType", ""),
                            "modifiedTime": file_meta.get("modifiedTime", ""),
                        }
                    )
                    files[path] = revision
                else:
                    files.pop(path, None)
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

        if files or "files" in state:
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
