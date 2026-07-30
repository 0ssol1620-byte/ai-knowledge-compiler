from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from akc_url_fetcher import FetchPolicy, SecureUrlFetcher, UrlFetchError


class FakeResponse:
    def __init__(
        self,
        status: int,
        *,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = headers
        self._body = body
        self._offset = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        result = self._body[self._offset : self._offset + amount]
        self._offset += len(result)
        return result

    def close(self) -> None:
        self.closed = True


def test_https_pdf_fetch_pins_ip_hashes_body_and_redacts_query() -> None:
    calls: list[tuple[str, str]] = []
    response = FakeResponse(
        200,
        headers={
            "Content-Type": "application/pdf",
            "Content-Length": "12",
        },
        body=b"%PDF-1.7\nEOF",
    )

    def resolver(host: str, port: int) -> set[str]:
        calls.append((host, str(port)))
        return {"93.184.216.34"}

    def requester(target: object, _headers: object, _policy: object) -> FakeResponse:
        calls.append((target.host, target.pinned_ip))  # type: ignore[attr-defined]
        return response

    result = SecureUrlFetcher(
        resolver=resolver,
        requester=requester,
        wall_clock=lambda: datetime(2026, 7, 29, tzinfo=UTC),
    ).fetch("https://Example.COM/report.pdf?temporary_secret=value")

    assert calls == [
        ("example.com", "443"),
        ("example.com", "93.184.216.34"),
    ]
    assert result.canonical_url == "https://example.com/report.pdf"
    assert result.query_sha256 is not None
    assert "temporary_secret" not in result.canonical_url
    assert result.sha256
    assert result.final_ip == "93.184.216.34"
    assert response.closed is True


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/file.pdf",
        "https://user:password@example.com/file.pdf",
        "https://example.com:8443/file.pdf",
        "file:///etc/passwd",
    ],
)
def test_unsafe_url_forms_are_rejected_before_dns(url: str) -> None:
    fetcher = SecureUrlFetcher(
        resolver=lambda _host, _port: pytest.fail("DNS must not be called"),
    )
    with pytest.raises(UrlFetchError):
        fetcher.fetch(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.100.100.200",
        "::1",
        "fe80::1",
    ],
)
def test_private_loopback_link_local_and_metadata_addresses_are_blocked(
    address: str,
) -> None:
    fetcher = SecureUrlFetcher(
        resolver=lambda _host, _port: {address},
        requester=lambda *_args: pytest.fail("request must not be sent"),
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_ADDRESS_FORBIDDEN"):
        fetcher.fetch("https://example.com/file.pdf")


def test_mixed_public_and_private_dns_answer_fails_closed() -> None:
    fetcher = SecureUrlFetcher(
        resolver=lambda _host, _port: {"93.184.216.34", "10.0.0.2"},
        requester=lambda *_args: pytest.fail("request must not be sent"),
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_ADDRESS_FORBIDDEN"):
        fetcher.fetch("https://example.com/file.pdf")


def test_redirect_target_is_resolved_and_revalidated() -> None:
    hosts: list[str] = []
    first = FakeResponse(
        302,
        headers={"Location": "https://internal.example/secret"},
    )

    def resolver(host: str, _port: int) -> set[str]:
        hosts.append(host)
        return {"93.184.216.34"} if host == "public.example" else {"10.0.0.9"}

    fetcher = SecureUrlFetcher(
        resolver=resolver,
        requester=lambda *_args: first,
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_ADDRESS_FORBIDDEN"):
        fetcher.fetch("https://public.example/start")
    assert hosts == ["public.example", "internal.example"]
    assert first.closed is True


def test_declared_and_streamed_size_limits_are_enforced() -> None:
    declared = FakeResponse(
        200,
        headers={
            "Content-Type": "application/pdf",
            "Content-Length": "2049",
        },
        body=b"%PDF-" + b"x" * 100,
    )
    streamed = FakeResponse(
        200,
        headers={"Content-Type": "application/pdf"},
        body=b"%PDF-" + b"x" * 2048,
    )
    responses = iter([declared, streamed])
    fetcher = SecureUrlFetcher(
        policy=FetchPolicy(max_bytes=2048),
        resolver=lambda _host, _port: {"93.184.216.34"},
        requester=lambda *_args: next(responses),
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_RESPONSE_TOO_LARGE"):
        fetcher.fetch("https://example.com/declared.pdf")
    with pytest.raises(UrlFetchError, match="URL_FETCH_RESPONSE_TOO_LARGE"):
        fetcher.fetch("https://example.com/streamed.pdf")
    assert declared.closed and streamed.closed


def test_declared_mime_must_match_magic() -> None:
    response = FakeResponse(
        200,
        headers={"Content-Type": "application/pdf"},
        body=b"<html>not a PDF</html>",
    )
    fetcher = SecureUrlFetcher(
        resolver=lambda _host, _port: {"93.184.216.34"},
        requester=lambda *_args: response,
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_MIME_MISMATCH"):
        fetcher.fetch("https://example.com/fake.pdf")


def test_compressed_http_body_is_rejected_to_avoid_decompression_bombs() -> None:
    response = FakeResponse(
        200,
        headers={
            "Content-Type": "text/html",
            "Content-Encoding": "gzip",
        },
        body=b"compressed",
    )
    fetcher = SecureUrlFetcher(
        resolver=lambda _host, _port: {"93.184.216.34"},
        requester=lambda *_args: response,
    )
    with pytest.raises(UrlFetchError, match="URL_FETCH_CONTENT_ENCODING_FORBIDDEN"):
        fetcher.fetch("https://example.com/page")


def test_all_special_ranges_in_ipaddress_remain_non_global() -> None:
    # Guard the assumption underlying the deny-by-default address policy.
    assert not ipaddress.ip_address("192.0.2.1").is_global
    assert not ipaddress.ip_address("198.51.100.1").is_global
    assert not ipaddress.ip_address("203.0.113.1").is_global
