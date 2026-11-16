"""Rights gate for public-data sources: unknown is deny."""

from __future__ import annotations

import dataclasses
import re
from datetime import date

import pytest
from akc_source_adapters.public_data.rights import (
    ACTIONS,
    RightsDenied,
    RightsRecord,
    permits,
    require,
)
from akc_source_adapters.public_data.sources import DEFAULT_RIGHTS, PUBLIC_SOURCES

TODAY = date(2026, 11, 16)
SHA = "a" * 64


def _rec(
    allow: tuple[str, ...],
    *,
    series: str | None = None,
    sha: str | None = SHA,
    expires: date | None = None,
    source: str = "alfred",
) -> RightsRecord:
    perms = {a: ("allow" if a in allow else "deny") for a in ACTIONS}
    return RightsRecord(
        f"{source}:{series}",
        source,
        series,
        "https://example.org/terms",
        sha,
        date(2026, 11, 1),
        "reviewer",
        expires,
        None,
        perms,  # type: ignore[arg-type]
    )


def test_every_default_record_denies_every_action() -> None:
    assert len(DEFAULT_RIGHTS) == len(PUBLIC_SOURCES) == 5
    for src in PUBLIC_SOURCES.values():
        for action in ACTIONS:
            assert not any(permits(r, action, today=TODAY) for r in DEFAULT_RIGHTS)
            with pytest.raises(RightsDenied) as e:
                require(src, None, action, DEFAULT_RIGHTS, today=TODAY)
            assert e.value.reason == "unknown"


def test_allow_without_terms_snapshot_is_still_denied() -> None:
    r = _rec(("ingest",), sha=None)
    assert not permits(r, "ingest", today=TODAY)
    with pytest.raises(RightsDenied) as e:
        require(PUBLIC_SOURCES["alfred"], None, "ingest", [r], today=TODAY)
    assert e.value.reason == "unverified"


def test_verified_allow_permits_only_the_listed_actions() -> None:
    r = _rec(("ingest", "model_processing"))
    assert {a for a in ACTIONS if permits(r, a, today=TODAY)} == {"ingest", "model_processing"}
    with pytest.raises(RightsDenied) as e:
        require(PUBLIC_SOURCES["alfred"], None, "derive", [r], today=TODAY)
    assert e.value.reason == "denied"


def test_expired_record_denies() -> None:
    r = _rec(("ingest",), expires=date(2026, 11, 15))
    assert not permits(r, "ingest", today=TODAY)
    assert permits(r, "ingest", today=date(2026, 11, 15))
    with pytest.raises(RightsDenied) as e:
        require(PUBLIC_SOURCES["alfred"], None, "ingest", [r], today=TODAY)
    assert e.value.reason == "expired"


def test_alfred_source_record_cannot_license_a_series_for_redistribution() -> None:
    alfred = PUBLIC_SOURCES["alfred"]
    src = _rec(ACTIONS)
    with pytest.raises(RightsDenied) as e:
        require(alfred, "GDP", "redistribute", [src], today=TODAY)
    assert e.value.reason == "series_record_required"
    assert require(alfred, "GDP", "ingest", [src], today=TODAY) is src
    ser = _rec(ACTIONS, series="GDP")
    assert require(alfred, "GDP", "redistribute", [src, ser], today=TODAY) is ser


def test_unknown_action_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(_rec(()), permissions={"trade": "allow"})
    with pytest.raises(ValueError):
        permits(_rec(()), "trade", today=TODAY)


def test_every_source_forbids_trading_and_endorsement_claims() -> None:
    required = {"trading_signal", "investment_advice", "projected_return", "government_endorsement"}
    for s in PUBLIC_SOURCES.values():
        assert required <= set(s.forbidden_claims)


def test_census_forbids_parcel_level_approval() -> None:
    assert "parcel_level_approval" in PUBLIC_SOURCES["census_bps"].forbidden_claims
    assert "property_valuation" in PUBLIC_SOURCES["fhfa_hpi"].forbidden_claims


def test_register_matches_repository_notes() -> None:
    p = PUBLIC_SOURCES
    assert p["sec_edgar"].api_key == "not_required"
    assert (p["alfred"].api_key, p["alfred"].key_env_var) == ("required", "FRED_API_KEY")
    assert p["alfred"].per_series_rights
    for sid in ("eia", "fhfa_hpi", "census_bps"):
        assert p[sid].api_key == "unverified"
    key_like = re.compile(r"[A-Za-z0-9]{20,}")
    for s in p.values():
        assert any(u.startswith("https://") for u in s.docs_urls)
        for v in (s.source_id, s.publisher, s.key_env_var or "", s.notes, *s.docs_urls):
            assert not key_like.search(v), v
