from __future__ import annotations

import hashlib
import io

import pytest
from akc_security.preview_redaction import (
    UnsafePreviewError,
    crop_preview_png,
    redact_preview_png,
)
from PIL import Image


def _png(*, width: int = 100, height: int = 80) -> bytes:
    image = Image.new("RGB", (width, height), (255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_redaction_returns_new_integrity_checked_derivative() -> None:
    source = _png()

    result = redact_preview_png(source, [(100, 200, 600, 500)])

    assert result.png_bytes != source
    assert result.sha256 == hashlib.sha256(result.png_bytes).hexdigest()
    assert result.masked_region_count == 1
    assert (result.width, result.height) == (100, 80)
    with Image.open(io.BytesIO(result.png_bytes)) as image:
        assert image.getpixel((30, 25)) == (0, 0, 0)
        assert image.getpixel((90, 70)) == (255, 255, 255)


@pytest.mark.parametrize(
    "box",
    [
        (-1, 0, 10, 10),
        (0, 0, 1001, 10),
        (10, 10, 10, 20),
        (20, 20, 10, 30),
    ],
)
def test_invalid_normalized_boxes_fail_closed(box: tuple[int, int, int, int]) -> None:
    with pytest.raises(UnsafePreviewError, match="coordinate"):
        redact_preview_png(_png(), [box])


def test_non_png_and_oversized_inputs_fail_closed() -> None:
    with pytest.raises(UnsafePreviewError, match=r"PNG|malformed"):
        redact_preview_png(b"not-an-image", [])
    with pytest.raises(UnsafePreviewError, match="byte size"):
        redact_preview_png(_png(), [], maximum_bytes=2)
    with pytest.raises(UnsafePreviewError, match="dimensions"):
        redact_preview_png(_png(width=20, height=20), [], maximum_pixels=399)


def test_region_count_is_bounded() -> None:
    boxes = [(0, 0, 1, 1)] * 3
    with pytest.raises(UnsafePreviewError, match="region count"):
        redact_preview_png(_png(), boxes, maximum_regions=2)


def test_proof_crop_uses_bbox1000_with_bounded_padding() -> None:
    result = crop_preview_png(
        _png(width=100, height=200),
        (250, 250, 750, 750),
        padding1000=0,
    )

    assert (result.width, result.height) == (50, 100)
    assert result.sha256 == hashlib.sha256(result.png_bytes).hexdigest()


@pytest.mark.parametrize("box", [(-1, 0, 2, 2), (0, 0, 1001, 2), (5, 5, 5, 9)])
def test_proof_crop_rejects_invalid_boxes(box: tuple[int, int, int, int]) -> None:
    with pytest.raises(UnsafePreviewError):
        crop_preview_png(_png(), box)
