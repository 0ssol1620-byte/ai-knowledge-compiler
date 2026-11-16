"""Offline polling adapter for public series (no network transport in this module).

`fetch` is injected: the adapter never opens a connection itself. The rights
gate runs first and fails closed; a required API key is checked before any
fetch and is appended only to the URL handed to `fetch`, never to an event,
cursor or `discover()` result.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import fields
from datetime import date, datetime
from typing import Any

from akc_source_adapters.envelope import ChangeEvent, Cursor, FetchResult, utc_now

from .rights import RightsRecord, require
from .sources import PublicSource
from .vintage import VintageObservation

PROVIDER = "public_series"
KIND_VINTAGE = "observation_vintage"
# ponytail: query parameter name unverified (FRED docs name it api_key); make it
# a constructor argument when a source with another name is wired up.
KEY_PARAM = "api_key"

Parser = Callable[[bytes, str, str], tuple[VintageObservation, ...]]


class PublicDataKeyMissing(RuntimeError):
    """A source that requires an API key was polled without one."""


def _payload(o: VintageObservation) -> dict[str, object]:
    out: dict[str, object] = {}
    for f in fields(o):
        v = getattr(o, f.name)
        out[f.name] = v.isoformat() if isinstance(v, date) else v
    return out


class PublicSeriesAdapter:
    provider: str = PROVIDER

    def __init__(
        self,
        source: PublicSource,
        series_id: str,
        request_url: str,
        parse: Parser,
        fetch: Callable[[str], bytes],
        rights: RightsRecord,
        *,
        key_provider: Callable[[], str | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not series_id.strip():
            raise ValueError("series_id must be non-empty")
        if not request_url.startswith("https://"):
            raise ValueError("request_url must be https")
        if urllib.parse.parse_qs(urllib.parse.urlsplit(request_url).query).get(KEY_PARAM):
            raise ValueError("request_url must not carry an API key")
        self.source = source
        self.series_id = series_id
        self.request_url = request_url
        self.source_id = f"{source.source_id}:{series_id}"
        self._parse = parse
        self._fetch = fetch
        self._rights = rights
        self._key_provider = key_provider
        self._clock: Callable[[], datetime] = clock or utc_now

    def discover(self) -> Mapping[str, object]:
        """Static description; fetches nothing and reports no key."""
        return {
            "provider": PROVIDER,
            "source_id": self.source_id,
            "public_source": self.source.source_id,
            "series_id": self.series_id,
            "docs_urls": list(self.source.docs_urls),
            "availability": self.source.availability,
            "rights_id": self._rights.rights_id,
            "rights_verified": self._rights.verified,
        }

    def checkpoint(self) -> Cursor:
        return Cursor(PROVIDER, self.source_id, {"seen": {}})

    def _seen(self, cursor: Cursor | None) -> dict[str, list[list[str]]]:
        if cursor is None:
            return {}
        if cursor.provider != PROVIDER:
            raise ValueError(f"cursor provider {cursor.provider!r} does not match {PROVIDER!r}")
        if cursor.source_id != self.source_id:
            raise ValueError(
                f"cursor source {cursor.source_id!r} does not match {self.source_id!r}"
            )
        seen: Any = cursor.state.get("seen", {})
        if not isinstance(seen, Mapping):
            raise ValueError("cursor state 'seen' must be a mapping")
        return {str(k): [[str(x) for x in p] for p in v] for k, v in seen.items()}

    def fetch_changes(self, cursor: Cursor | None) -> FetchResult:
        seen = self._seen(cursor)
        observed_at = self._clock()
        require(self.source, self.series_id, "ingest", (self._rights,), today=observed_at.date())
        url = self.request_url
        if self.source.api_key == "required":
            key = self._key_provider() if self._key_provider is not None else None
            if not key:
                raise PublicDataKeyMissing(f"{self.source.source_id}: API key not provided")
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.urlencode({KEY_PARAM: key})}"
        raw = self._fetch(url)
        sha = "sha256:" + hashlib.sha256(raw).hexdigest()
        observations = self._parse(raw, self.request_url, sha)
        for o in observations:
            if o.source_id != self.source.source_id or o.rights_id != self._rights.rights_id:
                raise ValueError(f"{o.logical_id}: observation is not of this source and rights")

        # A vintage is known by (vintage_id, value): the same vintage re-published
        # with another value is a change to surface, never to drop.
        known = {(lid, v, val) for lid, pairs in seen.items() for v, val in pairs}
        events: list[ChangeEvent] = []
        new_seen = {lid: list(pairs) for lid, pairs in seen.items()}
        for o in sorted(
            observations,
            key=lambda o: (o.logical_id, o.available_on or date.min, o.vintage_id, o.value),
        ):
            ident = (o.logical_id, o.vintage_id, o.value)
            if ident in known:
                continue
            known.add(ident)
            new_seen.setdefault(o.logical_id, []).append([o.vintage_id, o.value])
            events.append(
                ChangeEvent(
                    source_id=self.source_id,
                    provider=PROVIDER,
                    kind=KIND_VINTAGE,
                    revision=f"{o.vintage_id}:{o.raw_sha256}",
                    observed_at=observed_at,
                    payload=_payload(o),
                )
            )
        state = {"seen": {k: sorted(v) for k, v in sorted(new_seen.items())}}
        return FetchResult(tuple(events), Cursor(PROVIDER, self.source_id, state))
