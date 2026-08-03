from akc_quality.conformal_risk import calibrate_conformal_threshold, conformal_accept
from akc_quality.final_metrics import (
    FinalDisposition,
    FinalMetricInput,
    calculate_final_metrics,
)
from akc_quality.knowledge_quality import KnowledgeObject, validate_knowledge_quality
from akc_quality.numeric_authority import verify_authority_number
from akc_quality.page_coverage import validate_page_coverage
from akc_quality.table_conservation import validate_table_conservation


def test_final_metrics_do_not_hide_unresolved_or_excluded_items() -> None:
    metrics = calculate_final_metrics(
        (
            FinalMetricInput(FinalDisposition.VERIFIED),
            FinalMetricInput(FinalDisposition.RECOVERED_VERIFIED),
            FinalMetricInput(FinalDisposition.UNRESOLVED),
            FinalMetricInput(FinalDisposition.EXCLUDED),
        )
    )
    assert metrics.verified_coverage == 0.5
    assert not metrics.publishable
    assert "unresolved_output_present" in metrics.reason_codes


def test_critical_false_verified_is_a_hard_publish_failure() -> None:
    metrics = calculate_final_metrics(
        (FinalMetricInput(FinalDisposition.VERIFIED, critical_error=True),)
    )
    assert metrics.critical_false_verified_count == 1
    assert metrics.accepted_precision == 0
    assert not metrics.publishable


def test_page_table_numeric_and_knowledge_gates_fail_closed() -> None:
    pages = validate_page_coverage(3, (1, 3))
    assert pages.missing_pages == (2,)
    table = validate_table_conservation(
        source_shape=(2, 2),
        output_shape=(2, 2),
        source_numeric_tokens=("1", "2"),
        output_numeric_tokens=("1", "3"),
    )
    assert not table.passed
    assert verify_authority_number("1,200", "1200").accepted
    assert not verify_authority_number("1201", "1200").accepted
    quality = validate_knowledge_quality(
        (KnowledgeObject("n1", ("s1",), ("sha256:a",), ("b1",), ("missing",)),)
    )
    assert not quality.passed
    assert quality.orphan_relation_targets == ("missing",)


def test_conformal_calibration_abstains_when_sample_cannot_support_alpha() -> None:
    calibration = calibrate_conformal_threshold(
        tuple((0.99 - index / 100, True) for index in range(20)), alpha=0.01
    )
    assert calibration.accepted_count == 0
    assert not conformal_accept(1.0, calibration)
