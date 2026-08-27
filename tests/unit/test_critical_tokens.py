from __future__ import annotations

from akc_cir.critical_tokens import CriticalTokenKind, verify_critical_tokens

SOURCE = "Warranty ID AB-204 is valid on 2026-08-15. Limit is -10.5 kg and price USD 1,250."


def test_identical_text_preserves_critical_tokens() -> None:
    report = verify_critical_tokens(SOURCE, SOURCE, expected_identifiers=["AB-204"])
    assert report.passed
    assert report.risk == 0.0


def test_silent_numeric_unit_date_currency_and_sign_changes_are_detected() -> None:
    output = "Warranty ID AB-204 is valid on 2026-08-16. Limit is +10.5 lb and price EUR 1,250."
    report = verify_critical_tokens(SOURCE, output, expected_identifiers=["AB-204"])
    kinds = {item.kind for item in report.mismatches}
    assert CriticalTokenKind.DATE in kinds
    assert CriticalTokenKind.SIGN in kinds
    assert CriticalTokenKind.UNIT in kinds
    assert CriticalTokenKind.CURRENCY in kinds
    assert not report.passed
    assert report.as_detector_signal() is not None


def test_expected_identifier_and_critical_cell_are_checked_explicitly() -> None:
    report = verify_critical_tokens(
        SOURCE,
        SOURCE.replace("AB-204", "AB-240"),
        expected_identifiers=["AB-204"],
        source_table_cells={"B4": "2 years"},
        output_table_cells={"B4": "5 years"},
    )
    kinds = {item.kind for item in report.mismatches}
    assert CriticalTokenKind.IDENTIFIER in kinds
    assert CriticalTokenKind.TABLE_CELL in kinds