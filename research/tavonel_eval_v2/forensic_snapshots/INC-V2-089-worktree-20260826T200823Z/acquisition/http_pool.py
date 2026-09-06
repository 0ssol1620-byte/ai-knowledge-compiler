"""Host-scoped concurrency, backoff and rate-limit handling for the parallel walk.

The serial walk paced itself with a fixed sleep after every request. That is a
crude form of politeness and it is also why 2,271 lineages did not terminate:
the sleep applied to every host equally, so a slow provider set the pace for all
of them.

This replaces it with per-host budgets. Each host gets its own semaphore and its
own cooldown, so a provider that starts throttling stalls only the workers
touching that provider — a GitHub 403 must not stop an eCFR worker. That
property is the whole reason the pool exists and it is what
`test_a_throttled_host_does_not_block_another` checks.

Nothing here changes what is fetched. The URLs, the predicate and the ordering
belong to the frozen acquisition contract; this module only decides *when* a
request is allowed to leave.
"""

from __future__ import annotations

import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

#: Concurrency per host. Chosen for politeness against each provider's published
#: guidance, not tuned against observed yield.
HOST_LIMITS: dict[str, int] = {
    "api.github.com": 8,
    "raw.githubusercontent.com": 12,
    "www.ecfr.gov": 4,
    "en.wikipedia.org": 6,
    "data.sec.gov": 4,
    "www.sec.gov": 4,
}
DEFAULT_LIMIT = 4

#: A floor between consecutive requests to one host, in seconds. Per host, so a
#: strict provider cannot slow a permissive one.
HOST_MIN_INTERVAL: dict[str, float] = {
    "www.ecfr.gov": 0.20,
    "data.sec.gov": 0.12,
    "www.sec.gov": 0.12,
    "en.wikipedia.org": 0.05,
    "api.github.com": 0.05,
}
DEFAULT_MIN_INTERVAL = 0.05

MAX_ATTEMPTS = 5
BASE_BACKOFF = 0.75
MAX_BACKOFF = 60.0
#: A Retry-After longer than this is treated as "come back later", not slept on.
MAX_HONOURED_RETRY_AFTER = 120.0


class _HostState:
    def __init__(self, limit: int, interval: float) -> None:
        self.semaphore = threading.BoundedSemaphore(limit)
        self.interval = interval
        self.lock = threading.Lock()
        self.next_allowed = 0.0
        self.requests = 0
        self.throttles = 0
        self.retry_after_seconds = 0.0
        self.errors = 0


class HttpPool:
    """One pool for the whole run. Thread-safe, and the only place that sleeps."""

    def __init__(self) -> None:
        self._hosts: dict[str, _HostState] = {}
        self._lock = threading.Lock()

    def _state(self, host: str) -> _HostState:
        with self._lock:
            state = self._hosts.get(host)
            if state is None:
                state = _HostState(
                    HOST_LIMITS.get(host, DEFAULT_LIMIT),
                    HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL),
                )
                self._hosts[host] = state
            return state

    def _wait_turn(self, state: _HostState) -> None:
        while True:
            with state.lock:
                now = time.monotonic()
                if now >= state.next_allowed:
                    state.next_allowed = now + state.interval
                    return
                delay = state.next_allowed - now
            time.sleep(min(delay, 5.0))

    @staticmethod
    def _retry_after(error: Exception) -> float:
        header = getattr(getattr(error, "headers", None), "get", lambda _name: None)
        value = header("Retry-After") if header else None
        if not value:
            return 0.0
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def fetch(self, url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> bytes:
        """One GET, with the host's budget, its cooldown and bounded retries.

        Backoff is exponential with jitter. The jitter matters more than it looks:
        without it, every worker that hits one throttle retries in lockstep and
        reproduces the burst that caused it.
        """
        host = urllib.parse.urlparse(url).netloc
        state = self._state(host)
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            with state.semaphore:
                self._wait_turn(state)
                try:
                    request = urllib.request.Request(url, headers=headers or {})
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        with state.lock:
                            state.requests += 1
                        return response.read()
                except urllib.error.HTTPError as error:
                    last = error
                    throttled = error.code in (403, 429, 503)
                    wait = self._retry_after(error)
                    with state.lock:
                        state.requests += 1
                        if throttled:
                            state.throttles += 1
                            state.retry_after_seconds += wait
                        else:
                            state.errors += 1
                    if not throttled or error.code == 404:
                        raise
                except Exception as error:  # transport failure, retried
                    last = error
                    wait = 0.0
                    with state.lock:
                        state.errors += 1
            delay = min(MAX_BACKOFF, BASE_BACKOFF * (2**attempt)) + random.random() * 0.5
            if wait:
                delay = max(delay, min(wait, MAX_HONOURED_RETRY_AFTER))
            # the cooldown is pushed out for *every* worker on this host, not
            # only this one; a throttle is a property of the host, not the call.
            with state.lock:
                state.next_allowed = max(state.next_allowed, time.monotonic() + delay)
            time.sleep(min(delay, MAX_BACKOFF))
        raise RuntimeError("fetch failed after %d attempts: %s" % (MAX_ATTEMPTS, last))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            hosts = dict(self._hosts)
        return {
            host: {
                "requests": state.requests,
                "throttles": state.throttles,
                "errors": state.errors,
                "retry_after_seconds": round(state.retry_after_seconds, 2),
                "limit": HOST_LIMITS.get(host, DEFAULT_LIMIT),
                "min_interval": HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL),
            }
            for host, state in sorted(hosts.items())
        }


def install(pool: HttpPool, fetch_module: Any, github_module: Any, user_agent: str) -> None:
    """Route the frozen enumerators' transport through the pool.

    The enumerators are not reimplemented. They are the ones the serial walk used
    and they keep building the same URLs in the same order; only the function
    that carries the bytes is swapped, and the per-call sleeps are removed
    because the pool now owns pacing. A second enumeration implementation is
    exactly the defect INC-V2-007 and INC-V2-009 record.
    """
    import json  # noqa: PLC0415

    def pooled_fetch(url: str, *, retries: int = 3) -> bytes:
        """Same signature and same bytes-returning contract as the original."""
        del retries
        return pool.fetch(url, headers={"User-Agent": user_agent})

    def pooled_github(url: str, *, retries: int = 3) -> Any:
        del retries
        import os  # noqa: PLC0415

        headers = {"User-Agent": user_agent, "Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        return json.loads(pool.fetch(url, headers=headers))

    fetch_module.fetch = pooled_fetch
    fetch_module.PAUSE_SECONDS = 0.0
    github_module.gh = pooled_github
    github_module.PAUSE = 0.0
