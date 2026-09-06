#!/usr/bin/env python3
"""VBC2 acquisition: walk each frozen lineage's history for a value transition.

One lineage at a time, newest revision first, adjacent pair by adjacent pair,
stopping at the first pair across which a stable property's value actually
moved. That pair is the acquisition unit. The walk is not a search for the best
transition — it is the newest one, and stopping early is what keeps the choice
deterministic and cheap.

Three boundaries are worth naming because they are what make this case
ascertainment rather than outcome fitting:

* the predicate is the frozen `ValueFact` extractor and nothing else. No
  retrieval score, no coverage result and no model output is visible here.
* the pair brackets *consecutive* observed revisions, so the contrast carries as
  few unrelated edits as the source allows.
* the selector reads values; the query generator never does. They are separate
  stages so that boundary can be tested rather than promised.

CPU and network reads only. No GPU, no spend.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "acquisition"))
sys.path.insert(0, str(HERE.parents[0] / "canonicalization"))
sys.path.insert(0, str(HERE.parents[0] / "endpoint"))

import fetch_p4c_corpus as p4c  # noqa: E402
import fetch_p4g_corpus as p4g  # noqa: E402
from common import NS, canonical_sha, now, rel, sha_bytes, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_vbc2 import (  # noqa: E402
    ADMISSION_FAILURE_CODES,
    CONSUMPTION_ORDER,
    FAMILY_QUOTA,
    FAMILY_SHARE,
    HISTORY,
    PRIMARY_TARGET,
)
from value_fact import (  # noqa: E402
    atom_contrast_is_single,
    contrast,
    observations,
    property_id,
)

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V2.yaml"
LINEAGES = NS / "artifacts" / "development" / "vbc2_lineages.json"
RAW = NS / "artifacts" / "development" / "raw_vbc2"
CANONICAL = NS / "artifacts" / "development" / "canonical_vbc2"
MANIFEST = NS / "artifacts" / "development" / "vbc2_cohort.json"

MAX_REVISIONS = HISTORY["max_revisions_inspected_per_lineage"]
CUTOFF = _dt.datetime.fromisoformat(HISTORY["acquisition_cutoff"].replace("Z", "+00:00"))
HORIZON = CUTOFF - _dt.timedelta(days=HISTORY["horizon_days"])

NO_TRANSITION = "NO_QUALIFYING_TRANSITION"
TOO_FEW = "TOO_FEW_REVISIONS"
LISTING_FAILED = "LISTING_FAILED"
PAYLOAD_UNAVAILABLE = "PAYLOAD_UNAVAILABLE"
PARSE_FLOOR = "PARSE_FLOOR"


def _in_window(stamp: str) -> bool:
    try:
        moment = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return HORIZON <= moment <= CUTOFF


# --- revision enumeration, newest first ---------------------------------------


def git_revisions(lineage: dict[str, Any]) -> list[dict[str, str]]:
    url = "https://api.github.com/repos/%s/%s/commits?per_page=%d&path=%s" % (
        lineage["owner"],
        lineage["repo"],
        MAX_REVISIONS,
        urllib.parse.quote(lineage["path"]),
    )
    commits = p4g.gh(url)
    time.sleep(p4g.PAUSE)
    rows = []
    for commit in commits if isinstance(commits, list) else []:
        stamp = commit["commit"]["committer"]["date"]
        if not _in_window(stamp):
            continue
        rows.append(
            {
                "version": commit["sha"],
                "known_at": stamp,
                "url": "https://raw.githubusercontent.com/%s/%s/%s/%s"
                % (lineage["owner"], lineage["repo"], commit["sha"], lineage["path"]),
            }
        )
    return rows[:MAX_REVISIONS]


def ecfr_revisions(lineage: dict[str, Any]) -> list[dict[str, str]]:
    url = "https://www.ecfr.gov/api/versioner/v1/versions/title-%s.json?part=%s" % (
        lineage["title"],
        lineage["part"],
    )
    rows = json.loads(p4c.fetch(url)).get("content_versions", [])
    time.sleep(p4g.PAUSE)
    dates = sorted(
        {
            row["date"]
            for row in rows
            if row.get("type") == "section"
            and not row.get("removed")
            and row["identifier"] == lineage["identifier"]
        },
        reverse=True,
    )
    dates = [date for date in dates if _in_window(date + "T00:00:00Z")]
    return [
        {
            "version": date,
            "known_at": date,
            "url": "https://www.ecfr.gov/api/versioner/v1/full/%s/title-%s.xml?part=%s&section=%s"
            % (date, lineage["title"], lineage["part"], lineage["identifier"]),
        }
        for date in dates[:MAX_REVISIONS]
    ]


def wikipedia_revisions(lineage: dict[str, Any]) -> list[dict[str, str]]:
    url = (
        "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=%s"
        "&rvlimit=%d&rvprop=ids%%7Ctimestamp&format=json&formatversion=2"
        % (urllib.parse.quote(lineage["article"]), MAX_REVISIONS)
    )
    pages = json.loads(p4c.fetch(url)).get("query", {}).get("pages", [])
    time.sleep(p4g.PAUSE)
    revisions = pages[0].get("revisions", []) if pages else []
    return [
        {
            "version": str(revision["revid"]),
            "known_at": revision["timestamp"],
            "url": "https://en.wikipedia.org/w/api.php?action=parse&oldid=%s"
            "&prop=text&format=json&formatversion=2" % revision["revid"],
        }
        for revision in revisions
        if _in_window(revision["timestamp"])
    ][:MAX_REVISIONS]


def sec_revisions(lineage: dict[str, Any]) -> list[dict[str, str]]:
    index = json.loads(p4c.fetch("https://data.sec.gov/submissions/CIK" + lineage["cik"] + ".json"))
    time.sleep(p4g.PAUSE)
    recent = index["filings"]["recent"]
    rows = []
    for position in range(len(recent["form"])):
        if p4g._base_form(recent["form"][position]) != lineage["form"]:
            continue
        stamp = recent["filingDate"][position]
        if not _in_window(stamp + "T00:00:00Z"):
            continue
        accession = recent["accessionNumber"][position].replace("-", "")
        rows.append(
            {
                "version": recent["accessionNumber"][position],
                "known_at": stamp,
                "url": "https://www.sec.gov/Archives/edgar/data/%s/%s/%s"
                % (int(lineage["cik"]), accession, recent["primaryDocument"][position]),
            }
        )
    return rows[:MAX_REVISIONS]


ENUMERATORS = {
    "git_docs": git_revisions,
    "regulation_ecfr": ecfr_revisions,
    "encyclopedia_wikipedia": wikipedia_revisions,
    "sec_edgar": sec_revisions,
}


# --- the walk -------------------------------------------------------------------


def _payload(lineage: dict[str, Any], revision: dict[str, str]) -> bytes:
    document = {"fetch": {"only": revision["url"]}, "family": lineage["family"]}
    if lineage["family"] == "encyclopedia_wikipedia":
        document["unwrap"] = "parse.text"
    return p4c.payload_for(document, "only")


def _state(lineage: dict[str, Any], raw: bytes) -> dict[str, dict[str, Any]]:
    return observations(
        raw.decode("utf-8", errors="replace"), lineage["suffix"], lineage["lineage_id"]
    )


def qualifying(after: dict[str, Any], before: dict[str, Any]) -> list[dict[str, Any]]:
    """Properties whose value moved across this adjacent pair, and only those."""
    found: list[dict[str, Any]] = []
    for key, current in after.items():
        superseded = before.get(key)
        if superseded is None:
            continue
        if current["value_kind"] != superseded["value_kind"]:
            continue
        pair = contrast(current["value_text"], superseded["value_text"])
        if not pair["distinguishable"]:
            continue
        if current["value"] == superseded["value"]:
            continue
        found.append(
            {
                "property_id": key,
                "property_label": current["property_label"],
                "column_label": current["column_label"],
                "heading_path": current["heading_path"],
                "value_kind": current["value_kind"],
                "current_value": current["value"],
                "superseded_value": superseded["value"],
                "current_value_text": current["value_text"],
                "superseded_value_text": superseded["value_text"],
            }
        )
    #: deterministic, content-derived, fixed before any value was read
    return sorted(found, key=lambda item: item["property_id"])


def walk(lineage: dict[str, Any]) -> dict[str, Any]:
    """Newest adjacent pair carrying a qualifying transition, or a reason code."""
    revisions = ENUMERATORS[lineage["family"]](lineage)
    if len(revisions) < 2:
        return {"code": TOO_FEW, "revisions_seen": len(revisions)}
    cache: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    inspected = 0
    for index in range(len(revisions) - 1):
        after, before = revisions[index], revisions[index + 1]
        for revision in (after, before):
            if revision["version"] in cache:
                continue
            raw = _payload(lineage, revision)
            payloads[revision["version"]] = raw
            cache[revision["version"]] = _state(lineage, raw)
            inspected += 1
        transitions = qualifying(cache[after["version"]], cache[before["version"]])
        if transitions:
            return {
                "code": None,
                "after": after,
                "before": before,
                "adjacent": True,
                "adjacency_index": index,
                "revisions_seen": len(revisions),
                "revisions_inspected": inspected,
                "transitions": transitions,
                "payloads": {
                    "after": payloads[after["version"]],
                    "before": payloads[before["version"]],
                },
            }
    return {
        "code": NO_TRANSITION,
        "revisions_seen": len(revisions),
        "revisions_inspected": inspected,
    }


def _record(lineage: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    after, before = found["after"], found["before"]
    return {
        "family": lineage["family"],
        "container": lineage.get("container", ""),
        "container_name": lineage.get("container_name", lineage.get("container", "")),
        "document_id": lineage["lineage_id"],
        "lineage_id": lineage["lineage_id"],
        "title_field": lineage.get("article")
        or lineage.get("container_name")
        or lineage.get("path", lineage["lineage_id"]),
        "doc_type": {
            "git_docs": "markdown documentation",
            "regulation_ecfr": "Code of Federal Regulations section",
            "encyclopedia_wikipedia": "encyclopedia article",
            "sec_edgar": "SEC filing",
        }[lineage["family"]],
        "spoken_type": lineage["family"],
        "identity": lineage.get("article") or lineage["lineage_id"],
        "licence": lineage["licence"],
        "suffix": lineage["suffix"],
        "before_version": before["version"],
        "after_version": after["version"],
        "before_known_at": before["known_at"],
        "after_known_at": after["known_at"],
        "adjacent_pair": True,
        "adjacency_index": found["adjacency_index"],
        "revisions_seen": found["revisions_seen"],
        "revisions_inspected": found["revisions_inspected"],
        "fetch": {"before": before["url"], "after": after["url"]},
        **({"unwrap": "parse.text"} if lineage["family"] == "encyclopedia_wikipedia" else {}),
    }


def interleave(lineages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin across families, declared order preserved inside each one.

    This is a scheduling decision and not a selection one. Quotas are per family
    and each family is consumed in its frozen order, so the admitted set is
    identical to walking the families one after another — only the wall-clock
    order changes. What it buys is that a run interrupted partway through has
    seen every family rather than only the first, which is the difference
    between a partial result that can be read and one that cannot.

    It is recorded in the receipt for the same reason: an ordering that affects
    nothing still has to be visible, or a later reader cannot verify that it
    affected nothing.
    """
    queues: dict[str, list[dict[str, Any]]] = {}
    for lineage in lineages:
        queues.setdefault(lineage["family"], []).append(lineage)
    order = [family for family in FAMILY_QUOTA if family in queues]
    out: list[dict[str, Any]] = []
    position = 0
    while any(len(queue) > position for queue in queues.values()):
        for family in order:
            queue = queues[family]
            if position < len(queue):
                out.append(queue[position])
        position += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--budget-seconds",
        type=int,
        default=0,
        help="wall-clock stop. Recorded in the receipt when it fires; never silent.",
    )
    args = parser.parse_args()
    started = now()

    clock_started = time.monotonic()
    stopped_on_budget = False
    frozen = json.loads(LINEAGES.read_text(encoding="utf-8"))
    lineages = interleave(frozen["lineages"])
    admitted: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_family: Counter[str] = Counter()
    seen_lineages: set[str] = set()

    for position, lineage in enumerate(lineages):
        if args.limit and position >= args.limit:
            break
        if args.budget_seconds and time.monotonic() - clock_started > args.budget_seconds:
            stopped_on_budget = True
            break
        if all(per_family[name] >= FAMILY_QUOTA[name] for name in FAMILY_QUOTA):
            # every quota is met; walking further would spend network to fill
            # nothing. Recorded rather than left as an unexplained early exit.
            rejected.append({"lineage_id": lineage["lineage_id"], "code": "BEYOND_FAMILY_QUOTA"})
            continue
        family = lineage["family"]
        if per_family[family] >= FAMILY_QUOTA[family]:
            rejected.append({"lineage_id": lineage["lineage_id"], "code": "BEYOND_FAMILY_QUOTA"})
            continue
        if lineage["lineage_id"] in seen_lineages:
            rejected.append({"lineage_id": lineage["lineage_id"], "code": "OTHER"})
            continue
        try:
            found = walk(lineage)
        except Exception as error:
            rejected.append(
                {
                    "lineage_id": lineage["lineage_id"],
                    "code": LISTING_FAILED
                    if "HTTP" not in type(error).__name__
                    else PAYLOAD_UNAVAILABLE,
                    "error": type(error).__name__,
                }
            )
            continue
        if found["code"] is not None:
            rejected.append({"lineage_id": lineage["lineage_id"], "code": found["code"]})
            continue

        record = _record(lineage, found)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", record["document_id"]).strip("-").lower()[:80]
        record["document_slug"] = slug
        try:
            canonical = {
                side: p4c.canonicalise(record, side, found["payloads"][side])
                for side in ("before", "after")
            }
        except Exception as error:
            rejected.append(
                {
                    "lineage_id": lineage["lineage_id"],
                    "code": PARSE_FLOOR,
                    "error": type(error).__name__,
                }
            )
            continue
        if any(len(value["units"]) < p4g.MIN_UNITS for value in canonical.values()):
            rejected.append({"lineage_id": lineage["lineage_id"], "code": PARSE_FLOOR})
            continue

        for side in ("before", "after"):
            raw_path = RAW / slug / (side + record["suffix"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(found["payloads"][side])
            canonical_path = CANONICAL / slug / (side + ".json")
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                json.dumps(canonical[side], sort_keys=True, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            record[side] = {
                "raw_path": rel(raw_path),
                "raw_sha256": sha_bytes(found["payloads"][side]),
                "canonical_path": rel(canonical_path),
                "unit_count": len(canonical[side]["units"]),
            }

        transitions = found["transitions"]
        primary.append({**transitions[0], "lineage_id": lineage["lineage_id"], "slug": slug})
        diagnostics.extend(
            {**item, "lineage_id": lineage["lineage_id"], "excluded_from": "primary McNemar sample"}
            for item in transitions[1:]
        )
        admitted.append(record)
        seen_lineages.add(lineage["lineage_id"])
        per_family[family] += 1
        if len(admitted) % 10 == 0:
            print(
                json.dumps({"stage": "walk", "position": position, "admitted": len(admitted)}),
                flush=True,
            )

    lineage_ids = [row["lineage_id"] for row in primary]
    body = {
        "schema": "tavonel.v2.vbc2_cohort.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "started_at": started,
        "ended_at": now(),
        "lineage_list": rel(LINEAGES),
        "history_bounds": HISTORY,
        "family_share": FAMILY_SHARE,
        "family_quota": FAMILY_QUOTA,
        "primary_target": PRIMARY_TARGET,
        "consumption_order": CONSUMPTION_ORDER,
        "documents": admitted,
        "document_count": len(admitted),
        "documents_sha256": canonical_sha(admitted),
        "primary_transitions": primary,
        "primary_count": len(primary),
        "diagnostic_transitions": diagnostics,
        "diagnostic_count": len(diagnostics),
        "by_family": dict(per_family),
        "rejected": rejected[:4000],
        "rejected_count": len(rejected),
        "rejected_by_code": dict(Counter(row["code"] for row in rejected)),
        "admission_failure_codes": list(ADMISSION_FAILURE_CODES),
        "one_question_per_lineage": {
            "primary_questions": len(primary),
            "distinct_lineages": len(set(lineage_ids)),
            "holds": len(primary) == len(set(lineage_ids)),
        },
        "all_pairs_adjacent": all(row["adjacent_pair"] for row in admitted),
        "walk_coverage": {
            "family_scheduling": (
                "round robin across families, declared order preserved within each. "
                "Per-family quotas make the admitted set identical to sequential "
                "walking; only wall-clock order and partial-run composition change."
            ),
            "lineages_available": len(lineages),
            "lineages_considered": position + 1 if lineages else 0,
            "stopped_on_wall_clock_budget": stopped_on_budget,
            "budget_seconds": args.budget_seconds or None,
            "note": (
                "a wall-clock stop is a coverage limit, not a source property. It is "
                "reported here so an admitted count is never read as an exhausted list."
            ),
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    written = write_immutable(
        "vbc2-cohort",
        {
            **{k: v for k, v in body.items() if k not in ("documents", "rejected")},
            "manifest_path": rel(MANIFEST),
        },
        tool=Path(__file__).resolve(),
        protocol=PROTOCOL,
    )
    print(
        json.dumps(
            {
                **written,
                "admitted": len(admitted),
                "by_family": dict(per_family),
                "rejected_by_code": body["rejected_by_code"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
