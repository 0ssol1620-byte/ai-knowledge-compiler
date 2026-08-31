"""Generator provenance for the RQ-01 qualification smoke fixture.

This script documents *how* ``rq-01-smoke-001.png`` was produced. It is not
meant to be re-run to regenerate the committed artifact: font rasterization is
not guaranteed byte-identical across Pillow versions or host font libraries,
so the on-disk PNG bytes are the frozen fixture and this script is provenance,
not a build step. If it is re-run and produces different bytes than the
committed file, the committed file remains authoritative (see
``manifest.json``'s ``regeneration_note``).

The image is 100% self-authored synthetic content: a caption line, a short
paragraph of plain ASCII text, one 2x2 table, and one "critical token" line
(a version string). It is not derived from OmniDocBench, the frozen
SEM-RISK-CONF-02 confirmatory cohort, or any other external corpus. It exists
only so a RunPod qualification smoke test has a deterministic-shaped document
image to feed the model and confirm the pipeline returns *some* markdown-like
output -- it is not a benchmark input and carries no ground truth.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURE_DIR = Path(__file__).resolve().parent
IMAGE_PATH = FIXTURE_DIR / "rq-01-smoke-001.png"

_WIDTH = 900
_HEIGHT = 600
_MARGIN = 40
_INK = (20, 20, 20)
_RULE = (120, 120, 120)


def _load_font(size: int) -> ImageFont.ImageFont:
    """Best-effort monospace/default font; falls back to the PIL bitmap font."""
    for candidate in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_image() -> Image.Image:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    heading_font = _load_font(28)
    body_font = _load_font(18)

    y = _MARGIN
    draw.text((_MARGIN, y), "RQ-01 Qualification Smoke Fixture", fill=_INK, font=heading_font)
    y += 46

    body_lines = [
        "This is a synthetic smoke document. It contains no real",
        "content and no ground truth. It exists to confirm that a",
        "RunPod-hosted OCR model returns structured output at all.",
    ]
    for line in body_lines:
        draw.text((_MARGIN, y), line, fill=_INK, font=body_font)
        y += 26

    y += 20
    draw.text((_MARGIN, y), "Sample Table", fill=_INK, font=body_font)
    y += 30

    table_top = y
    col_w = 200
    row_h = 40
    cells = [["Item", "Count"], ["Widget", "7"]]
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            x0 = _MARGIN + c * col_w
            y0 = table_top + r * row_h
            draw.rectangle(
                [x0, y0, x0 + col_w, y0 + row_h], outline=_RULE, width=2
            )
            draw.text((x0 + 12, y0 + 10), text, fill=_INK, font=body_font)
    y = table_top + len(cells) * row_h + 40

    draw.text((_MARGIN, y), "Version: 1.4.2", fill=_INK, font=heading_font)

    return image


def main() -> None:
    image = build_image()
    if IMAGE_PATH.exists():
        print(f"{IMAGE_PATH} already exists; not overwriting the frozen fixture.")
        return
    image.save(IMAGE_PATH, format="PNG")
    digest = hashlib.sha256(IMAGE_PATH.read_bytes()).hexdigest()
    print(f"wrote {IMAGE_PATH} sha256={digest} bytes={IMAGE_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
