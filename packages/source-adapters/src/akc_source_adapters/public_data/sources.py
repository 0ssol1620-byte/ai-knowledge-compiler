"""Register of public-data sources, exactly as the repository notes state them.

Everything not established by a repository note is ``unverified``/``unknown``.
Only env var names are stored, never key values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .rights import ACTIONS, RightsRecord

BASE_FORBIDDEN_CLAIMS = (
    "trading_signal",
    "investment_advice",
    "projected_return",
    "government_endorsement",
)


@dataclass(frozen=True)
class PublicSource:
    source_id: str
    publisher: str
    docs_urls: tuple[str, ...]
    api_key: Literal["required", "not_required", "unverified"]
    key_env_var: str | None
    availability: Literal["vintage_day", "filed_day", "unknown"]
    per_series_rights: bool
    aggregate_only: bool
    forbidden_claims: tuple[str, ...]
    notes: str


PUBLIC_SOURCES: dict[str, PublicSource] = {
    s.source_id: s
    for s in (
        PublicSource(
            "sec_edgar",
            "U.S. Securities and Exchange Commission",
            ("https://www.sec.gov/search-filings/edgar-application-programming-interfaces",),
            "not_required",
            None,
            "filed_day",
            False,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "Redistribution terms unverified (EXP-0103 3.2); User-Agent/rate limit unverified.",
        ),
        PublicSource(
            "alfred",
            "Federal Reserve Bank of St. Louis (FRED/ALFRED)",
            (
                "https://fred.stlouisfed.org/docs/api/fred/alfred.html",
                "https://fred.stlouisfed.org/docs/api/fred/realtime_period.html",
                "https://alfred.stlouisfed.org/",
                "https://fred.stlouisfed.org/",
            ),
            "required",
            "FRED_API_KEY",
            "vintage_day",
            True,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "Rights are per series; same-key use for ALFRED is inferred, unverified.",
        ),
        PublicSource(
            "eia",
            "U.S. Energy Information Administration",
            ("https://www.eia.gov/opendata/",),
            "unverified",
            "EIA_API_KEY",
            "unknown",
            False,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "Terms and per-row release timing unverified.",
        ),
        PublicSource(
            "fhfa_hpi",
            "Federal Housing Finance Agency",
            ("https://www.fhfa.gov/data/hpi",),
            "unverified",
            None,
            "unknown",
            False,
            True,
            (*BASE_FORBIDDEN_CLAIMS, "property_valuation"),
            "Terms and geography vintage unverified.",
        ),
        PublicSource(
            "census_bps",
            "U.S. Census Bureau",
            (
                "https://www.census.gov/construction/bps/",
                "https://www.census.gov/construction/bps/methodology.html",
                "https://www.census.gov/construction/bps/definitions.html",
            ),
            "unverified",
            None,
            "unknown",
            False,
            True,
            (*BASE_FORBIDDEN_CLAIMS, "parcel_level_approval"),
            "Aggregated permit data must not be misrepresented as individual legal approvals.",
        ),
    )
}

DEFAULT_RIGHTS: tuple[RightsRecord, ...] = tuple(
    RightsRecord(
        rights_id=f"{s.source_id}:default",
        source_id=s.source_id,
        series_id=None,
        terms_url=None,
        terms_snapshot_sha256=None,
        verified_on=None,
        reviewer=None,
        expires_on=None,
        attribution=None,
        permissions=dict.fromkeys(ACTIONS, "unknown"),
    )
    for s in PUBLIC_SOURCES.values()
)
