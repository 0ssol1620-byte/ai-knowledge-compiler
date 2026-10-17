"""Per-document vendor cost, from the price snapshot and from response metadata (§4.7).

Both figures are computed for every vendor document; the charged figure is the larger of the two
("둘 중 큰 값"), so a spend cap is never under-counted. Free credits are not applied. A document
that never reached the vendor (``attempts == 0``) costs zero. TAVONEL arms have no list price —
pricing is founder-owned and internal cost never sits beside a vendor price — so their cost is
``None`` (not applicable), never zero. Snapshot freshness (the 7-day rule) is lane AT-3.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from .adapters.base import Document, ParseResult, UsageValue

WEB = "competitor-protocol-receipts/web/"


@dataclass(frozen=True)
class PriceSnapshot:
    vendor: str
    price_point: str
    sources: tuple[tuple[str, str, str], ...]  # (receipt file, sha256, downloaded UTC)
    quoted: tuple[str, ...]


SNAPSHOTS: Mapping[str, PriceSnapshot] = {
    snapshot.vendor: snapshot
    for snapshot in (
        PriceSnapshot(
            "reducto",
            "reducto_parse_default",
            (
                (
                    WEB + "reducto-pricing.html",
                    "db2496594aabf5e779eec25e7826be12d8fbd359aba55f4672ff9498d264e667",
                    "2026-10-17T01:24:50.789Z",
                ),
            ),
            ("Endpoint Per 1,000 pages", "r-1 Parse $10"),
        ),
        PriceSnapshot(
            "llamaparse",
            "llamaparse_tier_credits",
            (
                (
                    WEB + "llamaparse-docs-pricing.html",
                    "2eabf853344060b989e7a6740447a18ef6ddbcf63bada2eeeb371a6511717d8b",
                    "2026-10-17T01:25:48.240Z",
                ),
            ),
            (
                "$1.25 per 1,000 credits.",
                "Fast 1",
                "Cost-effective 3",
                "Agentic 10",
                "Agentic Plus 45",
            ),
        ),
        PriceSnapshot(
            "unstructured",
            "unstructured_default",
            (
                (
                    WEB + "unstructured-pricing.html",
                    "dcf420b91189d7ed0e14ecd5cbc9e3899721dffb643a3ea8480339396870d8bf",
                    "2026-10-17T01:24:55.572Z",
                ),
            ),
            ("Pay only $0.015 a page after your first 10,000 free pages.",),
        ),
        PriceSnapshot(
            "landingai",
            "landingai_dpt3pro_priority",
            (
                (
                    WEB + "landingai-credit-consumption.html",
                    "64a6eeedb1339919031867b415ebef1bc9bec92f902e4700db273687e8254db8",
                    "2026-10-17T01:27:20.821Z",
                ),
                (
                    WEB + "landingai-pricing.html",
                    "a8cf10851a3622a3f3c8578edba63a8b832c275788046426f05dd7d2c716a084",
                    "2026-10-17T01:24:58.435Z",
                ),
            ),
            (
                "Synchronous Parse requests run on the priority tier.",
                "1 credit per page",
                "0.5 credits per 1,000 output characters",
                "All credit totals are rounded up to the nearest 0.1 credit.",
                "$1 buys 100 credits.",
            ),
        ),
    )
}

REDUCTO_USD_PER_PAGE = Decimal(10) / 1000
UNSTRUCTURED_USD_PER_PAGE = Decimal("0.015")
LLAMAPARSE_USD_PER_CREDIT = Decimal("1.25") / 1000
LLAMAPARSE_CREDITS_PER_PAGE = {"fast": 1, "cost_effective": 3, "agentic": 10, "agentic_plus": 45}
LANDINGAI_USD_PER_CREDIT = Decimal("0.01")
LANDINGAI_CREDITS_PER_PAGE = Decimal(1)  # priority tier
LANDINGAI_CREDITS_PER_1000_CHARS = Decimal("0.5")  # priority tier


@dataclass(frozen=True)
class Cost:
    snapshot_usd: Decimal
    metadata_usd: Decimal | None  # None: the response reported no usable usage figure

    @property
    def charged_usd(self) -> Decimal:
        if self.metadata_usd is None:
            return self.snapshot_usd
        return max(self.snapshot_usd, self.metadata_usd)


def _number(usage: Mapping[str, UsageValue], key: str) -> Decimal | None:
    value = usage.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return Decimal(str(value))
    return None


def _landingai_credits(pages: int, output_chars: int) -> Decimal:
    credits = pages * LANDINGAI_CREDITS_PER_PAGE + (
        Decimal(output_chars) / 1000 * LANDINGAI_CREDITS_PER_1000_CHARS
    )
    return (credits * 10).to_integral_value(rounding=ROUND_CEILING) / 10


def document_cost(
    vendor: str, result: ParseResult, document: Document, config: Mapping[str, str]
) -> Cost | None:
    if vendor == "tavonel_live":
        return None
    if vendor not in SNAPSHOTS:
        raise ValueError(f"no price snapshot for vendor {vendor!r}")
    if result.attempts == 0:
        return Cost(Decimal(0), None)
    pages = document.pages
    if vendor == "reducto":
        return Cost(pages * REDUCTO_USD_PER_PAGE, None)  # usage field not captured
    if vendor == "unstructured":
        return Cost(pages * UNSTRUCTURED_USD_PER_PAGE, None)  # usage field not captured
    if vendor == "llamaparse":
        per_page = LLAMAPARSE_CREDITS_PER_PAGE[config["tier"]] * LLAMAPARSE_USD_PER_CREDIT
        billed = _number(result.usage, "num_pages_billed")
        return Cost(pages * per_page, None if billed is None else billed * per_page)
    if vendor == "landingai":
        # Output characters are the code points of the returned markdown field (receipt above).
        snapshot = _landingai_credits(pages, len(result.markdown)) * LANDINGAI_USD_PER_CREDIT
        credits = _number(result.usage, "total_credits")
        return Cost(snapshot, None if credits is None else credits * LANDINGAI_USD_PER_CREDIT)
    raise ValueError(f"no price snapshot for vendor {vendor!r}")
