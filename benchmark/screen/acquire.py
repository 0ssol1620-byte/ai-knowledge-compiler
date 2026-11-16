"""Rights-checked, paced acquisition of screen-corpus sources from an explicit URL list.

CSV columns: url, source_family, licence (a key under that family's `licences` in sources.yaml).
Bytes go to a corpus root outside the repository; one JSONL record per document carries the
rights fields of the screen manifest. Rights decisions are not made here (see sources.yaml).
"""

from __future__ import annotations

import csv
import email.utils
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_PATH = Path(__file__).with_name("sources.yaml")
MAX_BYTES = 200 * 1024 * 1024
MAX_RETRIES = 3
MAX_RETRY_AFTER_S = 300.0


class AcquireError(Exception):
    """A source was refused or could not be acquired; nothing is written for it."""


def load_families(path: Path = SOURCES_PATH) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))[
        "families"
    ]
    return families


def check_corpus_root(root: Path) -> Path:
    root = root.resolve()
    if root == REPO_ROOT or REPO_ROOT in root.parents:
        raise AcquireError(f"corpus root must be outside the repository: {root}")
    return root


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    if value.strip().isdigit():
        return float(value)
    parsed = email.utils.parsedate_to_datetime(value)
    return max(0.0, (parsed - datetime.now(UTC)).total_seconds())


class PacedClient:
    """GET with a descriptive User-Agent, a minimum interval, and Retry-After honoured."""

    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx.BaseTransport | None = None,
        min_interval_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise AcquireError("a descriptive User-Agent is required")
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            transport=transport,
            follow_redirects=False,
            timeout=60,
        )
        self._interval = min_interval_s
        self._sleep = sleep
        self._last = 0.0

    def get(self, url: str) -> bytes:
        for attempt in range(MAX_RETRIES + 1):
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            with self._http.stream("GET", url) as resp:
                if resp.status_code in (429, 503):
                    delay = _retry_after(resp.headers.get("Retry-After"))
                    if delay is None:
                        delay = self._interval * 2**attempt
                    if delay > MAX_RETRY_AFTER_S or attempt == MAX_RETRIES:
                        raise AcquireError(
                            f"{url}: HTTP {resp.status_code}, giving up (wait {delay:.0f}s)"
                        )
                    self._sleep(delay)
                    continue
                if resp.status_code != 200:
                    raise AcquireError(f"{url}: HTTP {resp.status_code}")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise AcquireError(f"{url}: larger than {MAX_BYTES} bytes")
                return bytes(body)
        raise AcquireError(f"{url}: unreachable")


def _check_row(
    row: dict[str, str], families: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], str]:
    fam = families.get(row["source_family"])
    if fam is None:
        raise AcquireError(f"source family not on the allowlist: {row['source_family']!r}")
    if not fam["download"]:
        raise AcquireError(
            f"family {row['source_family']!r} is not downloaded by URL; ingest it locally"
        )
    licence_url = fam["licences"].get(row["licence"])
    if licence_url is None:
        raise AcquireError(
            f"licence {row['licence']!r} is not allowed for {row['source_family']!r}"
        )
    u = urlparse(row["url"])
    if u.scheme != "https" or u.hostname not in fam["hosts"]:
        raise AcquireError(f"url host not allowed for {row['source_family']!r}: {row['url']}")
    return fam, licence_url


def acquire(
    csv_path: Path,
    corpus_root: Path,
    out_jsonl: Path,
    client: PacedClient,
    *,
    recorded_by: str,
    families: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Acquire every row. All rows are validated before the first request."""
    root = check_corpus_root(corpus_root)
    families = families or load_families()
    with csv_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if set(row) != {"url", "source_family", "licence"}:
            raise AcquireError("csv columns must be exactly: url, source_family, licence")
        _check_row(row, families)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "licences").mkdir(exist_ok=True)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    snapshots: dict[str, str] = {}
    for row in rows:
        fam, licence_url = _check_row(row, families)
        if licence_url not in snapshots:
            snap = client.get(licence_url)
            if not snap:
                raise AcquireError(f"empty licence snapshot: {licence_url}")
            snapshots[licence_url] = hashlib.sha256(snap).hexdigest()
            (root / "licences" / f"{snapshots[licence_url]}.html").write_bytes(snap)
        data = client.get(row["url"])
        if not data:
            raise AcquireError(f"empty download: {row['url']}")
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        suffix = Path(urlparse(row["url"]).path).suffix[:8]
        (root / "docs" / f"{sha}{suffix}").write_bytes(data)
        records.append(
            {
                "doc_id": f"d-{sha[:16]}",
                "source_sha256": sha,
                "byte_size": len(data),
                "rights": {
                    "source_url": row["url"],
                    "licence_id": row["licence"],
                    "licence_snapshot_sha256": snapshots[licence_url],
                    "rights_class": fam["rights_class"],
                    "redistribution": "unreviewed",
                    "recorded_by": recorded_by,
                    "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            }
        )
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return records
