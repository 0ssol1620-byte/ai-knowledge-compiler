"""Synthetic warm-up page (masterplan section 15.3, stage 2).

The warm-up must exercise the same code path as a real page — decode, resize,
prompt, generate — without touching a benchmark sample. This draws a plain
white A4-ish page with a heading, body lines and a 3x3 table, entirely with
Pillow so no font file or network fetch is needed.

Deterministic: the same arguments always produce byte-identical PNG output, so
a warm-up receipt can be compared across pods.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

from arena.worker.util import atomic_write_bytes

DEFAULT_WIDTH: Final = 1240
DEFAULT_HEIGHT: Final = 1754

HEADING: Final = "TAVONEL ARENA WARMUP PAGE"
BODY_LINES: Final = (
    "This page is synthetic. It is not a benchmark sample and carries",
    "no ground truth. It exists only to prove that the loaded model can",
    "decode an image, follow the campaign prompt and emit text.",
)
TABLE_CELLS: Final = (
    ("Column A", "Column B", "Column C"),
    ("row 1", "12.5", "OK"),
    ("row 2", "308", "OK"),
)


class SyntheticPageError(RuntimeError):
    """Pillow is unavailable, so no warm-up page can be produced."""


def render_synthetic_page(
    *, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT
) -> bytes:
    """Return the PNG bytes of the warm-up page."""
    # Guarded import: pillow is the worker's only non-stdlib dependency and a
    # runtime image that lacks it must fail loudly at warm-up, not silently.
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - pillow is a declared dependency
        raise SyntheticPageError(
            "pillow is required to render the warm-up page; the runtime image must ship it"
        ) from exc

    if width < 320 or height < 320:
        raise SyntheticPageError(f"synthetic page too small: {width}x{height}")

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = width // 12
    black = (0, 0, 0)

    # Heading: real glyphs plus a rule, so OCR has something unambiguous.
    draw.text((margin, margin), HEADING, fill=black)
    draw.rectangle(
        (margin, margin + 24, width - margin, margin + 30), fill=black
    )

    y = margin + 70
    for line in BODY_LINES:
        draw.text((margin, y), line, fill=black)
        # A solid bar under each line keeps the page legible at any downscale.
        draw.rectangle((margin, y + 16, width - margin - width // 6, y + 20), fill=black)
        y += 46

    # 3x3 table.
    table_top = y + 60
    table_left = margin
    table_right = width - margin
    col_width = (table_right - table_left) // 3
    row_height = 90
    for row in range(4):
        line_y = table_top + row * row_height
        draw.line((table_left, line_y, table_right, line_y), fill=black, width=3)
    for col in range(4):
        line_x = table_left + col * col_width
        draw.line(
            (line_x, table_top, line_x, table_top + 3 * row_height), fill=black, width=3
        )
    for row_index, row_cells in enumerate(TABLE_CELLS):
        for col_index, cell in enumerate(row_cells):
            draw.text(
                (
                    table_left + col_index * col_width + 16,
                    table_top + row_index * row_height + 30,
                ),
                cell,
                fill=black,
            )

    buffer = io.BytesIO()
    # optimize=False keeps the encoder deterministic across Pillow builds.
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


def synthetic_page_png(
    path: Path, *, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT
) -> Path:
    """Write the warm-up page to ``path`` atomically and return the path."""
    atomic_write_bytes(path, render_synthetic_page(width=width, height=height))
    return path


__all__ = [
    "BODY_LINES",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "HEADING",
    "TABLE_CELLS",
    "SyntheticPageError",
    "render_synthetic_page",
    "synthetic_page_png",
]
