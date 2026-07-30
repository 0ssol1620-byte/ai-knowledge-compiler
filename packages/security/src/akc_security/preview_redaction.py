"""Deterministic redaction of derived page-preview images."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, UnidentifiedImageError

type NormalizedBox = tuple[int, int, int, int]


class UnsafePreviewError(ValueError):
    """Raised when a derived preview cannot be safely redacted."""


@dataclass(frozen=True, slots=True)
class RedactedPreview:
    png_bytes: bytes
    sha256: str
    masked_region_count: int
    width: int
    height: int


def _validate_box(box: NormalizedBox) -> None:
    if len(box) != 4:
        raise UnsafePreviewError("normalized box must contain four coordinates")
    left, top, right, bottom = box
    if not (0 <= left < right <= 1000 and 0 <= top < bottom <= 1000):
        raise UnsafePreviewError("normalized box is outside the 0..1000 coordinate space")


def redact_preview_png(
    png_bytes: bytes,
    boxes1000: list[NormalizedBox] | tuple[NormalizedBox, ...],
    *,
    maximum_bytes: int = 16 * 1024 * 1024,
    maximum_pixels: int = 20_000_000,
    maximum_regions: int = 2_000,
) -> RedactedPreview:
    """Return a black-box redacted PNG derivative.

    The source PNG is immutable.  Bounding boxes use the CIR ``bbox1000``
    coordinate system and are expanded slightly so anti-aliased glyph edges do
    not remain visible.
    """

    if not png_bytes or len(png_bytes) > maximum_bytes:
        raise UnsafePreviewError("preview byte size is outside the configured bound")
    if len(boxes1000) > maximum_regions:
        raise UnsafePreviewError("preview redaction region count exceeds the configured bound")
    for box in boxes1000:
        _validate_box(box)
    try:
        with Image.open(io.BytesIO(png_bytes)) as source:
            if source.format != "PNG":
                raise UnsafePreviewError("preview must be a PNG")
            width, height = source.size
            if width < 1 or height < 1 or width * height > maximum_pixels:
                raise UnsafePreviewError("preview dimensions exceed the configured bound")
            source.load()
            redacted = source.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise UnsafePreviewError("preview image is malformed") from exc

    draw = ImageDraw.Draw(redacted)
    for left, top, right, bottom in boxes1000:
        pixel_box = (
            max(0, (left * width) // 1000 - 2),
            max(0, (top * height) // 1000 - 2),
            min(width - 1, ((right * width) + 999) // 1000 + 2),
            min(height - 1, ((bottom * height) + 999) // 1000 + 2),
        )
        draw.rectangle(pixel_box, fill=(0, 0, 0))

    output = io.BytesIO()
    redacted.save(output, format="PNG", optimize=True)
    result = output.getvalue()
    if not result or len(result) > maximum_bytes:
        raise UnsafePreviewError("redacted preview exceeds the configured byte bound")
    return RedactedPreview(
        png_bytes=result,
        sha256=hashlib.sha256(result).hexdigest(),
        masked_region_count=len(boxes1000),
        width=width,
        height=height,
    )
