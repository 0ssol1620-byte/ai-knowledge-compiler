#!/usr/bin/env python3
"""Reconcile per-request provider charges against the provider's own global counter.

SFIR7 left 240 provider charges unattributed. That number happens to equal
`MAX_GIT_API_REQUESTS_PER_ROOT`, and a numeric coincidence is a hypothesis and
nothing more -- so it is not concluded from, here or anywhere.

Instead the question is instrumented so the next run answers it. Three sums are
taken independently over the same window of work:

    logical_request_count      what the caller asked for
    network_hop_count          responses actually received
    per_request_charge_sum     the per-response `x-ratelimit-remaining` deltas

and one more from outside that window entirely:

    provider_used_delta        `/rate_limit` read before and after

`/rate_limit` is not itself charged, so it is a free external witness. If the sum
of per-response deltas equals the global delta, our accounting is complete and a
budget can be denominated in it. If it does not, the difference is real and is
recorded as `UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA` -- **not** classified. A
secondary limit, a provider-side charge we cannot see, and another process
holding the same credential all produce the same arithmetic, and this module
cannot tell them apart.

**Contamination is bounded, not assumed away.** The probe reads the global
counter immediately before and after its own work, but the credential is not
provably exclusive to this process, so a non-zero delta cannot be attributed with
certainty even to us. That is recorded as a limitation rather than argued away.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"


@dataclass(frozen=True, slots=True)
class GlobalReading:
    """A free read of the provider's own counter."""

    limit: int
    remaining: int
    used: int
    reset_epoch: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "used": self.used,
            "reset_epoch": self.reset_epoch,
        }


def read_global(opener: Any = None) -> GlobalReading:
    """`/rate_limit` costs no quota, so it can witness without disturbing."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TAVONEL-SFIR8-provider-accounting/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        "https://api.github.com/rate_limit", headers=headers
    )
    with (opener or urllib.request.urlopen)(request, timeout=30) as response:
        core = json.load(response)["resources"]["core"]
    return GlobalReading(
        limit=int(core["limit"]),
        remaining=int(core["remaining"]),
        used=int(core["used"]),
        reset_epoch=int(core["reset"]),
    )


def reconcile(
    *,
    before: GlobalReading,
    after: GlobalReading,
    logical_request_count: int,
    network_hop_count: int,
    per_request_charge_sum: int,
    credential_exclusivity_established: bool = False,
) -> dict[str, Any]:
    """Compare the three internal sums with the one external witness."""
    window_reset = after.reset_epoch != before.reset_epoch
    provider_used_delta = None if window_reset else after.used - before.used
    unattributed = (
        None if provider_used_delta is None else provider_used_delta - per_request_charge_sum
    )

    return {
        "protocol_id": PROTOCOL_ID,
        "global_before": before.as_dict(),
        "global_after": after.as_dict(),
        "rate_window_reset_mid_measurement": window_reset,
        "counts": {
            "logical_request_count": logical_request_count,
            "network_hop_count": network_hop_count,
            "per_request_charge_sum": per_request_charge_sum,
            "provider_used_delta": provider_used_delta,
        },
        "hops_equal_charges": network_hop_count == per_request_charge_sum,
        "logical_equals_charges": logical_request_count == per_request_charge_sum,
        "UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA": unattributed,
        "accounting_is_complete": unattributed == 0,
        "what_a_nonzero_delta_does_not_establish": (
            "which of three things caused it. A secondary rate limit, a provider-side "
            "charge our per-response headers do not expose, and another process "
            "holding the same credential all produce identical arithmetic. This "
            "module records the difference and refuses to classify it."
        ),
        "limitations": _limitations(window_reset, credential_exclusivity_established),
        "why_rate_limit_is_a_valid_witness": (
            "/rate_limit is not charged against the quota it reports, so reading it "
            "before and after does not perturb the measurement it is witnessing"
        ),
    }


def _limitations(window_reset: bool, exclusivity: bool) -> list[str]:
    limitations: list[str] = []
    if window_reset:
        limitations.append(
            "the rate window reset between the two global readings, so `used` is not "
            "comparable across them and no delta was computed. This is a refusal to "
            "measure, not a measurement of zero."
        )
    if not exclusivity:
        limitations.append(
            "exclusive use of the credential during the measurement was not "
            "established, so a non-zero delta cannot be attributed to this process "
            "with certainty. Recorded rather than argued away."
        )
    if not limitations:
        limitations.append(
            "none identified: the window did not reset and credential exclusivity was "
            "asserted by the caller"
        )
    return limitations
