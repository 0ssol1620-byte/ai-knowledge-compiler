"""KOGL type 1 gold: Korean government press releases from 대한민국 정책브리핑.

A page is accepted only when it carries the 공공누리 제1유형 mark itself; the
exact alt text read from the page is stored as the licence evidence. Pages
without a mark, or with a type 2-4 mark, are skipped and counted. The text is
the attached PDF's own text layer -- the same file a user would upload.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Iterator
from typing import Final

import pypdfium2 as pdfium  # type: ignore[import-untyped]

from karena.corpus import Document, Licence
from karena.gold.fetch import Fetcher, FetchError

__all__ = ["KOGL_TYPE1_MARK", "kogl_press_releases", "pdf_text"]

BASE: Final = "https://www.korea.kr"
KOGL_TYPE1_MARK: Final = "공공누리 공공저작물 자유이용허락 1유형 출처표시"
NEWS_ID: Final = re.compile(r"pressReleaseView\.do\?newsId=(\d+)")
PDF_LINK: Final = re.compile(
    r'href="(/common/download\.do\?fileId=\d+&(?:amp;)?tblKey=\w+)">\s*<img[^>]*icon_ipdf'
)
MINISTRY: Final = re.compile(r"이 자료는 (.+?)의 보도자료를 전재")
KOGL_BASIS: Final = "공공누리 제1유형(출처표시): 상업적 이용·변경 허용, 출처 표시 의무"


def pdf_text(data: bytes) -> str:
    document = pdfium.PdfDocument(data)
    try:
        pages = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            pages.append(textpage.get_text_bounded())
            textpage.close()
            page.close()
        return "\n".join(pages)
    finally:
        document.close()


def kogl_press_releases(
    fetcher: Fetcher, *, list_pages: int, limit: int, drops: Counter[str] | None = None
) -> Iterator[Document]:
    skipped: Counter[str] = Counter() if drops is None else drops
    produced = 0
    for page_index in range(1, list_pages + 1):
        listing = fetcher.get(f"{BASE}/briefing/pressReleaseList.do?pageIndex={page_index}")
        for news_id in dict.fromkeys(NEWS_ID.findall(listing.text())):
            if produced >= limit:
                return
            url = f"{BASE}/briefing/pressReleaseView.do?newsId={news_id}"
            try:
                page = fetcher.get(url)
            except FetchError:
                skipped["kogl:view_fetch_failed"] += 1
                continue
            body = page.text()
            if f'alt="{KOGL_TYPE1_MARK}"' not in body:
                skipped["kogl:no_type1_mark"] += 1
                continue
            link = PDF_LINK.search(body)
            ministry = MINISTRY.search(body)
            if link is None or ministry is None:
                skipped["kogl:no_pdf_or_ministry"] += 1
                continue
            pdf_url = BASE + html.unescape(link.group(1))
            try:
                pdf = fetcher.get(pdf_url)
                text = pdf_text(pdf.read())
            except (FetchError, pdfium.PdfiumError):
                skipped["kogl:pdf_failed"] += 1
                continue
            if len(text.strip()) < 300:
                skipped["kogl:too_short"] += 1
                continue
            title = re.search(r"<title>(.*?)</title>", body, re.S)
            yield Document(
                doc_id=f"kogl:{news_id}",
                origin="KOGL",
                family_id=f"kogl:ministry:{ministry.group(1).strip()}",
                label="KR_GOV_PRESS_RELEASE",
                language="ko",
                url=pdf_url,
                fetched_at=pdf.fetched_at,
                raw_sha256=pdf.sha256,
                text=text,
                licence=Licence(
                    licence_id="KOGL-TYPE-1",
                    basis=KOGL_BASIS,
                    evidence=f'alt="{KOGL_TYPE1_MARK}" on {url} (page {page.sha256})',
                    source_url=url,
                    attribution=(
                        f"출처: 대한민국 정책브리핑(www.korea.kr), {ministry.group(1).strip()}"
                    ),
                ),
                meta={
                    "title": html.unescape(title.group(1).strip()) if title else None,
                    "ministry": ministry.group(1).strip(),
                    "view_url": url,
                    "pdf_raw_sha256": pdf.sha256,
                },
            )
            produced += 1
