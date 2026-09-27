"""Shared plumbing for the Google adapters: auth abstraction, backoff, JSON GETs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0


class GoogleTokenProvider(Protocol):
    """Supplies a bearer token per call. Real issuance is a deployment step."""

    def token(self) -> str: ...


class StaticTokenProvider:
    """Tests and air-gapped deployments pin the token directly."""

    def __init__(self, value: str) -> None:
        self._value = value

    def token(self) -> str:
        return self._value


class GoogleAdapterError(RuntimeError):
    """One request failed after its retry budget."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def get_json(
    url: str,
    token_provider: GoogleTokenProvider,
    *,
    timeout: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET one JSON document with polite backoff on 429/5xx and Retry-After.

    Non-retryable 4xx raise immediately. Every attempt honors the server's
    ``Retry-After`` over our own exponential schedule.
    """
    delay = BASE_BACKOFF_SECONDS
    last_status: int | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url)  # noqa: S310 - caller-built base URL
        request.add_header("Authorization", f"Bearer {token_provider.token()}")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            headers = dict(exc.headers or {})
            retry_after = str(headers.get("Retry-After") or "")
            retryable = exc.code == 429 or exc.code >= 500
            if attempt == MAX_ATTEMPTS or not retryable:
                raise GoogleAdapterError(
                    f"GET {urllib.parse.urlsplit(url).path} failed (HTTP {exc.code})",
                    status=exc.code,
                ) from exc
            wait = float(retry_after) if retry_after.isdigit() else delay
            sleep(min(wait, MAX_BACKOFF_SECONDS))
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
        except urllib.error.URLError as exc:
            if attempt == MAX_ATTEMPTS:
                raise GoogleAdapterError(f"GET {url} failed: {exc.reason}") from exc
            sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
    raise GoogleAdapterError(f"GET {url} failed: retries exhausted", status=last_status)
