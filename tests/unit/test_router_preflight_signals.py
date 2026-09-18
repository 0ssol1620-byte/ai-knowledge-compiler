"""WP-R3: the `PageMetrics` -> `RiskVector` adapter and the lane-B estimator."""

from __future__ import annotations

import io

import pytest
from akc_router import PageMetrics, RiskFeature
from akc_router.risk_adapter import PAGE_LOCAL_BLIND_SPOTS, page_metrics_to_risk_vector
from akc_router.source_preflight import (
    NATIVE_FAMILY_SIGNALS,
    UNREADABLE_FAMILIES,
    estimate_page_visual,
    inspect_pdf_native,
    merge_visual_estimate,
    native_unknown_features,
)
from PIL import Image, ImageDraw, ImageFilter

_BASE: dict[str, object] = {
    "page_index0": 0,
    "width": 612,
    "height": 792,
    "native_text_chars": 3000,
    "native_word_count": 500,
    "native_block_count": 24,
    "native_text_coverage": 0.90,
    "image_coverage": 0.02,
    "invalid_unicode_ratio": 0.0,
    "replacement_char_ratio": 0.0,
    "whitespace_anomaly_score": 0.0,
    "native_reading_order_score": 0.98,
    "font_size_p10": None,
    "estimated_columns": 1,
    "table_density": 0.0,
    "formula_density": 0.0,
    "chart_probability": 0.0,
    "handwriting_probability": None,
    "rotation_degrees": None,
    "skew_degrees": None,
    "blur_score": None,
    "contrast_score": None,
    "small_text_score": None,
    "script_distribution": {"Latin": 1.0},
    "suspected_prompt_injection": False,
}


def _metrics(**overrides: object) -> PageMetrics:
    return PageMetrics.model_validate({**_BASE, **overrides})


# --- the adapter -------------------------------------------------------------


def test_every_section_four_signal_is_present() -> None:
    vector = page_metrics_to_risk_vector(_metrics())
    assert set(vector.signals) == set(RiskFeature)
    assert len(RiskFeature) == 22


def test_blind_spots_and_unmeasured_visuals_are_unknown_not_zero() -> None:
    vector = page_metrics_to_risk_vector(_metrics())
    expected_unknown = PAGE_LOCAL_BLIND_SPOTS | {
        RiskFeature.HANDWRITING_RISK,
        RiskFeature.SMALL_TEXT_RISK,
        RiskFeature.DEGRADATION_RISK,
        RiskFeature.ROTATION_SKEW_RISK,
    }
    assert set(vector.unknown_features) == expected_unknown
    for feature in expected_unknown:
        assert vector.is_unknown(feature)
        assert vector.signals[feature].value is None
        assert vector.confidence(feature) == 0.0


def test_nothing_the_adapter_emits_claims_calibration() -> None:
    vector = page_metrics_to_risk_vector(_metrics(handwriting_probability=0.1))
    assert not any(signal.calibrated for signal in vector.signals.values())
    assert all(vector.confidence(feature) == 0.0 for feature in RiskFeature)


def test_measured_visual_fields_become_observed_signals() -> None:
    vector = page_metrics_to_risk_vector(
        _metrics(
            handwriting_probability=0.8,
            small_text_score=0.4,
            blur_score=0.6,
            contrast_score=0.9,
            rotation_degrees=90,
            skew_degrees=0.0,
        )
    )
    assert not vector.is_unknown(RiskFeature.HANDWRITING_RISK)
    assert vector.signals[RiskFeature.HANDWRITING_RISK].value == pytest.approx(0.8)
    # Blur 0.6 beats (1 - contrast 0.9) = 0.1.
    assert vector.signals[RiskFeature.DEGRADATION_RISK].value == pytest.approx(0.6)
    # A 90-degree rotation is full rotation risk even at zero skew.
    assert vector.signals[RiskFeature.ROTATION_SKEW_RISK].value == pytest.approx(1.0)


def test_half_measured_degradation_is_observed_not_unknown() -> None:
    vector = page_metrics_to_risk_vector(_metrics(contrast_score=0.2))
    assert not vector.is_unknown(RiskFeature.DEGRADATION_RISK)
    assert vector.signals[RiskFeature.DEGRADATION_RISK].value == pytest.approx(0.8)


def test_supplied_blind_spot_signal_is_accepted() -> None:
    from akc_router.risk import ObservationSource, RiskSignal

    vector = page_metrics_to_risk_vector(
        _metrics(),
        known={
            RiskFeature.AUTHORITY_CONFLICT_RISK: RiskSignal(
                value=0.3, observation_source=ObservationSource.AUTHORITY_SOURCE
            )
        },
    )
    assert not vector.is_unknown(RiskFeature.AUTHORITY_CONFLICT_RISK)
    assert RiskFeature.AUTHORITY_CONFLICT_RISK not in vector.unknown_features


def test_corruption_and_injection_reach_their_signals() -> None:
    vector = page_metrics_to_risk_vector(
        _metrics(replacement_char_ratio=0.01, suspected_prompt_injection=True)
    )
    assert vector.signals[RiskFeature.SOURCE_INTEGRITY_RISK].value == pytest.approx(1.0)
    assert vector.signals[RiskFeature.PROMPT_INJECTION_RISK].value == pytest.approx(1.0)


# --- lane A, native inspection ----------------------------------------------


def _one_page_pdf(*, with_text: bool = True) -> bytes:
    """A minimal valid PDF written by hand; no writer dependency."""
    content = b"BT /F1 24 Tf 72 700 Td (Native page text) Tj ET" if with_text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    start_xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(start_xref).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def test_native_pdf_inspection_reads_structure() -> None:
    report = inspect_pdf_native(io.BytesIO(_one_page_pdf()))
    assert not report.corrupt_structure
    assert report.page_count == 1
    page = report.pages[0]
    assert page.width_pt == pytest.approx(612.0)
    assert page.height_pt == pytest.approx(792.0)
    assert page.rotation_degrees == 0
    assert page.embedded_text_chars > 0
    assert page.text_object_count >= 1
    assert page.image_object_count == 0


def test_corrupt_pdf_fails_closed_and_says_so() -> None:
    report = inspect_pdf_native(io.BytesIO(b"%PDF-1.7\nnot actually a pdf"))
    assert report.corrupt_structure
    assert report.corrupt_reason
    assert report.pages == ()


def test_families_without_a_reader_declare_every_signal_unknown() -> None:
    for family in UNREADABLE_FAMILIES:
        assert family not in NATIVE_FAMILY_SIGNALS
        assert native_unknown_features(family) == frozenset(RiskFeature)
    assert RiskFeature.HANDWRITING_RISK in native_unknown_features("pdf")
    assert RiskFeature.FORMULA_RISK in native_unknown_features("pdf")
    assert RiskFeature.FORMULA_RISK not in native_unknown_features("xlsx")
    assert RiskFeature.TRACKED_CHANGE_RISK not in native_unknown_features("docx")


# --- lane B, visual estimation ----------------------------------------------


def _text_page(*, font_height: int = 14, rows: int = 30) -> Image.Image:
    image = Image.new("L", (800, 1000), color=255)
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        top = 40 + row * 30
        for column in range(24):
            left = 40 + column * 30
            draw.rectangle((left, top, left + 12, top + font_height), fill=0)
    return image


def test_sharp_page_is_less_blurred_than_the_same_page_blurred() -> None:
    sharp = estimate_page_visual(_text_page())
    blurred = estimate_page_visual(_text_page().filter(ImageFilter.GaussianBlur(4)))
    assert sharp.blur_score is not None
    assert blurred.blur_score is not None
    assert blurred.blur_score > sharp.blur_score


def test_small_text_scores_higher_than_large_text() -> None:
    large = estimate_page_visual(_text_page(font_height=40, rows=14))
    small = estimate_page_visual(_text_page(font_height=4, rows=30))
    assert small.small_text_score is not None
    assert large.small_text_score is not None
    assert small.small_text_score > large.small_text_score


def test_blank_page_measures_nothing_rather_than_reporting_clean() -> None:
    estimate = estimate_page_visual(Image.new("L", (800, 1000), color=255))
    assert estimate.blur_score is None
    assert estimate.small_text_score is None
    assert estimate.skew_degrees is None
    assert estimate.handwriting_probability is None
    assert "blur_score" in estimate.unmeasured


def test_skew_search_finds_a_rotated_page() -> None:
    straight = estimate_page_visual(_text_page())
    tilted = estimate_page_visual(
        _text_page().rotate(-3.0, resample=Image.Resampling.BILINEAR, fillcolor=255)
    )
    assert straight.skew_degrees == pytest.approx(0.0, abs=0.5)
    assert tilted.skew_degrees is not None
    assert tilted.skew_degrees > 1.0


def test_estimate_is_never_marked_calibrated() -> None:
    assert estimate_page_visual(_text_page()).calibrated is False


def test_merge_fills_only_unmeasured_fields() -> None:
    estimate = estimate_page_visual(_text_page())
    measured = _metrics(blur_score=0.11)
    merged = merge_visual_estimate(measured, estimate)
    # A real observation survives the heuristic.
    assert merged.blur_score == pytest.approx(0.11)
    assert merged.small_text_score == estimate.small_text_score
    # And an estimate that measured nothing changes nothing.
    blank = estimate_page_visual(Image.new("L", (40, 40), color=255))
    assert merge_visual_estimate(measured, blank) == measured
