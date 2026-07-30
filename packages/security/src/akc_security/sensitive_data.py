"""Privacy-safe PII and secret detection for untrusted document text.

The scanner intentionally keeps findings positional: matched values are never
stored in a finding or returned by its public serializer.  Callers can create a
redacted derivative while preserving the immutable source separately.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SensitiveKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    KR_RESIDENT_NUMBER = "kr_resident_number"
    PAYMENT_CARD = "payment_card"
    API_KEY = "api_key"
    AWS_ACCESS_KEY = "aws_access_key"
    JWT = "jwt"
    PRIVATE_KEY = "private_key"


class SensitiveSeverity(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SensitiveFinding:
    """A non-content-bearing sensitive span."""

    kind: SensitiveKind
    start: int
    end: int
    confidence: float
    severity: SensitiveSeverity
    explanation_code: str
    preview_mask_default: bool = True

    @property
    def redaction_label(self) -> str:
        return self.kind.value.upper()

    def to_public_dict(self) -> dict[str, str | int | float | bool]:
        """Serialize metadata without leaking the matched value."""

        return {
            "kind": self.kind.value,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "severity": self.severity.value,
            "explanation_code": self.explanation_code,
            "preview_mask_default": self.preview_mask_default,
        }


@dataclass(frozen=True, slots=True)
class SensitiveScan:
    findings: tuple[SensitiveFinding, ...]

    @property
    def has_pii(self) -> bool:
        return any(
            finding.kind
            in {
                SensitiveKind.EMAIL,
                SensitiveKind.PHONE,
                SensitiveKind.KR_RESIDENT_NUMBER,
                SensitiveKind.PAYMENT_CARD,
            }
            for finding in self.findings
        )

    @property
    def has_secret(self) -> bool:
        return any(
            finding.kind
            in {
                SensitiveKind.API_KEY,
                SensitiveKind.AWS_ACCESS_KEY,
                SensitiveKind.JWT,
                SensitiveKind.PRIVATE_KEY,
            }
            for finding in self.findings
        )

    @property
    def external_transfer_requires_confirmation(self) -> bool:
        """Secrets always require an explicit external-processing decision."""

        return self.has_secret

    def public_summary(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.kind.value] = counts.get(finding.kind.value, 0) + 1
        return {
            "has_pii": self.has_pii,
            "has_secret": self.has_secret,
            "external_transfer_requires_confirmation": (
                self.external_transfer_requires_confirmation
            ),
            "counts": counts,
            "findings": [finding.to_public_dict() for finding in self.findings],
            "limitations": [
                "pattern detection can miss sensitive data",
                "pattern detection can produce false positives",
                "review findings before relying on a redacted derivative",
            ],
        }


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """A derivative string and its content-free finding metadata."""

    text: str
    scan: SensitiveScan


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    kind: SensitiveKind
    confidence: float
    severity: SensitiveSeverity
    explanation_code: str
    priority: int


_RULES = (
    _Rule(
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
            r"[\s\S]{16,16384}?"
            r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        ),
        SensitiveKind.PRIVATE_KEY,
        0.99,
        SensitiveSeverity.CRITICAL,
        "private_key_pem_boundary",
        100,
    ),
    _Rule(
        re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,255}(?![A-Za-z0-9_])"),
        SensitiveKind.API_KEY,
        0.99,
        SensitiveSeverity.CRITICAL,
        "github_fine_grained_token_shape",
        95,
    ),
    _Rule(
        re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{20,255}(?![A-Za-z0-9_])"),
        SensitiveKind.API_KEY,
        0.98,
        SensitiveSeverity.CRITICAL,
        "github_legacy_token_shape",
        95,
    ),
    _Rule(
        re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{20,255}(?![A-Za-z0-9])"),
        SensitiveKind.API_KEY,
        0.94,
        SensitiveSeverity.CRITICAL,
        "api_key_prefix_and_entropy_shape",
        90,
    ),
    _Rule(
        re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
        SensitiveKind.AWS_ACCESS_KEY,
        0.98,
        SensitiveSeverity.CRITICAL,
        "aws_access_key_id_shape",
        90,
    ),
    _Rule(
        re.compile(
            r"(?<![A-Za-z0-9_-])"
            r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
            r"(?![A-Za-z0-9_-])"
        ),
        SensitiveKind.JWT,
        0.92,
        SensitiveSeverity.HIGH,
        "three_segment_jwt_shape",
        85,
    ),
    _Rule(
        re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)"),
        SensitiveKind.KR_RESIDENT_NUMBER,
        0.99,
        SensitiveSeverity.CRITICAL,
        "kr_resident_number_date_and_checksum",
        80,
    ),
    _Rule(
        re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w-])", re.I),
        SensitiveKind.EMAIL,
        0.96,
        SensitiveSeverity.HIGH,
        "email_address_shape",
        60,
    ),
    _Rule(
        re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
        SensitiveKind.PAYMENT_CARD,
        0.98,
        SensitiveSeverity.CRITICAL,
        "payment_card_luhn_checksum",
        70,
    ),
    _Rule(
        re.compile(r"(?<!\d)(?:\+?82[- .]?)?(?:0?1[016789])[- .]?\d{3,4}[- .]?\d{4}(?!\d)"),
        SensitiveKind.PHONE,
        0.91,
        SensitiveSeverity.HIGH,
        "kr_mobile_number_shape",
        50,
    ),
)


def _is_valid_kr_resident_number(value: str) -> bool:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 13 or digits[6] not in "1234":
        return False
    century = 1900 if digits[6] in "12" else 2000
    try:
        date(century + int(digits[:2]), int(digits[2:4]), int(digits[4:6]))
    except ValueError:
        return False
    weighted = sum(
        int(digit) * weight
        for digit, weight in zip(digits[:12], (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5), strict=True)
    )
    return (11 - (weighted % 11)) % 10 == int(digits[-1])


def _passes_luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _validated_match(rule: _Rule, value: str) -> bool:
    if rule.kind == SensitiveKind.KR_RESIDENT_NUMBER:
        return _is_valid_kr_resident_number(value)
    if rule.kind == SensitiveKind.PAYMENT_CARD:
        return _passes_luhn(value)
    return True


def detect_sensitive_data(text: str, *, maximum_findings: int = 500) -> SensitiveScan:
    """Detect bounded, high-confidence PII and secret spans.

    Overlapping matches are collapsed deterministically in favor of the
    higher-priority and then wider finding.  The source value is never copied
    into the returned scan.
    """

    if maximum_findings < 1 or maximum_findings > 10_000:
        raise ValueError("maximum_findings must be between 1 and 10000")
    candidates: list[tuple[int, int, int, SensitiveFinding]] = []
    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            if not _validated_match(rule, match.group(0)):
                continue
            finding = SensitiveFinding(
                kind=rule.kind,
                start=match.start(),
                end=match.end(),
                confidence=rule.confidence,
                severity=rule.severity,
                explanation_code=rule.explanation_code,
            )
            candidates.append((rule.priority, match.end() - match.start(), -match.start(), finding))

    selected: list[SensitiveFinding] = []
    for _, _, _, candidate in sorted(candidates, reverse=True):
        if any(
            candidate.start < existing.end and existing.start < candidate.end
            for existing in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= maximum_findings:
            break
    return SensitiveScan(tuple(sorted(selected, key=lambda finding: (finding.start, finding.end))))


def mask_sensitive_text(
    text: str,
    findings: Iterable[SensitiveFinding] | None = None,
) -> RedactionResult:
    """Create a redacted derivative without mutating or returning altered source state."""

    scan = detect_sensitive_data(text) if findings is None else SensitiveScan(tuple(findings))
    cursor = 0
    fragments: list[str] = []
    for finding in sorted(scan.findings, key=lambda item: (item.start, item.end)):
        if finding.start < cursor or finding.end > len(text):
            raise ValueError("findings must be ordered, non-overlapping, and in bounds")
        fragments.append(text[cursor : finding.start])
        fragments.append(f"[REDACTED:{finding.redaction_label}]")
        cursor = finding.end
    fragments.append(text[cursor:])
    return RedactionResult(text="".join(fragments), scan=scan)


def finding_fingerprint(
    source_text: str,
    finding: SensitiveFinding,
    *,
    hmac_key: bytes,
) -> str:
    """Create a tenant-purpose-bound correlation value without exposing content."""

    if len(hmac_key) < 32:
        raise ValueError("hmac_key must contain at least 32 bytes")
    if finding.start < 0 or finding.end > len(source_text) or finding.start >= finding.end:
        raise ValueError("finding span is outside source text")
    digest = hmac.new(
        hmac_key,
        f"{finding.kind.value}\0".encode() + source_text[finding.start : finding.end].encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"h1_{digest}"
