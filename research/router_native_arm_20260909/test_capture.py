"""Protect the denominator and spent-only scope before any parser is invoked."""

import json

import pytest
from capture_spent import select_rows


def row(index: int) -> dict:
    return {
        "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
        "sample_id": f"olmocr:fixture-{index}",
        "benchmark": "olmocr",
        "media_type": "pdf",
        "original_source_relative_path": f"bench_data/pdfs/family/{index}.pdf",
    }


def encode(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(item) for item in rows).encode()


def test_full_capture_keeps_units_beyond_pilot_limit_and_is_order_independent():
    rows = [row(index) for index in range(17)]
    full, count = select_rows(encode(rows), all_units=True, expected_units=17)
    reversed_full, _ = select_rows(encode(rows[::-1]), all_units=True, expected_units=17)
    pilot, pilot_count = select_rows(encode(rows), all_units=False, expected_units=17)
    assert full == reversed_full
    assert {item["sample_id"] for item in full} == {item["sample_id"] for item in rows}
    assert count == pilot_count == 17
    assert len(pilot) == 8


def test_duplicate_source_cannot_inflate_the_denominator():
    with pytest.raises(ValueError, match="DUPLICATE_SPENT_SOURCE_UNIT"):
        select_rows(encode([row(0), row(0)]), all_units=True, expected_units=2)


def test_missing_source_cannot_be_silently_dropped():
    with pytest.raises(ValueError, match="SPENT_SOURCE_DENOMINATOR_MISMATCH"):
        select_rows(encode([row(0)]), all_units=True, expected_units=2)


def test_different_campaign_cannot_be_used_as_spent_development():
    item = row(0)
    item["campaign_id"] = "fresh-holdout"
    with pytest.raises(ValueError, match="SPENT_CAMPAIGN_MISMATCH"):
        select_rows(encode([item]), all_units=True, expected_units=1)


def test_other_benchmark_is_outside_the_declared_native_pdf_scope():
    excluded = row(1)
    excluded["benchmark"] = "omnidoc"
    selected, count = select_rows(encode([row(0), excluded]), all_units=True, expected_units=1)
    assert selected == [row(0)]
    assert count == 1


@pytest.mark.parametrize("relative", ["../private.pdf", "bench_data/pdfs/file.txt"])
def test_source_path_must_remain_a_pdf_within_the_bound_inventory(relative):
    item = row(0)
    item["original_source_relative_path"] = relative
    with pytest.raises(ValueError, match="PUBLIC_SOURCE_PATH_INVALID"):
        select_rows(encode([item]), all_units=True, expected_units=1)


@pytest.mark.parametrize("count", [0, 2001, True])
def test_capture_scope_is_bounded(count):
    with pytest.raises(ValueError, match="SPENT_SCOPE_BOUND_INVALID"):
        select_rows(encode([row(0)]), all_units=True, expected_units=count)
