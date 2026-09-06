#!/usr/bin/env python3
"""Expand SFI1's declared roots into a frozen lineage list. Identities only.

The step between "which sources" and "what changed in them". It walks each
declared root and writes down the *identities* of the lineages it contains — a
repository path, a CFR section, an article title. It reads no revision content,
extracts no facts and compares no values, so the list it seals cannot have been
shaped by anything the study measures.

Two properties this run must have, both of them consequences of INC-V2-027:

* it runs AFTER the protocol freeze. The frozen protocol already fixes the
  quotas, the families, the payload bound and the seven endpoints, so nothing
  this walk discovers can move them.
* it produces no outcome. Family counts of *candidate identities* are frame
  information; a classification count would not be. Nothing here classifies.

Freshness is computed rather than promised. Every candidate is checked against
the predecessor's spent set — derived from SFH1's own receipts by
`sources_sfi1.spent_lineages`, never hand-copied — and against the four forensic
diagnostic lineages, and anything matching is dropped with a code before it can
reach acquisition. A case used to diagnose the defect cannot certify its repair.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "acquisition"))

import fetch_p4c_corpus as p4c  # noqa: E402
import fetch_p4g_corpus as p4g  # noqa: E402
import sources_sfi1 as frame  # noqa: E402
from common import NS, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

PROTOCOL = NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V1.yaml"
OUT = NS / "artifacts" / "development" / "sfi1_lineages.json"

#: Enough candidates per family that the walk is not the binding constraint —
#: the family quota is. A cap that bound before the quota did would make the
#: cohort a property of this tool rather than of the frozen protocol.
CANDIDATE_CAP = {
    "git_docs": 900,
    "regulation_ecfr": 900,
    "encyclopedia_wikipedia": 700,
}
PER_ROOT_CAP = {
    "git_docs": 40,
    "regulation_ecfr": 40,
    "encyclopedia_wikipedia": 90,
}

NOT_FRESH = "LINEAGE_NOT_FRESH"
LISTING_FAILED = "LISTING_FAILED"


def spent() -> set[str]:
    """Every lineage id the predecessor studies consumed, plus the forensic four."""
    return set(frame.spent_lineages())


def git_lineages(used: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for entry in frame.GIT_ROOTS:
        container = entry["owner"] + "/" + entry["repo"]
        if len(found) >= CANDIDATE_CAP["git_docs"]:
            break
        try:
            paths, branch, _note = p4g._markdown_paths(entry)
        except Exception as error:
            dropped.append(
                {"root": container, "code": LISTING_FAILED, "error": type(error).__name__}
            )
            continue
        for path in paths[: PER_ROOT_CAP["git_docs"]]:
            lineage_id = "git:" + container + ":" + path
            if lineage_id in used:
                dropped.append({"root": container, "lineage_id": lineage_id, "code": NOT_FRESH})
                continue
            found.append(
                {
                    "family": "git_docs",
                    "lineage_id": lineage_id,
                    "container": container,
                    "owner": entry["owner"],
                    "repo": entry["repo"],
                    "path": path,
                    "branch": branch,
                    "licence": entry["license"],
                    "suffix": ".md",
                }
            )
        time.sleep(p4g.PAUSE)
    return found, dropped


def ecfr_lineages(used: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for title, part, part_name in frame.ECFR_ROOTS:
        if len(found) >= CANDIDATE_CAP["regulation_ecfr"]:
            break
        url = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
        try:
            rows = json.loads(p4c.fetch(url)).get("content_versions", [])
        except Exception as error:
            dropped.append(
                {
                    "root": f"{title}-{part}",
                    "code": LISTING_FAILED,
                    "error": type(error).__name__,
                }
            )
            continue
        identifiers = sorted(
            {
                row["identifier"]
                for row in rows
                if row.get("type") == "section" and not row.get("removed")
            }
        )
        for identifier in identifiers[: PER_ROOT_CAP["regulation_ecfr"]]:
            lineage_id = f"ecfr:{title}:{part}:{identifier}"
            if lineage_id in used:
                dropped.append(
                    {"root": f"{title}-{part}", "lineage_id": lineage_id, "code": NOT_FRESH}
                )
                continue
            found.append(
                {
                    "family": "regulation_ecfr",
                    "lineage_id": lineage_id,
                    "container": f"{title} CFR {part}",
                    "container_name": part_name,
                    "title": title,
                    "part": part,
                    "identifier": identifier,
                    "licence": p4g.LICENCES["regulation_ecfr"],
                    "suffix": ".xml",
                }
            )
        time.sleep(p4g.PAUSE)
    return found, dropped


def wikipedia_lineages(used: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in frame.WIKIPEDIA_CATEGORY_ROOTS:
        if len(found) >= CANDIDATE_CAP["encyclopedia_wikipedia"]:
            break
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
            f"&cmtitle={urllib.parse.quote(category)}"
            f"&cmlimit={PER_ROOT_CAP['encyclopedia_wikipedia']}"
            "&cmnamespace=0&format=json&formatversion=2"
        )
        try:
            members = json.loads(p4c.fetch(url))["query"]["categorymembers"]
        except Exception as error:
            dropped.append(
                {"root": category, "code": LISTING_FAILED, "error": type(error).__name__}
            )
            continue
        for member in members:
            article = member["title"]
            lineage_id = "wikipedia:en:" + article
            if lineage_id in used or article in seen:
                dropped.append({"root": category, "lineage_id": lineage_id, "code": NOT_FRESH})
                continue
            seen.add(article)
            found.append(
                {
                    "family": "encyclopedia_wikipedia",
                    "lineage_id": lineage_id,
                    "container": category,
                    "article": article,
                    "licence": p4g.LICENCES["encyclopedia_wikipedia"],
                    "suffix": ".html",
                }
            )
        time.sleep(p4g.PAUSE)
    return found, dropped


def main() -> int:
    freezes = sorted((NS / "receipts").glob("sfi1-protocol-freeze--*.json"))
    if not freezes:
        print(
            "the protocol is not frozen. Expanding a frame first would let the "
            "frame shape the protocol, which is the order INC-V2-027 records.",
            file=sys.stderr,
        )
        return 3

    started = now()
    clock = time.time()
    used = spent()

    lineages: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for walk in (git_lineages, ecfr_lineages, wikipedia_lineages):
        found, missed = walk(used)
        lineages.extend(found)
        dropped.extend(missed)
        print(
            f"  {walk.__name__:<20} found {len(found):>4}  dropped {len(missed):>4}",
            flush=True,
        )

    lineages.sort(key=lambda row: frame.order_key(row["lineage_id"]))
    body: dict[str, Any] = {
        "schema": "tavonel.v2.sfi1_lineages.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "protocol_freeze": freezes[-1].name,
        "split": "held_out",
        "what_this_is": (
            "lineage identities only. No revision content was read, no fact was "
            "extracted and no value was compared, so this list cannot have been "
            "shaped by what the study measures."
        ),
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "spent_excluded": len(used),
        "candidates": len(lineages),
        "by_family": dict(sorted(Counter(row["family"] for row in lineages).items())),
        "dropped": dropped,
        "dropped_by_code": dict(sorted(Counter(row["code"] for row in dropped).items())),
        "order": f"ascending sha256 of (lineage_id + {frame.ORDER_SALT!r})",
        "lineages": lineages,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    receipt = write_immutable(
        "sfi1-lineage-freeze",
        {
            "schema": "tavonel.v2.sfi1_lineage_freeze.v1",
            "frame": rel(OUT),
            "frame_sha256": sha_file(OUT),
            "candidates": body["candidates"],
            "by_family": body["by_family"],
            "spent_excluded": body["spent_excluded"],
            "dropped_by_code": body["dropped_by_code"],
            "protocol_sha256": body["protocol_sha256"],
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        },
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
    )
    print(
        json.dumps(
            {**receipt, "candidates": body["candidates"], "by_family": body["by_family"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
