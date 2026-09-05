"""Read-only JSON access to huggingface.co and api.github.com.

Rules that are contract, not style:

- Only ``huggingface.co`` and ``api.github.com`` are reachable. Any other host
  raises instead of being fetched.
- ``HF_TOKEN`` is read from the environment ONLY after a public request answers
  401 or 429, is never logged, never echoed and never written into a payload.
- Every response body is recorded verbatim into a fixture directory when one is
  given, so ``--offline --fixtures <dir>`` reproduces a resolution byte for byte.
- No silent fallback: a request that cannot be satisfied raises
  ``SourceUnavailableError``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from arena.registry.errors import SourceUnavailableError

ALLOWED_HOSTS: frozenset[str] = frozenset({"huggingface.co", "api.github.com"})
USER_AGENT = "tavonel-arena-registry/1.0 (+read-only campaign resolution)"
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9]+")
_SLUG_MAX = 80
_TIMEOUT_SECONDS = 30.0


def fixture_key(url: str) -> str:
    """Deterministic, filesystem-safe, collision-resistant fixture file stem."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    slug = _SLUG_UNSAFE.sub("_", url.removeprefix("https://")).strip("_")
    return f"{slug[:_SLUG_MAX].rstrip('_')}__{digest}"


def require_allowed_host(url: str) -> str:
    """Return the host of ``url``, raising when it is outside the allow list."""
    host = urllib.parse.urlparse(url).netloc
    if host not in ALLOWED_HOSTS:
        raise SourceUnavailableError(
            f"host {host!r} is not in the registry allow list {sorted(ALLOWED_HOSTS)}"
        )
    return host


class FixtureStore:
    """Records and replays JSON payloads keyed by request URL."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, url: str) -> Path:
        return self.directory / f"{fixture_key(url)}.json"

    def has(self, url: str) -> bool:
        return self.path_for(url).is_file()

    def read(self, url: str) -> Any:
        path = self.path_for(url)
        if not path.is_file():
            raise SourceUnavailableError(f"no recorded fixture for {url} (expected {path})")
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, url: str, payload: Any) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(url)
        tmp = path.with_suffix(".json.tmp")
        text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return path


class JsonFetcher(Protocol):
    """Everything the resolver needs from the outside world."""

    def get_json(self, url: str) -> Any: ...


class OfflineFetcher:
    """Replays recorded fixtures. Never opens a socket."""

    def __init__(self, store: FixtureStore) -> None:
        self._store = store

    def get_json(self, url: str) -> Any:
        require_allowed_host(url)
        return self._store.read(url)


class CachedFetcher:
    """Serves a URL from a recorded fixture when one exists, else fetches it live.

    This is a cache, not a fallback. A URL with no fixture is fetched live and a
    live failure raises exactly as it would without the cache - nothing is
    skipped and no value is invented. ``cache_hits`` names every URL that was
    replayed, so a run can say which half of its inputs was re-read today.
    """

    def __init__(self, store: FixtureStore, live: JsonFetcher) -> None:
        self._store = store
        self._live = live
        self._cache_hits: list[str] = []

    @property
    def cache_hits(self) -> tuple[str, ...]:
        return tuple(self._cache_hits)

    def get_json(self, url: str) -> Any:
        require_allowed_host(url)
        if self._store.has(url):
            self._cache_hits.append(url)
            return self._store.read(url)
        return self._live.get_json(url)


class HttpFetcher:
    """Live read-only fetcher for the two allowed hosts."""

    def __init__(self, record_to: FixtureStore | None = None) -> None:
        self._record_to = record_to
        self._token_used = False

    @property
    def token_used(self) -> bool:
        """True when an authenticated retry was needed. The value is never exposed."""
        return self._token_used

    def _open(self, url: str, token: str | None) -> bytes:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # S310 is suppressed because the scheme is checked to be https by the caller
        # and the host is checked against ALLOWED_HOSTS before either line runs.
        request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            body: bytes = response.read()
        return body

    def get_json(self, url: str) -> Any:
        require_allowed_host(url)
        if not url.startswith("https://"):
            raise SourceUnavailableError(f"registry fetches are https-only, got {url!r}")
        try:
            body = self._open(url, None)
        except urllib.error.HTTPError as first_error:
            if first_error.code not in (401, 429):
                raise SourceUnavailableError(
                    f"GET {url} failed with HTTP {first_error.code}"
                ) from first_error
            token = os.environ.get("HF_TOKEN") if "huggingface.co" in url else None
            if not token:
                raise SourceUnavailableError(
                    f"GET {url} failed with HTTP {first_error.code} and no anonymous retry "
                    "is possible (HF_TOKEN is not set)"
                ) from first_error
            try:
                body = self._open(url, token)
            except urllib.error.HTTPError as second_error:
                raise SourceUnavailableError(
                    f"GET {url} failed with HTTP {second_error.code} even after an "
                    "authenticated retry"
                ) from second_error
            self._token_used = True
        except urllib.error.URLError as network_error:
            raise SourceUnavailableError(f"GET {url} could not be reached") from network_error

        try:
            payload: Any = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
            raise SourceUnavailableError(f"GET {url} did not return JSON") from decode_error
        if self._record_to is not None:
            self._record_to.write(url, payload)
        return payload


__all__ = [
    "ALLOWED_HOSTS",
    "CachedFetcher",
    "FixtureStore",
    "HttpFetcher",
    "JsonFetcher",
    "OfflineFetcher",
    "fixture_key",
    "require_allowed_host",
]
