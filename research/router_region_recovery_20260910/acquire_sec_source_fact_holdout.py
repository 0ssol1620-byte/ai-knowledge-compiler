"""Acquire the filing bytes selected by the frozen SEC holdout protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

USER_AGENT = "TAVONEL Research hello@tavonel.com"
CUTOFF = date(2026, 9, 10)
ISSUERS = (
    ("MSFT", "0000789019"),
    ("NVDA", "0001045810"),
    ("COST", "0000909832"),
    ("ADBE", "0000796343"),
    ("CRM", "0001108524"),
    ("ORCL", "0001341439"),
)
MIN_INTERVAL_SECONDS = 0.55
MAX_BYTES = 50 * 1024 * 1024


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class SecClient:
    session: requests.Session
    last_request: float = 0.0

    def get(self, url: str) -> tuple[bytes, dict[str, str]]:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=(15, 60), allow_redirects=False)
        self.last_request = time.monotonic()
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError("SEC_RESPONSE_TOO_LARGE")
        return response.content, {
            "content_type": response.headers.get("content-type", ""),
            "etag": response.headers.get("etag", ""),
            "last_modified": response.headers.get("last-modified", ""),
        }


def select_filing(payload: dict[str, Any]) -> dict[str, str] | None:
    recent = payload.get("filings", {}).get("recent", {})
    required = ("form", "filingDate", "accessionNumber", "primaryDocument")
    if not isinstance(recent, dict) or any(
        not isinstance(recent.get(key), list) for key in required
    ):
        raise ValueError("SEC_SUBMISSIONS_SCHEMA_INVALID")
    count = len(recent["form"])
    if any(len(recent[key]) != count for key in required):
        raise ValueError("SEC_SUBMISSIONS_COLUMNS_MISMATCH")
    candidates: list[dict[str, str]] = []
    for index in range(count):
        form = str(recent["form"][index])
        filing_date = str(recent["filingDate"][index])
        accession = str(recent["accessionNumber"][index])
        document = str(recent["primaryDocument"][index])
        if form != "10-Q" or not filing_date or date.fromisoformat(filing_date) > CUTOFF:
            continue
        if not accession or not document or "/" in document or "\\" in document:
            raise ValueError("SEC_PRIMARY_DOCUMENT_INVALID")
        candidates.append(
            {
                "form": form,
                "filing_date": filing_date,
                "accession": accession,
                "primary_document": document,
            }
        )
    return (
        max(candidates, key=lambda row: (row["filing_date"], row["accession"]))
        if candidates
        else None
    )


def repository_contains(repo: Path, needle: str) -> bool:
    command = [
        "rg",
        "-F",
        "-l",
        "--hidden",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/.chatgpt2codex/**",
        "--glob",
        "*.json",
        "--glob",
        "*.jsonl",
        "--glob",
        "*.md",
        needle,
        str(repo / "benchmark"),
        str(repo / "research"),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed rg argv, no shell
        command, capture_output=True, text=True, check=False
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError("REPOSITORY_EXCLUSION_SCAN_FAILED")
    return completed.returncode == 0


def run(args: argparse.Namespace) -> None:
    repo = args.repository.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("SEC_HOLDOUT_OUTPUT_MUST_BE_NEW")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        }
    )
    client = SecClient(session)
    artifacts: list[tuple[str, bytes]] = []
    records: list[dict[str, object]] = []
    for ticker, cik in ISSUERS:
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        submissions_bytes, submissions_headers = client.get(submissions_url)
        submissions = json.loads(submissions_bytes.decode("utf-8-sig"))
        filing = select_filing(submissions)
        record: dict[str, object] = {
            "ticker": ticker,
            "cik": cik,
            "company_name": submissions.get("name"),
            "submissions_url": submissions_url,
            "submissions_sha256": digest(submissions_bytes),
            "submissions_headers": submissions_headers,
            "status": "unresolved",
        }
        artifacts.append((f"submissions/{cik}.json", submissions_bytes))
        if filing is None:
            record["reason"] = "NO_ELIGIBLE_10_Q"
            records.append(record)
            continue
        accession = filing["accession"]
        if repository_contains(repo, accession):
            record.update(filing)
            record["reason"] = "ACCESSION_ALREADY_PRESENT"
            records.append(record)
            continue
        accession_compact = accession.replace("-", "")
        cik_compact = str(int(cik))
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_compact}/"
            f"{accession_compact}/{filing['primary_document']}"
        )
        html_bytes, html_headers = client.get(filing_url)
        html_sha = digest(html_bytes)
        if repository_contains(repo, html_sha):
            record.update(filing)
            record.update(
                filing_url=filing_url,
                filing_html_sha256=html_sha,
                reason="PRIMARY_DOCUMENT_SHA_ALREADY_PRESENT",
            )
            records.append(record)
            continue
        artifact_name = f"filings/{ticker}-{accession_compact}-{filing['primary_document']}"
        artifacts.append((artifact_name, html_bytes))
        record.update(
            filing,
            status="acquired",
            filing_url=filing_url,
            filing_html_sha256=html_sha,
            filing_html_bytes=len(html_bytes),
            filing_headers=html_headers,
            artifact_relative_path=artifact_name,
        )
        records.append(record)

    output.mkdir(parents=True)
    for relative, data in artifacts:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest_path = output / "FILINGS.jsonl"
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "issuers": len(ISSUERS),
        "status_counts": dict(
            sorted(
                {
                    status: sum(record["status"] == status for record in records)
                    for status in {str(record["status"]) for record in records}
                }.items()
            )
        ),
        "filings_manifest_sha256": digest(manifest_path.read_bytes()),
        "sec_user_agent": USER_AGENT,
        "maximum_requests_per_second": 1 / MIN_INTERVAL_SECONDS,
        "source_domains": ["data.sec.gov", "www.sec.gov"],
        "model_output_opened": False,
        "gpu_cost_usd": 0,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
