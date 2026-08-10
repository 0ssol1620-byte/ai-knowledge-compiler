"""Post-parse inspection — §N8's taxonomy and §N9's detectors.

Two of these tests encode mistakes the campaign actually made. The blank/empty
pair is the harness gap §2.6 lists as a known weakness: two documents were scored
as empty when they were not, and one page was scored as a failure when zero
characters was the right answer. The correlation test is the provider-wide stop
that got read as four independent worker failures.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir.inspection import (
    CATASTROPHIC_CODES,
    SECURITY_CODES,
    UNKNOWN_REFERENCE,
    CalibrationTable,
    DetectorSignal,
    FailureCode,
    FailureEvent,
    InspectionStatus,
    Severity,
    SourceScope,
    Stage,
    correlate_failures,
    detect_completeness,
    detect_duplication,
    detect_garble,
    detect_reading_order,
    detect_table,
    inspect_output,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _signal(code: FailureCode, score: float, **kw) -> DetectorSignal:
    return DetectorSignal(code=code, score=score, **kw)


# --------------------------------------------------------------------------
# §N9.2 — blank source and empty output are different facts
# --------------------------------------------------------------------------


def test_a_page_that_is_genuinely_blank_produces_no_finding() -> None:
    """One page in the campaign measured 100% near-white. Zero chars was right."""
    signal, unknown = detect_completeness(output_chars=0, blank_probability=1.0)

    assert signal is None
    assert unknown is None


def test_a_page_with_content_and_no_output_is_a_hard_fail() -> None:
    signal, _ = detect_completeness(output_chars=0, blank_probability=0.02)

    assert signal is not None
    assert signal.code is FailureCode.F8_EMPTY_OUTPUT
    assert signal.hard_fail is True


def test_an_empty_output_with_no_blank_classifier_is_unanswerable() -> None:
    """The third state. Guessing either way is what produced both campaign errors."""
    signal, unknown = detect_completeness(output_chars=0, blank_probability=None)

    assert signal is not None
    assert signal.hard_fail is False
    assert unknown == UNKNOWN_REFERENCE
    assert "unanswerable" in signal.detail


def test_an_unanswerable_empty_output_escalates_rather_than_passing() -> None:
    signal, unknown = detect_completeness(output_chars=0, blank_probability=None)

    result = inspect_output([signal], unknown_references=[unknown])

    assert result.status is InspectionStatus.SUSPICIOUS
    assert UNKNOWN_REFERENCE in result.unknown_references


def test_output_far_shorter_than_its_reference_is_suspicious() -> None:
    signal, _ = detect_completeness(output_chars=120, reference_chars=4000)

    assert signal is not None
    assert signal.code is FailureCode.F9_SUSPICIOUSLY_SHORT
    assert signal.raw["char_ratio"] == pytest.approx(0.03)


def test_output_matching_its_reference_is_not_a_finding() -> None:
    signal, _ = detect_completeness(output_chars=3900, reference_chars=4000)

    assert signal is None


def test_no_reference_at_all_is_recorded_not_assumed() -> None:
    signal, unknown = detect_completeness(output_chars=3900)

    assert signal is None
    assert unknown == UNKNOWN_REFERENCE


def test_visual_coverage_stands_in_when_there_is_no_character_reference() -> None:
    signal, unknown = detect_completeness(
        output_chars=500, parsed_foreground_area=12.0, expected_foreground_area=100.0
    )

    assert signal is not None
    assert signal.raw["coverage_ratio"] == pytest.approx(0.12)
    assert unknown == UNKNOWN_REFERENCE


# --------------------------------------------------------------------------
# §N9.3 — duplication
# --------------------------------------------------------------------------


def test_a_decoder_loop_shows_up_as_repeated_ngrams() -> None:
    looped = "\n".join(["the warranty covers parts and labour for two years"] * 12)

    signal = detect_duplication(looped)

    assert signal is not None
    assert signal.code is FailureCode.F10_DUPLICATED_CONTENT
    assert signal.raw["dup_ratio"] > 0.5


def test_ordinary_prose_is_not_duplication() -> None:
    prose = (
        "The warranty covers parts and labour.\n"
        "Claims must be filed within thirty days.\n"
        "Shipping is arranged by the carrier with the earliest window.\n"
        "Consumable parts and cosmetic damage are excluded from coverage.\n"
    )

    assert detect_duplication(prose) is None


def test_a_page_header_repeating_is_not_duplicated_content() -> None:
    """Tested at a threshold where the exclusion actually decides the verdict.

    At the default 0.30 a repeated header never trips duplication on its own, so
    asserting `is None` there would prove nothing. A table calibrated for a
    document type whose bodies are short -- forms, certificates -- sits low
    enough that the header would dominate, and that is the case worth pinning.
    """
    header = "ACME CORPORATION CONFIDENTIAL QUARTERLY REPORT"
    bodies = [
        "Warranty coverage extends to parts and labour for twenty four months.",
        "Claims must be filed with supporting photographs within thirty calendar days.",
        "Shipments are tendered to whichever carrier offers the earliest pickup window.",
        "Consumable items such as filters belts and fuses fall outside coverage.",
        "Refunds are issued to the original payment method after inspection completes.",
        "Installation performed by an unauthorised technician voids all remaining cover.",
        "Replacement units ship from the regional depot nearest the delivery address.",
        "Disputes proceed to arbitration under the rules of the seller jurisdiction.",
    ]
    lines: list[str] = []
    for body in bodies:
        lines += [header, body]
    text = "\n".join(lines)

    assert detect_duplication(text, threshold=0.05) is not None
    assert detect_duplication(text, header_lines=[header], threshold=0.05) is None


def test_text_too_short_to_judge_produces_nothing() -> None:
    assert detect_duplication("only a few words here") is None


# --------------------------------------------------------------------------
# §N9.4 — garble
# --------------------------------------------------------------------------


def test_replacement_characters_are_garble() -> None:
    signal = detect_garble("The warranty covers " + "�" * 20 + " for two years")

    assert signal is not None
    assert signal.code is FailureCode.F11_GARBLED_TEXT
    assert signal.raw["replacement_chars"] == 20


def test_clean_text_is_not_garble() -> None:
    assert detect_garble("The warranty covers parts for two years.") is None


def test_the_script_check_is_skipped_when_nothing_profiled_the_document() -> None:
    """A document nobody profiled is not evidence that its script is wrong."""
    signal = detect_garble("보증은 부품과 공임을 2년간 보장합니다.")

    assert signal is None


def test_an_unprofiled_script_is_flagged_when_the_profile_exists() -> None:
    signal = detect_garble(
        "warranty " + "一" * 40, expected_scripts=frozenset({"LATIN"})
    )

    assert signal is not None
    assert signal.raw["foreign_script_ratio"] is not None


# --------------------------------------------------------------------------
# §N9.5 — reading order
# --------------------------------------------------------------------------


def test_a_correctly_ordered_page_produces_nothing() -> None:
    assert detect_reading_order([0, 1, 2, 3, 4, 5]) is None


def test_a_two_column_page_read_across_is_flagged() -> None:
    # Expected reading order is down column one then column two; the parser
    # interleaved them.
    signal = detect_reading_order([0, 3, 1, 4, 2, 5])

    assert signal is not None
    assert signal.code is FailureCode.F12_READING_ORDER


def test_a_wholesale_reversal_scores_worse_than_one_stray_block() -> None:
    reversed_page = detect_reading_order(list(range(9, -1, -1)))
    one_stray = detect_reading_order([1, 2, 3, 4, 5, 6, 7, 8, 9, 0])

    assert reversed_page is not None
    assert one_stray is not None
    assert reversed_page.score > one_stray.score


def test_a_single_block_page_has_no_order_to_get_wrong() -> None:
    assert detect_reading_order([0]) is None


# --------------------------------------------------------------------------
# §N9.6 — tables
# --------------------------------------------------------------------------


def test_a_visible_table_with_no_table_output_is_flagged() -> None:
    signal, _ = detect_table(visual_table_probability=0.93, emitted_tables=0)

    assert signal is not None
    assert signal.code is FailureCode.F13_TABLE_STRUCTURE


def test_no_layout_model_is_unknown_not_no_table() -> None:
    """Inferring "no table" from "nobody looked" turns a miss into a clean pass."""
    signal, unknown = detect_table(visual_table_probability=None, emitted_tables=0)

    assert signal is None
    assert unknown == UNKNOWN_REFERENCE


def test_ragged_rows_do_not_round_trip_as_a_grid() -> None:
    signal, _ = detect_table(
        visual_table_probability=0.9, emitted_tables=1, row_lengths=[5, 5, 3, 5]
    )

    assert signal is not None
    assert signal.raw["row_lengths"] == "5,5,3,5"


def test_a_clean_grid_is_not_a_finding() -> None:
    signal, _ = detect_table(
        visual_table_probability=0.9, emitted_tables=1, row_lengths=[4, 4, 4]
    )

    assert signal is None


# --------------------------------------------------------------------------
# §N9.8 — aggregation
# --------------------------------------------------------------------------


def test_no_signals_is_a_pass() -> None:
    assert inspect_output([]).status is InspectionStatus.PASS


def test_one_hard_fail_fails_whatever_else_says() -> None:
    result = inspect_output(
        [
            _signal(FailureCode.F8_EMPTY_OUTPUT, 1.0, hard_fail=True),
            _signal(FailureCode.F15_FIGURE_CAPTION, 0.01),
        ]
    )

    assert result.status is InspectionStatus.FAIL
    assert result.severity is Severity.CRITICAL


def test_independent_weak_signals_accumulate_rather_than_averaging_out() -> None:
    """Three detectors at 0.5 are more worrying than one; a mean says otherwise."""
    one = inspect_output([_signal(FailureCode.F12_READING_ORDER, 0.5)])
    three = inspect_output(
        [
            _signal(FailureCode.F12_READING_ORDER, 0.5),
            _signal(FailureCode.F13_TABLE_STRUCTURE, 0.5),
            _signal(FailureCode.F11_GARBLED_TEXT, 0.5),
        ]
    )

    assert three.severity is Severity.HIGH
    assert one.severity is Severity.MEDIUM


def test_a_low_score_signal_still_passes() -> None:
    result = inspect_output([_signal(FailureCode.F15_FIGURE_CAPTION, 0.05)])

    assert result.status is InspectionStatus.PASS


def test_the_result_has_no_scalar_quality_score() -> None:
    """§N9 forbids one, and the blind detector is why."""
    result = inspect_output([_signal(FailureCode.F12_READING_ORDER, 0.5)])

    assert not hasattr(result, "quality")
    assert not hasattr(result, "score")


def test_the_recommendation_names_the_cause_not_the_severity() -> None:
    result = inspect_output(
        [
            _signal(FailureCode.F13_TABLE_STRUCTURE, 0.91),
            _signal(FailureCode.F18_PARSER_DISAGREEMENT, 0.84),
        ]
    )

    assert result.recommended_action() == "RECOVERY_FOR_F13_TABLE_STRUCTURE"


def test_a_passing_result_recommends_accepting_it() -> None:
    assert inspect_output([]).recommended_action() == "ACCEPT"


# --------------------------------------------------------------------------
# §N9.9 — the thresholds are not calibrated and the result says so
# --------------------------------------------------------------------------


def test_the_default_thresholds_admit_they_are_uncalibrated() -> None:
    result = inspect_output([_signal(FailureCode.F12_READING_ORDER, 0.5)])

    assert result.thresholds_are_calibrated is False
    assert result.as_record()["thresholds_calibrated"] is False


def test_a_table_claiming_calibration_must_name_its_corpus() -> None:
    with pytest.raises(ValueError, match="name the corpus"):
        CalibrationTable(calibrated=True)


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="suspicious <= catastrophic"):
        CalibrationTable(catastrophic_threshold=0.2, suspicious_threshold=0.8)


def test_a_route_specific_table_can_be_stricter() -> None:
    strict = CalibrationTable(
        route_class="R4_TABLE_HEAVY", suspicious_threshold=0.10
    )

    result = inspect_output(
        [_signal(FailureCode.F13_TABLE_STRUCTURE, 0.2)], calibration=strict
    )

    assert result.status is InspectionStatus.SUSPICIOUS


# --------------------------------------------------------------------------
# §N9.8 — raw values survive
# --------------------------------------------------------------------------


def test_a_finding_carries_the_numbers_it_was_computed_from() -> None:
    """A ratio without its denominator cannot be disputed by a reviewer."""
    signal, _ = detect_completeness(output_chars=120, reference_chars=4000)

    assert signal is not None
    assert signal.raw["output_chars"] == 120
    assert signal.raw["reference_chars"] == 4000


def test_a_score_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(ValueError, match=r"within 0\.\.1"):
        DetectorSignal(code=FailureCode.F12_READING_ORDER, score=1.4)


# --------------------------------------------------------------------------
# §N8 — the taxonomy
# --------------------------------------------------------------------------


def test_every_masterplan_code_exists() -> None:
    assert len(FailureCode) == 49
    assert FailureCode.F0_SOURCE_CORRUPT.value == "F0_SOURCE_CORRUPT"
    assert FailureCode.F48_RATE_LIMIT_OR_ABUSE.value == "F48_RATE_LIMIT_OR_ABUSE"


def test_security_codes_are_not_ordinary_failures() -> None:
    assert FailureCode.F29_PROMPT_INJECTION_SUSPECTED in SECURITY_CODES
    assert FailureCode.F12_READING_ORDER not in SECURITY_CODES


def test_a_permission_violation_is_catastrophic() -> None:
    assert FailureCode.F25_PERMISSION_VIOLATION in CATASTROPHIC_CODES


def test_a_signature_is_stable_for_the_same_kind_of_failure() -> None:
    left = _signal(FailureCode.F6_MODEL_OOM, 1.0, detail="cuda oom on load")
    right = _signal(FailureCode.F6_MODEL_OOM, 0.4, detail="cuda oom on load")

    assert left.signature == right.signature


def test_a_different_cause_gets_a_different_signature() -> None:
    left = _signal(FailureCode.F6_MODEL_OOM, 1.0, detail="cuda oom on load")
    right = _signal(FailureCode.F6_MODEL_OOM, 1.0, detail="host ram exhausted")

    assert left.signature != right.signature


# --------------------------------------------------------------------------
# §N8 — one incident or many. The four deleted pods.
# --------------------------------------------------------------------------


def _event(failure_id: str, signature: str, offset: int) -> FailureEvent:
    return FailureEvent(
        failure_id=failure_id,
        code=FailureCode.F5_MODEL_INIT,
        stage=Stage.PARSE,
        severity=Severity.HIGH,
        confidence=0.9,
        source_scope=SourceScope.DOCUMENT,
        signature=signature,
        first_seen_at=NOW.replace(second=offset),
    )


def test_the_same_failure_across_workers_at_once_is_one_provider_incident() -> None:
    """Read as four independent failures, this deleted four pods."""
    events = [_event(f"fail_{i}", "sha256:abc", i) for i in range(4)]

    verdict = correlate_failures(events)

    assert verdict["sha256:abc"] is SourceScope.PROVIDER


def test_one_document_failing_alone_stays_a_document_failure() -> None:
    verdict = correlate_failures([_event("fail_0", "sha256:abc", 0)])

    assert verdict["sha256:abc"] is SourceScope.DOCUMENT


def test_the_same_failure_spread_over_hours_is_not_one_incident() -> None:
    events = [
        FailureEvent(
            failure_id=f"fail_{i}",
            code=FailureCode.F5_MODEL_INIT,
            stage=Stage.PARSE,
            severity=Severity.HIGH,
            confidence=0.9,
            source_scope=SourceScope.DOCUMENT,
            signature="sha256:abc",
            first_seen_at=NOW.replace(hour=8 + i),
        )
        for i in range(4)
    ]

    verdict = correlate_failures(events)

    assert verdict["sha256:abc"] is SourceScope.DOCUMENT


def test_two_workers_is_not_enough_to_call_it_provider_wide() -> None:
    events = [_event(f"fail_{i}", "sha256:abc", i) for i in range(2)]

    verdict = correlate_failures(events)

    assert verdict["sha256:abc"] is not SourceScope.PROVIDER


def test_failures_on_one_worker_are_not_a_provider_incident() -> None:
    """Three retries on the same box is one sick box, not a sick provider."""
    events = [_event(f"fail_{i}", "sha256:abc", i) for i in range(4)]
    workers = {f"fail_{i}": "worker_a" for i in range(4)}

    verdict = correlate_failures(events, workers=workers)

    assert verdict["sha256:abc"] is not SourceScope.PROVIDER


def test_an_event_serialises_to_the_masterplan_shape() -> None:
    record = _event("fail_0", "sha256:abc", 0).as_record()

    assert set(record) == {
        "failure_id",
        "code",
        "stage",
        "severity",
        "confidence",
        "source_scope",
        "evidence_refs",
        "signature",
        "recoverable",
        "policy_id",
        "first_seen_at",
        "correlated_group_id",
    }
