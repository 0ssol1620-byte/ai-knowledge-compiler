"""Isolated, SSRF-hardened URL ingestion primitives."""

from .fetcher import (
    FetchPolicy,
    FetchResult,
    SecureUrlFetcher,
    UrlFetchError,
)
from .security import ProtectedUrl, UrlSecretCodec

__all__ = [
    "FetchPolicy",
    "FetchResult",
    "ProtectedUrl",
    "SecureUrlFetcher",
    "UrlFetchError",
    "UrlSecretCodec",
]
