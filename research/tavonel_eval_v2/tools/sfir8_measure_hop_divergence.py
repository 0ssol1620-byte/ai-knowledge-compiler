#!/usr/bin/env python3
"""Measure why GitHub charged SFIR7 more requests than SFIR7 counted.

A controlled comparison rather than an explanation. SFIR7's roster splits itself
into two groups the census already identified: nine addresses GitHub reports as
renamed, and forty-one it does not. If redirect following is the cause, the
renamed group costs more per logical request and the unrenamed group costs
exactly one. If both groups cost one, redirects are not the cause and the search
continues elsewhere -- which is the outcome this probe is written to be capable
of producing.

Each repository is asked for the same three endpoint shapes the traversal itself
uses, so the comparison is against the real access pattern and not a convenient
one:

    /repos/{owner}/{name}                     the metadata request
    /repos/{owner}/{name}/commits/{branch}    the immutable head
    /repos/{owner}/{name}/git/trees/{sha}     one tree object

The cost is a few dozen requests. SFIR7's roots are spent development material by
founder ruling, so spending a handful of requests on them is instrument work and
produces no capacity claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir8_hop_accounting as hops  # noqa: E402

SCHEMA = "tavonel.sfir8.hop_divergence.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

CENSUS = NS / "receipts/sfir7-capacity-metadata-census.json"

#: Paced like the census, so the probe cannot trip a secondary limit and
#: contaminate its own measurement.
MIN_INTERVAL_SECONDS = 0.5


class DivergenceRefused(RuntimeError):
    """The probe cannot produce a comparison worth reading."""


def sample(census: dict[str, Any], *, per_group: int) -> dict[str, list[str]]:
    """Take renamed and unrenamed repositories from SFIR7's own observation.

    Neither group is chosen by yield, tree size, language or any other property
    that could make the comparison flattering. The split is on the one fact under
    test -- whether GitHub reported the address as moved.
    """
    attestation = census["identity_attestation"]
    renamed = sorted(attestation["renames_observed"])
    dispositions = census["families"]["git_docs"]["root_dispositions"]
    visited = [
        row["discovery_root_id"].removeprefix("git:")
        for row in dispositions
        if row.get("response_refs")
    ]
    unrenamed = sorted(name for name in visited if name not in set(renamed))
    if not renamed or not unrenamed:
        raise DivergenceRefused(
            f"the census offers {len(renamed)} renamed and {len(unrenamed)} unrenamed "
            "repositories; a comparison needs both"
        )
    return {"renamed": renamed[:per_group], "unrenamed": unrenamed[:per_group]}


def probe(fetcher: hops.HopCountingFetcher, repository: str) -> list[dict[str, Any]]:
    """The three endpoint shapes the traversal uses, in the order it uses them."""
    results: list[dict[str, Any]] = []

    def record(url: str, label: str) -> Any:
        _pace()
        accounting = fetcher.fetch(url)
        results.append(
            {
                "repository": repository,
                "endpoint": label,
                "url": url,
                "status": accounting.status,
                "redirected": accounting.redirected,
                "network_hops": accounting.network_hops,
                "provider_charged": accounting.provider_charged,
            }
        )
        return accounting

    meta = record(f"https://api.github.com/repos/{repository}", "repository_metadata")
    if meta.status != 200:
        return results
    branch = (meta.body or {}).get("default_branch")
    if not isinstance(branch, str):
        return results
    head = record(
        f"https://api.github.com/repos/{repository}/commits/{branch}", "immutable_head"
    )
    if head.status != 200:
        return results
    head_body = head.body or {}
    tree_sha = ((head_body.get("commit") or {}).get("tree") or {}).get("sha")
    if not isinstance(tree_sha, str):
        return results
    tree = record(
        f"https://api.github.com/repos/{repository}/git/trees/{tree_sha}", "tree_object"
    )
    #: The commit-history shape is the bulk of a traversal -- up to eighty per
    #: root against a handful of tree requests -- so its per-request charge
    #: dominates any reconciliation. Measuring only the cheap shapes would give a
    #: confident answer about the wrong endpoint.
    head_sha = head_body.get("sha")
    path = _first_document_path(tree.body)
    if isinstance(head_sha, str) and path:
        record(
            f"https://api.github.com/repos/{repository}/commits"
            f"?path={urllib.parse.quote(path)}&sha={head_sha}&per_page=2",
            "commit_history",
        )
    return results


def _first_document_path(tree_body: Any) -> str | None:
    """Any real path from the tree, so the history request is a realistic one."""
    entries = (tree_body or {}).get("tree") or []
    for entry in entries:
        name = entry.get("path")
        if entry.get("type") == "blob" and isinstance(name, str):
            return name
    return None


_LAST = [0.0]


def _pace() -> None:
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _LAST[0])
    if wait > 0:
        time.sleep(wait)
    _LAST[0] = time.monotonic()


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for group in ("renamed", "unrenamed"):
        selected = [r for r in rows if r["group"] == group and r["provider_charged"] is not None]
        charged = [r["provider_charged"] for r in selected]
        groups[group] = {
            "logical_requests": len(selected),
            "network_hops": sum(r["network_hops"] for r in selected),
            "provider_charged": sum(charged),
            "charged_per_logical_request": (
                round(sum(charged) / len(charged), 4) if charged else None
            ),
            "requests_that_redirected": sum(1 for r in selected if r["redirected"]),
            "requests_charged_more_than_one": sum(1 for c in charged if c > 1),
        }
    verdict = _verdict(groups)
    return {"groups": groups, **verdict}


def _verdict(groups: dict[str, Any]) -> dict[str, Any]:
    """State what was measured, and refuse to state more than that."""
    renamed = groups["renamed"]["charged_per_logical_request"]
    unrenamed = groups["unrenamed"]["charged_per_logical_request"]
    if renamed is None or unrenamed is None:
        return {
            "finding": "NO_PROVIDER_ACCOUNTING",
            "means": "GitHub returned no rate-limit headers, so nothing can be concluded",
        }
    if renamed > unrenamed:
        finding = "RENAMED_ADDRESSES_COST_MORE"
        means = (
            "a renamed address costs more per logical request than an unrenamed one. "
            "Redirect following is supported as a contributor to SFIR7's divergence. "
            "Whether it is the WHOLE of it depends on how many requests in that census "
            "went to renamed addresses, which is arithmetic this probe does not do."
        )
    elif renamed == unrenamed == 1:
        finding = "REDIRECTS_ARE_NOT_THE_CAUSE"
        means = (
            "both groups cost exactly one request each. Redirect following does not "
            "explain SFIR7's divergence and the cause is elsewhere. This probe was "
            "written to be able to return this."
        )
    else:
        finding = "INCONCLUSIVE"
        means = (
            f"renamed cost {renamed} per request and unrenamed cost {unrenamed}, which "
            "matches neither the redirect hypothesis nor its negation cleanly"
        )
    return {
        "finding": finding,
        "means": means,
        "what_this_does_not_establish": (
            "the size of SFIR7's divergence. That census is terminal evidence and is "
            "not re-run; this probe measures the per-request cost of a renamed address "
            "today, which is a different and smaller claim."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, default=CENSUS)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--per-group", type=int, default=9)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()

    census = json.loads(args.census.read_text(encoding="utf-8"))
    chosen = sample(census, per_group=args.per_group)

    fetcher = hops.HopCountingFetcher()
    hops.prime(fetcher)
    rows: list[dict[str, Any]] = []
    for group, repositories in chosen.items():
        for repository in repositories:
            for row in probe(fetcher, repository):
                rows.append({**row, "group": group})

    body = {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": args.generated_at,
        "study_kind": "DEVELOPMENT_INSTRUMENT_CALIBRATION",
        "produces_capacity_claim": False,
        "sfir7_is_terminal_evidence_and_was_not_rerun": True,
        "sample": chosen,
        "requests": rows,
        "totals": fetcher.totals(),
        **summarise(rows),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
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
                "groups": body["groups"],
                "totals": {
                    k: body["totals"][k]
                    for k in ("logical_requests", "network_hops", "provider_charged")
                },
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
