#!/usr/bin/env python3
"""Build the P4e cohort: wider revision spacing, same independence rule.

Network reads only. Nothing is sent anywhere, no credential is transmitted, and
every artifact lands under research/tavonel_eval_v2/.

The parsers, the canonicaliser bridge and the on-disk families are **imported**
from ``fetch_p4c_corpus`` rather than copied. Only the two selectors that decide
*which pair of revisions* a document contributes are written here, because that
is the only thing the frozen spacing rule changes.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_p4c_corpus as p4c  # noqa: E402
from common import NS, ROOT, canonical_sha, now, rel, sha_bytes  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_p4e import (  # noqa: E402
    DART,
    ECFR_PARTS,
    FAMILY_QUOTA,
    LICENCES,
    QUERY_FIELDS,
    REDISTRIBUTION,
    REVISION_SPACING,
    SELECTION_RULE,
    WIKIPEDIA_ARTICLES,
)

RAW = NS / "artifacts" / "development" / "raw_p4e"
CANONICAL = NS / "artifacts" / "development" / "canonical_p4e"
SOURCES = Path(__file__).resolve().parent / "sources_p4e.py"
CONTAINER_CAP = 6
MIN_UNITS = 3
WIKIPEDIA_SEPARATION_DAYS = 180
#: How far back the revision list is walked looking for a revision old enough.
#: A window, not a filter on content: it bounds the API call, not the choice.
WIKIPEDIA_REVISION_WINDOW = 500


def _parse_iso(stamp: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def wikipedia_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Newest revision, paired with the newest one at least 180 days older.

    The rule is evaluated on timestamps alone. Nothing about how much the
    article changed, or about any later score, enters the choice.
    """
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for article in WIKIPEDIA_ARTICLES:
        if len(documents) >= FAMILY_QUOTA["encyclopedia_wikipedia"]:
            break
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=%s"
            "&rvlimit=%d&rvprop=ids%%7Ctimestamp&format=json&formatversion=2"
            % (urllib.parse.quote(article), WIKIPEDIA_REVISION_WINDOW)
        )
        pages = json.loads(p4c.fetch(url)).get("query", {}).get("pages", [])
        revisions = pages[0].get("revisions", []) if pages else []
        if len(revisions) < 2:
            excluded.append({"document_id": "wikipedia:en:" + article, "reason": "TOO_FEW_REVISIONS"})
            continue
        newest = revisions[0]
        cutoff = _parse_iso(newest["timestamp"]) - _dt.timedelta(days=WIKIPEDIA_SEPARATION_DAYS)
        older = next(
            (rev for rev in revisions[1:] if _parse_iso(rev["timestamp"]) <= cutoff), None
        )
        if older is None:
            excluded.append(
                {
                    "document_id": "wikipedia:en:" + article,
                    "reason": "INELIGIBLE_SPACING_NOT_MET",
                    "required_days": WIKIPEDIA_SEPARATION_DAYS,
                    "oldest_seen": revisions[-1]["timestamp"],
                }
            )
            time.sleep(p4c.PAUSE_SECONDS)
            continue
        documents.append(
            {
                "family": "encyclopedia_wikipedia",
                "container": "en.wikipedia.org",
                "container_name": "English Wikipedia",
                "document_id": "wikipedia:en:" + article,
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
        time.sleep(p4c.PAUSE_SECONDS)
    return documents, excluded


def ecfr_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Newest dated version paired with the **oldest** the versioner reports.

    P4c took the two most recent dates, which for an actively amended section
    can be weeks apart. Maximal available separation is still a rule about
    dates, decidable before anything is scored.
    """
    documents: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for title, part, part_name in ECFR_PARTS:
        if len(documents) >= FAMILY_QUOTA["regulation_ecfr"]:
            break
        url = (
            "https://www.ecfr.gov/api/versioner/v1/versions/title-%s.json?part=%s"
            % (title, part)
        )
        rows = json.loads(p4c.fetch(url)).get("content_versions", [])
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
            time.sleep(p4c.PAUSE_SECONDS)
    return documents, excluded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acquisition", type=Path, default=NS / "receipts" / "p0-acquisition-manifest.json"
    )
    args = parser.parse_args()
    started = now()

    dart = p4c.probe_dart()
    documents = p4c.existing_documents(args.acquisition)
    ecfr, ecfr_excluded = ecfr_documents()
    wiki, wiki_excluded = wikipedia_documents()
    documents.extend(ecfr)
    documents.extend(wiki)

    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = list(ecfr_excluded) + list(wiki_excluded)

    for document in documents:
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
        canonical = {side: p4c.canonicalise(document, side, sides[side]) for side in sides}
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

    manifest = {
        "schema": "tavonel.v2.p4e_cohort.v1",
        "built_at": started,
        "ended_at": now(),
        "sources_declaration": rel(SOURCES),
        "revision_spacing": REVISION_SPACING,
        "selection_rule": SELECTION_RULE,
        "family_quota": FAMILY_QUOTA,
        "query_fields": QUERY_FIELDS,
        "redistribution": REDISTRIBUTION,
        "dart": dart,
        "documents": admitted,
        "excluded": excluded,
        "family_counts": {
            family: sum(1 for d in admitted if d["family"] == family)
            for family in sorted({d["family"] for d in admitted})
        },
        "document_count": len(admitted),
        "documents_sha256": canonical_sha(admitted),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    path = NS / "artifacts" / "development" / "p4e_cohort.json"
    path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    written = write_immutable(
        "p4e-cohort-manifest",
        {
            "schema": "tavonel.v2.p4e_cohort_receipt.v1",
            "manifest_path": rel(path),
            "documents_sha256": manifest["documents_sha256"],
            "document_count": len(admitted),
            "family_counts": manifest["family_counts"],
            "excluded_count": len(excluded),
            "dart": dart,
            "revision_spacing": REVISION_SPACING,
            "frozen_before_any_retrieval_result": True,
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
                "families": manifest["family_counts"],
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
