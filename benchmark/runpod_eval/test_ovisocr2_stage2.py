from pathlib import Path

import pytest
from ovisocr2_stage2 import chunked, clean_truncated_repeats, filter_visual_region_tags


def test_filters_only_vendor_visual_region_blocks() -> None:
    markdown = 'Heading\n\n<img src="images/bbox_1_2_3_4.jpg" />\n\nBody'
    assert filter_visual_region_tags(markdown) == "Heading\n\nBody"


def test_preserves_inline_image_tag() -> None:
    markdown = 'Caption <img src="images/bbox_1_2_3_4.jpg" />'
    assert filter_visual_region_tags(markdown) == markdown


def test_cleans_long_repeated_tail() -> None:
    prefix = "x" * 8_000
    unit = "ABCD" * 30
    assert clean_truncated_repeats(prefix + unit * 6) == prefix + "ABCD"


def test_chunks_inputs_and_rejects_invalid_size() -> None:
    items = [Path(str(index)) for index in range(5)]
    assert [len(batch) for batch in chunked(items, 2)] == [2, 2, 1]
    with pytest.raises(ValueError):
        list(chunked(items, 0))
