"""Register of public-data sources, exactly as the repository notes state them.

Everything not established by a repository note is ``unverified``/``unknown``.
Only env var names are stored, never key values.

``DEFAULT_RIGHTS`` is the deny-everything baseline. ``REVIEWED_RIGHTS`` holds
what an agent read on each publisher's primary terms page on 2026-11-17
(WO-D21-5): every changed permission is backed by a quoted sentence of a
snapshot whose sha256 is recorded here and in the WO-D21-5 receipt. It is an
agent's reading, not a legal review: no ``redistribute`` or ``resell`` is
``allow`` until a human legal reviewer says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .rights import ACTIONS, Permission, RightsRecord

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
            (
                "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
                "https://www.sec.gov/os/accessing-edgar-data",
                "https://www.sec.gov/os/webmaster-faq",
                "https://www.sec.gov/privacy.htm",
            ),
            "not_required",
            None,
            "filed_day",
            False,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "API page: no authentication or API keys. Fair access: declare a User-Agent;"
            " at most 10 requests per second. Reuse: see REVIEWED_RIGHTS.",
        ),
        PublicSource(
            "alfred",
            "Federal Reserve Bank of St. Louis (FRED/ALFRED)",
            (
                "https://fred.stlouisfed.org/docs/api/fred/alfred.html",
                "https://fred.stlouisfed.org/docs/api/fred/realtime_period.html",
                "https://alfred.stlouisfed.org/",
                "https://fred.stlouisfed.org/",
                "https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
                "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
                "https://fred.stlouisfed.org/legal/",
            ),
            "required",
            "FRED_API_KEY",
            "vintage_day",
            True,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "Vintages come from the FRED API series observations request with a real-time"
            " period, which needs the FRED key. The FRED terms forbid caching FRED content"
            " and its use in connection with developing AI systems: see REVIEWED_RIGHTS.",
        ),
        PublicSource(
            "eia",
            "U.S. Energy Information Administration",
            (
                "https://www.eia.gov/opendata/",
                "https://www.eia.gov/opendata/documentation.php",
                "https://www.eia.gov/opendata/terms-of-service.php",
                "https://www.eia.gov/about/copyrights_reuse.php",
            ),
            # The documentation page says "You must use the API key"; the field stays
            # "unverified" until the register test that pins it is updated (WO-D21-5 delta).
            "unverified",
            "EIA_API_KEY",
            "unknown",
            False,
            False,
            BASE_FORBIDDEN_CLAIMS,
            "API documentation: a registered API key is required. No key was provided and"
            " no EIA data was fetched. Per-row release timing unverified.",
        ),
        PublicSource(
            "fhfa_hpi",
            "Federal Housing Finance Agency",
            (
                "https://www.fhfa.gov/data/hpi",
                "https://www.fhfa.gov/data/hpi/datasets",
                "https://www.fhfa.gov/document/d/hpi/hpi_dictionary.xlsx",
                "https://www.fhfa.gov/about/fhfa-policies/website-privacy-policy",
            ),
            "unverified",
            None,
            "unknown",
            False,
            True,
            (*BASE_FORBIDDEN_CLAIMS, "property_valuation"),
            "Master file columns per the FHFA dictionary. Geography vintage unverified."
            " Expanded-data indexes use licensed vendor data (datasets page).",
        ),
        PublicSource(
            "census_bps",
            "U.S. Census Bureau",
            (
                "https://www.census.gov/construction/bps/",
                "https://www.census.gov/construction/bps/methodology.html",
                "https://www.census.gov/construction/bps/definitions.html",
                "https://www2.census.gov/econ/bps/Documentation/cbsaasc.pdf",
                "https://www.census.gov/data/developers/about/terms-of-service.html",
            ),
            "unverified",
            None,
            "unknown",
            False,
            True,
            (*BASE_FORBIDDEN_CLAIMS, "parcel_level_approval"),
            "Aggregated permit data must not be misrepresented as individual legal approvals."
            " CBSA file layout per the CBSA ASCII documentation; seasonal adjustment and"
            " delineation vintage are not stated in it.",
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

REVIEWED_ON = date(2026, 11, 17)
# A re-read date chosen by this register, not a publisher's date: each terms page
# says it may change without notice.
REREAD_BY = date(2027, 5, 17)
REVIEWER = "agent reading of the primary terms page, WO-D21-5 (not a legal review)"
_PROCESSING = ("ingest", "model_processing", "derive")
_OUTPUT = ("quote", "display", "export")


def _reviewed(
    source_id: str,
    terms_url: str,
    snapshot_sha256: str,
    attribution: str | None,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
) -> RightsRecord:
    permissions: dict[str, Permission] = dict.fromkeys(ACTIONS, "unknown")
    permissions.update(dict.fromkeys(allow, "allow"))
    permissions.update(dict.fromkeys(deny, "deny"))
    return RightsRecord(
        rights_id=f"{source_id}:reviewed-{REVIEWED_ON.isoformat()}",
        source_id=source_id,
        series_id=None,
        terms_url=terms_url,
        terms_snapshot_sha256=snapshot_sha256,
        verified_on=REVIEWED_ON,
        reviewer=REVIEWER,
        expires_on=REREAD_BY,
        attribution=attribution,
        permissions=permissions,
    )


# The quoted sentences behind each permission are in the WO-D21-5 rights document.
REVIEWED_RIGHTS: tuple[RightsRecord, ...] = (
    # "All Government-created content on sec.gov and EDGAR public filing content are
    # free to access and reuse." (webmaster FAQ) and "Information presented on sec.gov
    # is considered public information and may be copied or further distributed by
    # users of the web site without the SEC's permission." (privacy.htm)
    _reviewed(
        "sec_edgar",
        "https://www.sec.gov/privacy.htm",
        "sha256:3eb66aef23052c5036ccc0900658884a4901b6343c2b03579642a19b83a1e16f",
        "Source: U.S. Securities and Exchange Commission (EDGAR); no SEC seal or logo,"
        " no implied affiliation or approval",
        allow=(*_PROCESSING, *_OUTPUT),
    ),
    # FRED API prohibitions (k) "... in connection with the development or training of
    # any software program or system or machine learning ..." and (l) "... storing,
    # caching, or archiving any portion of the FRED Services or FRED Content ...";
    # Property Rights: FRED Content "may not be modified, duplicated, copied,
    # distributed, ... displayed, ... incorporated in any other database or
    # compilation or sold ... without the Bank's prior written permission".
    _reviewed(
        "alfred",
        "https://fred.stlouisfed.org/legal/",
        "sha256:7d032ef70fb1e934f5ca76dc69e0ba941f09620078c7d138d4c39dc664abc8b4",
        "This product uses the FRED API but is not endorsed or certified by the Federal"
        " Reserve Bank of St. Louis.",
        deny=ACTIONS,
    ),
    # "U.S. government publications are in the public domain and are not subject to
    # copyright protection. You may use and/or distribute any of our data, files,
    # databases, reports, graphs, charts, and other information products ..."
    _reviewed(
        "eia",
        "https://www.eia.gov/about/copyrights_reuse.php",
        "sha256:33c1a9f95672c78e3ebdbbe5cd30edd0065029174391188f458ca8651204f05a",
        "Source: U.S. Energy Information Administration (<publication date>)",
        allow=(*_PROCESSING, *_OUTPUT),
    ),
    # "Generally, information and materials produced by Federal agencies, including
    # FHFA, are in the public domain and may be copied and distributed without
    # permission." -- "Generally", and third-party material on the site, leave the
    # output actions to a human reviewer.
    _reviewed(
        "fhfa_hpi",
        "https://www.fhfa.gov/about/fhfa-policies/website-privacy-policy",
        "sha256:113342fc0cd543b7c4a43d769d74929259948247912743e11bddfb9bd6083202",
        "This product uses FHFA data but is neither endorsed nor certified by FHFA.",
        allow=_PROCESSING,
    ),
    # The API terms cover the Census Data API only; no reuse statement was found for
    # the www2.census.gov BPS files. Nothing is changed from unknown.
    _reviewed(
        "census_bps",
        "https://www.census.gov/data/developers/about/terms-of-service.html",
        "sha256:d99a828175882caf42038b39fad828cb03f9e6fdd6a20bfeab523e62fb23d8b7",
        None,
    ),
)
