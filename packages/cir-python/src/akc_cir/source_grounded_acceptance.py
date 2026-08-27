"""Source-grounded acceptance receipts for recovery arbitration.

Candidate agreement is not source correspondence.  The recovery core already
refuses to ACCEPT when ``source_aware_checks_passed`` is false, but a bare boolean
can be supplied without evidence.  This module turns that boolean into a typed,
hash-bound receipt and provides one concrete source-grounded check for
born-digital/native-text documents.

Scanned/visual-only pages are intentionally not guessed through this lane.  A
visual source verifier may provide a separately hash-bound check receipt; if no
source-grounded check is available, the gate remains unavailable and arbitration
cannot ACCEPT merely because candidates agree or a model reports confidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from .critical_tokens import verify_critical_tokens
from .recovery_policy import AgreementVector, Arbitration, arbitrate

__all__ = [
    "SourceCheckKind",
    "SourceCheckStatus",
    "SourceGroundedAcceptanceReceipt",
    "SourceGroundedCheck",
    "arbitrate_source_grounded",
    "native_text_source_check",
    "unavailable_source_check",
]


class SourceCheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - status enum, not a credential
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


class SourceCheckKind(StrEnum):
    NATIVE_TEXT_CORRESPONDENCE = "NATIVE_TEXT_CORRESPONDENCE"
    VISUAL_SOURCE_CORRESPONDENCE = "VISUAL_SOURCE_CORRESPONDENCE"
    TABLE_SOURCE_CORRESPONDENCE = "TABLE_SOURCE_CORRESPONDENCE"
    FORMULA_SOURCE_CORRESPONDENCE = "FORMULA_SOURCE_CORRESPONDENCE"


@dataclass(frozen=True, slots=True)
class SourceGroundedCheck:
    check_id: str
    kind: SourceCheckKind
    status: SourceCheckStatus
    source_revision_sha256: str
    source_region_ref: str
    candidate_sha256: str
    required: bool = True
    reason: str = ""
    normalized_similarity: float | None = None
    critical_token_mismatch_count: int | None = None

    def __post_init__(self) -> None:
        if not self.check_id or not self.source_region_ref:
            raise ValueError("check_id and source_region_ref are required")
        for value, label in (
            (self.source_revision_sha256, "source_revision_sha256"),
            (self.candidate_sha256, "candidate_sha256"),
        ):
            if not value.startswith("sha256:") or len(value) != 71:
                raise ValueError(f"{label} must be a sha256:<64 hex> digest")
        if self.normalized_similarity is not None and not 0.0 <= self.normalized_similarity <= 1.0:
            raise ValueError("normalized_similarity must be within 0..1")
        if (
            self.critical_token_mismatch_count is not None
            and self.critical_token_mismatch_count < 0
        ):
            raise ValueError("critical_token_mismatch_count cannot be negative")

    def as_record(self) -> dict[str, object]:
        """Secret-safe record: hashes/metrics only, never source or candidate text."""

        return {
            "check_id": self.check_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "source_revision_sha256": self.source_revision_sha256,
            "source_region_ref": self.source_region_ref,
            "candidate_sha256": self.candidate_sha256,
            "required": self.required,
            "reason": self.reason,
            "normalized_similarity": self.normalized_similarity,
            "critical_token_mismatch_count": self.critical_token_mismatch_count,
        }


@dataclass(frozen=True, slots=True)
class SourceGroundedAcceptanceReceipt:
    receipt_id: str
    checks: tuple[SourceGroundedCheck, ...]

    def __post_init__(self) -> None:
        if not self.receipt_id:
            raise ValueError("receipt_id is required")
        if not self.checks:
            raise ValueError("at least one source-grounded check is required")
        if len({check.check_id for check in self.checks}) != len(self.checks):
            raise ValueError("source-grounded check ids must be unique")

    @property
    def source_aware_checks_passed(self) -> bool:
        required = tuple(check for check in self.checks if check.required)
        if not required:
            return False
        # An actual source correspondence check must exist; candidate-only
        # agreement is deliberately not representable by this enum.
        has_source_correspondence = any(
            check.kind
            in {
                SourceCheckKind.NATIVE_TEXT_CORRESPONDENCE,
                SourceCheckKind.VISUAL_SOURCE_CORRESPONDENCE,
                SourceCheckKind.TABLE_SOURCE_CORRESPONDENCE,
                SourceCheckKind.FORMULA_SOURCE_CORRESPONDENCE,
            }
            for check in required
        )
        return has_source_correspondence and all(
            check.status is SourceCheckStatus.PASS for check in required
        )

    @property
    def source_revision_hashes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(check.source_revision_sha256 for check in self.checks))

    def as_record(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "source_aware_checks_passed": self.source_aware_checks_passed,
            "source_revision_hashes": list(self.source_revision_hashes),
            "checks": [check.as_record() for check in self.checks],
        }


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def native_text_source_check(
    *,
    check_id: str,
    source_revision_sha256: str,
    source_region_ref: str,
    source_text: str,
    candidate_text: str,
    minimum_normalized_similarity: float = 0.90,
    required: bool = True,
) -> SourceGroundedCheck:
    """Compare a candidate directly with native text anchored to a source revision.

    Text similarity and critical-token correspondence remain separate evidence.
    A candidate fails if either falls outside the native-source contract.  The
    threshold is an internal policy input, not an externally generalized claim.
    """

    if not 0.0 <= minimum_normalized_similarity <= 1.0:
        raise ValueError("minimum_normalized_similarity must be within 0..1")
    similarity = SequenceMatcher(
        None,
        " ".join(source_text.split()).casefold(),
        " ".join(candidate_text.split()).casefold(),
    ).ratio()
    critical = verify_critical_tokens(source_text, candidate_text)
    mismatches = len(critical.mismatches)
    passed = similarity >= minimum_normalized_similarity and mismatches == 0
    return SourceGroundedCheck(
        check_id=check_id,
        kind=SourceCheckKind.NATIVE_TEXT_CORRESPONDENCE,
        status=SourceCheckStatus.PASS if passed else SourceCheckStatus.FAIL,
        source_revision_sha256=source_revision_sha256,
        source_region_ref=source_region_ref,
        candidate_sha256=_sha256_text(candidate_text),
        required=required,
        reason=(
            "native source correspondence passed"
            if passed
            else "candidate did not satisfy native source correspondence"
        ),
        normalized_similarity=similarity,
        critical_token_mismatch_count=mismatches,
    )


def unavailable_source_check(
    *,
    check_id: str,
    kind: SourceCheckKind,
    source_revision_sha256: str,
    source_region_ref: str,
    candidate_sha256: str,
    reason: str,
    required: bool = True,
) -> SourceGroundedCheck:
    """Represent missing source verification honestly instead of substituting PASS."""

    return SourceGroundedCheck(
        check_id=check_id,
        kind=kind,
        status=SourceCheckStatus.UNAVAILABLE,
        source_revision_sha256=source_revision_sha256,
        source_region_ref=source_region_ref,
        candidate_sha256=candidate_sha256,
        required=required,
        reason=reason,
    )


def arbitrate_source_grounded(
    agreement: AgreementVector,
    *,
    receipt: SourceGroundedAcceptanceReceipt,
    parser_self_confidence: float | None = None,
) -> Arbitration:
    """Bind recovery arbitration to a structured source-grounded receipt."""

    return arbitrate(
        agreement,
        source_aware_checks_passed=receipt.source_aware_checks_passed,
        parser_self_confidence=parser_self_confidence,
    )
