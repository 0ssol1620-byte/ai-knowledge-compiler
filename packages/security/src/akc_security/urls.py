"""SSRF-safe URL policy with explicit DNS results and redirect revalidation."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from akc_cir import ContractModel

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)


class UrlValidationResult(ContractModel):
    normalized_url: str
    hostname_ascii: str
    port: int
    resolved_ips: tuple[str, ...]


class UnsafeUrlError(ValueError):
    pass


def _normalized_parts(url: str) -> tuple[SplitResult, str]:
    if len(url) > 2048:
        raise UnsafeUrlError("url_too_long")
    if any(ord(character) < 0x20 for character in url):
        raise UnsafeUrlError("url_contains_control_character")
    parts = urlsplit(url)
    if parts.scheme.casefold() != "https":
        raise UnsafeUrlError("https_required")
    if not parts.netloc or not parts.hostname:
        raise UnsafeUrlError("hostname_required")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("credentials_forbidden")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("invalid_port") from exc
    if port not in {None, 443}:
        raise UnsafeUrlError("port_forbidden")
    hostname = parts.hostname.rstrip(".").casefold()
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise UnsafeUrlError("hostname_blocked")
    try:
        hostname_ascii = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("hostname_invalid") from exc
    if len(hostname_ascii) > 253:
        raise UnsafeUrlError("hostname_too_long")
    try:
        ipaddress.ip_address(hostname_ascii)
    except ValueError:
        labels = hostname_ascii.split(".")
        if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
            raise UnsafeUrlError("hostname_invalid") from None
    normalized_host = f"[{hostname_ascii}]" if ":" in hostname_ascii else hostname_ascii
    normalized = SplitResult(
        scheme="https",
        netloc=normalized_host if port is None else f"{normalized_host}:{port}",
        path=parts.path or "/",
        query=parts.query,
        fragment="",
    )
    return normalized, hostname_ascii


def _validate_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise UnsafeUrlError("dns_result_invalid") from exc
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UnsafeUrlError("dns_result_not_public")
    return address.compressed


def validate_resolved_url(url: str, resolved_ips: Iterable[str]) -> UrlValidationResult:
    parts, hostname = _normalized_parts(url)
    addresses = tuple(sorted({_validate_ip(value) for value in resolved_ips}))
    if not addresses:
        raise UnsafeUrlError("dns_result_required")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if literal.compressed not in addresses:
            raise UnsafeUrlError("literal_ip_resolution_mismatch")
    return UrlValidationResult(
        normalized_url=urlunsplit(parts),
        hostname_ascii=hostname,
        port=parts.port or 443,
        resolved_ips=addresses,
    )


def validate_redirect_chain(
    chain: Iterable[tuple[str, Iterable[str]]],
    *,
    max_redirects: int = 5,
) -> tuple[UrlValidationResult, ...]:
    candidates = tuple(chain)
    if not candidates:
        raise UnsafeUrlError("empty_redirect_chain")
    if len(candidates) - 1 > max_redirects:
        raise UnsafeUrlError("too_many_redirects")
    return tuple(validate_resolved_url(url, addresses) for url, addresses in candidates)
