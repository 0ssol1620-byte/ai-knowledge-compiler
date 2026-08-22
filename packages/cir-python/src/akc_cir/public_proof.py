"""Locale-aware public proof contracts with immutable source/result binding."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .base import ContractModel, NonEmptyStr, Sha256, StableId, canonical_json, sha256_digest
from .models import BBox1000


class PublicProofMarket(StrEnum):
    DART = "dart"
    SEC = "sec"


class PublicProofLocale(StrEnum):
    KO = "ko"
    EN = "en"


class PublicProofAnchor(ContractModel):
    page_number1: Annotated[int, Field(ge=1)]
    bbox1000: BBox1000 | None = None
    source_fragment: NonEmptyStr | None = None

    @model_validator(mode="after")
    def require_visual_or_native_anchor(self) -> PublicProofAnchor:
        if self.bbox1000 is None and self.source_fragment is None:
            raise ValueError("public proof requires a bbox or native source fragment")
        return self


class PublicAuthorityReceipt(ContractModel):
    issuer_id: NonEmptyStr
    accession_id: NonEmptyStr
    filing_type: NonEmptyStr
    filing_date: NonEmptyStr
    report_period: NonEmptyStr
    taxonomy_or_statement: NonEmptyStr
    concept: NonEmptyStr
    context: NonEmptyStr
    unit: NonEmptyStr
    source_locator: NonEmptyStr
    archive_sha256: Sha256
    consolidation_scope: NonEmptyStr | None = None


class PublicProofFixture(ContractModel):
    id: StableId
    market: PublicProofMarket
    locale: PublicProofLocale
    issuer: NonEmptyStr
    source_document_url: NonEmptyStr
    source_document_sha256: Sha256
    selected_proof: PublicProofAnchor
    authority: PublicAuthorityReceipt
    markdown_object: NonEmptyStr
    note_object: NonEmptyStr
    graph_delta_sha256: Sha256
    disclosures: tuple[NonEmptyStr, ...]

    @field_validator("source_document_url")
    @classmethod
    def require_public_https_source(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("public proof source must be a credential-free HTTPS URL")
        return value

    @field_validator("disclosures")
    @classmethod
    def require_disclosures(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("public proof requires at least one disclosure")
        return value

    @model_validator(mode="after")
    def require_market_authority(self) -> PublicProofFixture:
        if self.market is PublicProofMarket.DART and not self.authority.consolidation_scope:
            raise ValueError("DART proof requires consolidated or separate scope")
        if self.market is PublicProofMarket.SEC and self.authority.consolidation_scope:
            raise ValueError("SEC proof must preserve XBRL context rather than DART scope")
        return self

    @property
    def fixture_sha256(self) -> str:
        return sha256_digest(canonical_json(self))


class PublicProofResult(ContractModel):
    fixture_id: StableId
    fixture_sha256: Sha256
    source_document_sha256: Sha256
    markdown_object: NonEmptyStr
    note_object: NonEmptyStr
    graph_delta_sha256: Sha256

    @classmethod
    def from_fixture(cls, fixture: PublicProofFixture) -> PublicProofResult:
        return cls(
            fixture_id=fixture.id,
            fixture_sha256=fixture.fixture_sha256,
            source_document_sha256=fixture.source_document_sha256,
            markdown_object=fixture.markdown_object,
            note_object=fixture.note_object,
            graph_delta_sha256=fixture.graph_delta_sha256,
        )


def resolve_public_proof_market(
    *,
    explicit: PublicProofMarket | None,
    account_preference: PublicProofMarket | None,
    locale: PublicProofLocale | str,
) -> PublicProofMarket:
    """Resolve without accepting IP, country, or geolocation as an input."""
    if explicit is not None:
        return explicit
    if account_preference is not None:
        return account_preference
    if locale == PublicProofLocale.KO or locale == "ko":
        return PublicProofMarket.DART
    return PublicProofMarket.SEC


def validate_public_proof_binding(
    fixture: PublicProofFixture, result: PublicProofResult
) -> None:
    expected = PublicProofResult.from_fixture(fixture)
    if result != expected:
        raise ValueError("public proof source/result fixture mismatch")


__all__ = [
    "PublicAuthorityReceipt",
    "PublicProofAnchor",
    "PublicProofFixture",
    "PublicProofLocale",
    "PublicProofMarket",
    "PublicProofResult",
    "resolve_public_proof_market",
    "validate_public_proof_binding",
]
