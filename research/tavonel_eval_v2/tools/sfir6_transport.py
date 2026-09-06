#!/usr/bin/env python3
"""SFIR6's transport: SFIR5's pacing and ledger, with Wikipedia repaired.

SFIR6 changes exactly one thing about SFIR5, and it is the Wikipedia adapter
(INC-V2-106). Everything else is inherited by subclassing rather than copying:
the per-host pacing, the frozen budgets, the response ledger that every family
writes to, and the family-coverage refusal.

Git and eCFR are untouched and still run through the modules SFIR4 froze. That
matters more than it looks: SFIR5 measured them, and re-measuring them under a
transport that had quietly changed their code path would make SFIR6's numbers
incomparable with SFIR5's for reasons unrelated to the repair.

The declared frame is carried forward exactly -- roots, caps, salt, ordering,
thresholds, identity rules. SFIR6 repairs an instrument. It does not redesign a
study, and `git_docs` in particular gains no root: adding one after seeing 293
would turn a confirmatory repair into an outcome-conditioned redesign, which is
the move the standing instruction forbids by name.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import probe_sfir4_capacity as probe4  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir5_transport as t5  # noqa: E402
import sfir6_wikipedia as wiki  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

SCHEMA = "tavonel.sfir6.transport_freeze.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6"

#: Two batched requests per fifty pages, plus category listing. The declared
#: frame needs roughly 500 Wikipedia requests rather than 4,500, which is what
#: lets a 7-second pace finish inside a finite budget.
MAX_TOTAL_WALL_CLOCK_SECONDS = 6 * 60 * 60


def _disposition(root_id: str, state: str, reason: str, proof: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "discovery_root_id": root_id,
        "state": state,
        "reason": reason,
        "traversal_proof": dict(proof),
    }


class SFIR6Transport(t5.PacedObservingTransport):
    """SFIR5's transport with `encyclopedia_wikipedia` served by the repaired adapter."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._wiki_seen: set[int] = set()

    def __call__(self, family: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if family != "encyclopedia_wikipedia":
            return super().__call__(family, request)
        self._current = (family, str(request.get("expected_discovery_root_id", "")))
        try:
            return self._wiki6(request)
        except probe4.TransportInterrupted as error:
            root = str(request["expected_discovery_root_id"])
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"transport-interrupted:{root}",
                "response_refs": [],
                "rate_limited": False,
                "transport_interrupted": True,
                "retry_after_seconds": error.retry_after_seconds,
            }
        except probe4.RateLimited as error:
            root = str(request["expected_discovery_root_id"])
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"rate-limited:{root}",
                "response_refs": [],
                "rate_limited": True,
                "retry_after_seconds": error.retry_after_seconds,
            }

    def _wiki6(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        categories = pool["category_roots"]
        if index >= len(categories):
            raise protocol.SFIR4Refused("Wikipedia cursor escaped the frozen roots")
        category = categories[index]
        root_id = sources.discovery_root_id("encyclopedia_wikipedia", category)
        if request.get("expected_discovery_root_id") != root_id:
            raise protocol.SFIR4Refused("Wikipedia request escaped frozen roots")
        next_cursor = str(index + 1) if index + 1 < len(categories) else None
        refs: list[str] = []
        proof: dict[str, Any] = {
            "algorithm": "CATEGORY_MEMBERS_THEN_TWO_PASS_BATCHED_REVISIONS",
            "category_requests": 0,
            "revision_requests": 0,
            "members_enumerated": 0,
            "members_selected": 0,
            "pages_absent_at_revision_time": 0,
            "pages_without_a_parent_revision": 0,
            "redirects_skipped": 0,
            "pairs_built": 0,
            "continuation_exhausted": False,
        }

        # --- category enumeration, with continuation ------------------------
        members: dict[int, str] = {}
        continuation: str | None = None
        for _page in range(pool["max_category_pages_per_root"]):
            url = wiki.category_url(
                category, size=pool["category_page_size"], continuation=continuation
            )
            refs.append(url)
            proof["category_requests"] += 1
            body = self._observe("encyclopedia_wikipedia", root_id, url)
            query = wiki.require_protocol_success(body, url=url)
            for row in query.get("categorymembers") or []:
                if isinstance(row, Mapping) and isinstance(row.get("pageid"), int):
                    members[int(row["pageid"])] = str(row.get("title") or "")
            following = (
                (body.get("continue") or {}).get("cmcontinue")
                if isinstance(body, Mapping)
                else None
            )
            if not following:
                proof["continuation_exhausted"] = True
                break
            continuation = str(following)
        proof["members_enumerated"] = len(members)
        if not proof["continuation_exhausted"]:
            return {
                "items": [],
                "next_cursor": next_cursor,
                "snapshot_id": f"zero:{root_id}:CATEGORY_PAGE_BOUND_BEFORE_CONTINUATION_EXHAUSTED",
                "response_refs": refs,
                "rate_limited": False,
                "root_disposition": _disposition(
                    root_id,
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "CATEGORY_PAGE_BOUND_BEFORE_CONTINUATION_EXHAUSTED",
                    proof,
                ),
            }

        # --- deterministic selection, unchanged from the frozen adapter -----
        ordered = sorted(members, key=lambda page_id: wiki.selection_rank(category, page_id))
        selected = [p for p in ordered if p not in self._wiki_seen][
            : pool["max_candidates_per_category"]
        ]
        proof["members_selected"] = len(selected)

        items: list[dict[str, Any]] = []
        for start in range(0, len(selected), wiki.MAX_IDS_PER_REQUEST):
            batch = selected[start : start + wiki.MAX_IDS_PER_REQUEST]

            url1 = wiki.latest_revision_url(batch)
            # Also defence in depth: `latest_revision_url` does not build an
            # rvlimit, so this cannot fire against today's code. It exists so a
            # future edit that reintroduces it is refused before it is sent.
            wiki.forbids_rvlimit_with_multiple_pages(url1)
            refs.append(url1)
            proof["revision_requests"] += 1
            body1 = self._observe("encyclopedia_wikipedia", root_id, url1)
            query1 = wiki.require_protocol_success(body1, url=url1)
            wiki.require_batch_complete(body1, url=url1)
            accounting = wiki.require_every_identity_accounted(
                batch, list(query1.get("pages") or []), key="pageid", url=url1
            )
            proof["pages_absent_at_revision_time"] += len(accounting["absent"])

            pages = {int(p["pageid"]): p for p in query1["pages"] if not p.get("missing")}
            wanted: dict[int, int] = {}
            for page_id, page in pages.items():
                revisions = page.get("revisions") or []
                if page.get("redirect") is True:
                    proof["redirects_skipped"] += 1
                    continue
                parent = revisions[0].get("parentid") if revisions else None
                if not parent:
                    proof["pages_without_a_parent_revision"] += 1
                    continue
                wanted[int(parent)] = page_id
            resolved: dict[int, Mapping[str, Any]] = {}
            if wanted:
                url2 = wiki.parent_revision_url(sorted(wanted))
                refs.append(url2)
                proof["revision_requests"] += 1
                body2 = self._observe("encyclopedia_wikipedia", root_id, url2)
                query2 = wiki.require_protocol_success(body2, url=url2)
                wiki.require_batch_complete(body2, url=url2)
                for page in query2.get("pages") or []:
                    for revision in page.get("revisions") or []:
                        resolved[int(revision["revid"])] = revision
                # Defence in depth, and honestly labelled as such: `pair_from`
                # refuses an unresolved parent per page, so this batch-level
                # check cannot currently be the thing that fires. It is kept for
                # the better error it gives and for the day the inner gate moves,
                # not counted as a guard this study has watched fail.
                unresolved = sorted(set(wanted) - set(resolved))
                if unresolved:
                    raise wiki.WikipediaSemanticIncomplete(
                        f"{len(unresolved)} parent revisions requested but never resolved"
                    )

            for page_id, page in pages.items():
                pair = wiki.pair_from(page, resolved)
                if pair is None:
                    continue
                aliases = [
                    str(row["title"])
                    for row in page.get("redirects") or []
                    if isinstance(row, Mapping) and isinstance(row.get("title"), str)
                ]
                items.append(
                    {
                        "category": category,
                        "page_id": page_id,
                        "title": page.get("title") or members.get(page_id, ""),
                        "aliases": aliases,
                        "redirect": False,
                        **pair,
                    }
                )
                self._wiki_seen.add(page_id)
        proof["pairs_built"] = len(items)

        if not items:
            return {
                "items": [],
                "next_cursor": next_cursor,
                "snapshot_id": f"zero:{root_id}:NO_PAGE_YIELDED_A_REVISION_PAIR",
                "response_refs": refs,
                "rate_limited": False,
                "root_disposition": _disposition(
                    root_id,
                    "ZERO_CANDIDATE_ROOT_DISPOSITION",
                    "NO_PAGE_YIELDED_A_REVISION_PAIR",
                    proof,
                ),
            }
        return {
            "items": items,
            "next_cursor": next_cursor,
            "snapshot_id": f"wikipedia:{category}:members:{len(members)}:pairs:{len(items)}",
            "response_refs": refs,
            "rate_limited": False,
            "root_disposition": _disposition(
                root_id, "COMPLETE", "CATEGORY_CONTINUATION_EXHAUSTED_AND_PAIRS_RESOLVED", proof
            ),
        }
