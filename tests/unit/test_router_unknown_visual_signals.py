"""C-09: an unmeasured visual signal is unknown, never a neutral 0.5.

The production defect this pins: the CPU worker persisted
`handwriting_probability = 0.5` as an "unknown" sentinel, `classify_page`
returned `HANDWRITTEN` at `>= 0.50`, and so every natively parsed page in
production carried `technical_class = handwritten` while `HPD_FAST`
(`engine.py`, `handwriting_probability < 0.2`) was unreachable.

T4 in `MATRIX_RESEARCH_2026-09-08.md` reproduced it: a clean native page with
the worker's own sentinels classified `HANDWRITTEN`, difficulty 7.24; the same
page with the four fields at 0.0 classified `NATIVE_CLEAN`, difficulty 0.24.
"""

from __future__ import annotations

import pytest
from akc_router import (
    FeatureFlags,
    PageMetrics,
    PageTechnicalClass,
    ProcessingMode,
    Route,
    RouterContext,
    classify_page,
    preflight_difficulty,
    select_first_route,
    unmeasured_visual_signals,
)
from pydantic import ValidationError

#: The T4 page: 3,000 native chars, coverage 0.90, reading order 0.98, no
#: tables, formulas or charts. Only the six visual fields vary between cases.
_T4_NATIVE_PAGE: dict[str, object] = {
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
    "script_distribution": {"Latin": 1.0},
    "suspected_prompt_injection": False,
}

#: What the CPU worker used to persist when it had no visual estimator.
_WORKER_SENTINELS: dict[str, object] = {
    "handwriting_probability": 0.5,
    "rotation_degrees": 0,
    "skew_degrees": 0.0,
    "blur_score": 0.5,
    "contrast_score": 0.5,
    "small_text_score": 0.5,
}

#: What the CPU worker persists now: unmeasured is null.
_WORKER_UNMEASURED: dict[str, object] = dict.fromkeys(_WORKER_SENTINELS)


def _page(**visual: object) -> PageMetrics:
    return PageMetrics.model_validate({**_T4_NATIVE_PAGE, **visual})


def test_t4_sentinels_still_reproduce_the_defect() -> None:
    """The threshold itself was never wrong: 0.5 really is >= 0.50."""
    page = _page(**_WORKER_SENTINELS)
    assert classify_page(page) is PageTechnicalClass.HANDWRITTEN
    assert preflight_difficulty(page) == pytest.approx(7.24)


def test_t4_unmeasured_visual_signals_classify_native_clean() -> None:
    """The fix: the worker's own values no longer claim handwriting."""
    page = _page(**_WORKER_UNMEASURED)
    assert classify_page(page) is PageTechnicalClass.NATIVE_CLEAN
    # 0.24 is the T4 all-zero difficulty; skipping the unknown terms lands on
    # the same number because those terms were zero-valued, not because the
    # unknowns were scored as zero -- `unmeasured_visual_signals` says which.
    assert preflight_difficulty(page) == pytest.approx(0.24)
    assert unmeasured_visual_signals(page) == (
        "handwriting_probability",
        "rotation_degrees",
        "skew_degrees",
        "blur_score",
        "contrast_score",
        "small_text_score",
    )


def test_unknown_is_not_scored_as_zero() -> None:
    """An unknown term is absent from the difficulty sum, not scored 0."""
    measured_clean = _page(
        handwriting_probability=0.0,
        rotation_degrees=0,
        skew_degrees=0.0,
        blur_score=0.0,
        contrast_score=1.0,
        small_text_score=0.0,
    )
    assert unmeasured_visual_signals(measured_clean) == ()
    # Same score, different epistemic state: only one of the two pages claims
    # the page is not blurred.
    assert preflight_difficulty(measured_clean) == pytest.approx(
        preflight_difficulty(_page(**_WORKER_UNMEASURED))
    )
    blurred = _page(**{**_WORKER_UNMEASURED, "blur_score": 1.0})
    assert preflight_difficulty(blurred) == pytest.approx(8.24)


def test_measured_handwriting_still_classifies_handwritten() -> None:
    page = _page(**{**_WORKER_UNMEASURED, "handwriting_probability": 0.5})
    assert classify_page(page) is PageTechnicalClass.HANDWRITTEN


def test_measured_rotation_and_skew_still_classify_rotated() -> None:
    assert (
        classify_page(_page(**{**_WORKER_UNMEASURED, "rotation_degrees": 90}))
        is PageTechnicalClass.ROTATED_OR_WARPED
    )
    assert (
        classify_page(_page(**{**_WORKER_UNMEASURED, "skew_degrees": 3.0}))
        is PageTechnicalClass.ROTATED_OR_WARPED
    )


def test_hpd_fast_is_reachable_once_handwriting_is_measured() -> None:
    """The other half of C-09: `HPD_FAST` was unreachable under the sentinel."""
    context = RouterContext(
        mode=ProcessingMode.SPEED,
        dominant_language="en",
        feature_flags=FeatureFlags(hpd_enabled=True, paddle_fast_enabled=True),
        ready_routes=frozenset({Route.HPD_FAST, Route.PADDLE_FAST}),
    )
    # A scan page, so the native gate does not take it first.
    scan = {
        **_T4_NATIVE_PAGE,
        "native_text_chars": 0,
        "native_word_count": 0,
        "native_block_count": 0,
        "native_text_coverage": 0.0,
        "native_reading_order_score": 0.0,
        "image_coverage": 0.6,
        "script_distribution": {"Latin": 1.0},
    }
    sentinel = PageMetrics.model_validate({**scan, **_WORKER_SENTINELS})
    assert select_first_route(context, sentinel).route is Route.PADDLE_FAST

    measured = PageMetrics.model_validate(
        {**scan, **_WORKER_UNMEASURED, "handwriting_probability": 0.05}
    )
    assert select_first_route(context, measured).route is Route.HPD_FAST


def test_unmeasured_handwriting_does_not_open_the_cheap_lane() -> None:
    """Fail closed: unknown handwriting is not evidence of no handwriting."""
    context = RouterContext(
        mode=ProcessingMode.SPEED,
        dominant_language="en",
        feature_flags=FeatureFlags(hpd_enabled=True, paddle_fast_enabled=True),
        ready_routes=frozenset({Route.HPD_FAST, Route.PADDLE_FAST}),
    )
    page = PageMetrics.model_validate(
        {
            **_T4_NATIVE_PAGE,
            **_WORKER_UNMEASURED,
            "native_text_chars": 0,
            "native_word_count": 0,
            "native_block_count": 0,
            "native_text_coverage": 0.0,
            "native_reading_order_score": 0.0,
            "image_coverage": 0.6,
        }
    )
    assert select_first_route(context, page).route is Route.PADDLE_FAST


def test_visual_fields_are_required_even_when_unknown() -> None:
    """A producer must state "unmeasured"; it cannot omit the field."""
    incomplete = {key: value for key, value in _T4_NATIVE_PAGE.items()}
    with pytest.raises(ValidationError):
        PageMetrics.model_validate(incomplete)


def test_unmeasured_rotation_is_not_a_rotation_of_zero() -> None:
    """`rotation_degrees=None` dumps as null, distinct from a measured 0."""
    unmeasured = _page(**_WORKER_UNMEASURED).model_dump(mode="json")
    assert unmeasured["rotationDegrees"] is None
    assert unmeasured["handwritingProbability"] is None
    measured = _page(**{**_WORKER_UNMEASURED, "rotation_degrees": 0}).model_dump(mode="json")
    assert measured["rotationDegrees"] == 0
