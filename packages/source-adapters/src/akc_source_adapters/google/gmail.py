"""Gmail adapter: historyId increments, TRASHED tombstones, plain-text bodies.

Freshness tier F0 (mail is near-real-time by nature).
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, UTC
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult
from akc_source_adapters.google._common import GoogleTokenProvider, get_json

PROVIDER = "gmail"
FRESHNESS_TIER = "F0"


class GmailAdapter:
    """One mailbox polled through the history API."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        source_name: str,
        token_provider: GoogleTokenProvider,
        api_base: str = "https://gmail.googleapis.com/gmail/v1/users/me",
        label_filter: str | None = None,
        page_size: int = 100,
    ) -> None:
        self.source_id = f"gmail:{source_name}"
        self.api_base = api_base.rstrip("/")
        self.token_provider = token_provider
        self.label_filter = label_filter
        self.page_size = page_size

    # -- internals --------------------------------------------------------

    def _message(self, message_id: str) -> dict[str, Any]:
        params = {"format": "metadata", "metadataHeaders": "Subject"}
        query = urllib.parse.urlencode(params)
        return get_json(
            f"{self.api_base}/messages/{message_id}?{query}", self.token_provider
        )

    @staticmethod
    def _subject(message: dict[str, Any]) -> str:
        for header in message.get("payload", {}).get("headers", []):
            if header.get("name") == "Subject":
                return str(header.get("value", ""))
        return ""

    def _emit_message(self, message_id: str, removed: bool, observed_at, history_id: Any = "") -> ChangeEvent:
        revision = f"{message_id}@{history_id}"
        if removed:
            payload: dict[str, object] = {"message_id": message_id}
            kind = "message_removed"
        else:
            message = self._message(message_id)
            labels = list(message.get("labelIds", []))
            kind = (
                "message_trashed"
                if "TRASH" in labels
                else "message_added"
                if "INBOX" in labels
                else "message_changed"
            )
            payload = {
                "message_id": message_id,
                "thread_id": message.get("threadId", ""),
                "subject": self._subject(message),
                "labels": labels,
                "snippet": str(message.get("snippet", ""))[:280],
            }
        return ChangeEvent(
            source_id=self.source_id,
            provider=PROVIDER,
            kind=kind,
            revision=revision,
            observed_at=observed_at,
            payload=payload,
        )

    # -- SourceAdapter ----------------------------------------------------

    def discover(self) -> Mapping[str, object]:
        profile = get_json(f"{self.api_base}/profile", self.token_provider)
        return {
            "provider": PROVIDER,
            "account": profile.get("emailAddress", ""),
            "history_id": profile.get("historyId"),
            "freshness_tier": FRESHNESS_TIER,
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        state: dict[str, object] = dict(cursor.state) if cursor is not None else {}
        history_id = state.get("history_id")
        observed_at = datetime.now(UTC)
        events: list[ChangeEvent] = []

        if history_id is None:
            profile = get_json(f"{self.api_base}/profile", self.token_provider)
            state["history_id"] = profile.get("historyId")
            state["last_polled_at"] = observed_at.isoformat()
            cursor_out = Cursor(provider=PROVIDER, source_id=self.source_id, state=state)
            return FetchResult(events=(), cursor=cursor_out)

        params: dict[str, str] = {
            "startHistoryId": str(history_id),
            "maxResults": str(self.page_size),
        }
        if self.label_filter:
            params["labelId"] = self.label_filter
        query = urllib.parse.urlencode(params)
        history = get_json(f"{self.api_base}/history?{query}", self.token_provider)

        seen: set[str] = set()
        for record in history.get("history", []):
            for removed in record.get("messagesDeleted", []):
                mid = (removed.get("message") or {}).get("id", "")
                if mid and mid not in seen:
                    events.append(self._emit_message(mid, True, observed_at, state.get("history_id", "")))
                    seen.add(mid)
            for change in record.get("labelsChanged", []):
                mid = (change.get("message") or {}).get("id", "")
                if mid and mid not in seen:
                    events.append(
                        self._emit_message(mid, False, observed_at, state.get("history_id", ""))
                    )
                    seen.add(mid)
            for added in record.get("messagesAdded", []):
                mid = (added.get("message") or {}).get("id", "")
                if mid and mid not in seen:
                    events.append(
                        self._emit_message(mid, False, observed_at, state.get("history_id", ""))
                    )
                    seen.add(mid)

        if "historyId" in history:
            state["history_id"] = history["historyId"]
        state["last_polled_at"] = observed_at.isoformat()
        self._history_id = state["history_id"]
        cursor_out = Cursor(provider=PROVIDER, source_id=self.source_id, state=state)
        return FetchResult(events=tuple(events), cursor=cursor_out)

    def checkpoint(self) -> Cursor:
        profile = get_json(f"{self.api_base}/profile", self.token_provider)
        return Cursor(
            provider=PROVIDER,
            source_id=self.source_id,
            state={"history_id": profile.get("historyId")},
        )
