"""Pinned-IP HTTPS fetcher for the isolated URL-ingestion service."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import math
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import filetype

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("192.0.0.192"),
    }
)
_OOXML_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
_DEFAULT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "text/html",
        "text/plain",
        *_OOXML_TYPES,
    }
)


class UrlFetchError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class FetchPolicy:
    max_bytes: int = 50 * 1024 * 1024
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 20.0
    total_timeout_seconds: float = 30.0
    max_redirects: int = 5
    allowed_ports: frozenset[int] = frozenset({443})
    allowed_content_types: frozenset[str] = _DEFAULT_CONTENT_TYPES
    user_agent: str = "AKC-UrlFetcher/1.0"

    def __post_init__(self) -> None:
        if not 1024 <= self.max_bytes <= 1024 * 1024 * 1024:
            raise ValueError("max_bytes must be between 1 KiB and 1 GiB")
        for value in (
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.total_timeout_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("fetch timeouts must be finite and positive")
        if self.total_timeout_seconds < max(
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
        ):
            raise ValueError("total timeout cannot be shorter than component timeout")
        if not 0 <= self.max_redirects <= 10:
            raise ValueError("max_redirects must be 0..10")
        if not self.allowed_ports or any(
            not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
            for port in self.allowed_ports
        ):
            raise ValueError("invalid port allowlist")
        if not self.allowed_content_types or any(
            value != value.casefold() or "/" not in value for value in self.allowed_content_types
        ):
            raise ValueError("invalid content-type allowlist")
        if not self.user_agent or len(self.user_agent) > 200:
            raise ValueError("invalid user agent")


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    content_type: str
    sha256: str
    canonical_url: str
    query_sha256: str | None
    retrieved_at: datetime
    redirect_count: int
    final_ip: str


@dataclass(frozen=True)
class _Target:
    url: str
    host: str
    port: int
    request_target: str
    pinned_ip: str


class _Response(Protocol):
    status: int

    @property
    def headers(self) -> Mapping[str, str]: ...

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


Resolver = Callable[[str, int], set[str]]
Requester = Callable[[_Target, Mapping[str, str], FetchPolicy], _Response]


def _default_resolver(host: str, port: int) -> set[str]:
    try:
        return {
            ipaddress.ip_address(item[4][0]).compressed
            for item in socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        }
    except socket.gaierror as exc:
        raise UrlFetchError("URL_FETCH_DNS_FAILED", retryable=True) from exc


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        pinned_ip: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        self._pinned_ip = pinned_ip
        self._akc_context = context
        super().__init__(
            host=host,
            port=port,
            timeout=timeout,
            context=context,
        )

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
        )
        try:
            self.sock = self._akc_context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


class _HttpResponse:
    def __init__(
        self,
        connection: _PinnedHttpsConnection,
        response: http.client.HTTPResponse,
    ) -> None:
        self._connection = connection
        self._response = response
        self.status = response.status
        self.headers = {key: value for key, value in response.getheaders()}

    def read(self, amount: int = -1) -> bytes:
        return self._response.read(amount)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


def _default_requester(
    target: _Target,
    headers: Mapping[str, str],
    policy: FetchPolicy,
) -> _Response:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = _PinnedHttpsConnection(
        host=target.host,
        port=target.port,
        pinned_ip=target.pinned_ip,
        timeout=policy.connect_timeout_seconds,
        context=context,
    )
    try:
        connection.request(
            "GET",
            target.request_target,
            headers=dict(headers),
        )
        response = connection.getresponse()
        if connection.sock is not None:
            connection.sock.settimeout(policy.read_timeout_seconds)
        return _HttpResponse(connection, response)
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
        connection.close()
        raise UrlFetchError("URL_FETCH_NETWORK_ERROR", retryable=True) from exc


def _header(headers: Mapping[str, str], name: str) -> str | None:
    folded = name.casefold()
    return next(
        (value for key, value in headers.items() if key.casefold() == folded),
        None,
    )


def _safe_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise UrlFetchError("URL_FETCH_DNS_INVALID") from exc
    if address in _METADATA_ADDRESSES or not address.is_global:
        raise UrlFetchError("URL_FETCH_ADDRESS_FORBIDDEN")
    return address


def _target(url: str, policy: FetchPolicy, resolver: Resolver) -> _Target:
    if len(url) > 4096 or any(ord(character) < 0x20 for character in url):
        raise UrlFetchError("URL_FETCH_URL_INVALID")
    parsed = urlsplit(url)
    raw_host = (parsed.hostname or "").rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not raw_host
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise UrlFetchError("URL_FETCH_URL_INVALID")
    try:
        host = raw_host.encode("idna").decode("ascii").casefold()
        port = parsed.port or 443
    except (UnicodeError, ValueError) as exc:
        raise UrlFetchError("URL_FETCH_URL_INVALID") from exc
    if port not in policy.allowed_ports:
        raise UrlFetchError("URL_FETCH_PORT_FORBIDDEN")
    try:
        decoded_path = unquote(parsed.path, errors="strict")
    except UnicodeDecodeError as exc:
        raise UrlFetchError("URL_FETCH_URL_INVALID") from exc
    if any(ord(character) < 0x20 for character in decoded_path):
        raise UrlFetchError("URL_FETCH_URL_INVALID")
    addresses = resolver(host, port)
    if not addresses:
        raise UrlFetchError("URL_FETCH_DNS_FAILED", retryable=True)
    safe_addresses = sorted(_safe_ip(value).compressed for value in addresses)
    path = parsed.path or "/"
    request_target = urlunsplit(("", "", path, parsed.query, ""))
    display_host = f"[{host}]" if ":" in host else host
    canonical_netloc = display_host if port == 443 else f"{display_host}:{port}"
    canonical_url = urlunsplit(("https", canonical_netloc, path, parsed.query, ""))
    return _Target(
        url=canonical_url,
        host=host,
        port=port,
        request_target=request_target,
        pinned_ip=safe_addresses[0],
    )


def _media_type(headers: Mapping[str, str], policy: FetchPolicy) -> str:
    content_type = _header(headers, "Content-Type")
    if content_type is None:
        raise UrlFetchError("URL_FETCH_CONTENT_TYPE_REQUIRED")
    value = content_type.split(";", 1)[0].strip().casefold()
    if value not in policy.allowed_content_types:
        raise UrlFetchError("URL_FETCH_CONTENT_TYPE_FORBIDDEN")
    return value


def _validate_magic(body: bytes, content_type: str) -> None:
    if content_type == "application/pdf":
        if not body.startswith(b"%PDF-"):
            raise UrlFetchError("URL_FETCH_MIME_MISMATCH")
        return
    if content_type in _OOXML_TYPES:
        if not body.startswith(b"PK\x03\x04"):
            raise UrlFetchError("URL_FETCH_MIME_MISMATCH")
        return
    if content_type == "text/html":
        sample = body[:8192].lstrip().lower()
        if not (
            sample.startswith(b"<!doctype html")
            or sample.startswith(b"<html")
            or b"<html" in sample
        ):
            raise UrlFetchError("URL_FETCH_MIME_MISMATCH")
        return
    if content_type == "text/plain":
        if b"\x00" in body[:8192]:
            raise UrlFetchError("URL_FETCH_MIME_MISMATCH")
        try:
            body[:8192].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UrlFetchError("URL_FETCH_MIME_MISMATCH") from exc
        return
    guessed = filetype.guess(body[:8192])
    if guessed is None or guessed.mime != content_type:
        raise UrlFetchError("URL_FETCH_MIME_MISMATCH")


def _read_body(
    response: _Response,
    *,
    policy: FetchPolicy,
    started_at: float,
    clock: Callable[[], float],
) -> bytes:
    content_encoding = _header(response.headers, "Content-Encoding")
    if content_encoding and content_encoding.casefold() not in {"identity"}:
        raise UrlFetchError("URL_FETCH_CONTENT_ENCODING_FORBIDDEN")
    content_length = _header(response.headers, "Content-Length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise UrlFetchError("URL_FETCH_CONTENT_LENGTH_INVALID") from exc
        if declared < 0 or declared > policy.max_bytes:
            raise UrlFetchError("URL_FETCH_RESPONSE_TOO_LARGE")
    chunks: list[bytes] = []
    total = 0
    while True:
        if clock() - started_at > policy.total_timeout_seconds:
            raise UrlFetchError("URL_FETCH_TOTAL_TIMEOUT", retryable=True)
        try:
            chunk = response.read(min(64 * 1024, policy.max_bytes - total + 1))
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            raise UrlFetchError("URL_FETCH_NETWORK_ERROR", retryable=True) from exc
        if not chunk:
            break
        total += len(chunk)
        if total > policy.max_bytes:
            raise UrlFetchError("URL_FETCH_RESPONSE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def _redacted_url(url: str) -> tuple[str, str | None]:
    parsed = urlsplit(url)
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))
    query_hash = hashlib.sha256(parsed.query.encode()).hexdigest() if parsed.query else None
    return canonical, query_hash


class SecureUrlFetcher:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        resolver: Resolver = _default_resolver,
        requester: Requester = _default_requester,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._resolver = resolver
        self._requester = requester
        self._clock = clock
        self._wall_clock = wall_clock

    def fetch(self, url: str) -> FetchResult:
        started_at = self._clock()
        current_url = url
        redirects = 0
        while True:
            if self._clock() - started_at > self.policy.total_timeout_seconds:
                raise UrlFetchError("URL_FETCH_TOTAL_TIMEOUT", retryable=True)
            target = _target(current_url, self.policy, self._resolver)
            display_host = f"[{target.host}]" if ":" in target.host else target.host
            host_header = display_host if target.port == 443 else f"{display_host}:{target.port}"
            response = self._requester(
                target,
                {
                    "Accept": ", ".join(sorted(self.policy.allowed_content_types)),
                    "Connection": "close",
                    "Host": host_header,
                    "User-Agent": self.policy.user_agent,
                },
                self.policy,
            )
            try:
                if response.status in _REDIRECT_STATUSES:
                    if redirects >= self.policy.max_redirects:
                        raise UrlFetchError("URL_FETCH_TOO_MANY_REDIRECTS")
                    location = _header(response.headers, "Location")
                    if not location or len(location) > 4096:
                        raise UrlFetchError("URL_FETCH_REDIRECT_INVALID")
                    current_url = urljoin(target.url, location)
                    redirects += 1
                    continue
                if response.status == 429 or response.status >= 500:
                    raise UrlFetchError("URL_FETCH_UPSTREAM_UNAVAILABLE", retryable=True)
                if response.status != 200:
                    raise UrlFetchError("URL_FETCH_UPSTREAM_REJECTED")
                content_type = _media_type(response.headers, self.policy)
                body = _read_body(
                    response,
                    policy=self.policy,
                    started_at=started_at,
                    clock=self._clock,
                )
                if not body:
                    raise UrlFetchError("URL_FETCH_EMPTY_RESPONSE")
                _validate_magic(body, content_type)
                canonical_url, query_hash = _redacted_url(target.url)
                return FetchResult(
                    body=body,
                    content_type=content_type,
                    sha256=hashlib.sha256(body).hexdigest(),
                    canonical_url=canonical_url,
                    query_sha256=query_hash,
                    retrieved_at=self._wall_clock(),
                    redirect_count=redirects,
                    final_ip=target.pinned_ip,
                )
            finally:
                response.close()
