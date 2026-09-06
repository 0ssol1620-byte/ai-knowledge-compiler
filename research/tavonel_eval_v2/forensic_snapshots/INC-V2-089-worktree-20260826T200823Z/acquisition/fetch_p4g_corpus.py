#!/usr/bin/env python3
"""Build the P4g cohort: 400 documents, four families, container cap 8.

Network reads only. Nothing is sent anywhere, every artifact lands under
research/tavonel_eval_v2/, and the only credential used is a GitHub token read
from the environment for the listing rate limit — GET requests to
api.github.com, nothing else.

Parsers, the canonicaliser bridge and the eCFR/Wikipedia selectors are
**imported** from the P4c and P4e fetchers rather than copied. What is written
here is the two selectors P4e did not have to write, because P4e reused pairs
already on disk and P4g cannot: markdown paths across repositories, and SEC
amendment pairs across issuers.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_p4c_corpus as p4c  # noqa: E402
from common import NS, canonical_sha, now, rel, sha_bytes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_p4g import (  # noqa: E402
    DART,
    ECFR_PARTS,
    ECFR_PARTS_RESERVE,
    FAMILY_QUOTA,
    GIT_PATH_RULE,
    GIT_REPOSITORIES,
    GIT_REPOSITORIES_RESERVE,
    LICENCES,
    NETWORK,
    REDISTRIBUTION,
    REVISION_SPACING,
    SEC_BASE_FORMS,
    SEC_ISSUERS,
    SEC_ISSUERS_RESERVE,
    SELECTION_RULE,
    TOP_UP,
    TOP_UP_QUOTA,
    USER_AGENT,
    WIKIPEDIA_ARTICLES,
    WIKIPEDIA_ARTICLES_RESERVE,
)

#: Set by --top-up. The reserves are additional INPUTS under the unchanged
#: rules; no spacing clause, cap or eligibility test moves. See INC-V2-014.
TOPPING_UP = False


def _repositories() -> tuple[dict[str, str], ...]:
    return GIT_REPOSITORIES + GIT_REPOSITORIES_RESERVE if TOPPING_UP else GIT_REPOSITORIES


def _parts() -> tuple[tuple[str, str, str], ...]:
    return ECFR_PARTS + ECFR_PARTS_RESERVE if TOPPING_UP else ECFR_PARTS


def _articles() -> tuple[str, ...]:
    return WIKIPEDIA_ARTICLES + WIKIPEDIA_ARTICLES_RESERVE if TOPPING_UP else WIKIPEDIA_ARTICLES


def _issuers() -> tuple[tuple[str, str], ...]:
    return SEC_ISSUERS + SEC_ISSUERS_RESERVE if TOPPING_UP else SEC_ISSUERS


def _quota(family: str) -> int:
    return (TOP_UP_QUOTA if TOPPING_UP else FAMILY_QUOTA)[family]

RAW = NS / "artifacts" / "development" / "raw_p4g"
CANONICAL = NS / "artifacts" / "development" / "canonical_p4g"
SOURCES = Path(__file__).resolve().parent / "sources_p4g.py"

CONTAINER_CAP = SELECTION_RULE["container_cap"]
MIN_UNITS = 3
SEPARATION_DAYS = 180
#: Bounds the listing call, not the choice. A window is not a filter on content.
COMMIT_WINDOW = 100
WIKIPEDIA_REVISION_WINDOW = 500
PAUSE = 0.35


def _parse_iso(stamp: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def gh(url: str, *, retries: int = 3) -> Any:
    """Authenticated GET against the GitHub API. Read-only, listing only."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except Exception as error:
            last = error
            time.sleep(PAUSE * (attempt + 1) * 3)
    raise RuntimeError("github listing failed: %s" % last)


# --- git_docs ----------------------------------------------------------------


def _markdown_paths(entry: dict[str, str]) -> tuple[list[str], str | None, str | None]:
    """Every .md path under the declared prefix, lexicographic, names excluded."""
    meta = gh("https://api.github.com/repos/%s/%s" % (entry["owner"], entry["repo"]))
    branch = meta.get("default_branch")
    if not branch:
        return [], None, "NO_DEFAULT_BRANCH"
    time.sleep(PAUSE)
    tree = gh(
        "https://api.github.com/repos/%s/%s/git/trees/%s?recursive=1"
        % (entry["owner"], entry["repo"], branch)
    )
    time.sleep(PAUSE)
    excluded_names = set(GIT_PATH_RULE["excluded_names"])
    paths = sorted(
        node["path"]
        for node in tree.get("tree", [])
        if node.get("type") == "blob"
        and node["path"].startswith(entry["prefix"])
        and node["path"].endswith(GIT_PATH_RULE["extension"])
        and node["path"].rsplit("/", 1)[-1] not in excluded_names
    )
    return paths, branch, ("TREE_TRUNCATED" if tree.get("truncated") else None)


def git_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Markdown across repositories, newest commit vs one >= 180 days older."""
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    quota = _quota("git_docs")
    for entry in _repositories():
        if len(documents) >= quota:
            break
        container = entry["owner"] + "/" + entry["repo"]
        try:
            paths, branch, note = _markdown_paths(entry)
        except Exception as error:
            excluded.append(
                {
                    "document_id": "git:" + container,
                    "reason": "LISTING_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        if note:
            excluded.append({"document_id": "git:" + container, "reason": note})
        if not paths:
            excluded.append(
                {"document_id": "git:" + container, "reason": "NO_MARKDOWN_UNDER_PREFIX"}
            )
            continue
        admitted_here = 0
        for path in paths:
            if admitted_here >= CONTAINER_CAP or len(documents) >= quota:
                break
            document_id = "git:" + container + ":" + path
            listing = (
                "https://api.github.com/repos/%s/%s/commits?per_page=%d&path=%s"
                % (entry["owner"], entry["repo"], COMMIT_WINDOW, urllib.parse.quote(path))
            )
            try:
                commits = gh(listing)
            except Exception as error:
                excluded.append(
                    {
                        "document_id": document_id,
                        "reason": "LISTING_FAILED",
                        "error": type(error).__name__,
                    }
                )
                continue
            time.sleep(PAUSE)
            if not isinstance(commits, list) or len(commits) < 2:
                excluded.append({"document_id": document_id, "reason": "TOO_FEW_COMMITS"})
                continue
            newest = commits[0]
            newest_at = newest["commit"]["committer"]["date"]
            cutoff = _parse_iso(newest_at) - _dt.timedelta(days=SEPARATION_DAYS)
            older = next(
                (
                    commit
                    for commit in commits[1:]
                    if _parse_iso(commit["commit"]["committer"]["date"]) <= cutoff
                ),
                None,
            )
            if older is None:
                excluded.append(
                    {
                        "document_id": document_id,
                        "reason": "INELIGIBLE_SPACING_NOT_MET",
                        "required_days": SEPARATION_DAYS,
                        "oldest_seen": commits[-1]["commit"]["committer"]["date"],
                    }
                )
                continue
            older_at = older["commit"]["committer"]["date"]
            stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            identity = entry["repo"] + " " + stem.replace("-", " ").replace("_", " ")
            documents.append(
                {
                    "family": "git_docs",
                    "container": container,
                    "container_name": container,
                    "document_id": document_id,
                    "title_field": identity,
                    "doc_type": "markdown documentation",
                    "spoken_type": "documentation",
                    "identity": identity,
                    "before_version": older["sha"],
                    "after_version": newest["sha"],
                    "before_known_at": older_at,
                    "after_known_at": newest_at,
                    "spacing_days": (_parse_iso(newest_at) - _parse_iso(older_at)).days,
                    "branch": branch,
                    "licence": entry["license"],
                    "fetch": {
                        side: "https://raw.githubusercontent.com/%s/%s/%s"
                        % (container, sha, path)
                        for side, sha in (("before", older["sha"]), ("after", newest["sha"]))
                    },
                    "suffix": ".md",
                }
            )
            admitted_here += 1
    return documents, excluded


# --- sec_edgar ---------------------------------------------------------------


def _base_form(form: str) -> str:
    return form[:-2] if form.endswith("/A") else form


def sec_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Amendment pairs from the live submissions index, capped per issuer."""
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    quota = _quota("sec_edgar")
    for ticker, cik in _issuers():
        if len(documents) >= quota:
            break
        try:
            index = json.loads(p4c.fetch("https://data.sec.gov/submissions/CIK" + cik + ".json"))
        except Exception as error:
            excluded.append(
                {
                    "document_id": "sec:" + cik,
                    "reason": "LISTING_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        time.sleep(PAUSE)
        recent = index["filings"]["recent"]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for position in range(len(recent["form"])):
            form = recent["form"][position]
            report_date = recent["reportDate"][position]
            if _base_form(form) not in SEC_BASE_FORMS or not report_date:
                continue
            grouped[(_base_form(form), report_date)].append(
                {
                    "form": form,
                    "accession": recent["accessionNumber"][position],
                    "primary_document": recent["primaryDocument"][position],
                    "filing_date": recent["filingDate"][position],
                }
            )
        candidates: list[dict[str, Any]] = []
        for (form, report_date), filings in grouped.items():
            originals = [item for item in filings if not item["form"].endswith("/A")]
            amendments = [item for item in filings if item["form"].endswith("/A")]
            if not originals or not amendments:
                continue
            document_id = "sec:" + cik + ":" + form + ":" + report_date
            if len(originals) > 1:
                excluded.append(
                    {
                        "document_id": document_id,
                        "reason": "INELIGIBLE_RELATION",
                        "detail": "more than one original for this period",
                    }
                )
                continue
            original = originals[0]
            amendment = sorted(amendments, key=lambda item: item["filing_date"])[0]
            if not original["primary_document"] or not amendment["primary_document"]:
                excluded.append({"document_id": document_id, "reason": "NO_PRIMARY_DOCUMENT"})
                continue
            candidates.append(
                {
                    "family": "sec_edgar",
                    "container": ticker,
                    "container_name": index.get("name", ticker),
                    "document_id": document_id,
                    "title_field": form + " filing",
                    "doc_type": form,
                    "spoken_type": form + " filing",
                    "identity": form,
                    "before_version": original["accession"],
                    "after_version": amendment["accession"],
                    "before_known_at": original["filing_date"],
                    "after_known_at": amendment["filing_date"],
                    "report_date": report_date,
                    "relation_basis": (
                        "same CIK, same base form, same period of report, as published "
                        "in the issuer submissions index"
                    ),
                    "licence": LICENCES["sec_edgar"],
                    "fetch": {
                        side: "https://www.sec.gov/Archives/edgar/data/%d/%s/%s"
                        % (int(cik), item["accession"].replace("-", ""), item["primary_document"])
                        for side, item in (("before", original), ("after", amendment))
                    },
                    "suffix": ".html",
                }
            )
        candidates.sort(key=lambda item: (item["after_known_at"], item["document_id"]), reverse=True)
        for candidate in candidates[:CONTAINER_CAP]:
            if len(documents) >= quota:
                break
            documents.append(candidate)
    return documents, excluded


# --- eCFR and Wikipedia, selectors reused ------------------------------------


def ecfr_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P4e's rule — newest against oldest dated version — over 18 parts."""
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    quota = _quota("regulation_ecfr")
    for title, part, part_name in _parts():
        if len(documents) >= quota:
            break
        url = (
            "https://www.ecfr.gov/api/versioner/v1/versions/title-%s.json?part=%s" % (title, part)
        )
        try:
            rows = json.loads(p4c.fetch(url)).get("content_versions", [])
        except Exception as error:
            excluded.append(
                {
                    "document_id": "ecfr:%s:%s" % (title, part),
                    "reason": "LISTING_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        by_section: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row.get("type") != "section" or row.get("removed"):
                continue
            by_section.setdefault(row["identifier"], []).append(row)
        eligible = []
        for identifier, versions in sorted(by_section.items()):
            dates = sorted({row["date"] for row in versions})
            if len(dates) < 2:
                excluded.append(
                    {
                        "document_id": "ecfr:%s:%s:%s" % (title, part, identifier),
                        "reason": "INELIGIBLE_SINGLE_VERSION",
                    }
                )
                continue
            eligible.append((identifier, dates))
        for identifier, dates in eligible[:CONTAINER_CAP]:
            if len(documents) >= quota:
                break
            documents.append(
                {
                    "family": "regulation_ecfr",
                    "container": "%s CFR %s" % (title, part),
                    "container_name": part_name,
                    "document_id": "ecfr:%s:%s:%s" % (title, part, identifier),
                    "title_field": "%s CFR part %s %s" % (title, part, part_name),
                    "doc_type": "Code of Federal Regulations section",
                    "spoken_type": "Code of Federal Regulations section",
                    "identity": "%s CFR %s" % (title, identifier),
                    "before_version": dates[0],
                    "after_version": dates[-1],
                    "version_count": len(dates),
                    "licence": LICENCES["regulation_ecfr"],
                    "fetch": {
                        side: (
                            "https://www.ecfr.gov/api/versioner/v1/full/%s/title-%s.xml"
                            "?part=%s&section=%s" % (date, title, part, identifier)
                        )
                        for side, date in (("before", dates[0]), ("after", dates[-1]))
                    },
                    "suffix": ".xml",
                }
            )
            time.sleep(PAUSE)
    return documents, excluded


def wikipedia_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P4e's rule — newest against one at least 180 days older — over 100 articles."""
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    quota = _quota("encyclopedia_wikipedia")
    for article in _articles():
        if len(documents) >= quota:
            break
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=%s"
            "&rvlimit=%d&rvprop=ids%%7Ctimestamp&format=json&formatversion=2"
            % (urllib.parse.quote(article), WIKIPEDIA_REVISION_WINDOW)
        )
        document_id = "wikipedia:en:" + article
        try:
            pages = json.loads(p4c.fetch(url)).get("query", {}).get("pages", [])
        except Exception as error:
            excluded.append(
                {
                    "document_id": document_id,
                    "reason": "LISTING_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        revisions = pages[0].get("revisions", []) if pages else []
        if len(revisions) < 2:
            excluded.append({"document_id": document_id, "reason": "TOO_FEW_REVISIONS"})
            continue
        newest = revisions[0]
        cutoff = _parse_iso(newest["timestamp"]) - _dt.timedelta(days=SEPARATION_DAYS)
        older = next((rev for rev in revisions[1:] if _parse_iso(rev["timestamp"]) <= cutoff), None)
        if older is None:
            excluded.append(
                {
                    "document_id": document_id,
                    "reason": "INELIGIBLE_SPACING_NOT_MET",
                    "required_days": SEPARATION_DAYS,
                    "oldest_seen": revisions[-1]["timestamp"],
                }
            )
            time.sleep(PAUSE)
            continue
        documents.append(
            {
                "family": "encyclopedia_wikipedia",
                "container": document_id,
                "container_name": article,
                "document_id": document_id,
                "title_field": article,
                "doc_type": "encyclopedia article",
                "spoken_type": "encyclopedia article",
                "identity": article,
                "before_version": str(older["revid"]),
                "after_version": str(newest["revid"]),
                "before_known_at": older["timestamp"],
                "after_known_at": newest["timestamp"],
                "spacing_days": (
                    _parse_iso(newest["timestamp"]) - _parse_iso(older["timestamp"])
                ).days,
                "licence": LICENCES["encyclopedia_wikipedia"],
                "fetch": {
                    side: (
                        "https://en.wikipedia.org/w/api.php?action=parse&oldid=%s"
                        "&prop=text&format=json&formatversion=2" % revision
                    )
                    for side, revision in (("before", older["revid"]), ("after", newest["revid"]))
                },
                "suffix": ".html",
                "unwrap": "parse.text",
            }
        )
        time.sleep(PAUSE)
    return documents, excluded


# --- assembly ----------------------------------------------------------------


def main() -> int:
    global TOPPING_UP
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-payloads", action="store_true", help="selection only, no bodies")
    parser.add_argument(
        "--top-up",
        action="store_true",
        help="add the declared reserves to an existing manifest. INC-V2-014.",
    )
    args = parser.parse_args()
    started = now()
    TOPPING_UP = args.top_up

    path = NS / "artifacts" / "development" / "p4g_cohort.json"
    carried: list[dict[str, Any]] = []
    already: set[str] = set()
    if TOPPING_UP and path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        carried = previous["documents"]
        already = {record["document_id"] for record in carried}
        # the first pass's receipt binds this path by hash, so the file it
        # bound is kept rather than overwritten out from under it
        preserved = path.with_name("p4g_cohort_pass1.json")
        if not preserved.exists():
            preserved.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    dart = p4c.probe_dart()
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    per_family_excluded: dict[str, int] = {}
    for family, selector in (
        ("git_docs", git_documents),
        ("regulation_ecfr", ecfr_documents),
        ("encyclopedia_wikipedia", wikipedia_documents),
        ("sec_edgar", sec_documents),
    ):
        selected, rejected = selector()
        documents.extend(selected)
        excluded.extend(rejected)
        per_family_excluded[family] = len(rejected)
        print(
            json.dumps({"stage": "selected", "family": family, "documents": len(selected)}),
            flush=True,
        )

    if args.skip_payloads:
        print(json.dumps({"selected": len(documents), "excluded": len(excluded)}, sort_keys=True))
        return 0

    admitted: list[dict[str, Any]] = list(carried)
    documents = [d for d in documents if d["document_id"] not in already]
    for position, document in enumerate(documents):
        if position and position % 25 == 0:
            print(
                json.dumps({"stage": "payloads", "done": position, "admitted": len(admitted)}),
                flush=True,
            )
        try:
            sides = {side: p4c.payload_for(document, side) for side in ("before", "after")}
        except Exception as error:
            excluded.append(
                {
                    "document_id": document["document_id"],
                    "reason": "FETCH_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        if sides["before"] == sides["after"]:
            excluded.append(
                {"document_id": document["document_id"], "reason": "INELIGIBLE_NO_SOURCE_CHANGE"}
            )
            continue
        try:
            canonical = {side: p4c.canonicalise(document, side, sides[side]) for side in sides}
        except Exception as error:
            excluded.append(
                {
                    "document_id": document["document_id"],
                    "reason": "CANONICALISATION_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        if any(len(value["units"]) < MIN_UNITS for value in canonical.values()):
            excluded.append(
                {
                    "document_id": document["document_id"],
                    "reason": "INELIGIBLE_PARSE_FLOOR",
                    "units": {s: len(v["units"]) for s, v in canonical.items()},
                }
            )
            continue

        slug = re.sub(r"[^A-Za-z0-9]+", "-", document["document_id"]).strip("-").lower()[:80]
        record = {k: v for k, v in document.items() if not k.startswith("_")}
        record["document_slug"] = slug
        for side in ("before", "after"):
            raw_path = RAW / slug / (side + document["suffix"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(sides[side])
            canonical_path = CANONICAL / slug / (side + ".json")
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                json.dumps(canonical[side], sort_keys=True, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record[side] = {
                **{k: v for k, v in record.get(side, {}).items()},
                "raw_path": rel(raw_path),
                "raw_sha256": sha_bytes(sides[side]),
                "canonical_path": rel(canonical_path),
                "unit_count": len(canonical[side]["units"]),
            }
        admitted.append(record)

    family_counts = {
        family: sum(1 for d in admitted if d["family"] == family)
        for family in sorted({d["family"] for d in admitted})
    }
    manifest = {
        "schema": "tavonel.v2.p4g_cohort.v1",
        "protocol": "P4g_cohort_expansion",
        "built_at": started,
        "ended_at": now(),
        "sources_declaration": rel(SOURCES),
        "revision_spacing": REVISION_SPACING,
        "selection_rule": SELECTION_RULE,
        "family_quota": FAMILY_QUOTA,
        "git_path_rule": GIT_PATH_RULE,
        "network": NETWORK,
        "top_up": {**TOP_UP, "applied": TOPPING_UP, "carried_forward": len(carried)}
        if TOPPING_UP
        else {"applied": False},
        "redistribution": REDISTRIBUTION,
        "dart": dart,
        "documents": admitted,
        "excluded": excluded,
        "excluded_by_family_selector": per_family_excluded,
        "family_counts": family_counts,
        "document_count": len(admitted),
        "documents_sha256": canonical_sha(admitted),
        "frozen_before_any_eligibility_result": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    written = write_immutable(
        "p4g-cohort-manifest",
        {
            "schema": "tavonel.v2.p4g_cohort_receipt.v1",
            "protocol": "P4g_cohort_expansion",
            "manifest_path": rel(path),
            "documents_sha256": manifest["documents_sha256"],
            "document_count": len(admitted),
            "family_counts": family_counts,
            "excluded_count": len(excluded),
            "targets": {"documents": 400, "markdown": 120, "container_cap": CONTAINER_CAP},
            "dart": dart,
            "revision_spacing": REVISION_SPACING,
            "extension_recorded_as": "INC-V2-012",
            "frozen_before_any_eligibility_result": True,
            "gpu_seconds": 0,
            "estimated_cost_usd": 0.0,
        },
        tool=Path(__file__).resolve(),
        protocol=SOURCES,
    )
    print(
        json.dumps(
            {
                "documents": len(admitted),
                "families": family_counts,
                "excluded": len(excluded),
                "dart": dart["state"],
                "manifest": rel(path),
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
