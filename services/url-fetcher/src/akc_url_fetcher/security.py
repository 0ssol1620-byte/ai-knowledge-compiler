"""Secret-safe URL normalization and authenticated encryption."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from akc_url_fetcher.fetcher import UrlFetchError


@dataclass(frozen=True, slots=True)
class ProtectedUrl:
    ciphertext: bytes
    canonical_url: str
    query_hmac: str | None


def _normalize_url(value: str) -> tuple[str, str, str]:
    if (
        not value
        or len(value) > 2048
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise UrlFetchError("URL_FETCH_URL_INVALID")
    parsed = urlsplit(value)
    raw_host = (parsed.hostname or "").rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not raw_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise UrlFetchError("URL_FETCH_URL_INVALID")
    try:
        try:
            host = ipaddress.ip_address(raw_host).compressed
        except ValueError:
            host = raw_host.encode("idna").decode("ascii").casefold()
        port = parsed.port or 443
        decoded_path = unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, UnicodeError, ValueError) as exc:
        raise UrlFetchError("URL_FETCH_URL_INVALID") from exc
    if port != 443 or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in decoded_path
    ):
        raise UrlFetchError("URL_FETCH_PORT_FORBIDDEN" if port != 443 else "URL_FETCH_URL_INVALID")
    # Preserve valid URL separators and percent-encode unsafe Unicode/control
    # forms into one deterministic representation before encryption.
    path = quote(parsed.path or "/", safe="/:@!$&'()*+,;=-._~%")
    netloc = f"[{host}]" if ":" in host else host
    normalized = urlunsplit(("https", netloc, path, parsed.query, ""))
    canonical = urlunsplit(("https", netloc, path, "", ""))
    return normalized, canonical, parsed.query


class UrlSecretCodec:
    """Encrypt full URLs and expose only a query-free identifier."""

    def __init__(self, *, encryption_key: str, query_hmac_secret: bytes) -> None:
        try:
            self._cipher = Fernet(encryption_key.encode("ascii"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("URL encryption key must be Fernet-compatible") from exc
        if len(query_hmac_secret) < 32:
            raise ValueError("URL query HMAC secret must contain at least 32 bytes")
        self._query_hmac_secret = query_hmac_secret

    def protect(self, value: str) -> ProtectedUrl:
        normalized, canonical, query = _normalize_url(value)
        query_digest = (
            hmac.new(
                self._query_hmac_secret,
                b"akc-url-query-v1\0" + query.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if query
            else None
        )
        return ProtectedUrl(
            ciphertext=self._cipher.encrypt(normalized.encode("utf-8")),
            canonical_url=canonical,
            query_hmac=query_digest,
        )

    def reveal(self, ciphertext: bytes) -> str:
        try:
            value = self._cipher.decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise UrlFetchError("URL_FETCH_SECRET_INVALID") from exc
        normalized, _, _ = _normalize_url(value)
        if not hmac.compare_digest(value.encode("utf-8"), normalized.encode("utf-8")):
            raise UrlFetchError("URL_FETCH_SECRET_INVALID")
        return value
