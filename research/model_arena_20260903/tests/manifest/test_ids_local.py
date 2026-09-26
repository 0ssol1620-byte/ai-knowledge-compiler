from __future__ import annotations

import pytest
from arena.manifest.ids_local import compute_case_key, compute_sample_id


def test_sample_id_image_strips_extension_and_has_no_page_suffix() -> None:
    sample_id = compute_sample_id(
        benchmark="omnidoc",
        source_relative_path="images/PPT_1001115_eng_page_003.png",
        media_type="image",
        page_index=3,
    )
    assert sample_id == "omnidoc:images/PPT_1001115_eng_page_003"


def test_sample_id_pdf_appends_page_index() -> None:
    sample_id = compute_sample_id(
        benchmark="parsebench",
        source_relative_path="docs/chart/(Web_version)_E-Government_Survey_2024_1392024_p101.pdf",
        media_type="pdf",
        page_index=0,
    )
    assert sample_id == (
        "parsebench:docs/chart/(Web_version)_E-Government_Survey_2024_1392024_p101#p0"
    )


def test_sample_id_olmocr_example_from_contract() -> None:
    sample_id = compute_sample_id(
        benchmark="olmocr",
        source_relative_path="bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf",
        media_type="pdf",
        page_index=0,
    )
    assert sample_id == "olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0"


def test_sample_id_rejects_empty_benchmark() -> None:
    with pytest.raises(ValueError, match="benchmark"):
        compute_sample_id(
            benchmark="", source_relative_path="a.png", media_type="image", page_index=0
        )


def test_sample_id_rejects_empty_source_path() -> None:
    with pytest.raises(ValueError, match="source_relative_path"):
        compute_sample_id(
            benchmark="omnidoc", source_relative_path="", media_type="image", page_index=0
        )


def test_sample_id_rejects_unsupported_media_type() -> None:
    with pytest.raises(ValueError, match="media_type"):
        compute_sample_id(
            benchmark="omnidoc", source_relative_path="a.png", media_type="tiff", page_index=0
        )


def test_sample_id_rejects_negative_page_index_for_pdf() -> None:
    with pytest.raises(ValueError, match="page_index"):
        compute_sample_id(
            benchmark="olmocr", source_relative_path="a.pdf", media_type="pdf", page_index=-1
        )


def test_case_key_is_verbatim() -> None:
    assert compute_case_key("omnidocbench-58851882e7b39101a6f5756c") == (
        "omnidocbench-58851882e7b39101a6f5756c"
    )


def test_case_key_rejects_empty() -> None:
    with pytest.raises(ValueError, match="case_id"):
        compute_case_key("")
