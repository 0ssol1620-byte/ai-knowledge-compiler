"""Offline PublicSeriesAdapter: rights first, injected fetch, no network. Synthetic."""

from __future__ import annotations

import functools
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from akc_source_adapters.envelope import Cursor, SourceAdapter
from akc_source_adapters.public_data.adapter import (
    PublicDataKeyMissing,
    PublicSeriesAdapter,
)
from akc_source_adapters.public_data.alfred import (
    build_alfred_request_url,
    parse_alfred_observations,
)
from akc_source_adapters.public_data.rights import ACTIONS, RightsDenied, RightsRecord
from akc_source_adapters.public_data.sources import DEFAULT_RIGHTS, PUBLIC_SOURCES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "public_data"
RAW = (FIXTURES / "synthetic_alfred_observations.json").read_bytes()
SENTINEL_KEY = "SENTINELKEY0123456789abcdef"
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
SERIES = "SYNTH1"
SOURCE = PUBLIC_SOURCES["alfred"]


def _rights(*allow: str) -> RightsRecord:
    return RightsRecord(
        f"alfred:{SERIES}",
        "alfred",
        SERIES,
        "https://example.org/terms",
        "a" * 64,
        date(2026, 11, 1),
        "reviewer",
        None,
        None,
        {a: ("allow" if a in allow else "deny") for a in ACTIONS},  # type: ignore[misc]
    )


class FakeFetch:
    def __init__(self, body: bytes = RAW) -> None:
        self.body = body
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.body


def _adapter(
    fetch: FakeFetch,
    rights: RightsRecord | None = None,
    key: str | None = SENTINEL_KEY,
) -> PublicSeriesAdapter:
    rights = rights or _rights("ingest")
    parse = functools.partial(
        parse_alfred_observations,
        series_id=SERIES,
        units="index",
        frequency="monthly",
        seasonal_adjustment="NSA",
        rights_id=rights.rights_id,
    )
    return PublicSeriesAdapter(
        SOURCE,
        SERIES,
        build_alfred_request_url(SERIES),
        parse,
        fetch,
        rights,
        key_provider=(lambda: key),
        clock=lambda: NOW,
    )


def test_adapter_satisfies_the_protocol() -> None:
    assert isinstance(_adapter(FakeFetch()), SourceAdapter)


def test_default_rights_refuse_before_any_fetch() -> None:
    fetch = FakeFetch()
    default = next(r for r in DEFAULT_RIGHTS if r.source_id == "alfred")
    with pytest.raises(RightsDenied) as e:
        _adapter(fetch, default).fetch_changes(None)
    assert e.value.reason == "unknown"
    assert fetch.urls == []


def test_rights_for_another_series_refuse_before_any_fetch() -> None:
    fetch = FakeFetch()
    other = RightsRecord(**{**_rights("ingest").__dict__, "series_id": "OTHER"})
    with pytest.raises(RightsDenied):
        _adapter(fetch, other).fetch_changes(None)
    assert fetch.urls == []


def test_missing_required_key_fails_before_fetch() -> None:
    fetch = FakeFetch()
    for key in (None, ""):
        with pytest.raises(PublicDataKeyMissing):
            _adapter(fetch, key=key).fetch_changes(None)
    assert fetch.urls == []


def test_key_never_appears_in_events_cursor_or_discover() -> None:
    fetch = FakeFetch()
    adapter = _adapter(fetch)
    result = adapter.fetch_changes(None)
    assert len(fetch.urls) == 1 and SENTINEL_KEY in fetch.urls[0]  # only the fetched URL
    assert result.events
    blobs = [e.canonical() for e in result.events]
    blobs += [result.cursor.encoded(), repr(result.cursor), repr(adapter.discover())]
    blobs += [repr(adapter.checkpoint()), adapter.request_url]
    assert not any(SENTINEL_KEY in b for b in blobs)


def test_incremental_poll_emits_only_new_vintages_then_nothing() -> None:
    fetch = FakeFetch()
    adapter = _adapter(fetch)
    first = adapter.fetch_changes(None)
    assert len(first.events) == 4
    assert {e.kind for e in first.events} == {"observation_vintage"}
    again = adapter.fetch_changes(first.cursor)
    assert again.events == ()
    assert again.cursor == first.cursor
    # A later release of the same series: only the new vintage is emitted.
    extra = (
        b'{"observations":[{"realtime_start":"2020-01-15","realtime_end":"2021-02-09",'
        b'"date":"2019-12-01","value":"100.10"},{"realtime_start":"2021-02-10",'
        b'"realtime_end":"2022-01-01","date":"2019-12-01","value":"101.50"},'
        b'{"realtime_start":"2022-01-02","realtime_end":"9999-12-31","date":"2019-12-01",'
        b'"value":"102.25"}]}'
    )
    fetch.body = extra
    later = adapter.fetch_changes(first.cursor)
    assert [e.payload["vintage_id"] for e in later.events] == ["2022-01-02"]
    assert later.events[0].payload["value"] == "102.25"


def test_a_republished_vintage_with_another_value_is_not_dropped() -> None:
    fetch = FakeFetch()
    adapter = _adapter(fetch)
    first = adapter.fetch_changes(None)
    fetch.body = RAW.replace(b"102.00", b"102.07")
    changed = adapter.fetch_changes(first.cursor)
    assert [e.payload["value"] for e in changed.events] == ["102.07"]


def test_same_cursor_same_events_across_instances() -> None:
    a, b = _adapter(FakeFetch()), _adapter(FakeFetch())
    first = a.fetch_changes(None)
    assert first.events == b.fetch_changes(None).events
    cursor = Cursor.decode(first.cursor.encoded())
    assert a.fetch_changes(cursor) == b.fetch_changes(cursor)


def test_foreign_cursor_rejected() -> None:
    adapter = _adapter(FakeFetch())
    for bad in (
        Cursor("github", adapter.source_id, {}),
        Cursor("public_series", "alfred:OTHER", {}),
    ):
        with pytest.raises(ValueError, match="does not match"):
            adapter.fetch_changes(bad)


def test_event_hash_is_stable() -> None:
    events = _adapter(FakeFetch()).fetch_changes(None).events
    again = _adapter(FakeFetch()).fetch_changes(None).events
    assert [e.event_hash for e in events] == [e.event_hash for e in again]
    assert len({e.event_hash for e in events}) == len(events)
    assert all(e.revision.startswith(str(e.payload["vintage_id"]) + ":sha256:") for e in events)


def test_observation_of_another_source_is_refused() -> None:
    parse = functools.partial(
        parse_alfred_observations,
        series_id=SERIES,
        units="index",
        frequency=None,
        seasonal_adjustment=None,
        rights_id="someone-else",
    )
    adapter = PublicSeriesAdapter(
        SOURCE,
        SERIES,
        build_alfred_request_url(SERIES),
        parse,
        FakeFetch(),
        _rights("ingest"),
        key_provider=lambda: SENTINEL_KEY,
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="not of this source and rights"):
        adapter.fetch_changes(None)


def test_request_url_with_a_key_is_refused() -> None:
    with pytest.raises(ValueError, match="API key"):
        PublicSeriesAdapter(
            SOURCE,
            SERIES,
            build_alfred_request_url(SERIES) + "&api_key=x",
            lambda *_: (),
            FakeFetch(),
            _rights("ingest"),
        )
