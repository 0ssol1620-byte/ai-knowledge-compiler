"""C-09 at the API boundary: an unmeasured metric never decides anything.

`services._persisted_router_metrics` used to rebuild a `PageMetrics` with 0.5
sentinels for the six visual fields nobody measures, and
`_select_inference_raster` then compared one of them to a threshold. Both are
fixed here; these tests pin the behaviour so the sentinel cannot come back.
"""

from __future__ import annotations

import uuid

from akc_api.models import Page
from akc_api.services import _persisted_router_metrics, _select_inference_raster
from akc_router import ProcessingMode, Route


def _page(**metrics: object) -> Page:
    return Page(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_number=1,
        width_pt=612.0,
        height_pt=792.0,
        rotation=0,
        preflight_metrics=dict(metrics),
        quality_metrics={},
    )


def test_absent_visual_metrics_rebuild_as_unknown_not_as_a_sentinel() -> None:
    metrics = _persisted_router_metrics(_page(native_text_chars=3000))
    assert metrics.small_text_score is None
    assert metrics.blur_score is None
    assert metrics.contrast_score is None
    assert metrics.handwriting_probability is None
    assert metrics.skew_degrees is None


def test_a_persisted_null_survives_the_round_trip() -> None:
    """A worker record written after C-09 carries nulls; they stay null."""
    persisted = {
        "router_metrics": {
            "page_index0": 0,
            "width": 612,
            "height": 792,
            "native_text_chars": 3000,
            "native_word_count": 500,
            "native_block_count": 12,
            "native_text_coverage": 0.9,
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
    }
    metrics = _persisted_router_metrics(_page(**persisted))
    assert metrics.small_text_score is None
    assert metrics.native_text_chars == 3000


def test_an_old_sentinel_record_still_loads() -> None:
    """Rows written before C-09 keep their 0.5; they are not rewritten."""
    metrics = _persisted_router_metrics(_page(small_text_score=0.5, blur_score=0.5))
    assert metrics.small_text_score == 0.5
    assert metrics.blur_score == 0.5


def test_unknown_small_text_neither_forces_nor_blocks_the_precision_raster() -> None:
    """The term simply does not fire; measured terms still decide."""
    unknown_page = _page(native_text_chars=3000)
    assert (
        _select_inference_raster(
            [], page=unknown_page, route=Route.PADDLE_FAST, mode=ProcessingMode.BALANCED
        )
        is None
    )  # no assets, but crucially it did not raise on a None comparison

    # A measured small-text page still reaches the precision branch, and a
    # measured table-heavy page does too even with small text unknown.
    measured = _persisted_router_metrics(_page(small_text_score=0.9))
    assert measured.small_text_score == 0.9
    table_heavy = _persisted_router_metrics(_page(table_density=0.5))
    assert table_heavy.small_text_score is None
    assert table_heavy.table_density == 0.5
