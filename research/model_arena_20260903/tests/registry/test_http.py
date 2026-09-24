"""Happy and failure paths for the registry's read-only HTTP layer."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from arena.registry.errors import SourceUnavailableError
from arena.registry.http import (
    ALLOWED_HOSTS,
    CachedFetcher,
    FixtureStore,
    HttpFetcher,
    OfflineFetcher,
    _SameHostHttpsRedirectHandler,
    fixture_key,
    require_allowed_host,
)

HF_URL = "https://huggingface.co/api/models/ATH-MaaS/OvisOCR2?blobs=true"
GH_URL = "https://api.github.com/repos/opendatalab/MinerU"


class _RecordingFetcher:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        return self.payload


class _ExplodingFetcher:
    def get_json(self, url: str) -> Any:
        raise SourceUnavailableError(f"live fetch of {url} was not expected")


def test_allowed_hosts_are_exactly_the_two_public_apis() -> None:
    assert frozenset({"huggingface.co", "api.github.com"}) == ALLOWED_HOSTS


def test_fixture_key_is_deterministic_safe_and_distinct() -> None:
    first = fixture_key(HF_URL)
    assert first == fixture_key(HF_URL)
    assert first != fixture_key(GH_URL)
    assert "/" not in first and ":" not in first and "?" not in first
    assert len(first) <= 90


def test_require_allowed_host_rejects_everything_else() -> None:
    assert require_allowed_host(HF_URL) == "huggingface.co"
    with pytest.raises(SourceUnavailableError, match="allow list"):
        require_allowed_host("https://example.invalid/api/models/x")


def test_fixture_store_round_trip(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    assert not store.has(HF_URL)
    store.write(HF_URL, {"sha": "abc", "unicode": "표"})
    assert store.has(HF_URL)
    assert store.read(HF_URL) == {"sha": "abc", "unicode": "표"}
    assert not list(tmp_path.glob("*.tmp"))


def test_offline_fetcher_fails_closed_on_a_missing_fixture(tmp_path: Path) -> None:
    fetcher = OfflineFetcher(FixtureStore(tmp_path))
    with pytest.raises(SourceUnavailableError, match="no recorded fixture"):
        fetcher.get_json(HF_URL)


def test_offline_fetcher_still_enforces_the_host_allow_list(tmp_path: Path) -> None:
    fetcher = OfflineFetcher(FixtureStore(tmp_path))
    with pytest.raises(SourceUnavailableError, match="allow list"):
        fetcher.get_json("https://evil.invalid/api/models/x")


def test_cached_fetcher_replays_a_recorded_url_and_never_calls_the_network(
    tmp_path: Path,
) -> None:
    store = FixtureStore(tmp_path)
    store.write(HF_URL, {"sha": "recorded"})
    fetcher = CachedFetcher(store, _ExplodingFetcher())
    assert fetcher.get_json(HF_URL) == {"sha": "recorded"}
    assert fetcher.cache_hits == (HF_URL,)


def test_cached_fetcher_goes_live_for_an_unrecorded_url(tmp_path: Path) -> None:
    live = _RecordingFetcher({"sha": "live"})
    fetcher = CachedFetcher(FixtureStore(tmp_path), live)
    assert fetcher.get_json(GH_URL) == {"sha": "live"}
    assert live.calls == [GH_URL]
    assert fetcher.cache_hits == ()


def test_cached_fetcher_does_not_swallow_a_live_failure(tmp_path: Path) -> None:
    fetcher = CachedFetcher(FixtureStore(tmp_path), _ExplodingFetcher())
    with pytest.raises(SourceUnavailableError):
        fetcher.get_json(GH_URL)


def test_http_fetcher_refuses_a_disallowed_host_before_opening_a_socket() -> None:
    with pytest.raises(SourceUnavailableError, match="allow list"):
        HttpFetcher().get_json("http://huggingface.co.evil.invalid/api/models/x")


def test_http_fetcher_refuses_plain_http_on_an_allowed_host() -> None:
    with pytest.raises(SourceUnavailableError, match="https-only"):
        HttpFetcher().get_json("http://huggingface.co/api/models/x")


def test_http_fetcher_reports_no_token_use_before_any_request() -> None:
    assert HttpFetcher().token_used is False


def test_hf_token_never_retries_on_github_path_containing_hf_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "test-token")
    fetcher = HttpFetcher()
    calls: list[str | None] = []
    url = "https://api.github.com/repos/example/huggingface.co"

    def rejected(_url: str, token: str | None) -> bytes:
        calls.append(token)
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(fetcher, "_open", rejected)
    with pytest.raises(SourceUnavailableError, match="this host cannot receive HF_TOKEN"):
        fetcher.get_json(url)
    assert calls == [None]
    assert fetcher.token_used is False


def test_hf_token_retries_only_on_hf_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "test-token")
    fetcher = HttpFetcher()
    calls: list[str | None] = []

    def first_unauthorized(_url: str, token: str | None) -> bytes:
        calls.append(token)
        if token is None:
            raise urllib.error.HTTPError(HF_URL, 401, "unauthorized", {}, None)
        return b'{"sha":"ok"}'

    monkeypatch.setattr(fetcher, "_open", first_unauthorized)
    assert fetcher.get_json(HF_URL) == {"sha": "ok"}
    assert calls == [None, "test-token"]
    assert fetcher.token_used is True


@pytest.mark.parametrize("destination", [
    "https://api.github.com/redirected",
    "https://evil.invalid/redirected",
    "http://huggingface.co/redirected",
])
def test_authenticated_request_refuses_cross_origin_redirect(destination: str) -> None:
    request = urllib.request.Request(
        HF_URL, headers={"Authorization": "Bearer test-token"}, method="GET",
    )
    handler = _SameHostHttpsRedirectHandler()
    with pytest.raises(SourceUnavailableError, match="approved HTTPS host"):
        handler.redirect_request(request, None, 302, "Found", {}, destination)


def test_authenticated_request_allows_same_host_https_redirect() -> None:
    request = urllib.request.Request(
        HF_URL, headers={"Authorization": "Bearer test-token"}, method="GET",
    )
    handler = _SameHostHttpsRedirectHandler()
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://huggingface.co/api/models/renamed",
    )
    assert redirected is not None
    assert redirected.full_url == "https://huggingface.co/api/models/renamed"
    assert redirected.get_header("Authorization") == "Bearer test-token"


def test_open_blocks_cross_host_redirect_before_a_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_https_open(
        _handler: object, request: urllib.request.Request,
    ) -> urllib.response.addinfourl:
        seen.append(request.full_url)
        headers = Message()
        headers["Location"] = "https://api.github.com/redirected"
        response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
        response.msg = "Found"
        return response

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", fake_https_open)
    with pytest.raises(SourceUnavailableError, match="approved HTTPS host"):
        HttpFetcher()._open(HF_URL, "test-token")
    assert seen == [HF_URL]


def test_open_keeps_credentials_on_same_host_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str | None]] = []
    destination = "https://huggingface.co/api/models/renamed"

    def fake_https_open(
        _handler: object, request: urllib.request.Request,
    ) -> urllib.response.addinfourl:
        seen.append((request.full_url, request.get_header("Authorization")))
        headers = Message()
        if request.full_url == HF_URL:
            headers["Location"] = destination
            response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, 302)
            response.msg = "Found"
            return response
        response = urllib.response.addinfourl(
            io.BytesIO(b'{"sha":"ok"}'), headers, request.full_url, 200,
        )
        response.msg = "OK"
        return response

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", fake_https_open)
    assert HttpFetcher()._open(HF_URL, "test-token") == b'{"sha":"ok"}'
    assert seen == [(HF_URL, "Bearer test-token"), (destination, "Bearer test-token")]
