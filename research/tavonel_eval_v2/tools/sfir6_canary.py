#!/usr/bin/env python3
"""SFIR6's pre-freeze live canary: does the repaired grammar actually work?

The red controls in `tests/test_sfir6_wikipedia.py` run against envelopes the
endpoint really sent, but they are still fixtures. This asks the live API the
repaired questions and checks the answers, once, before the charter is frozen.

**Why it cannot contaminate the study.** Three separate reasons, and any one of
them would be enough:

1. It reads a fixed list of pages chosen for being outside the thirty declared
   category roots. They are not a cohort; they are a grammar test.
2. It computes and emits **no candidate and no count**. Nothing it returns can be
   compared with `C_f`, because it never forms one. It checks response *shape*.
3. Its requests are not in the census, and its pages are excluded from the
   scientific denominator by construction -- the census enumerates category
   members, and this never asks a category anything.

So this is a measurement of the endpoint's grammar, admissible for designing an
instrument on the same footing as the pacing trials that motivated SFIR5: no
candidate counted, no threshold evaluated, no capacity root read.

**What it must establish**, in the founder's terms: the response contains the
expected page and revision objects, carries no MediaWiki error envelope, accounts
for every requested identity, completes its pagination, and does not silently
truncate -- with the request/response evidence chain intact throughout. HTTP 200
is not evidence of any of that, which is the entire reason SFIR6 exists.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
import sfir6_wikipedia as wiki  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402
from common import now  # noqa: E402

STEM = "sfir6-adapter-canary"
SCHEMA = "tavonel.sfir6.adapter_canary.v1"

#: Fixed, public, and deliberately outside the declared frame. Chosen so that no
#: reading of this canary can be mistaken for a reading of the cohort.
CANARY_PAGES: dict[str, int] = {
    "Cheese": 6784,
    "The Beatles": 21501,
    "Association football": 10568,
}

USER_AGENT = "TAVONEL-research-adapter-canary/1.0"
PACE_SECONDS = 7.0


def _fetch(url: str) -> tuple[Any, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        raw = response.read()
        return json.loads(raw), {
            "status": response.status,
            "observed_length": len(raw),
            "content_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }


def run(sleep=time.sleep) -> dict[str, Any]:
    """Ask the repaired questions and check every answer. Refuses on any gate."""
    checks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    page_ids = sorted(CANARY_PAGES.values())

    # --- pass 1 -------------------------------------------------------------
    url1 = wiki.latest_revision_url(page_ids)
    wiki.forbids_rvlimit_with_multiple_pages(url1)
    body1, seen1 = _fetch(url1)
    evidence.append({"url": url1, **seen1})
    query1 = wiki.require_protocol_success(body1, url=url1)
    wiki.require_batch_complete(body1, url=url1)
    accounting1 = wiki.require_every_identity_accounted(
        page_ids, list(query1.get("pages") or []), key="pageid", url=url1
    )
    checks.append(
        {
            "gate": "pass_1_batched_latest_revision",
            "transport_status": seen1["status"],
            "protocol_success": True,
            "batch_complete": True,
            "identities_accounted": accounting1,
            "carries_rvlimit": "rvlimit" in url1,
        }
    )

    pages = {int(p["pageid"]): p for p in query1["pages"] if not p.get("missing")}
    parents = {
        int(p["revisions"][0]["parentid"]): int(p["pageid"])
        for p in pages.values()
        if (p.get("revisions") or []) and p["revisions"][0].get("parentid")
    }
    if not parents:
        raise wiki.WikipediaSemanticIncomplete("no canary page yielded a parent revision")

    sleep(PACE_SECONDS)

    # --- pass 2 -------------------------------------------------------------
    url2 = wiki.parent_revision_url(sorted(parents))
    body2, seen2 = _fetch(url2)
    evidence.append({"url": url2, **seen2})
    query2 = wiki.require_protocol_success(body2, url=url2)
    wiki.require_batch_complete(body2, url=url2)
    resolved: dict[int, dict[str, Any]] = {}
    for page in query2.get("pages") or []:
        for revision in page.get("revisions") or []:
            resolved[int(revision["revid"])] = revision
    unresolved = sorted(set(parents) - set(resolved))
    if unresolved:
        raise wiki.WikipediaSemanticIncomplete(
            f"parent revisions requested but never resolved: {unresolved}"
        )
    checks.append(
        {
            "gate": "pass_2_batched_parent_revisions",
            "transport_status": seen2["status"],
            "protocol_success": True,
            "batch_complete": True,
            "parents_requested": len(parents),
            "parents_resolved": len(resolved),
        }
    )

    # --- the pairs the census would build -----------------------------------
    pairs = 0
    for page in pages.values():
        pair = wiki.pair_from(page, resolved)
        if pair is None:
            continue
        if not (pair["timestamp_before"] and pair["timestamp_after"]):
            raise wiki.WikipediaSemanticIncomplete("a resolved pair carries no timestamp")
        if pair["revision_before"] == pair["revision_after"]:
            raise wiki.WikipediaSemanticIncomplete("a pair resolves to one revision")
        if pair["timestamp_before"] >= pair["timestamp_after"]:
            raise wiki.WikipediaSemanticIncomplete("a pair is not chronologically ordered")
        pairs += 1
    checks.append(
        {
            "gate": "pair_construction",
            "pages_yielding_a_pair": pairs,
            "note": (
                "a count of CANARY pages only. It is not a candidate count and has no "
                "relationship to C_f for any family."
            ),
        }
    )

    # --- the defect itself, asserted against the live grammar ---------------
    broken = wiki.latest_revision_url(page_ids) + "&rvlimit=2"
    body3, seen3 = _fetch(broken)
    evidence.append({"url": broken, **seen3})
    refused = False
    try:
        wiki.require_protocol_success(body3, url=broken)
    except wiki.WikipediaProtocolError as error:
        refused = "invalidparammix" in str(error)
    if not refused:
        raise wiki.WikipediaSemanticIncomplete(
            "the endpoint no longer refuses the SFIR5 request shape; the premise of "
            "INC-V2-106 must be re-established before this canary can pass"
        )
    checks.append(
        {
            "gate": "sfir5_request_shape_still_refused_by_the_live_endpoint",
            "transport_status": seen3["status"],
            "http_status_was_success": seen3["status"] == 200,
            "protocol_layer_refused": True,
            "why_this_gate_exists": (
                "it proves the two layers really are independent, live rather than in a "
                "fixture: the transport succeeded and the protocol refused, in the same "
                "response."
            ),
        }
    )
    return {"checks": checks, "response_evidence": evidence}


def build(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "protocol_id": "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6",
        "state": "ADAPTER_CANARY_PASS",
        "purpose": (
            "verify the repaired MediaWiki grammar against the live endpoint before "
            "SFIR6 is frozen (INC-V2-106)"
        ),
        "canary_pages": dict(sorted(CANARY_PAGES.items())),
        "excluded_from_the_scientific_denominator": True,
        "why_it_cannot_contaminate": (
            "it emits no candidate and no count, reads no declared category root, and "
            "evaluates no threshold. It checks response shape. The pages are fixed, "
            "public and outside the thirty declared roots."
        ),
        "declared_roots_untouched": sorted(
            sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"]
        ),
        "checks": result["checks"],
        "response_evidence": result["response_evidence"],
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    try:
        result = run()
    except (wiki.WikipediaProtocolError, wiki.WikipediaSemanticIncomplete) as error:
        print(json.dumps({"state": "CANARY_REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    body = build(result)
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    written = protocol.write_immutable(NS / "receipts" / f"{STEM}.json", body)
    print(json.dumps({"state": body["state"], "path": written.as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
