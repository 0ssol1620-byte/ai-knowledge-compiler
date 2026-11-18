"""WO-D07-5: the router census must not turn unmeasured sentinels into verdicts."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from akc_native_parsers import ParseContext, parse_pdf_to_cir
from akc_router import (
    Route,
    RouterContext,
    classify_page,
    preflight_difficulty,
    select_first_route,
)
from akc_router.preflight import PageMetrics, PageTechnicalClass
from akc_worker_document.worker import AnalysisWorker
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

UNKNOWN = frozenset(
    {
        "handwriting_probability",
        "rotation_degrees",
        "skew_degrees",
        "blur_score",
        "contrast_score",
        "small_text_score",
    }
)
_BODY = "Quarterly evidence summary. " * 12


def _metrics(**over: Any) -> PageMetrics:
    base: dict[str, Any] = {
        "page_index0": 0,
        "width": 612,
        "height": 792,
        "native_text_chars": 400,
        "native_word_count": 60,
        "native_block_count": 3,
        "native_text_coverage": 0.2,
        "image_coverage": 0.0,
        "invalid_unicode_ratio": 0.0,
        "replacement_char_ratio": 0.0,
        "whitespace_anomaly_score": 0.0,
        "native_reading_order_score": 0.95,
        "estimated_columns": 1,
        "table_density": 0.0,
        "formula_density": 0.0,
        "chart_probability": 0.0,
        "handwriting_probability": 0.5,  # the worker's sentinel
        "rotation_degrees": 0,
        "skew_degrees": 0.0,
        "blur_score": 0.5,
        "contrast_score": 0.5,
        "small_text_score": 0.5,
        "script_distribution": {"Latin": 1.0},
        "suspected_prompt_injection": False,
    }
    base.update(over)
    return PageMetrics(**base)


def _context() -> RouterContext:
    return RouterContext()


def test_sentinel_handwriting_is_not_a_handwriting_verdict() -> None:
    m = _metrics()
    assert classify_page(m) is PageTechnicalClass.HANDWRITTEN  # documents the defect
    assert classify_page(m, unknown_metrics=UNKNOWN) is PageTechnicalClass.NATIVE_CLEAN
    assert preflight_difficulty(m, unknown_metrics=UNKNOWN) < preflight_difficulty(m)


def test_measured_handwriting_still_wins() -> None:
    m = _metrics(handwriting_probability=0.9)
    assert classify_page(m) is PageTechnicalClass.HANDWRITTEN
    # an unknown list that does not name handwriting must not hide a real measurement
    assert (
        classify_page(m, unknown_metrics=UNKNOWN - {"handwriting_probability"})
        is PageTechnicalClass.HANDWRITTEN
    )


def test_unknown_rotation_and_skew_are_skipped_but_measured_ones_count() -> None:
    m = _metrics(rotation_degrees=90, skew_degrees=5.0)
    assert classify_page(m, unknown_metrics=UNKNOWN) is PageTechnicalClass.NATIVE_CLEAN
    measured = UNKNOWN - {"rotation_degrees", "skew_degrees"}
    assert classify_page(m, unknown_metrics=measured) is PageTechnicalClass.ROTATED_OR_WARPED


# --- fixture census: PDF -> CIR -> worker preflight -> router ---------------


def _pdf(*texts: str | None) -> bytes:
    """One page per entry: a text page, or a full-page raster image when None."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in texts:
        if text is None:
            buffer = io.BytesIO()
            Image.new("RGB", (612, 792), "white").save(buffer, format="PDF", resolution=72)
            writer.add_page(PdfReader(io.BytesIO(buffer.getvalue())).pages[0])
            continue
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        ops = b"BT /F1 11 Tf 72 720 Td 14 TL "
        for i in range(0, len(text), 80):
            ops += b"(" + text[i : i + 80].encode("ascii") + b") Tj T* "
        content.set_data(ops + b"ET")
        page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _census(pdf: bytes) -> list[tuple[PageTechnicalClass, Route]]:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    document = parse_pdf_to_cir(
        filename="f.pdf",
        declared_mime="application/pdf",
        data=pdf,
        context=ParseContext(
            tenant_id="tenant-census",
            document_id="doc-census",
            document_version_id="doc-census:v1",
            created_at=now,
            retrieved_at=now,
        ),
        max_pages=8,
    )
    result = []
    for page_no in range(1, len(document.metadata["pages"]) + 1):
        blocks = [b for b in document.blocks if b.source_refs[0].page_number1 == page_no]
        image = any("embedded_image_native" in b.quality_flags for b in blocks)
        text = "\n".join(
            b.raw_text or "" for b in blocks if "embedded_image_native" not in b.quality_flags
        )
        m = AnalysisWorker._page_preflight(
            text,
            image_coverage=1.0 if image else 0.0,
            width_pt=612.0,
            height_pt=792.0,
            canonical_blocks=blocks,
        )
        pm = _metrics(
            native_text_chars=int(m["native_text_chars"]),
            native_word_count=int(m["native_words"]),
            native_block_count=max(1, len(blocks)),
            native_text_coverage=float(m["native_text_coverage"]),
            image_coverage=1.0 if image else 0.0,
            invalid_unicode_ratio=float(m["invalid_char_ratio"]),
            replacement_char_ratio=float(m["replacement_char_ratio"]),
            whitespace_anomaly_score=float(m["whitespace_anomaly_score"]),
            native_reading_order_score=float(m["native_reading_order_score"]),
            estimated_columns=int(m["estimated_columns"]),
            script_distribution=dict(m["script_distribution"]),
        )
        unknown = frozenset(m["unknown_visual_metrics"])
        result.append(
            (
                classify_page(pm, unknown_metrics=unknown),
                select_first_route(_context(), pm).route,
            )
        )
    return result


def test_fixture_pdfs_census_end_to_end() -> None:
    digital = _census(_pdf(_BODY))
    assert digital[0][1] is Route.NATIVE
    assert digital[0][0] in {PageTechnicalClass.NATIVE_CLEAN, PageTechnicalClass.NATIVE_COMPLEX}

    scan = _census(_pdf(None))
    assert scan[0][1] is not Route.NATIVE
    assert not scan[0][0].value.startswith("NATIVE")

    mixed = _census(_pdf(_BODY, None))
    assert mixed[0][1] is Route.NATIVE
    assert mixed[1][1] is not Route.NATIVE


def test_malformed_unicode_page_is_not_native() -> None:
    bad = "Evidence � text \x01\x02 broken � " * 12
    m = AnalysisWorker._page_preflight(
        bad, image_coverage=0.0, width_pt=612.0, height_pt=792.0, canonical_blocks=[]
    )
    pm = _metrics(
        native_text_chars=int(m["native_text_chars"]),
        invalid_unicode_ratio=float(m["invalid_char_ratio"]),
        replacement_char_ratio=float(m["replacement_char_ratio"]),
        native_reading_order_score=float(m["native_reading_order_score"]),
        native_text_coverage=float(m["native_text_coverage"]),
    )
    assert select_first_route(_context(), pm).route is not Route.NATIVE
    assert not classify_page(pm, unknown_metrics=UNKNOWN).value.startswith("NATIVE")


def test_page_with_no_blocks_is_not_native_and_not_silent() -> None:
    m = AnalysisWorker._page_preflight(
        "", image_coverage=0.0, width_pt=612.0, height_pt=792.0, canonical_blocks=[]
    )
    assert m["native_text_chars"] == 0
    pm = _metrics(
        native_text_chars=0,
        native_word_count=0,
        native_block_count=0,
        native_text_coverage=0.0,
        native_reading_order_score=0.0,
        script_distribution={},
    )
    assert classify_page(pm, unknown_metrics=UNKNOWN) is PageTechnicalClass.UNKNOWN
    assert select_first_route(_context(), pm).route is not Route.NATIVE
