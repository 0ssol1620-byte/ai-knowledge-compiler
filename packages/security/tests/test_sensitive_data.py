from __future__ import annotations

import pytest
from akc_security.sensitive_data import (
    SensitiveKind,
    detect_sensitive_data,
    finding_fingerprint,
    mask_sensitive_text,
)


def _valid_kr_resident_number(prefix: str = "900101-1") -> str:
    first_twelve = prefix.replace("-", "") + "23456"
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    weighted = sum(int(digit) * weight for digit, weight in zip(first_twelve, weights, strict=True))
    checksum = (11 - (weighted % 11)) % 10
    return f"{prefix}23456{checksum}"


def test_scan_reports_content_free_metadata_and_secret_policy() -> None:
    source = (
        "owner=user@example.com "
        "token=github_pat_" + ("A" * 36) + " "
        "jwt=eyJheader12345.eyJpayload12345.signature12345"
    )

    scan = detect_sensitive_data(source)

    assert {finding.kind for finding in scan.findings} == {
        SensitiveKind.EMAIL,
        SensitiveKind.API_KEY,
        SensitiveKind.JWT,
    }
    assert scan.has_pii is True
    assert scan.has_secret is True
    assert scan.external_transfer_requires_confirmation is True
    serialized = repr(scan.public_summary())
    assert "user@example.com" not in serialized
    assert "github_pat_" not in serialized
    assert "eyJheader" not in serialized
    assert "false positives" in serialized


def test_masking_creates_derivative_and_keeps_source_unchanged() -> None:
    resident_number = _valid_kr_resident_number()
    source = f"연락처 010-1234-5678, 주민번호 {resident_number}, 메일 a@b.co.kr"

    result = mask_sensitive_text(source)

    assert source.endswith("a@b.co.kr")
    assert "010-1234-5678" not in result.text
    assert resident_number not in result.text
    assert "a@b.co.kr" not in result.text
    assert result.text.count("[REDACTED:") == 3
    assert result.scan.has_pii is True
    assert result.scan.has_secret is False


def test_email_before_sentence_punctuation_is_detected() -> None:
    scan = detect_sensitive_data("Contact pii@example.com. Next sentence.")

    assert [finding.kind for finding in scan.findings] == [SensitiveKind.EMAIL]


@pytest.mark.parametrize(
    "candidate",
    [
        "1111 1111 1111 1111",
        "1234 5678 9012 3456",
        "not-a-card-0000",
    ],
)
def test_invalid_card_shapes_are_not_reported(candidate: str) -> None:
    assert SensitiveKind.PAYMENT_CARD not in {
        finding.kind for finding in detect_sensitive_data(candidate).findings
    }


def test_valid_luhn_card_is_reported_without_returning_value() -> None:
    source = "test card 4111 1111 1111 1111"
    scan = detect_sensitive_data(source)

    assert [finding.kind for finding in scan.findings] == [SensitiveKind.PAYMENT_CARD]
    assert "4111" not in repr(scan.public_summary())


def test_invalid_korean_resident_date_or_checksum_is_rejected() -> None:
    assert not detect_sensitive_data("991332-1234567").findings
    valid = _valid_kr_resident_number()
    invalid = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    assert not detect_sensitive_data(invalid).findings
    assert detect_sensitive_data(valid).findings[0].kind == SensitiveKind.KR_RESIDENT_NUMBER


def test_private_key_wins_over_nested_token_shapes() -> None:
    source = (
        "-----BEGIN "
        + "PRIVATE KEY-----\n"
        + "github_pat_"
        + ("Z" * 40)
        + "\n-----END "
        + "PRIVATE KEY-----"
    )

    scan = detect_sensitive_data(source)

    assert [finding.kind for finding in scan.findings] == [SensitiveKind.PRIVATE_KEY]


def test_fingerprint_is_stable_and_requires_strong_key() -> None:
    source = "email first@example.com"
    finding = detect_sensitive_data(source).findings[0]

    first = finding_fingerprint(source, finding, hmac_key=b"k" * 32)
    second = finding_fingerprint(source, finding, hmac_key=b"k" * 32)

    assert first == second
    assert first.startswith("h1_")
    assert "first@example.com" not in first
    with pytest.raises(ValueError, match="32 bytes"):
        finding_fingerprint(source, finding, hmac_key=b"weak")


def test_detection_is_bounded_and_validates_limits() -> None:
    scan = detect_sensitive_data(
        " ".join(f"u{i}@example.com" for i in range(20)),
        maximum_findings=3,
    )
    assert len(scan.findings) == 3
    with pytest.raises(ValueError, match="between"):
        detect_sensitive_data("x", maximum_findings=0)


def test_masking_rejects_out_of_bounds_findings() -> None:
    source = "a@example.com"
    finding = detect_sensitive_data(source).findings[0]
    with pytest.raises(ValueError, match="ordered"):
        mask_sensitive_text("short", (finding,))
