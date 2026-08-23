"""Google Calendar adapter: syncToken increments, cancelled-event tombstones.

Freshness tier F0.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, UTC
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult
from akc_source_adapters.google._common import GoogleTokenProvider, get_json

PROVIDER = "gcal"
FRESHNESS_TIER = "F0"


class CalendarAdapter:
    """One calendar polled through events.list syncToken."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        source_name: str,
        calendar_id: str,
        token_provider: GoogleTokenProvider,
        api_base: str = "https://www.googleapis.com/calendar/v3",
        page_size: int = 100,
    ) -> None:
        self.source_id = f"gcal:{source_name}"
        self.calendar_id = calendar_id
        self.api_base = api_base.rstrip("/")
        self.token_provider = token_provider
        self.page_size = page_size

    # -- internals --------------------------------------------------------

    def _events_url(self, params: dict[str, str]) -> str:
        query = urllib.parse.urlencode(params)
        return (
            f"{self.api_base}/calendars/"
            f"{urllib.parse.quote(self.calendar_id)}/events?{query}"
        )

    def _event_event(self, event: dict[str, Any], observed_at) -> ChangeEvent:
        status = event.get("status")
        kind = "event_cancelled" if status == "cancelled" else (
            "event_added" if status == "confirmed" else "event_changed"
        )
        start = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date", "")
        attendees = [
            a.get("email", "") for a in (event.get("attendees") or []) if a.get("email")
        ]
        revision = f"{event.get('id','')}@{event.get('etag', '')}"
        return ChangeEvent(
            source_id=self.source_id,
            provider=PROVIDER,
            kind=kind,
            revision=revision,
            observed_at=observed_at,
            payload={
                "event_id": event.get("id", ""),
                "summary": event.get("summary", ""),
                "start": start,
                "hangout_link": event.get("hangoutLink", ""),
                "attendees": attendees,
            },
        )

    # -- SourceAdapter ----------------------------------------------------

    def discover(self) -> Mapping[str, object]:
        cal = get_json(
            f"{self.api_base}/calendars/{urllib.parse.quote(self.calendar_id)}",
            self.token_provider,
        )
        return {
            "provider": PROVIDER,
            "calendar_summary": cal.get("summary", ""),
            "time_zone": cal.get("timeZone", ""),
            "freshness_tier": FRESHNESS_TIER,
        }

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        state: dict[str, object] = dict(cursor.state) if cursor is not None else {}
        sync_token = state.get("sync_token")
        observed_at = datetime.now(UTC)
        events: list[ChangeEvent] = []

        params: dict[str, str] = {"maxResults": str(self.page_size), "singleEvents": "false"}
        if sync_token:
            params["syncToken"] = str(sync_token)
        else:
            params["orderBy"] = "updated"

        while True:
            payload = get_json(self._events_url(params), self.token_provider)
            for event in payload.get("items", []):
                if event.get("status") == "transparent":  # not a real event state; skip noise
                    continue
                events.append(self._event_event(event, observed_at))
            next_page = payload.get("nextPageToken")
            if next_page:
                params["pageToken"] = str(next_page)
                continue
            break

        if "nextSyncToken" in payload:
            state["sync_token"] = str(payload["nextSyncToken"])
        state["last_polled_at"] = observed_at.isoformat()
        cursor_out = Cursor(provider=PROVIDER, source_id=self.source_id, state=state)
        return FetchResult(events=tuple(events), cursor=cursor_out)

    def checkpoint(self) -> Cursor:
        # A full list is the only way to mint a sync token without prior state.
        result = self.fetch_changes(None)
        return result.cursor
