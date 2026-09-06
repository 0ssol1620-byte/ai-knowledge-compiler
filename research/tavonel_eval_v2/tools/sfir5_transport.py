#!/usr/bin/env python3
"""SFIR5's transport: paced, and observing on every family. INC-V2-101, INC-V2-102.

SFIR5 changes exactly two things about SFIR4, both of them transport. The
scientific question is carried forward by REFERENCE, not by copy: SFIR5 runs
`probe_sfir4_capacity.probe_capacity` against SFIR4's own frozen charter, so the
family definitions, roots, inclusion rules, capacity criterion, C_f threshold,
Q_f equation, caps, salt, identity rules, scorer, acceptance logic and endpoint
definitions are not re-declared anywhere here. They are the same bytes, verified
by the same code, and `probe_capacity` re-checks its own sha against that charter
on every run. A copy could drift; a reference cannot.

## Change 1 -- pacing (INC-V2-101)

SFIR4 stopped because ~90 unpaced Wikimedia requests exhausted a 5-retry budget:
the endpoint admits about ten requests per sixty-second window and the frozen
total wait was 180 seconds.

SFIR4's `maximum_retries_per_request` (5) and `MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS`
(180) are NOT touched, here or anywhere. Raising them is the one repair the
founder's ruling and this study's own standard both refuse: a budget chosen after
watching a run fail is chosen partly by the failure. Pacing is a different kind
of change -- it does not decide how much throttling to tolerate, it keeps the
request pattern inside what the endpoint already permits, so the frozen budget is
not stressed rather than enlarged. If pacing is wrong, those bounds still stop
the run, which is the property that makes it safe to leave them alone.

Measured from the live endpoint BEFORE SFIR5 was designed, with a cool-down
between arms so one trial's quota could not bleed into the next:

    delay 0s -> 10 ok,  2 throttled
    delay 2s -> 10 ok,  2 throttled
    delay 5s -> 11 ok,  1 throttled
    delay 7s -> 20 ok,  0 throttled   (over 150s)

Spacing below about six seconds does not help, so the limit is a quota per
roughly-sixty-second window rather than a per-request rate. Admissible for
designing a successor because it measures the ENDPOINT: no candidate counted, no
threshold evaluated, no cohort read.

The delay is a frozen constant per host, never tuned during a run. A transport
that widened its own spacing when throttled would choose its parameters from the
data it is collecting. When the server sends `Retry-After` that is obeyed -- the
server's number, not ours -- and it is the only thing that moves.

## Change 2 -- every family is observed (INC-V2-102)

In SFIR4, `_observe` is the only thing that writes to the hash-chained response
ledger, and it has exactly one caller: `git_docs`. eCFR and Wikipedia reach the
network through `legacy_fetch -> _http_json`, which discards the observation.

Measured, not inferred: a full eCFR family call against SFIR4's transport records
**zero** ledger observations.

So SFIR4's response evidence covered one family of three, while the census
receipt presented itself as carrying a response-evidence chain. The consistency
check cannot catch it -- absent rows produce absent aggregates, and the two agree
perfectly. That is the INC-V2-036 defect class exactly: a check whose failure is
impossible because the thing it checks is not there.

SFIR5 routes the legacy families through `_observe` as well, so all three appear
in one chain, and `require_family_coverage` below refuses a census whose ledger
is missing a family that produced candidates.
"""

from __future__ import annotations

import sys
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir3_capacity as legacy_metadata  # noqa: E402
import probe_sfir4_capacity as probe4  # noqa: E402

SCHEMA = "tavonel.sfir5.transport_freeze.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5"

#: Minimum seconds between two requests to the same HOST -- a quota is a property
#: of the service, not of our loop, so the git and eCFR lanes are not slowed by
#: Wikimedia's limit and Wikimedia is not sped up by theirs.
HOST_MIN_INTERVAL_SECONDS: dict[str, float] = {
    "en.wikipedia.org": 7.0,
    "api.github.com": 0.5,
    "www.ecfr.gov": 0.5,
}

#: For any host not named above: paced by default rather than unpaced by omission.
DEFAULT_MIN_INTERVAL_SECONDS = 1.0

#: A finite ceiling on the whole census, frozen before the run. Generous on
#: purpose -- the point is to bound the run, not to squeeze it back under a
#: number a previous failure suggested.
MAX_TOTAL_WALL_CLOCK_SECONDS = 6 * 60 * 60

#: A hard cap on requests that actually left the machine, independent of the
#: per-root and global caps SFIR4 already enforces on what the algorithm asks for.
MAX_TOTAL_REQUESTS = 12_000

#: One request in flight per host. This transport is single-threaded, so it is a
#: statement a future change must keep rather than a knob.
MAX_CONCURRENT_REQUESTS_PER_HOST = 1


class TransportBudgetExceeded(RuntimeError):
    """A frozen transport bound was reached. Terminal, not retryable."""


class FamilyCoverageRefused(RuntimeError):
    """The response ledger is missing a family that produced candidates."""


class PacedObservingTransport(probe4.LiveMetadataTransport):
    """SFIR4's transport, paced per host, observing on every family.

    Subclassed rather than composed, and constructed with NO injected fetcher,
    because `LiveMetadataTransport` sets `_live_transport = fetch_json is
    _http_json`. Passing a wrapper -- the obvious way to add pacing -- would flip
    that to False and make every observation synthesised, which
    `require_observed_census` refuses at seal time. The pacing therefore goes
    around `_observe`, not around the fetcher.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._sleep = sleep
        self._started = clock()
        self._last_request_at: dict[str, float] = {}
        self.requests_made = 0
        self.paced_seconds = 0.0
        self.per_host_requests: dict[str, int] = {}
        self._current: tuple[str, str] = ("", "")

        def legacy_fetch(url: str) -> Mapping[str, Any] | list[Any]:
            family, root_id = self._current
            try:
                return self._observe(family, root_id, url)
            except probe4.RootUnavailable as error:
                raise legacy_metadata.RootUnavailable(error.status, error.response_ref) from error
            except probe4.RateLimited as error:
                raise legacy_metadata.RateLimited(str(error.retry_after_seconds)) from error

        # replaces the closure built by super().__init__, which reached the
        # network without recording anything
        self._legacy = legacy_metadata.LiveMetadataTransport(legacy_fetch)

    # -- bounds ----------------------------------------------------------
    def _check_budgets(self) -> None:
        elapsed = self._clock() - self._started
        if elapsed > MAX_TOTAL_WALL_CLOCK_SECONDS:
            raise TransportBudgetExceeded(
                "census exceeded the frozen wall-clock budget of "
                f"{MAX_TOTAL_WALL_CLOCK_SECONDS}s after {elapsed:.0f}s"
            )
        if self.requests_made >= MAX_TOTAL_REQUESTS:
            raise TransportBudgetExceeded(
                f"census reached the frozen request cap of {MAX_TOTAL_REQUESTS}"
            )

    # -- pacing ----------------------------------------------------------
    @staticmethod
    def host_of(url: str) -> str:
        return (urllib.parse.urlparse(url).hostname or "").lower()

    @staticmethod
    def interval_for(host: str) -> float:
        return HOST_MIN_INTERVAL_SECONDS.get(host, DEFAULT_MIN_INTERVAL_SECONDS)

    def _pace(self, url: str) -> None:
        self._check_budgets()
        host = self.host_of(url)
        previous = self._last_request_at.get(host)
        if previous is not None:
            wait = self.interval_for(host) - (self._clock() - previous)
            if wait > 0:
                self._sleep(wait)
                self.paced_seconds += wait
        # stamped AFTER the wait and BEFORE the call, so a slow response does not
        # shorten the gap before the next one
        self._last_request_at[host] = self._clock()
        self.requests_made += 1
        self.per_host_requests[host] = self.per_host_requests.get(host, 0) + 1

    # -- the two overrides ------------------------------------------------
    def _observe(self, family: str, root_id: str, url: str) -> Mapping[str, Any] | list[Any]:
        self._pace(url)
        return super()._observe(family, root_id, url)

    def __call__(self, family: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        # remembered so `legacy_fetch`, which the legacy adapter calls with a URL
        # and nothing else, can record against the right family and root
        self._current = (family, str(request.get("expected_discovery_root_id", "")))
        return super().__call__(family, request)

    def summary(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "requests_made": self.requests_made,
            "per_host_requests": dict(sorted(self.per_host_requests.items())),
            "seconds_spent_pacing": round(self.paced_seconds, 3),
            "wall_clock_seconds": round(self._clock() - self._started, 3),
            "frozen_bounds": {
                "host_min_interval_seconds": dict(HOST_MIN_INTERVAL_SECONDS),
                "default_min_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS,
                "max_total_wall_clock_seconds": MAX_TOTAL_WALL_CLOCK_SECONDS,
                "max_total_requests": MAX_TOTAL_REQUESTS,
                "max_concurrent_requests_per_host": MAX_CONCURRENT_REQUESTS_PER_HOST,
            },
        }


def require_family_coverage(
    ledger_families: set[str], families_with_candidates: set[str]
) -> dict[str, Any]:
    """Refuse a census whose response ledger is missing a family.

    The check SFIR4 could not fail. A family that never records leaves no rows,
    and no rows means no aggregate to disagree with -- so the consistency check
    passes while two thirds of the census carries no response evidence at all.
    This compares the ledger against what the CENSUS said it found, which is the
    one thing that cannot be satisfied by silence.
    """
    missing = sorted(families_with_candidates - ledger_families)
    if missing:
        raise FamilyCoverageRefused(
            "the response ledger records no observation for "
            f"{', '.join(missing)}, but the census reports candidates there. "
            "A census cannot carry response evidence for a family it never "
            "observed (INC-V2-102)."
        )
    return {
        "families_in_ledger": sorted(ledger_families),
        "families_with_candidates": sorted(families_with_candidates),
        "covered": True,
    }
