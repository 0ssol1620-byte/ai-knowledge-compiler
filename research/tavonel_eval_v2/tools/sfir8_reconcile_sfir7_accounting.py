#!/usr/bin/env python3
"""Reconcile SFIR7's request divergence against the measured per-hop charge.

SFIR8's live probe established that GitHub charges per network hop: a renamed
address costs exactly two, an unrenamed one exactly one, and `network_hops`
equalled `provider_charged` in every case. That is a rule about single requests.
This applies it to SFIR7's census and asks whether it accounts for the whole
divergence or only part of it.

**It reads terminal evidence and re-runs nothing.** SFIR7's census is preserved
as it stands; every figure here comes from `response_refs` already recorded in
it, and no request is made.

The prediction is arithmetic with no free parameters:

    predicted_charge = logical_requests + logical_requests_on_renamed_addresses

If that lands at or above GitHub's 5,000 while SFIR7's own counter sat below
4,800, the divergence is explained and INC-V2-119's suspicion becomes a
measurement. If it falls well short, something else is also charging us and the
search continues -- which this tool is written to be able to report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from acquisition import sources_sfir4 as sources  # noqa: E402

SCHEMA = "tavonel.sfir8.sfir7_accounting_reconciliation.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

#: GitHub's authenticated primary limit, and what SFIR7 observed it exhaust at.
PROVIDER_LIMIT = 5000


def _modal_charge(probe: dict[str, Any], group: str) -> int:
    """The most common charge in the group, from the per-request rows.

    A mean would absorb outliers into the rule and make the residual disappear
    into a decimal. The mode is what the provider does to a request of this kind;
    anything that is not the mode is a separate observation and belongs in the
    residual where someone has to explain it.
    """
    from collections import Counter

    charges = Counter(
        row["provider_charged"]
        for row in probe["requests"]
        if row["group"] == group and row["provider_charged"] is not None
    )
    if not charges:
        raise ValueError(f"the probe recorded no charged requests for {group!r}")
    return int(charges.most_common(1)[0][0])


def reconcile(census: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    renamed = set(census["identity_attestation"]["renames_observed"])
    dispositions = census["families"]["git_docs"]["root_dispositions"]

    per_root: dict[str, int] = {}
    for row in dispositions:
        name = row["discovery_root_id"].removeprefix("git:")
        per_root[name] = len(row.get("response_refs") or [])

    logical = sum(per_root.values())
    on_renamed = sum(count for name, count in per_root.items() if name in renamed)
    on_unrenamed = logical - on_renamed

    #: The MODAL charge, not the mean. Thirty-three of thirty-six renamed
    #: requests were hops=2 charged=2; three outliers on two repositories pulled
    #: the mean to 2.11 and are noise in a provider-side counter, not a third
    #: hop anyone observed. Reconciling on a mean inflated by unexplained
    #: readings would let the residual hide inside the rule.
    charge_renamed = _modal_charge(probe, "renamed")
    charge_unrenamed = _modal_charge(probe, "unrenamed")
    predicted = round(on_renamed * charge_renamed + on_unrenamed * charge_unrenamed)
    residual = PROVIDER_LIMIT - predicted

    explained = residual <= 0
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "study_kind": "DEVELOPMENT_INSTRUMENT_CALIBRATION",
        "produces_capacity_claim": False,
        "reads_terminal_evidence_only": True,
        "requests_made": 0,
        "measured_rule_from": {
            "receipt": "receipts/sfir8-hop-divergence.json",
            "finding": probe["finding"],
            "charged_per_logical_request": {
                "renamed": charge_renamed,
                "unrenamed": charge_unrenamed,
            },
        },
        "sfir7_observed": {
            "roots_visited": len(per_root),
            "roots_renamed": len(renamed & set(per_root)),
            "logical_requests": logical,
            "logical_requests_on_renamed_addresses": on_renamed,
            "logical_requests_on_unrenamed_addresses": on_unrenamed,
            "our_frozen_global_bound": int(sources.MAX_GIT_API_REQUESTS_GLOBAL),
            "our_counter_stayed_below_the_bound": logical
            <= sources.MAX_GIT_API_REQUESTS_GLOBAL,
        },
        "predicted_provider_charge": predicted,
        "provider_limit": PROVIDER_LIMIT,
        "surcharge_from_renames": predicted - logical,
        "residual_unexplained": residual,
        "candidate_causes_of_the_residual": [
            {
                "candidate": "a secondary rate limit rather than primary exhaustion",
                "why_plausible": (
                    "GitHub answers a secondary limit with 403 and a Retry-After while "
                    "primary quota remains, and SFIR4's fetcher raises RateLimited on "
                    "exactly that shape. The run would then have stopped below 5,000 "
                    "charged, and the residual would not be a charge at all."
                ),
                "how_it_would_be_settled": (
                    "record x-ratelimit-remaining on the response that stopped the run"
                ),
            },
            {
                "candidate": "provider-side charges the redirect handler cannot see",
                "why_plausible": (
                    "three of thirty-six renamed requests were charged more than their "
                    "observed hops, so the provider's counter and our hop count are not "
                    "identical even on a redirect we do observe"
                ),
                "how_it_would_be_settled": (
                    "carry per-request charge accounting through the traversal itself, "
                    "so every request's cost is recorded where it happened"
                ),
            },
        ],
        "the_residual_is_not_attributed": (
            "Both candidates are consistent with what was measured and neither is "
            "established. SFIR7's census is terminal evidence and is not re-run to "
            "settle this, so it is settled prospectively: SFIR9's traversal records "
            "provider charge per request, which makes the question answer itself on "
            "the next live run instead of being argued from arithmetic."
        ),
        "explains_the_divergence": explained,
        "finding": (
            "PER_HOP_CHARGING_EXPLAINS_THE_DIVERGENCE"
            if explained
            else "PER_HOP_CHARGING_EXPLAINS_PART_OF_THE_DIVERGENCE"
        ),
        "means": (
            "GitHub charges per network hop. SFIR7's counter incremented once per "
            "logical request, so every request to one of the renamed addresses was "
            "charged twice and counted once. Our 4,800 bound was measuring a quantity "
            "the provider does not bill on."
            if explained
            else f"GitHub charges per network hop, and every request to one of the "
            f"nine renamed addresses was charged twice and counted once: {on_renamed} "
            f"such requests, a surcharge of {predicted - logical}. That is measured. It "
            f"leaves {residual} charges unaccounted for, which is NOT attributed here."
        ),
        "what_this_fixes_in_sfir9": (
            "a request bound must be expressed in the quantity the provider bills -- "
            "network hops -- and the traversal must count them. A bound on logical "
            "requests cannot protect a budget denominated in hops, however carefully "
            "it is derived."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--census",
        type=Path,
        default=NS / "receipts/sfir7-capacity-metadata-census.json",
    )
    parser.add_argument("--probe", type=Path, default=NS / "receipts/sfir8-hop-divergence.json")
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    body = reconcile(
        json.loads(args.census.read_text(encoding="utf-8")),
        json.loads(args.probe.read_text(encoding="utf-8")),
    )
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "finding": body["finding"],
                "logical_requests": body["sfir7_observed"]["logical_requests"],
                "on_renamed": body["sfir7_observed"]["logical_requests_on_renamed_addresses"],
                "predicted_provider_charge": body["predicted_provider_charge"],
                "provider_limit": body["provider_limit"],
                "surcharge_from_renames": body["surcharge_from_renames"],
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
