"""WP-R3 lane-A native inspection and lane-B visual estimation (program §4).

Two cheap lanes that run *before* any inference and produce observations for the
§4 signals, or say they could not.

* **Lane A, native inspection** — PDF structure via `pypdfium2`, and a static
  capability table for the Office/structured families naming which §4 signals
  the readers in `packages/native-parsers` can supply. A family with no reader
  contributes no signal; it does not contribute a zero.
* **Lane B, low-resolution visual estimation** — `Pillow` only, no OCR, no
  PyMuPDF (§78). Blur, small text, skew, image dominance, layout density and a
  stroke-width handwriting *candidate*.

**Every threshold in this module is uncalibrated.** No corpus fixes them; they
are conservative starting points, and the estimates they produce are stamped
`calibrated=False` so nothing downstream can present them as measured. That is
also why `merge_visual_estimate` only fills fields the caller left unmeasured:
it never overwrites a real observation with a heuristic one.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import BinaryIO

from PIL import Image, ImageFilter, ImageStat

from .preflight import PageMetrics
from .risk import RiskFeature

_F = RiskFeature

#: Longest side of the working raster. Lane B is deliberately low resolution:
#: it is a triage pass, not a reader.
WORKING_SIDE = 1000

#: Uncalibrated. Laplacian variance at or above this reads as sharp.
SHARP_LAPLACIAN_VARIANCE = 400.0

#: Uncalibrated. A connected component shorter than this share of the working
#: image height is small text. 0.008 * 1000 px = 8 px, roughly 6 pt at 150 dpi.
SMALL_TEXT_HEIGHT_RATIO = 0.008

#: Uncalibrated. Coefficient of variation of foreground run lengths above which
#: stroke width looks hand-made rather than typeset.
HANDWRITING_STROKE_CV = 0.90

_SKEW_SEARCH_DEGREES = 5.0
_SKEW_STEP_DEGREES = 0.5


@dataclass(frozen=True, slots=True)
class VisualEstimate:
    """Lane-B output. `None` means the estimator declined, never 'zero'."""

    blur_score: float | None = None
    small_text_score: float | None = None
    skew_degrees: float | None = None
    handwriting_probability: float | None = None
    photo_probability: float | None = None
    image_dominant: bool | None = None
    layout_density: float | None = None
    elapsed_ms: float = 0.0
    calibrated: bool = False
    unmeasured: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NativePageInspection:
    """Lane-A per-page facts. Every field is read, none is inferred."""

    page_index0: int
    width_pt: float
    height_pt: float
    rotation_degrees: int
    embedded_text_chars: int
    text_object_count: int
    path_object_count: int
    image_object_count: int
    shading_object_count: int
    form_object_count: int
    table_line_candidates: int
    image_area_ratio: float


@dataclass(frozen=True, slots=True)
class NativeInspection:
    """Lane-A document facts, plus what could not be read."""

    source_family: str
    page_count: int | None = None
    pages: tuple[NativePageInspection, ...] = ()
    corrupt_structure: bool = False
    corrupt_reason: str | None = None
    elapsed_ms: float = 0.0
    unknown_features: frozenset[RiskFeature] = field(default_factory=frozenset)


#: Which §4 signals each family's *existing* reader can supply. Read off
#: `packages/native-parsers`: DOCX yields comments and tracked changes, PPTX
#: yields speaker notes, XLSX yields preserved (unexecuted) formulas, PDF yields
#: structure only. Everything absent here is UNKNOWN, and the report says so.
NATIVE_FAMILY_SIGNALS: Mapping[str, frozenset[RiskFeature]] = {
    "pdf": frozenset(
        {
            _F.SOURCE_INTEGRITY_RISK,
            _F.NATIVE_QUALITY,
            _F.SCAN_NEED,
            _F.TABLE_STRUCTURE_RISK,
            _F.IMAGE_SEMANTICS_RISK,
            _F.ROTATION_SKEW_RISK,
        }
    ),
    "docx": frozenset(
        {
            _F.SOURCE_INTEGRITY_RISK,
            _F.NATIVE_QUALITY,
            _F.TABLE_STRUCTURE_RISK,
            _F.FOOTNOTE_COMMENT_RISK,
            _F.TRACKED_CHANGE_RISK,
            _F.IMAGE_SEMANTICS_RISK,
        }
    ),
    "pptx": frozenset(
        {
            _F.SOURCE_INTEGRITY_RISK,
            _F.NATIVE_QUALITY,
            _F.READING_ORDER_RISK,
            _F.FOOTNOTE_COMMENT_RISK,
            _F.IMAGE_SEMANTICS_RISK,
        }
    ),
    "xlsx": frozenset(
        {
            _F.SOURCE_INTEGRITY_RISK,
            _F.NATIVE_QUALITY,
            _F.TABLE_STRUCTURE_RISK,
            _F.FORMULA_RISK,
            _F.CHART_VISUAL_RISK,
        }
    ),
    "html": frozenset({_F.SOURCE_INTEGRITY_RISK, _F.NATIVE_QUALITY, _F.TABLE_STRUCTURE_RISK}),
    "subtitle": frozenset({_F.SOURCE_INTEGRITY_RISK, _F.NATIVE_QUALITY}),
}

#: Families the program names that have no reader in this repository today.
#: Their §4 signals are all UNKNOWN. Naming them is the point: a silent absence
#: reads as "nothing risky here".
UNREADABLE_FAMILIES: frozenset[str] = frozenset({"json", "xml", "structured", "connector", "email"})


def native_unknown_features(source_family: str) -> frozenset[RiskFeature]:
    """§4 signals this family's reader cannot observe."""
    supplied = NATIVE_FAMILY_SIGNALS.get(source_family, frozenset())
    return frozenset(RiskFeature) - supplied


def inspect_pdf_native(source: str | BinaryIO | bytes) -> NativeInspection:
    """Lane A for PDF. Structure only; no rendering and no text is retained."""
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
    import pypdfium2.raw as pdfium_raw  # type: ignore[import-untyped]

    started = time.perf_counter()
    pages: list[NativePageInspection] = []
    document = None
    try:
        document = pdfium.PdfDocument(source)
        page_count = len(document)
        for index in range(page_count):
            pages.append(_inspect_pdf_page(document, index, pdfium_raw))
    except Exception as error:  # pdfium raises many concrete types
        return NativeInspection(
            source_family="pdf",
            page_count=len(pages) or None,
            pages=tuple(pages),
            corrupt_structure=True,
            corrupt_reason=type(error).__name__,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            unknown_features=native_unknown_features("pdf"),
        )
    finally:
        if document is not None:
            document.close()
    return NativeInspection(
        source_family="pdf",
        page_count=len(pages),
        pages=tuple(pages),
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        unknown_features=native_unknown_features("pdf"),
    )


def _inspect_pdf_page(document: object, index: int, raw: object) -> NativePageInspection:
    page = document[index]  # type: ignore[index]
    try:
        width, height = page.get_size()
        text_page = page.get_textpage()
        try:
            char_count = text_page.count_chars()
        finally:
            text_page.close()
        counts = dict.fromkeys(("text", "path", "image", "shading", "form"), 0)
        kinds = {
            raw.FPDF_PAGEOBJ_TEXT: "text",  # type: ignore[attr-defined]
            raw.FPDF_PAGEOBJ_PATH: "path",  # type: ignore[attr-defined]
            raw.FPDF_PAGEOBJ_IMAGE: "image",  # type: ignore[attr-defined]
            raw.FPDF_PAGEOBJ_SHADING: "shading",  # type: ignore[attr-defined]
            raw.FPDF_PAGEOBJ_FORM: "form",  # type: ignore[attr-defined]
        }
        table_lines = 0
        image_area = 0.0
        for obj in page.get_objects():
            name = kinds.get(obj.type)
            if name is None:
                continue
            counts[name] += 1
            left, bottom, right, top = obj.get_pos()
            span_x, span_y = abs(right - left), abs(top - bottom)
            if name == "path" and _is_rule(span_x, span_y, width, height):
                table_lines += 1
            elif name == "image":
                image_area += span_x * span_y
        page_area = max(1.0, width * height)
        return NativePageInspection(
            page_index0=index,
            width_pt=width,
            height_pt=height,
            rotation_degrees=page.get_rotation(),
            embedded_text_chars=max(0, char_count),
            text_object_count=counts["text"],
            path_object_count=counts["path"],
            image_object_count=counts["image"],
            shading_object_count=counts["shading"],
            form_object_count=counts["form"],
            table_line_candidates=table_lines,
            image_area_ratio=min(1.0, image_area / page_area),
        )
    finally:
        page.close()


def _is_rule(span_x: float, span_y: float, width: float, height: float) -> bool:
    """A long thin path is a table rule candidate, not a glyph outline."""
    return (span_x >= width * 0.15 and span_y <= 3.0) or (span_y >= height * 0.15 and span_x <= 3.0)


def estimate_page_visual(image: Image.Image) -> VisualEstimate:
    """Lane B. Pillow only, no OCR, no model, no network."""
    started = time.perf_counter()
    working = _to_working_grey(image)
    photo, dominant = _photo_signals(image, working)
    threshold = _otsu_threshold(working.histogram())
    # Otsu's threshold is the top of the dark class, so ink is `<=`, not `<`.
    binary = working.point(lambda value: 255 if value <= threshold else 0, mode="1")
    runs = tuple(_foreground_runs(binary))
    if not runs:
        # A blank raster measures nothing. Saying so beats reporting "clean".
        return VisualEstimate(
            photo_probability=photo,
            image_dominant=dominant,
            layout_density=0.0,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            unmeasured=("blur_score", "small_text_score", "skew_degrees", "handwriting"),
        )
    heights = _component_heights(runs)
    foreground = sum(length for _, _, length in runs)
    width, height = binary.size
    return VisualEstimate(
        blur_score=_blur_score(working),
        small_text_score=_small_text_score(heights, height),
        skew_degrees=_skew_degrees(binary),
        handwriting_probability=_handwriting_candidate(runs),
        photo_probability=photo,
        image_dominant=dominant,
        layout_density=min(1.0, foreground / max(1, width * height)),
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def merge_visual_estimate(metrics: PageMetrics, estimate: VisualEstimate) -> PageMetrics:
    """Fill only the fields the caller left unmeasured. Never overwrite."""
    filled = {
        "blur_score": estimate.blur_score,
        "small_text_score": estimate.small_text_score,
        "skew_degrees": estimate.skew_degrees,
        "handwriting_probability": estimate.handwriting_probability,
    }
    updates = {
        name: value
        for name, value in filled.items()
        if value is not None and getattr(metrics, name) is None
    }
    return metrics.model_copy(update=updates) if updates else metrics


def _to_working_grey(image: Image.Image) -> Image.Image:
    grey = image.convert("L")
    longest = max(grey.size)
    if longest > WORKING_SIDE:
        scale = WORKING_SIDE / longest
        grey = grey.resize(
            (max(1, round(grey.width * scale)), max(1, round(grey.height * scale))),
            Image.Resampling.BILINEAR,
        )
    return grey


def _blur_score(grey: Image.Image) -> float:
    """1.0 = fully blurred. Variance of a 3x3 Laplacian response."""
    laplacian = grey.filter(
        ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128)
    )
    variance = ImageStat.Stat(laplacian).var[0]
    return max(0.0, 1.0 - min(1.0, variance / SHARP_LAPLACIAN_VARIANCE))


def _otsu_threshold(histogram: Sequence[int]) -> int:
    """Otsu's between-class variance maximum over a 256-bin grey histogram."""
    total = sum(histogram)
    if total == 0:
        return 128
    sum_all = sum(index * count for index, count in enumerate(histogram))
    background = 0
    weight_background = 0
    best_threshold, best_variance = 128, -1.0
    for index, count in enumerate(histogram):
        weight_background += count
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        background += index * count
        mean_background = background / weight_background
        mean_foreground = (sum_all - background) / weight_foreground
        between = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if between > best_variance:
            best_variance, best_threshold = between, index
    return best_threshold


def _foreground_runs(binary: Image.Image) -> Iterator[tuple[int, int, int]]:
    """Yield `(row, start_column, length)` for each horizontal ink run.

    Run-length first because a page of text has thousands of runs and millions
    of pixels; every component statistic below is computed over the runs.
    """
    width, height = binary.size
    data = binary.convert("L").tobytes()
    for row in range(height):
        offset = row * width
        column = 0
        while column < width:
            if data[offset + column]:
                start = column
                while column < width and data[offset + column]:
                    column += 1
                yield row, start, column - start
            else:
                column += 1


def _component_heights(runs: Sequence[tuple[int, int, int]]) -> list[int]:
    """Component heights via union-find over vertically overlapping runs."""
    parent = list(range(len(runs)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    previous: list[int] = []
    current: list[int] = []
    previous_row = -2
    for index, (row, start, length) in enumerate(runs):
        if row != previous_row:
            # Only the immediately preceding row is adjacent. Carrying the last
            # inked row across a blank gap would weld the whole page into one
            # component and hide every height.
            previous = current if row == previous_row + 1 else []
            current, previous_row = [], row
        for other in previous:
            other_start, other_length = runs[other][1], runs[other][2]
            if start < other_start + other_length and other_start < start + length:
                union(index, other)
        current.append(index)

    extents: dict[int, tuple[int, int]] = {}
    for index, (row, _, _) in enumerate(runs):
        root = find(index)
        low, high = extents.get(root, (row, row))
        extents[root] = (min(low, row), max(high, row))
    return [high - low + 1 for low, high in extents.values()]


def _small_text_score(heights: Sequence[int], page_height: int) -> float:
    """Share of ink components shorter than the small-text height."""
    if not heights:
        return 0.0
    limit = max(2.0, page_height * SMALL_TEXT_HEIGHT_RATIO)
    # Single-pixel specks are noise, not text; they would inflate the share.
    text_like = [value for value in heights if value >= 2]
    if not text_like:
        return 0.0
    return sum(value < limit for value in text_like) / len(text_like)


def _skew_degrees(binary: Image.Image) -> float:
    """Projection-profile skew: the angle whose row sums vary most."""
    grey = binary.convert("L")
    best_angle, best_score = 0.0, -1.0
    steps = int(_SKEW_SEARCH_DEGREES / _SKEW_STEP_DEGREES)
    for step in range(-steps, steps + 1):
        angle = step * _SKEW_STEP_DEGREES
        rotated = grey if angle == 0.0 else grey.rotate(angle, resample=Image.Resampling.NEAREST)
        score = _row_profile_variance(rotated)
        if score > best_score:
            best_score, best_angle = score, angle
    return best_angle


def _row_profile_variance(grey: Image.Image) -> float:
    width, height = grey.size
    data = grey.tobytes()
    sums = [sum(data[row * width : (row + 1) * width]) for row in range(height)]
    mean = sum(sums) / len(sums)
    return sum((value - mean) ** 2 for value in sums) / len(sums)


def _handwriting_candidate(runs: Sequence[tuple[int, int, int]]) -> float:
    """Stroke-width variability. Typeset text is near-constant; ink is not.

    This is a *candidate*, not a measurement: it is uncalibrated, it sees no
    glyph shapes, and a table of rules or a dense figure will raise it. The
    §4 signal it feeds is stamped `calibrated=False` for exactly that reason.
    """
    lengths = [length for _, _, length in runs if length >= 1]
    if len(lengths) < 32:
        return 0.0
    mean = sum(lengths) / len(lengths)
    if mean <= 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in lengths) / len(lengths)
    coefficient = math.sqrt(variance) / mean
    return min(1.0, coefficient / HANDWRITING_STROKE_CV)


def _photo_signals(image: Image.Image, working: Image.Image) -> tuple[float, bool]:
    """Colour-histogram entropy plus edge density; a photo has both high."""
    colour = image.convert("RGB").resize(working.size, Image.Resampling.BILINEAR)
    histogram = colour.histogram()
    entropy = 0.0
    for channel in range(3):
        bins = histogram[channel * 256 : (channel + 1) * 256]
        total = sum(bins)
        if not total:
            continue
        for count in bins:
            if count:
                share = count / total
                entropy -= share * math.log2(share)
    normalised_entropy = min(1.0, entropy / (3 * 8.0))
    edges = ImageStat.Stat(working.filter(ImageFilter.FIND_EDGES)).mean[0] / 255.0
    probability = min(1.0, normalised_entropy * 0.7 + edges * 0.3)
    return probability, normalised_entropy >= 0.55


__all__ = [
    "NATIVE_FAMILY_SIGNALS",
    "SMALL_TEXT_HEIGHT_RATIO",
    "UNREADABLE_FAMILIES",
    "WORKING_SIDE",
    "NativeInspection",
    "NativePageInspection",
    "VisualEstimate",
    "estimate_page_visual",
    "inspect_pdf_native",
    "merge_visual_estimate",
    "native_unknown_features",
]
