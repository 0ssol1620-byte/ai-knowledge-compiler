from __future__ import annotations

import pytest
from akc_cir import (
    BBox1000,
    PublicAuthorityReceipt,
    PublicProofAnchor,
    PublicProofFixture,
    PublicProofLocale,
    PublicProofMarket,
    PublicProofResult,
    resolve_public_proof_market,
    validate_public_proof_binding,
)
from pydantic import ValidationError

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def receipt(*, consolidation_scope: str | None) -> PublicAuthorityReceipt:
    return PublicAuthorityReceipt(
        issuer_id="issuer-1",
        accession_id="filing-1",
        filing_type="annual",
        filing_date="2026-03-31",
        report_period="2025",
        taxonomy_or_statement="ifrs-full",
        concept="Revenue",
        context="duration-2025",
        unit="KRW",
        source_locator="page-7:cell-2-3",
        archive_sha256=SHA_A,
        consolidation_scope=consolidation_scope,
    )


def fixture(*, market: PublicProofMarket = PublicProofMarket.DART) -> PublicProofFixture:
    return PublicProofFixture(
        id=f"fixture-{market.value}",
        market=market,
        locale=PublicProofLocale.KO if market is PublicProofMarket.DART else PublicProofLocale.EN,
        issuer="Example issuer",
        source_document_url="https://example.test/filing",
        source_document_sha256=SHA_B,
        selected_proof=PublicProofAnchor(
            page_number1=7,
            bbox1000=BBox1000((100, 200, 500, 600)),
        ),
        authority=receipt(
            consolidation_scope="consolidated"
            if market is PublicProofMarket.DART
            else None
        ),
        markdown_object="| Revenue | 100 |",
        note_object="Revenue was 100 KRW.",
        graph_delta_sha256=SHA_C,
        disclosures=("Public filing fixture; not a benchmark.",),
    )


def test_market_resolution_never_accepts_ip_or_country_input() -> None:
    assert resolve_public_proof_market(
        explicit=PublicProofMarket.SEC,
        account_preference=PublicProofMarket.DART,
        locale=PublicProofLocale.KO,
    ) is PublicProofMarket.SEC
    assert resolve_public_proof_market(
        explicit=None,
        account_preference=PublicProofMarket.DART,
        locale=PublicProofLocale.EN,
    ) is PublicProofMarket.DART
    assert resolve_public_proof_market(
        explicit=None,
        account_preference=None,
        locale=PublicProofLocale.KO,
    ) is PublicProofMarket.DART
    assert resolve_public_proof_market(
        explicit=None,
        account_preference=None,
        locale="unknown",
    ) is PublicProofMarket.SEC


def test_dart_and_sec_authority_requirements_are_distinct() -> None:
    assert fixture(market=PublicProofMarket.DART).authority.consolidation_scope
    assert fixture(market=PublicProofMarket.SEC).authority.context == "duration-2025"
    with pytest.raises(ValidationError, match="DART proof requires"):
        PublicProofFixture.model_validate(
            {
                **fixture(market=PublicProofMarket.DART).model_dump(by_alias=False),
                "authority": receipt(consolidation_scope=None),
            }
        )


def test_result_binding_rejects_cross_fixture_and_stale_projection() -> None:
    source = fixture()
    result = PublicProofResult.from_fixture(source)
    validate_public_proof_binding(source, result)
    with pytest.raises(ValueError, match="source/result fixture mismatch"):
        validate_public_proof_binding(
            source,
            result.model_copy(update={"fixture_sha256": SHA_A}),
        )


def test_fixture_digest_is_deterministic_and_source_url_is_safe() -> None:
    first = fixture()
    assert first.fixture_sha256 == fixture().fixture_sha256
    with pytest.raises(ValidationError, match="credential-free HTTPS"):
        PublicProofFixture.model_validate(
            {
                **first.model_dump(by_alias=False),
                "source_document_url": "https://user:secret@example.test/filing",
            }
        )
