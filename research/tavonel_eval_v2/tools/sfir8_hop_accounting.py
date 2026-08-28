#!/usr/bin/env python3
"""Count what the provider charges, not what we think we asked for.

SFIR7 measured a divergence it could not explain: our counter said at most 4,800
Git requests and GitHub charged 5,000. Redirect following was the obvious
suspect, because a roster deposited in January 2020 had nine of fifty addresses
renamed by 2026 and `urllib`'s default opener follows a 301 silently. Obvious is
not measured, and INC-V2-119 recorded the suspicion as a suspicion.

**This module measures instead of theorising.** GitHub returns
`x-ratelimit-remaining` on every response, including the ones it serves at the
end of a redirect chain. The drop in that header across a single logical request
*is* what the provider charged for it -- not an inference from redirect counts,
not a model of GitHub's accounting, the number GitHub itself reports. A logical
request that costs two is visible as a drop of two, whatever caused it.

Three counts are kept apart, because SFIR7's whole problem was that two of them
were conflated:

    logical_requests   what the traversal algorithm asked for
    network_hops       HTTP responses actually received, redirects included
    provider_charged   what GitHub's own header says it deducted

`provider_charged` is the one that must be compared against a rate limit.
`logical_requests` is the one a traversal bound should govern. They are not the
same number and SFIR7 proved it the expensive way.

Development instrument. SFIR8 is a calibration study and nothing here produces a
capacity claim.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"


@dataclass
class Hop:
    """One HTTP response actually received."""

    url: str
    status: int
    redirected_to: str | None = None


@dataclass
class RequestAccounting:
    """What one logical request cost, by all three measures."""

    url: str
    final_url: str
    status: int
    hops: list[Hop] = field(default_factory=list)
    remaining_before: int | None = None
    remaining_after: int | None = None
    used_after: int | None = None
    body: Any = None

    @property
    def network_hops(self) -> int:
        return len(self.hops)

    @property
    def provider_charged(self) -> int | None:
        """What GitHub says it deducted. `None` when the headers were absent."""
        if self.remaining_before is None or self.remaining_after is None:
            return None
        return self.remaining_before - self.remaining_after

    @property
    def redirected(self) -> bool:
        return any(hop.redirected_to for hop in self.hops)


class _CountingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Record every redirect this opener follows, rather than following silently."""

    def __init__(self) -> None:
        self.recorded: list[Hop] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.recorded.append(Hop(url=req.full_url, status=int(code), redirected_to=newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HopCountingFetcher:
    """A GitHub fetcher that reports all three counts for every request.

    It deliberately does NOT disable redirect following. SFIR7's traversal
    followed redirects and its measurements are what SFIR8 is calibrating
    against; an instrument that stopped following them would be measuring a
    different thing. The point is to see them, not to prevent them.
    """

    USER_AGENT = "TAVONEL-SFIR8-hop-accounting/1.0"

    def __init__(self) -> None:
        self.requests: list[RequestAccounting] = []
        self._last_remaining: int | None = None

    def totals(self) -> dict[str, Any]:
        charged = [r.provider_charged for r in self.requests if r.provider_charged is not None]
        return {
            "logical_requests": len(self.requests),
            "network_hops": sum(r.network_hops for r in self.requests),
            "provider_charged": sum(charged),
            "requests_with_provider_accounting": len(charged),
            "requests_that_redirected": sum(1 for r in self.requests if r.redirected),
            "requests_charged_more_than_one": sum(1 for c in charged if c > 1),
            "why_three_counts": (
                "logical is what the algorithm asked for and is what a traversal "
                "bound should govern; hops are responses actually received; charged "
                "is what the provider deducted and is the only one comparable with a "
                "rate limit. SFIR7 conflated the first and the last and lost four runs."
            ),
        }

    def fetch(self, url: str) -> RequestAccounting:
        handler = _CountingRedirectHandler()
        opener = urllib.request.build_opener(handler)
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310

        accounting = RequestAccounting(
            url=url, final_url=url, status=0, remaining_before=self._last_remaining
        )
        try:
            with opener.open(request, timeout=60) as response:
                accounting.final_url = response.geturl()
                accounting.status = int(getattr(response, "status", 200) or 200)
                accounting.remaining_after = _header_int(response.headers, "x-ratelimit-remaining")
                accounting.used_after = _header_int(response.headers, "x-ratelimit-used")
                accounting.body = _parse(response.read())
        except urllib.error.HTTPError as error:
            accounting.status = int(error.code)
            accounting.remaining_after = _header_int(error.headers, "x-ratelimit-remaining")
            accounting.used_after = _header_int(error.headers, "x-ratelimit-used")

        #: the redirects the handler saw, then the response that ended the chain
        accounting.hops = [
            *handler.recorded,
            Hop(url=accounting.final_url, status=accounting.status),
        ]
        self._last_remaining = accounting.remaining_after
        self.requests.append(accounting)
        return accounting


def _parse(raw: bytes) -> Any:
    """Keep the parsed body alongside the counts.

    An earlier draft discarded it and rationalised the discard as keeping a
    counting instrument free of content responsibility. That was tidy-sounding
    and wrong: the caller then had no way to reach a repository's default branch
    without issuing a second, separately counted request for bytes it had
    already paid for. Counting and returning are not in tension.
    """
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _header_int(headers: Any, name: str) -> int | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def prime(fetcher: HopCountingFetcher) -> None:
    """Read the limit once so the first real request has a `remaining_before`.

    `/rate_limit` is not charged, so this establishes the baseline for free. A
    first request with no baseline would report `provider_charged` as None and
    quietly drop out of the totals, which is the sort of silent omission that
    turns a measurement into an estimate.
    """
    fetcher.fetch("https://api.github.com/rate_limit")
    #: that call is itself uncharged, so it must not sit in the sample
    fetcher.requests.pop()


def dump(fetcher: HopCountingFetcher) -> list[dict[str, Any]]:
    return [
        {
            "url": r.url,
            "final_url": r.final_url,
            "status": r.status,
            "redirected": r.redirected,
            "network_hops": r.network_hops,
            "provider_charged": r.provider_charged,
            "remaining_before": r.remaining_before,
            "remaining_after": r.remaining_after,
            "hop_chain": [
                {"url": h.url, "status": h.status, "redirected_to": h.redirected_to}
                for h in r.hops
            ],
        }
        for r in fetcher.requests
    ]


__all__ = [
    "Hop",
    "HopCountingFetcher",
    "RequestAccounting",
    "dump",
    "prime",
]


if __name__ == "__main__":  # pragma: no cover - manual probe
    f = HopCountingFetcher()
    prime(f)
    f.fetch("https://api.github.com/repos/facebook/react")
    print(json.dumps({"totals": f.totals(), "requests": dump(f)}, indent=1))
