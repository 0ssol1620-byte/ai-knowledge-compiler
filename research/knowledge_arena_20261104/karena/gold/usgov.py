"""US Government gold: Federal Register document types from the FR API.

The type label is the Office of the Federal Register's own classification
(``Rule``, ``Proposed Rule``, ``Notice``, ``Presidential Document``), so it costs
no annotation and carries no judgement of ours.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from typing import Any, Final
from urllib.parse import urlencode

from karena.corpus import Document, Licence
from karena.gold.fetch import Fetcher, FetchError
from karena.gold.htmltext import html_to_text

__all__ = ["FR_TYPES", "fr_documents"]

FR_TYPES: Final = {
    "RULE": "FR_RULE",
    "PRORULE": "FR_PROPOSED_RULE",
    "NOTICE": "FR_NOTICE",
    "PRESDOCU": "FR_PRESIDENTIAL_DOCUMENT",
}
FR_FIELDS: Final = (
    "document_number",
    "type",
    "agencies",
    "raw_text_url",
    "html_url",
    "title",
    "publication_date",
    "subtype",
)
FR_BASIS: Final = (
    "Work of the United States Government (17 U.S.C. 105), published in the Federal "
    "Register by the Office of the Federal Register / GPO."
)


def fr_search_url(type_code: str, start: str, end: str, page: int) -> str:
    params: list[tuple[str, str]] = [
        ("per_page", "100"),
        ("page", str(page)),
        ("order", "oldest"),
        ("conditions[type][]", type_code),
        ("conditions[publication_date][gte]", start),
        ("conditions[publication_date][lte]", end),
    ]
    params += [("fields[]", name) for name in FR_FIELDS]
    return "https://www.federalregister.gov/api/v1/documents.json?" + urlencode(params)


def family_of(item: dict[str, Any]) -> str:
    if item.get("type") == "Presidential Document":
        subtype = item.get("subtype") or "unspecified"
        return f"fr:presdoc:{subtype}:{str(item.get('publication_date', ''))[:7]}"
    agencies = item.get("agencies") or [{}]
    slug = agencies[0].get("slug") or agencies[0].get("raw_name") or "unknown"
    return f"fr:agency:{slug}"


def fr_documents(
    fetcher: Fetcher,
    type_code: str,
    *,
    start: str,
    end: str,
    limit: int,
    drops: Counter[str] | None = None,
) -> Iterator[Document]:
    skipped: Counter[str] = Counter() if drops is None else drops
    produced = 0
    for page in range(1, 6):
        body = json.loads(fetcher.get(fr_search_url(type_code, start, end, page)).text())
        for item in body.get("results", []):
            if produced >= limit:
                return
            raw_url = item.get("raw_text_url")
            if not raw_url:
                skipped["fr:no_raw_text_url"] += 1
                continue
            try:
                fetched = fetcher.get(raw_url)
            except FetchError:
                skipped["fr:fetch_failed"] += 1
                continue
            text = html_to_text(fetched.text()).text.strip()
            if len(text) < 500:
                skipped["fr:too_short"] += 1
                continue
            yield Document(
                doc_id=f"fr:{item['document_number']}",
                origin="US_GOV_FR",
                family_id=family_of(item),
                label=FR_TYPES[type_code],
                language="en",
                url=raw_url,
                fetched_at=fetched.fetched_at,
                raw_sha256=fetched.sha256,
                text=text,
                licence=Licence(
                    licence_id="US-GOV-17USC105",
                    basis=FR_BASIS,
                    evidence=f"Federal Register API type={item.get('type')!r}",
                    source_url=str(item.get("html_url") or raw_url),
                ),
                meta={
                    "title": item.get("title"),
                    "publication_date": item.get("publication_date"),
                    "fr_type": item.get("type"),
                },
            )
            produced += 1
        if not body.get("next_page_url"):
            return
