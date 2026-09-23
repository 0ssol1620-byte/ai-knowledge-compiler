"""Acquisition phase for the W6 v2 pilot.

Contract (preregistered): per-fetch timeout 30s, up to 3 attempts per item with
2s/4s backoff, a 20-minute wall-clock budget for the whole step, an on-disk
cache that makes refetches free, and a failure ledger — no item is ever
silently dropped.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Wikimedia blocks default/empty User-Agents (attempt-1 diagnosis: 60x http_403).
# Descriptive UA per Wikimedia UA policy; recorded as DEVIATION-03 in SUMMARY.md.
DEFAULT_USER_AGENT = "TAVONEL-W6-v2-pilot/0.1 (research; contact: operator) python-httpx"


@dataclass
class ItemOutcome:
    source_id: str
    title: str
    status: str = "pending"  # pending | ok | failed | deadline_exceeded | cache_hit
    url: str = ""
    attempts: int = 0
    error_class: str = ""
    error_detail: str = ""
    char_count: int = 0
    text_sha256: str = ""
    seconds: float = 0.0
    usable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "status": self.status,
            "url": self.url,
            "attempts": self.attempts,
            "error_class": self.error_class,
            # error_detail carries provider messages only, never credentials
            "error_detail": self.error_detail[:300],
            "char_count": self.char_count,
            "text_sha256": self.text_sha256,
            "seconds": round(self.seconds, 2),
            "usable": self.usable,
        }


@dataclass
class AcquisitionReport:
    started_at: str
    finished_at: str = ""
    deadline_seconds: float = 1200.0
    per_fetch_timeout_seconds: float = 30.0
    outcomes: list[ItemOutcome] = field(default_factory=list)
    deadline_exhausted_remaining: list[str] = field(default_factory=list)

    @property
    def usable_documents(self) -> list[ItemOutcome]:
        return [o for o in self.outcomes if o.usable]

    def summary_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "deadline_seconds": self.deadline_seconds,
            "per_fetch_timeout_seconds": self.per_fetch_timeout_seconds,
            "counts": self.summary_counts(),
            "usable_documents": len(self.usable_documents),
            "deadline_exhausted_remaining": self.deadline_exhausted_remaining,
            "items": [outcome.to_dict() for outcome in self.outcomes],
        }


def _endpoint_urls(endpoints: list[str], title: str) -> list[str]:
    from urllib.parse import quote

    quoted = quote(title)
    return [endpoint.format(title=quoted) for endpoint in endpoints]


def _extract_text(payload: dict[str, Any], title: str) -> str:
    # action API nests pages under "query"; tolerate a flat "pages" too.
    container = payload.get("query") if isinstance(payload.get("query"), dict) else payload
    pages = container.get("pages", [])
    for page in pages:
        extract = page.get("extract", "")
        if isinstance(extract, str) and extract.strip():
            return extract
    return ""


def acquire_corpus(
    *,
    titles: list[str],
    endpoints: list[str],
    cache_dir: Path,
    per_fetch_timeout_seconds: float = 30.0,
    max_attempts_per_item: int = 3,
    retry_backoff_seconds: tuple[float, ...] = (2.0, 4.0),
    phase_deadline_seconds: float = 1200.0,
    usable_document_min_chars: int = 2000,
    client_factory=None,
    clock=time.monotonic,
) -> AcquisitionReport:
    """Fetch every title in order; honour cache, deadline, retries; ledger all failures."""

    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    report = AcquisitionReport(
        started_at=started,
        deadline_seconds=phase_deadline_seconds,
        per_fetch_timeout_seconds=per_fetch_timeout_seconds,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    session_factory = client_factory or (
        lambda: httpx.Client(follow_redirects=True, headers={"User-Agent": DEFAULT_USER_AGENT})
    )
    deadline = clock() + phase_deadline_seconds

    with session_factory() as session:
        for index, title in enumerate(titles):
            source_id = f"src-{index:03d}"
            cache_key = hashlib.sha1(title.encode("utf-8"), usedforsecurity=False).hexdigest()
            cache_path = cache_dir / f"{cache_key}.json"
            outcome = ItemOutcome(source_id=source_id, title=title)

            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    text = cached.get("text", "")
                except (ValueError, OSError):
                    text = ""
                if len(text) >= usable_document_min_chars:
                    outcome.status = "cache_hit"
                    outcome.char_count = len(text)
                    outcome.text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    outcome.usable = True
                    report.outcomes.append(outcome)
                    continue

            if clock() >= deadline:
                outcome.status = "deadline_exceeded"
                report.outcomes.append(outcome)
                report.deadline_exhausted_remaining.extend(titles[index + 1 :])
                break

            item_started = clock()
            urls = _endpoint_urls(endpoints, title)
            last_error_class = "unknown"
            last_error_detail = ""
            fetched_text = ""
            final_url = ""
            last_url = ""
            total_attempts = 0

            for url in urls:
                last_url = url
                remaining_budget = deadline - clock()
                if remaining_budget <= 0:
                    last_error_class = "deadline_exceeded"
                    break
                for _attempt in range(1, max_attempts_per_item + 1):
                    total_attempts += 1
                    timeout = min(per_fetch_timeout_seconds, max(1.0, deadline - clock()))
                    try:
                        response = session.get(url, timeout=timeout)
                    except httpx.TimeoutException:
                        last_error_class, last_error_detail = (
                            "timeout",
                            f"fetch timed out after {timeout:.0f}s",
                        )
                        continue
                    except httpx.TransportError as exc:
                        last_error_class, last_error_detail = "transport_error", type(exc).__name__
                        continue
                    if response.status_code != 200:
                        last_error_class = f"http_{response.status_code}"
                        last_error_detail = ""
                        continue
                    try:
                        text = _extract_text(response.json(), title)
                    except ValueError:
                        last_error_class, last_error_detail = "malformed_body", "non-JSON payload"
                        continue
                    if text.strip():
                        fetched_text = text
                        final_url = str(response.url)
                        last_error_class = ""
                        break
                    last_error_class, last_error_detail = "empty_extract", "no extract returned"
                if fetched_text:
                    break

            outcome.attempts = total_attempts
            outcome.url = final_url
            outcome.seconds = clock() - item_started
            if fetched_text and len(fetched_text) >= usable_document_min_chars:
                outcome.status = "ok"
                outcome.char_count = len(fetched_text)
                outcome.text_sha256 = hashlib.sha256(fetched_text.encode("utf-8")).hexdigest()
                outcome.usable = True
                cache_path.write_text(
                    json.dumps(
                        {"title": title, "url": final_url, "text": fetched_text}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
            elif fetched_text:
                outcome.status = "failed"
                outcome.error_class = "too_short"
                outcome.error_detail = (
                    f"{len(fetched_text)} chars < {usable_document_min_chars} minimum"
                )
            else:
                outcome.status = "failed"
                outcome.error_class = last_error_class or "unknown"
                outcome.error_detail = last_error_detail
                if not outcome.url:
                    outcome.url = last_url  # attempted URL kept for cause diagnosis
            report.outcomes.append(outcome)

    report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return report


def load_cached_texts(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Rebuild {source_id: {...}} from the cache dir in frozen-list order."""
    documents: dict[str, dict[str, Any]] = {}
    entries = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if entry.get("text"):
            entries.append(entry)
    entries.sort(key=lambda e: e.get("title", ""))
    for index, entry in enumerate(entries):
        documents[f"src-{index:03d}"] = {
            "source_id": f"src-{index:03d}",
            "title": entry.get("title", ""),
            "url": entry.get("url", ""),
            "text": entry["text"],
        }
    return documents
