from __future__ import annotations

import hashlib

import pytest
from akc_cir.recovery_policy import AgreementVector, ArbitrationOutcome
from akc_cir.source_grounded_acceptance import (
    SourceCheckKind,
    SourceCheckStatus,
    SourceGroundedAcceptanceReceipt,
    SourceGroundedCheck,
    arbitrate_source_grounded,
    native_text_source_check,
    unavailable_source_check,
)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _agreement() -> AgreementVector:
    return AgreementVector(
        text_similarity=0.99,
        block_sequence_similarity=0.99,
        bbox_alignment=0.99,
        table_grid_similarity=0.99,
        reading_order_similarity=0.99,
        consensus_entropy=0.02,
    )


def test_native_source_correspondence_can_open_acceptance_gate() -> None:
    source = "TAVONEL DATE 2026-08-16 AMOUNT 42.50 USD POLICY MUST"
    candidate = source
    check = native_text_source_check(
        check_id="native-1",
        source_revision_sha256=_digest("source-revision"),
        source_region_ref="page:1/region:body",
        source_text=source,
        candidate_text=candidate,
    )
    receipt = SourceGroundedAcceptanceReceipt("receipt-1", (check,))

    verdict = arbitrate_source_grounded(_agreement(), receipt=receipt)

    assert check.status is SourceCheckStatus.PASS
    assert check.critical_token_mismatch_count == 0
    assert receipt.source_aware_checks_passed is True
    assert verdict.outcome is ArbitrationOutcome.ACCEPT


def test_candidate_agreement_cannot_override_native_source_numeric_mismatch() -> None:
    check = native_text_source_check(
        check_id="native-1",
        source_revision_sha256=_digest("source-revision"),
        source_region_ref="page:1/table:3/cell:B4",
        source_text="Warranty amount 42.50 USD",
        candidate_text="Warranty amount 24.50 USD",
    )
    receipt = SourceGroundedAcceptanceReceipt("receipt-2", (check,))

    verdict = arbitrate_source_grounded(_agreement(), receipt=receipt)

    assert check.status is SourceCheckStatus.FAIL
    assert check.critical_token_mismatch_count is not None
    assert check.critical_token_mismatch_count > 0
    assert receipt.source_aware_checks_passed is False
    assert verdict.outcome is ArbitrationOutcome.ESCALATE


def test_unavailable_visual_source_verification_is_not_silent_pass() -> None:
    check = unavailable_source_check(
        check_id="visual-1",
        kind=SourceCheckKind.VISUAL_SOURCE_CORRESPONDENCE,
        source_revision_sha256=_digest("scan-source"),
        source_region_ref="page:7/bbox:unknown",
        candidate_sha256=_digest("candidate"),
        reason="visual verifier unavailable",
    )
    receipt = SourceGroundedAcceptanceReceipt("receipt-3", (check,))

    verdict = arbitrate_source_grounded(_agreement(), receipt=receipt)

    assert check.status is SourceCheckStatus.UNAVAILABLE
    assert receipt.source_aware_checks_passed is False
    assert verdict.outcome is ArbitrationOutcome.ESCALATE


def test_model_self_confidence_still_cannot_accept_without_source_pass() -> None:
    check = unavailable_source_check(
        check_id="visual-1",
        kind=SourceCheckKind.VISUAL_SOURCE_CORRESPONDENCE,
        source_revision_sha256=_digest("scan-source"),
        source_region_ref="page:7",
        candidate_sha256=_digest("candidate"),
        reason="no independent source verifier",
    )
    receipt = SourceGroundedAcceptanceReceipt("receipt-4", (check,))

    verdict = arbitrate_source_grounded(
        _agreement(),
        receipt=receipt,
        parser_self_confidence=0.999,
    )

    assert verdict.outcome is ArbitrationOutcome.ESCALATE


def test_low_self_confidence_can_only_escalate_even_after_source_pass() -> None:
    check = native_text_source_check(
        check_id="native-1",
        source_revision_sha256=_digest("source-revision"),
        source_region_ref="page:1",
        source_text="Warranty 3 years",
        candidate_text="Warranty 3 years",
    )
    receipt = SourceGroundedAcceptanceReceipt("receipt-5", (check,))

    verdict = arbitrate_source_grounded(
        _agreement(),
        receipt=receipt,
        parser_self_confidence=0.2,
    )

    assert receipt.source_aware_checks_passed is True
    assert verdict.outcome is ArbitrationOutcome.ESCALATE


def test_receipt_is_hash_bound_and_does_not_serialize_source_text() -> None:
    source = "sensitive source body 42.50 USD"
    candidate = "sensitive source body 42.50 USD"
    check = native_text_source_check(
        check_id="native-1",
        source_revision_sha256=_digest("source-revision"),
        source_region_ref="page:1",
        source_text=source,
        candidate_text=candidate,
    )
    record = SourceGroundedAcceptanceReceipt("receipt-6", (check,)).as_record()
    encoded = repr(record)

    assert "sensitive source body" not in encoded
    assert _digest(candidate) in encoded
    assert _digest("source-revision") in encoded


def test_malformed_source_digest_is_rejected() -> None:
    with pytest.raises(ValueError, match="source_revision_sha256"):
        SourceGroundedCheck(
            check_id="forged",
            kind=SourceCheckKind.NATIVE_TEXT_CORRESPONDENCE,
            status=SourceCheckStatus.PASS,
            source_revision_sha256="not-a-digest",
            source_region_ref="page:1",
            candidate_sha256=_digest("candidate"),
        )
