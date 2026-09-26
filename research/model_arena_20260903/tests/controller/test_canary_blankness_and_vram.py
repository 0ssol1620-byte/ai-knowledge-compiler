"""Section 17 as a runtime qualification, not a quality bar.

Two findings from the real GLM-OCR canary of 2026-09-03 are pinned here.

* Every page receipt carried ``peak_vram_mb: null`` because the model server is
  a process the worker does not own, so ``vram_headroom_measured`` failed. The
  measurement is now whole-GPU, and the headroom denominator is the device
  total the worker measured rather than the floor the pod was rented against.
* One colourful textbook page (80% white, 1.9% ink) returned 0 chars and failed
  the whole canary, while ``blank_source`` was never set by anything at all.
  Blankness is now measured from the page bytes, and a runtime that answers on
  at least 90% of its non-blank pages qualifies -- the pages it left empty are
  listed for the recovery lane instead of failing the pod.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from arena.controller.canary import (
    BLANK_DARK_FRACTION,
    CanaryPageResult,
    canary_receipt_document,
    dark_pixel_fraction,
    evaluate_canary,
    results_from_receipts,
    write_canary_receipt,
    write_registry_update,
)
from arena.controller.paths import CampaignPaths
from arena.core.receipts import validate
from PIL import Image, ImageDraw

EXPECTED_REVISION = "a" * 40


def _page(
    index: int, *, status: str = "SUCCESS", chars: int = 1200, **kw: object
) -> CanaryPageResult:
    base: dict[str, object] = {
        "case_key": f"omnidocbench-{index:06d}",
        "sample_id": f"omnidoc:images/page_{index:04d}",
        "benchmark": "omnidoc",
        "status": status,
        "error_class": None if status == "SUCCESS" else "OUTPUT_EMPTY",
        "total_ms": 3500,
        "load_ms": 0,
        "preprocess_ms": 100,
        "inference_ms": 3340,
        "postprocess_ms": 60,
        "output_chars": chars,
        "peak_vram_mb": 17000,
        "model_revision": EXPECTED_REVISION,
        "schema_valid": status == "SUCCESS",
        "warm": index > 0,
    }
    base.update(kw)
    return CanaryPageResult(**base)  # type: ignore[arg-type]


def _png(*, ink_rows: int, width: int = 200, height: int = 200) -> bytes:
    """A white page with ``ink_rows`` rows of black pixels."""

    image = Image.new("RGB", (width, height), "white")
    if ink_rows:
        ImageDraw.Draw(image).rectangle([0, 0, width - 1, ink_rows - 1], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------- blankness


def test_a_truly_blank_page_measures_below_the_threshold() -> None:
    assert dark_pixel_fraction(_png(ink_rows=0)) == 0.0


def test_a_colourful_page_that_is_mostly_white_is_not_blank() -> None:
    """The 2026-09-03 page: 80% white, 1.9% ink. Not blank, and not blankable."""

    fraction = dark_pixel_fraction(_png(ink_rows=4))  # 4/200 rows = 2%
    assert fraction > BLANK_DARK_FRACTION
    assert fraction == 0.02


def test_the_threshold_boundary_is_measured_not_guessed() -> None:
    # 0.2% of 200 rows is 0.4 of a row, so one row (0.5%) is already ink and
    # zero rows is the only blank page in this geometry.
    assert dark_pixel_fraction(_png(ink_rows=1)) == 0.005 > BLANK_DARK_FRACTION


def test_results_from_receipts_classifies_blankness_from_the_page_bytes() -> None:
    receipts = [
        {"case_key": "blank", "started_at": "2026-09-03T20:05:00Z", "status": "SUCCESS"},
        {"case_key": "inked", "started_at": "2026-09-03T20:06:00Z", "status": "SUCCESS"},
    ]
    pages = {"blank": _png(ink_rows=0), "inked": _png(ink_rows=40)}

    results = results_from_receipts(receipts, page_bytes=lambda key: pages[key])

    by_key = {result.case_key: result for result in results}
    assert by_key["blank"].blank_source is True
    assert by_key["blank"].dark_fraction == 0.0
    assert by_key["inked"].blank_source is False
    assert by_key["inked"].dark_fraction == 0.2


def test_a_page_that_cannot_be_read_counts_as_non_blank() -> None:
    """Calling an unreadable page blank would excuse the model from answering."""

    def explode(_key: str) -> bytes:
        raise FileNotFoundError("staged page is gone")

    (result,) = results_from_receipts(
        [{"case_key": "gone", "started_at": "2026-09-03T20:05:00Z", "status": "SUCCESS"}],
        page_bytes=explode,
    )

    assert result.dark_fraction is None
    assert result.blank_source is False


def test_without_a_resolver_nothing_is_called_blank() -> None:
    (result,) = results_from_receipts(
        [{"case_key": "x", "started_at": "2026-09-03T20:05:00Z", "status": "SUCCESS"}]
    )

    assert result.dark_fraction is None
    assert result.blank_source is False


# ------------------------------------------------- the 90% non-empty floor


def test_one_empty_page_in_fifteen_no_longer_fails_the_runtime() -> None:
    """The real GLM-OCR canary: 15/15 SUCCESS, one page with 0 chars."""

    pages = [_page(index) for index in range(14)] + [_page(14, chars=0)]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )

    assert report.checks["output_non_empty_on_non_blank"] is True
    assert report.passed is True
    assert report.non_empty_output_ratio == 14 / 15


def test_exactly_ninety_percent_passes() -> None:
    pages = [_page(index) for index in range(9)] + [_page(9, chars=0)]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )

    assert report.non_empty_output_ratio == 0.9
    assert report.checks["output_non_empty_on_non_blank"] is True


def test_just_below_ninety_percent_still_fails() -> None:
    pages = [_page(index) for index in range(9)] + [
        _page(9, chars=0),
        _page(10, chars=0),
    ]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )

    assert report.non_empty_output_ratio == 9 / 11
    assert report.checks["output_non_empty_on_non_blank"] is False
    assert report.passed is False
    assert any("below the 90%" in message for message in report.failures)


def test_blank_pages_are_outside_the_denominator() -> None:
    pages = [_page(index) for index in range(2)] + [
        _page(index, chars=0, blank_source=True, dark_fraction=0.0) for index in range(2, 10)
    ]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )

    assert report.non_blank_success_count == 2
    assert report.non_empty_output_ratio == 1.0
    assert report.empty_output_pages == ()


def test_every_empty_non_blank_page_is_named_for_the_recovery_lane() -> None:
    pages = [_page(index) for index in range(14)] + [
        _page(14, chars=0, dark_fraction=0.019)
    ]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
    )

    (empty,) = report.empty_output_pages
    assert empty["case_key"] == "omnidocbench-000014"
    assert empty["dark_fraction"] == 0.019
    assert empty["total_ms"] == 3500
    assert empty["semantic_error_class"] == "OUTPUT_EMPTY"


def test_the_receipt_lists_the_empty_pages_and_stays_schema_valid(
    paths: CampaignPaths,
) -> None:
    pages = [_page(index) for index in range(14)] + [
        _page(14, chars=0, dark_fraction=0.019)
    ]
    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_000,
        hourly_rate_usd=0.34,
        price_row_sha256="c" * 64,
    )

    document = canary_receipt_document(
        report,
        model_revision=EXPECTED_REVISION,
        runtime_image_digest="bootstrap:sha256:" + "d" * 64,
        runtime_mode="bootstrap",
        gpu_type="NVIDIA GeForce RTX 4090",
        started_at="2026-09-03T20:05:00Z",
        finished_at="2026-09-03T20:16:00Z",
        pod_id="trzep8nu19x000",
    )

    validate(document, "canary-receipt")
    assert document["status"] == "PASS"
    (empty,) = document["empty_output_pages"]  # type: ignore[misc]
    assert empty["case_key"] == "omnidocbench-000014"
    assert document["non_empty_output_ratio"] == 0.9333

    receipt_path = write_canary_receipt(
        report,
        paths,
        model_revision=EXPECTED_REVISION,
        runtime_image_digest="bootstrap:sha256:" + "d" * 64,
        runtime_mode="bootstrap",
        gpu_type="NVIDIA GeForce RTX 4090",
        started_at="2026-09-03T20:05:00Z",
        finished_at="2026-09-03T20:16:00Z",
        pod_id="trzep8nu19x000",
    )
    assert Path(receipt_path).is_file()

    update = json.loads(
        Path(write_registry_update(report, paths)).read_text(encoding="utf-8")
    )
    assert update["fields"]["canary_empty_output_pages"][0]["case_key"] == (
        "omnidocbench-000014"
    )
    assert "OUTPUT_EMPTY" in update["note"]


# ------------------------------------------------------------------ VRAM


def test_a_whole_gpu_peak_satisfies_the_headroom_criterion() -> None:
    """A per-process figure does not exist for a separately served model."""

    pages = [
        _page(index, peak_vram_mb=18240, vram_total_mb=24564, vram_measurement_source="nvidia-smi")
        for index in range(5)
    ]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=None,  # the runtime declared no floor
        hourly_rate_usd=0.34,
    )

    assert report.checks["vram_headroom_measured"] is True
    assert report.vram_total_mb == 24564
    assert report.vram_headroom_mb == 24564 - 18240
    assert report.vram_measurement_source == "nvidia-smi"


def test_the_measured_device_total_beats_the_rented_floor() -> None:
    pages = [
        _page(index, peak_vram_mb=18240, vram_total_mb=24564, vram_measurement_source="nvidia-smi")
        for index in range(5)
    ]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_576,  # 24 GiB floor the pool was matched against
        hourly_rate_usd=0.34,
    )

    assert report.vram_headroom_mb == 24564 - 18240


def test_the_declared_floor_is_used_when_nothing_measured_the_total() -> None:
    pages = [_page(index, peak_vram_mb=18240) for index in range(5)]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_576,
        hourly_rate_usd=0.34,
    )

    assert report.vram_total_mb is None
    assert report.vram_headroom_mb == 24_576 - 18240
    assert report.checks["vram_headroom_measured"] is True


def test_a_canary_that_measured_no_vram_at_all_still_fails_the_criterion() -> None:
    pages = [_page(index, peak_vram_mb=None) for index in range(5)]

    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_576,
        hourly_rate_usd=0.34,
    )

    assert report.checks["vram_headroom_measured"] is False
    assert report.peak_vram_mb is None
    assert report.vram_headroom_mb is None


def test_the_receipt_reports_the_measured_total_not_the_rented_one() -> None:
    pages = [
        _page(index, peak_vram_mb=18240, vram_total_mb=24564, vram_measurement_source="nvidia-smi")
        for index in range(5)
    ]
    report = evaluate_canary(
        "glm_ocr",
        pages,
        expected_model_revision=EXPECTED_REVISION,
        gpu_vram_mb=24_576,
        hourly_rate_usd=0.34,
        price_row_sha256="c" * 64,
    )

    document = canary_receipt_document(
        report,
        model_revision=EXPECTED_REVISION,
        runtime_image_digest="bootstrap:sha256:" + "d" * 64,
        runtime_mode="bootstrap",
        gpu_type="NVIDIA GeForce RTX 4090",
        started_at="2026-09-03T20:05:00Z",
        finished_at="2026-09-03T20:16:00Z",
        pod_id="trzep8nu19x000",
        gpu_total_vram_mb=24_576,
    )

    validate(document, "canary-receipt")
    assert document["gpu_total_vram_mb"] == 24564
    assert document["vram_measurement_source"] == "nvidia-smi"


def test_receipts_carry_the_vram_columns_into_the_results() -> None:
    (result,) = results_from_receipts(
        [
            {
                "case_key": "x",
                "started_at": "2026-09-03T20:05:00Z",
                "status": "SUCCESS",
                "peak_vram_mb": 18240,
                "vram_total_mb": 24564,
                "vram_measurement_source": "nvidia-smi",
            }
        ]
    )

    assert result.peak_vram_mb == 18240
    assert result.vram_total_mb == 24564
    assert result.vram_measurement_source == "nvidia-smi"
