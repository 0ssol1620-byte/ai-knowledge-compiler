"""SEC EDGAR gold: form types from the dissemination index, values from inline XBRL.

Two independent SEC sources must agree before a number becomes gold: the
``ix:nonFraction`` tag in the filing's primary document, and the XBRL
``companyconcept`` API row for the same accession and period. A value only one
of them supports is dropped and counted, not kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from karena.corpus import CorpusError, Document, Licence
from karena.gold.fetch import Fetcher, FetchError
from karena.gold.htmltext import Parsed, fact_value, html_to_text, tidy

__all__ = [
    "CONCEPTS",
    "FORM_LABELS",
    "IndexRow",
    "SecFact",
    "parse_daily_index",
    "sec_user_agent",
]

FORM_LABELS: Final = {
    "10-K": "SEC_10K",
    "10-Q": "SEC_10Q",
    "8-K": "SEC_8K",
    "DEF 14A": "SEC_DEF14A",
    "S-1": "SEC_S1",
}
#: us-gaap concept -> (question label, unit). Fixed before any gold was read.
CONCEPTS: Final = {
    "Revenues": ("total revenues", "USD"),
    "RevenueFromContractWithCustomerExcludingAssessedTax": (
        "revenue from contracts with customers, excluding assessed tax",
        "USD",
    ),
    "NetIncomeLoss": ("net income (loss)", "USD"),
    "OperatingIncomeLoss": ("operating income (loss)", "USD"),
    "Assets": ("total assets", "USD"),
    "Liabilities": ("total liabilities", "USD"),
    "StockholdersEquity": ("total stockholders' equity", "USD"),
    "CashAndCashEquivalentsAtCarryingValue": ("cash and cash equivalents", "USD"),
    "EarningsPerShareBasic": ("basic earnings per share", "USD/shares"),
}
SEC_LICENCE_BASIS: Final = (
    "EDGAR public filing disseminated by the SEC; text authored by the filer. No licence "
    "grant exists; used only as public-record evaluation data, never redistributed."
)
INDEX_ROW: Final = re.compile(
    r"^(?P<form>\S.*?)\s{2,}(?P<company>\S.*?)\s{2,}(?P<cik>\d+)\s+(?P<date>\d{8})\s+"
    r"(?P<file>edgar/data/\S+\.txt)\s*$"
)
TABLE_WINDOW_MAX: Final = 6000
WINDOW_HALF: Final = 1500
LEAD_IN: Final = 400


def sec_user_agent() -> str:
    """SEC fair access requires a declared contact. It is configuration, never a default."""

    value = os.environ.get("KARENA_SEC_USER_AGENT", "").strip()
    if "@" not in value:
        raise CorpusError(
            "KARENA_SEC_USER_AGENT must be set to 'Organisation contact@domain' (SEC fair-access "
            "policy); the builder will not invent a contact"
        )
    return value


@dataclass(frozen=True, slots=True)
class IndexRow:
    form: str
    company: str
    cik: int
    date: str
    path: str

    @property
    def accession(self) -> str:
        return self.path.rsplit("/", 1)[1].removesuffix(".txt")


@dataclass(frozen=True, slots=True)
class SecFact:
    doc_id: str
    cik: int
    accession: str
    concept: str
    label: str
    unit: str
    value: Decimal
    displayed: str
    period_start: str | None
    period_end: str
    excerpt: str
    excerpt_offset: int
    companyconcept_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "cik": self.cik,
            "accession": self.accession,
            "concept": self.concept,
            "label": self.label,
            "unit": self.unit,
            "value": str(self.value),
            "displayed": self.displayed,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "excerpt": self.excerpt,
            "excerpt_offset": self.excerpt_offset,
            "companyconcept_url": self.companyconcept_url,
        }


def parse_daily_index(text: str) -> Iterator[IndexRow]:
    for line in text.splitlines():
        match = INDEX_ROW.match(line)
        if match is None:
            continue
        form = re.sub(r"\s+", " ", match["form"]).strip()
        yield IndexRow(
            form=form,
            company=match["company"].strip(),
            cik=int(match["cik"]),
            date=match["date"],
            path=match["file"],
        )


def daily_index_url(day: str) -> str:
    quarter = (int(day[4:6]) - 1) // 3 + 1
    return f"https://www.sec.gov/Archives/edgar/daily-index/{day[:4]}/QTR{quarter}/form.{day}.idx"


def order_key(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def primary_document(fetcher: Fetcher, row: IndexRow) -> str | None:
    submissions = json.loads(
        fetcher.get(f"https://data.sec.gov/submissions/CIK{row.cik:010d}.json").text()
    )
    recent = submissions.get("filings", {}).get("recent", {})
    for accession, primary in zip(
        recent.get("accessionNumber", []), recent.get("primaryDocument", []), strict=False
    ):
        if accession == row.accession and primary:
            return str(primary)
    return None


def fetch_filing(fetcher: Fetcher, row: IndexRow) -> tuple[Document, Parsed] | None:
    primary = primary_document(fetcher, row)
    if primary is None or not primary.lower().endswith((".htm", ".html")):
        return None
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{row.cik}/"
        f"{row.accession.replace('-', '')}/{primary}"
    )
    try:
        fetched = fetcher.get(url)
    except FetchError:
        return None
    parsed = html_to_text(fetched.text())
    if len(tidy(parsed.text)) < 500:
        return None
    document = Document(
        doc_id=f"sec:{row.accession}",
        origin="SEC",
        family_id=f"sec:cik:{row.cik}",
        label=FORM_LABELS[row.form],
        language="en",
        url=url,
        fetched_at=fetched.fetched_at,
        raw_sha256=fetched.sha256,
        text=parsed.text,
        licence=Licence(
            licence_id="SEC-EDGAR-PUBLIC-FILING",
            basis=SEC_LICENCE_BASIS,
            evidence=f"EDGAR dissemination index {row.date}, form {row.form}",
            source_url=url,
        ),
        meta={
            "cik": row.cik,
            "company": row.company,
            "form": row.form,
            "accession": row.accession,
            "date_filed": row.date,
        },
    )
    return document, parsed


def excerpt_for(parsed: Parsed, offset: int) -> tuple[str, int]:
    tables = [(s, e) for s, e in parsed.tables if s <= offset < e and e - s <= TABLE_WINDOW_MAX]
    if tables:
        start, end = max(tables, key=lambda span: span[0])
        start = max(0, start - LEAD_IN)
    else:
        start, end = max(0, offset - WINDOW_HALF), offset + WINDOW_HALF
    return parsed.text[start:end], start


def gold_facts(
    fetcher: Fetcher, document: Document, parsed: Parsed, *, per_filing: int
) -> tuple[list[SecFact], dict[str, int]]:
    """Facts both SEC sources agree on, first occurrence per concept, in document order."""

    counts = {
        "tagged": 0,
        "dimensional": 0,
        "unreadable": 0,
        "api_fetch_failed": 0,
        "api_missing": 0,
        "disagree": 0,
    }
    chosen: list[SecFact] = []
    seen: set[str] = set()
    cik = int(document.meta["cik"])
    accession = str(document.meta["accession"])
    for fact in parsed.facts:
        concept = fact.name.removeprefix("us-gaap:")
        if not fact.name.startswith("us-gaap:") or concept not in CONCEPTS or concept in seen:
            continue
        counts["tagged"] += 1
        context = parsed.contexts.get(fact.context_ref)
        if context is None or context.dimensional:
            counts["dimensional"] += 1
            continue
        value = fact_value(fact)
        end = context.end or context.instant
        if value is None or end is None:
            counts["unreadable"] += 1
            continue
        label, unit = CONCEPTS[concept]
        api_url = (
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"
        )
        try:
            api_value = _companyconcept_value(fetcher, api_url, unit, accession, context.start, end)
        except FetchError as exc:
            if exc.status != 404:
                counts["api_fetch_failed"] += 1  # operational, not a semantic absence
                continue
            api_value = None  # 404: the API has no such concept for this filer
        if api_value is None:
            counts["api_missing"] += 1
            continue
        if api_value != value:
            counts["disagree"] += 1
            continue
        excerpt, start = excerpt_for(parsed, fact.offset)
        excerpt = tidy(excerpt)
        seen.add(concept)
        chosen.append(
            SecFact(
                doc_id=document.doc_id,
                cik=cik,
                accession=accession,
                concept=concept,
                label=label,
                unit=unit,
                value=value,
                displayed=fact.displayed,
                period_start=context.start,
                period_end=end,
                excerpt=excerpt,
                excerpt_offset=start,
                companyconcept_url=api_url,
            )
        )
        if len(chosen) >= per_filing:
            break
    return chosen, counts


def _companyconcept_value(
    fetcher: Fetcher, url: str, unit: str, accession: str, start: str | None, end: str
) -> Decimal | None:
    try:
        body = json.loads(fetcher.get(url).text())
    except json.JSONDecodeError:
        return None
    rows: Sequence[dict[str, Any]] = body.get("units", {}).get(unit, [])
    for row in rows:
        if row.get("accn") == accession and row.get("end") == end and row.get("start") == start:
            return Decimal(str(row["val"]))
    return None
