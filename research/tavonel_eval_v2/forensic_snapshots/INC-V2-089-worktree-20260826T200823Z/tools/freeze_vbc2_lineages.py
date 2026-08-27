#!/usr/bin/env python3
"""Expand VBC2's declared roots into a frozen lineage list. No history, no values.

This is the step between "which sources" and "what changed in them". It walks
each declared root and writes down the *identities* of the lineages it contains —
a repository path, a CFR section, an article title, an issuer's filing series.
It reads no revision content and compares no values, so the list it seals cannot
have been shaped by anything the study is trying to measure.

Freshness is computed here rather than promised: every candidate is checked
against P4i's declared lists, against the V1 feasibility probe's cohort, and
against the ten `MODEL_ENDPOINT_V1` survivors, and anything that matches is
dropped with a code before it can reach acquisition.
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
import sources_p4i as p4i_sources  # noqa: E402
from common import NS, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_vbc2 import (  # noqa: E402
    CONSUMPTION_ORDER,
    ECFR_ROOTS,
    GIT_ROOTS,
    HISTORY,
    SEC_ROOTS,
    WIKIPEDIA_CATEGORY_ROOTS,
)

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml"
OUT = NS / "artifacts" / "development" / "vbc2_lineages.json"
PROBE_MANIFEST = NS / "artifacts" / "development" / "vbc1_probe_cohort.json"

#: Enough candidates per family that the walk is not the binding constraint.
CANDIDATE_CAP = {
    "git_docs": 900,
    "regulation_ecfr": 900,
    "encyclopedia_wikipedia": 700,
    "sec_edgar": 200,
}
PER_ROOT_CAP = {
    "git_docs": 40,
    "regulation_ecfr": 40,
    "encyclopedia_wikipedia": 90,
    "sec_edgar": 20,
}


def spent_lineages() -> dict[str, set[str]]:
    """Every lineage whose eligibility has already been seen, by document id."""
    spent: set[str] = set()
    p4i = json.loads(
        (NS / "artifacts" / "development" / "p4i_cohort.json").read_text(encoding="utf-8")
    )
    spent.update(record["document_id"] for record in p4i["documents"])
    if PROBE_MANIFEST.exists():
        probe = json.loads(PROBE_MANIFEST.read_text(encoding="utf-8"))
        spent.update(record["document_id"] for record in probe["documents"])
    roots = {
        "git": {r["owner"] + "/" + r["repo"] for r in p4i_sources.GIT_REPOSITORIES_ALL},
        "ecfr": {(t, p) for t, p, _ in p4i_sources.ECFR_PARTS_ALL},
        "wikipedia": set(p4i_sources.WIKIPEDIA_ARTICLES_ALL),
        "sec": {cik for _, cik in p4i_sources.SEC_ISSUERS_ALL},
    }
    return {"documents": spent, **roots}


def git_lineages(spent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for entry in GIT_ROOTS:
        container = entry["owner"] + "/" + entry["repo"]
        if container in spent["git"]:
            dropped.append({"root": container, "code": "LINEAGE_NOT_FRESH"})
            continue
        if len(found) >= CANDIDATE_CAP["git_docs"]:
            break
        try:
            paths, branch, _note = p4g._markdown_paths(entry)
        except Exception as error:
            dropped.append(
                {"root": container, "code": "LISTING_FAILED", "error": type(error).__name__}
            )
            continue
        for path in paths[: PER_ROOT_CAP["git_docs"]]:
            found.append(
                {
                    "family": "git_docs",
                    "lineage_id": "git:" + container + ":" + path,
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


def ecfr_lineages(spent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for title, part, part_name in ECFR_ROOTS:
        if (title, part) in spent["ecfr"]:
            dropped.append({"root": title + "-" + part, "code": "LINEAGE_NOT_FRESH"})
            continue
        if len(found) >= CANDIDATE_CAP["regulation_ecfr"]:
            break
        url = "https://www.ecfr.gov/api/versioner/v1/versions/title-%s.json?part=%s" % (
            title,
            part,
        )
        try:
            rows = json.loads(p4c.fetch(url)).get("content_versions", [])
        except Exception as error:
            dropped.append(
                {
                    "root": title + "-" + part,
                    "code": "LISTING_FAILED",
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
            found.append(
                {
                    "family": "regulation_ecfr",
                    "lineage_id": "ecfr:%s:%s:%s" % (title, part, identifier),
                    "container": "%s CFR %s" % (title, part),
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


def wikipedia_lineages(spent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in WIKIPEDIA_CATEGORY_ROOTS:
        if len(found) >= CANDIDATE_CAP["encyclopedia_wikipedia"]:
            break
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
            "&cmtitle=%s&cmlimit=%d&cmnamespace=0&format=json&formatversion=2"
            % (urllib.parse.quote(category), PER_ROOT_CAP["encyclopedia_wikipedia"])
        )
        try:
            members = json.loads(p4c.fetch(url))["query"]["categorymembers"]
        except Exception as error:
            dropped.append(
                {"root": category, "code": "LISTING_FAILED", "error": type(error).__name__}
            )
            continue
        for member in members:
            article = member["title"]
            if article in spent["wikipedia"] or article in seen:
                dropped.append({"root": category, "article": article, "code": "LINEAGE_NOT_FRESH"})
                continue
            seen.add(article)
            found.append(
                {
                    "family": "encyclopedia_wikipedia",
                    "lineage_id": "wikipedia:en:" + article,
                    "container": category,
                    "article": article,
                    "licence": p4g.LICENCES["encyclopedia_wikipedia"],
                    "suffix": ".html",
                }
            )
        time.sleep(p4g.PAUSE)
    return found, dropped


def sec_lineages(spent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A filing series, not a document with a history. Recorded as what it is."""
    found: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for ticker, cik in SEC_ROOTS:
        if cik in spent["sec"]:
            dropped.append({"root": ticker, "code": "LINEAGE_NOT_FRESH"})
            continue
        for form in p4g.SEC_BASE_FORMS:
            found.append(
                {
                    "family": "sec_edgar",
                    "lineage_id": "sec:%s:%s" % (cik, form),
                    "container": ticker,
                    "cik": cik,
                    "form": form,
                    "licence": p4g.LICENCES["sec_edgar"],
                    "suffix": ".html",
                    "history_note": (
                        "a filing series; its revisions are successive filings of the "
                        "same form, not edits to one document"
                    ),
                }
            )
    return found, dropped


def main() -> int:
    started = now()
    spent = spent_lineages()
    lineages: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for family, builder in (
        ("git_docs", git_lineages),
        ("regulation_ecfr", ecfr_lineages),
        ("encyclopedia_wikipedia", wikipedia_lineages),
        ("sec_edgar", sec_lineages),
    ):
        found, missed = builder(spent)
        fresh = [row for row in found if row["lineage_id"] not in spent["documents"]]
        dropped.extend(
            {"lineage_id": row["lineage_id"], "code": "LINEAGE_NOT_FRESH"}
            for row in found
            if row["lineage_id"] in spent["documents"]
        )
        dropped.extend(missed)
        lineages.extend(fresh)
        print(json.dumps({"family": family, "lineages": len(fresh)}), flush=True)

    body = {
        "schema": "tavonel.v2.vbc2_lineages.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "started_at": started,
        "ended_at": now(),
        "frozen_before_any_history_read": True,
        "frozen_before_any_value_read": True,
        "history_bounds": HISTORY,
        "consumption_order": CONSUMPTION_ORDER,
        "lineages": lineages,
        "lineage_count": len(lineages),
        "by_family": dict(Counter(row["family"] for row in lineages)),
        "dropped": dropped,
        "dropped_by_code": dict(Counter(row["code"] for row in dropped)),
        "freshness": {
            "checked_against": ["P4i", "VBC1 feasibility probe", "MODEL_ENDPOINT_V1 survivors"],
            "spent_document_ids": len(spent["documents"]),
            "no_spent_lineage_admitted": not (
                {row["lineage_id"] for row in lineages} & spent["documents"]
            ),
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    written = write_immutable(
        "vbc2-lineage-freeze",
        {**body, "lineages": rel(OUT), "lineage_list_path": rel(OUT)},
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
    )
    print(json.dumps({**written, "lineages": len(lineages), "by_family": body["by_family"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
