"""GT-free preflight features (masterplan section 41).

Blank-page / valid-empty handling: these are heuristic, source-only signals
computed without ever looking at ground truth or any evaluator label. They
are recorded so the QA and TAVONEL lanes can distinguish "valid blank source"
from "failed empty extraction" later; ``is_probably_blank`` is a heuristic
flag, never a ground-truth label and never a scoring input.

Pillow is a heavy/optional-in-spirit import (not stdlib); it is imported at
module load here because this module is only ever used off the hot worker
path (manifest build, tests), never inside a runtime adapter's module import.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

_MAX_DOWNSAMPLE_SIDE = 256
_NEAR_WHITE_THRESHOLD = 245
_EDGE_DELTA_THRESHOLD = 32
_BLANK_NEAR_WHITE_RATIO = 0.995
_BLANK_ENTROPY_BITS = 0.5


@dataclass(frozen=True, slots=True)
class PreflightResult:
    width: int
    height: int
    near_white_ratio: float
    render_entropy: float
    mean_intensity: float
    edge_density: float
    is_probably_blank: bool

    def as_features_dict(self) -> dict[str, Any]:
        return {
            "near_white_ratio": self.near_white_ratio,
            "render_entropy": self.render_entropy,
            "mean_intensity": self.mean_intensity,
            "edge_density": self.edge_density,
            "is_probably_blank": self.is_probably_blank,
        }


def compute_preflight_features(image_path: Path) -> PreflightResult:
    """Compute GT-blind preflight features for one staged PNG.

    All statistics (other than the returned original ``width``/``height``)
    are computed on a grayscale downsample capped at ``_MAX_DOWNSAMPLE_SIDE``
    on the long side, using Pillow's C-level histogram/crop/diff ops so this
    is cheap enough to run over the full 5,132-page corpus.
    """
    with Image.open(image_path) as source:
        width, height = source.size
        if width <= 0 or height <= 0:
            raise ValueError(f"image has invalid dimensions: {image_path}")
        grayscale = source.convert("L")
        scale = min(1.0, _MAX_DOWNSAMPLE_SIDE / max(width, height))
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        downsampled = (
            grayscale.resize(target, resample=Image.Resampling.BILINEAR)
            if target != (width, height)
            else grayscale
        )

        dw, dh = downsampled.size
        total = dw * dh
        if total == 0:
            raise ValueError(f"downsampled image has no pixels: {image_path}")

        histogram = downsampled.histogram()
        near_white = sum(histogram[_NEAR_WHITE_THRESHOLD:])
        near_white_ratio = near_white / total
        mean_intensity = sum(level * count for level, count in enumerate(histogram)) / total

        entropy = 0.0
        for count in histogram:
            if count == 0:
                continue
            probability = count / total
            entropy -= probability * math.log2(probability)

        horiz_hits = 0
        horiz_pairs = 0
        if dw > 1:
            left = downsampled.crop((0, 0, dw - 1, dh))
            right = downsampled.crop((1, 0, dw, dh))
            diff_h = ImageChops.difference(left, right).histogram()
            horiz_hits = sum(diff_h[_EDGE_DELTA_THRESHOLD + 1 :])
            horiz_pairs = (dw - 1) * dh

        vert_hits = 0
        vert_pairs = 0
        if dh > 1:
            top = downsampled.crop((0, 0, dw, dh - 1))
            bottom = downsampled.crop((0, 1, dw, dh))
            diff_v = ImageChops.difference(top, bottom).histogram()
            vert_hits = sum(diff_v[_EDGE_DELTA_THRESHOLD + 1 :])
            vert_pairs = dw * (dh - 1)

        edge_pairs = horiz_pairs + vert_pairs
        edge_density = (horiz_hits + vert_hits) / edge_pairs if edge_pairs else 0.0

    is_probably_blank = (
        near_white_ratio > _BLANK_NEAR_WHITE_RATIO and entropy < _BLANK_ENTROPY_BITS
    )

    return PreflightResult(
        width=width,
        height=height,
        near_white_ratio=near_white_ratio,
        render_entropy=entropy,
        mean_intensity=mean_intensity,
        edge_density=edge_density,
        is_probably_blank=is_probably_blank,
    )


__all__ = ["PreflightResult", "compute_preflight_features"]
