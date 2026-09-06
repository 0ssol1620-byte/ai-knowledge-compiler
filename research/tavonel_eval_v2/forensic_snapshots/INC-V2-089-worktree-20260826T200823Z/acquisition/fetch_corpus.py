#!/usr/bin/env python3
"""P0 step 4 -- CPU-only acquisition smoke for two source families.

Fetches raw bytes only. No parsing decision, no eligibility decision and no
equivalence computation happens here: this stage's single job is to put
verifiable revision pairs on disk with their digests and their provenance.

Network use is read-only HTTP GET against public endpoints. No credential is
sent, no GPU is touched and no paid API is called.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, now, rel, sha_bytes, write_hashed  # noqa: E402
from sources import (  # noqa: E402
    GIT_DOCS,
    REDISTRIBUTION,
    SEC_BASE_FORMS,
    SEC_ISSUERS,
)

USER_AGENT = "TAVONEL Research claude23@vieworks.com"
SEC_SLEEP = 0.4
GITHUB_SLEEP = 1.0


def get(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return handle.read()


def base_form(form: str) -> str:
    return form[:-2] if form.endswith("/A") else form


def sec_candidates(limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Amendment pairs, newest first, plus everything rejected and why."""
    pairs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for ticker, cik in SEC_ISSUERS:
        try:
            index = json.loads(get("https://data.sec.gov/submissions/CIK" + cik + ".json"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            rejected.append(
                {
                    "source_family": "sec_edgar",
                    "issuer": ticker,
                    "reason": "INELIGIBLE_FETCH",
                    "detail": type(error).__name__,
                }
            )
            continue
        time.sleep(SEC_SLEEP)
        recent = index["filings"]["recent"]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for position in range(len(recent["form"])):
            form = recent["form"][position]
            report_date = recent["reportDate"][position]
            if base_form(form) not in SEC_BASE_FORMS:
                continue
            if not report_date:
                # No period of report means the amendment relation would have to
                # be guessed from content. The protocol forbids that.
                continue
            grouped[(base_form(form), report_date)].append(
                {
                    "form": form,
                    "accession": recent["accessionNumber"][position],
                    "primary_document": recent["primaryDocument"][position],
                    "filing_date": recent["filingDate"][position],
                    "size": recent["size"][position],
                }
            )
        for (form, report_date), filings in grouped.items():
            originals = [item for item in filings if not item["form"].endswith("/A")]
            amendments = [item for item in filings if item["form"].endswith("/A")]
            if not originals or not amendments:
                continue
            if len(originals) > 1:
                rejected.append(
                    {
                        "source_family": "sec_edgar",
                        "issuer": ticker,
                        "form": form,
                        "report_date": report_date,
                        "reason": "INELIGIBLE_RELATION",
                        "detail": "more than one original for this period",
                    }
                )
                continue
            original = originals[0]
            amendment = sorted(amendments, key=lambda item: item["filing_date"])[0]
            pairs.append(
                {
                    "source_family": "sec_edgar",
                    "issuer": ticker,
                    "cik": cik,
                    "source_id": "sec:" + cik + ":" + form + ":" + report_date,
                    "base_form": form,
                    "report_date": report_date,
                    "before": original,
                    "after": amendment,
                    "relation_basis": (
                        "same CIK, same base form, same period of report, as published "
                        "in the issuer submissions index"
                    ),
                    "amendment_scope_verified": False,
                }
            )
    pairs.sort(key=lambda item: item["after"]["filing_date"], reverse=True)
    return pairs[:limit], rejected


def sec_document_url(cik: str, accession: str, document: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        + str(int(cik))
        + "/"
        + accession.replace("-", "")
        + "/"
        + document
    )


def git_candidates(per_file: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for entry in GIT_DOCS:
        url = (
            "https://api.github.com/repos/"
            + entry["owner"]
            + "/"
            + entry["repo"]
            + "/commits?per_page=30&path="
            + urllib.parse.quote(entry["path"])
        )
        try:
            commits = json.loads(get(url))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            rejected.append(
                {
                    "source_family": "git_docs",
                    "path": entry["path"],
                    "reason": "INELIGIBLE_FETCH",
                    "detail": type(error).__name__,
                }
            )
            continue
        time.sleep(GITHUB_SLEEP)
        if not isinstance(commits, list) or len(commits) < 2:
            rejected.append(
                {
                    "source_family": "git_docs",
                    "path": entry["path"],
                    "reason": "INELIGIBLE_RELATION",
                    "detail": "fewer than two commits touch this path",
                }
            )
            continue
        # commits[0] is newest. Consecutive commits touching this path are the
        # revision relation; the earlier of each adjacent pair is the before.
        taken = 0
        for position in range(min(len(commits) - 1, per_file * 2)):
            if taken >= per_file:
                break
            after = commits[position]
            before = commits[position + 1]
            pairs.append(
                {
                    "source_family": "git_docs",
                    "owner": entry["owner"],
                    "repo": entry["repo"],
                    "path": entry["path"],
                    "license": entry["license"],
                    "source_id": "git:"
                    + entry["owner"]
                    + "/"
                    + entry["repo"]
                    + ":"
                    + entry["path"],
                    "before": {
                        "sha": before["sha"],
                        "date": before["commit"]["committer"]["date"],
                    },
                    "after": {
                        "sha": after["sha"],
                        "date": after["commit"]["committer"]["date"],
                    },
                    "relation_basis": (
                        "consecutive commits touching this path, as listed by the "
                        "repository commit history for the path"
                    ),
                }
            )
            taken += 1
    return pairs, rejected


def raw_url_git(pair: dict[str, Any], side: str) -> str:
    return (
        "https://raw.githubusercontent.com/"
        + pair["owner"]
        + "/"
        + pair["repo"]
        + "/"
        + pair[side]["sha"]
        + "/"
        + pair["path"]
    )


def store(root: Path, pair_id: str, side: str, suffix: str, payload: bytes) -> dict[str, Any]:
    target = root / pair_id / (side + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"path": rel(target), "sha256": sha_bytes(payload), "bytes": len(payload)}


def acquire(split: str, sec_limit: int, git_per_file: int, output: Path) -> int:
    root = NS / "artifacts" / split / "raw"
    started = now()

    sec_pairs, sec_rejected = sec_candidates(sec_limit)
    git_pairs, git_rejected = git_candidates(git_per_file)

    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = [*sec_rejected, *git_rejected]

    for index, pair in enumerate(sec_pairs):
        pair_id = "sec-%03d-%s-%s" % (
            index,
            pair["issuer"].lower(),
            pair["base_form"].replace(" ", "").lower(),
        )
        try:
            before_bytes = get(
                sec_document_url(
                    pair["cik"], pair["before"]["accession"], pair["before"]["primary_document"]
                )
            )
            time.sleep(SEC_SLEEP)
            after_bytes = get(
                sec_document_url(
                    pair["cik"], pair["after"]["accession"], pair["after"]["primary_document"]
                )
            )
            time.sleep(SEC_SLEEP)
        except (urllib.error.URLError, TimeoutError) as error:
            rejected.append(
                {**pair, "pair_id": pair_id, "reason": "INELIGIBLE_FETCH", "detail": str(error)[:200]}
            )
            continue
        records.append(
            {
                "pair_id": pair_id,
                "group": "natural",
                "source_family": "sec_edgar",
                "source_id": pair["source_id"],
                "license": "US federal government work, public domain (17 USC 105)",
                "redistribution": REDISTRIBUTION,
                "relation_basis": pair["relation_basis"],
                "amendment_scope_verified": pair["amendment_scope_verified"],
                "before_version_id": pair["before"]["accession"],
                "after_version_id": pair["after"]["accession"],
                "before_known_at": pair["before"]["filing_date"],
                "after_known_at": pair["after"]["filing_date"],
                "valid_from": pair["report_date"],
                "before": store(root, pair_id, "before", ".html", before_bytes),
                "after": store(root, pair_id, "after", ".html", after_bytes),
            }
        )

    for index, pair in enumerate(git_pairs):
        pair_id = "git-%03d-%s-%s" % (
            index,
            pair["repo"],
            Path(pair["path"]).stem.replace("_", "-"),
        )
        try:
            before_bytes = get(raw_url_git(pair, "before"))
            after_bytes = get(raw_url_git(pair, "after"))
        except (urllib.error.URLError, TimeoutError) as error:
            rejected.append(
                {**pair, "pair_id": pair_id, "reason": "INELIGIBLE_FETCH", "detail": str(error)[:200]}
            )
            continue
        records.append(
            {
                "pair_id": pair_id,
                "group": "natural",
                "source_family": "git_docs",
                "source_id": pair["source_id"],
                "license": pair["license"],
                "redistribution": REDISTRIBUTION,
                "relation_basis": pair["relation_basis"],
                "before_version_id": pair["before"]["sha"],
                "after_version_id": pair["after"]["sha"],
                "before_known_at": pair["before"]["date"],
                "after_known_at": pair["after"]["date"],
                "valid_from": None,
                "before": store(root, pair_id, "before", ".md", before_bytes),
                "after": store(root, pair_id, "after", ".md", after_bytes),
            }
        )

    # Identical bytes are an eligibility exclusion, decided here, before any
    # downstream stage has seen a result.
    admitted: list[dict[str, Any]] = []
    for record in records:
        if record["before"]["sha256"] == record["after"]["sha256"]:
            rejected.append(
                {
                    "pair_id": record["pair_id"],
                    "source_family": record["source_family"],
                    "reason": "INELIGIBLE_IDENTICAL_BYTES",
                }
            )
            continue
        admitted.append(record)

    body: dict[str, Any] = {
        "schema": "tavonel.v2.acquisition_manifest.v1",
        "split": split,
        "started_at": started,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p0-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "selection_rule": {
            "sec_edgar": (
                "for each declared issuer, group filings by (base form, period of "
                "report) over the submissions index; admit a group holding exactly "
                "one original and at least one amendment; take the earliest "
                "amendment; sort admitted pairs by amendment filing date descending "
                "and keep the first %d" % sec_limit
            ),
            "git_docs": (
                "for each declared path, take the %d most recent adjacent commit "
                "pairs touching that path" % git_per_file
            ),
        },
        "sources_module_sha256": sha_bytes(
            (Path(__file__).resolve().parent / "sources.py").read_bytes()
        ),
        "fetcher_sha256": sha_bytes(Path(__file__).resolve().read_bytes()),
        "admitted_pair_count": len(admitted),
        "family_counts": {
            family: sum(1 for item in admitted if item["source_family"] == family)
            for family in sorted({item["source_family"] for item in admitted})
        },
        "rejected": rejected,
        "pairs": admitted,
        "network_reads_only": True,
        "credentials_sent": False,
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "admitted": len(admitted),
                "families": body["family_counts"],
                "rejected": len(rejected),
                "manifest": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="development")
    parser.add_argument("--sec-limit", type=int, default=10)
    parser.add_argument("--git-per-file", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p0-acquisition-manifest.json"
    )
    args = parser.parse_args()
    return acquire(args.split, args.sec_limit, args.git_per_file, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
