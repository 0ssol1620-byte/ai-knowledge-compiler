"""Deterministic, low-cost preflight analysis primitives."""

from __future__ import annotations

import math
import unicodedata
from enum import StrEnum
from typing import Annotated

from akc_cir import ContractModel
from pydantic import Field, field_validator, model_validator

Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class RiskTier(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


class PageTechnicalClass(StrEnum):
    NATIVE_CLEAN = "NATIVE_CLEAN"
    NATIVE_COMPLEX = "NATIVE_COMPLEX"
    SCAN_TEXT = "SCAN_TEXT"
    SCAN_COMPLEX = "SCAN_COMPLEX"
    TABLE_HEAVY = "TABLE_HEAVY"
    FORMULA_HEAVY = "FORMULA_HEAVY"
    CHART_HEAVY = "CHART_HEAVY"
    PHOTO_DOCUMENT = "PHOTO_DOCUMENT"
    ROTATED_OR_WARPED = "ROTATED_OR_WARPED"
    HANDWRITTEN = "HANDWRITTEN"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class DocumentMetrics(ContractModel):
    page_count: Annotated[int, Field(ge=1)]
    file_size_bytes: Annotated[int, Field(ge=0)]
    source_format: str
    encrypted: bool
    native_text_page_ratio: Ratio
    scanned_page_ratio: Ratio
    mixed_page_ratio: Ratio
    dominant_scripts: tuple[str, ...]
    layout_variance: Ratio
    repeated_header_candidates: Annotated[int, Field(ge=0)]
    repeated_footer_candidates: Annotated[int, Field(ge=0)]
    estimated_tables: Annotated[int, Field(ge=0)]
    estimated_figures: Annotated[int, Field(ge=0)]
    estimated_formulas: Annotated[int, Field(ge=0)]
    narrative_continuity_score: Ratio
    risk_tier: RiskTier

    @field_validator("native_text_page_ratio", "scanned_page_ratio", "mixed_page_ratio")
    @classmethod
    def validate_page_ratios(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("page ratios must be finite")
        return value

    @model_validator(mode="after")
    def validate_page_ratio_partition(self) -> DocumentMetrics:
        total = self.native_text_page_ratio + self.scanned_page_ratio + self.mixed_page_ratio
        if not math.isclose(total, 1.0, abs_tol=0.01):
            raise ValueError("native/scanned/mixed page ratios must sum to one")
        return self


class PageMetrics(ContractModel):
    page_index0: Annotated[int, Field(ge=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    native_text_chars: Annotated[int, Field(ge=0)]
    native_word_count: Annotated[int, Field(ge=0)]
    native_block_count: Annotated[int, Field(ge=0)]
    native_text_coverage: Ratio
    image_coverage: Ratio
    invalid_unicode_ratio: Ratio
    replacement_char_ratio: Ratio
    whitespace_anomaly_score: Ratio
    native_reading_order_score: Ratio
    font_size_p10: Annotated[float, Field(gt=0)] | None = None
    estimated_columns: Annotated[int, Field(ge=0)]
    table_density: Ratio
    formula_density: Ratio
    chart_probability: Ratio
    handwriting_probability: Ratio
    rotation_degrees: int
    skew_degrees: Annotated[float, Field(ge=-45.0, le=45.0)]
    blur_score: Ratio
    contrast_score: Ratio
    small_text_score: Ratio
    script_distribution: dict[str, Ratio]
    suspected_prompt_injection: bool

    @field_validator("rotation_degrees")
    @classmethod
    def validate_rotation(cls, value: int) -> int:
        normalized = value % 360
        if normalized not in {0, 90, 180, 270}:
            raise ValueError("rotationDegrees must normalize to 0, 90, 180, or 270")
        return normalized

    @field_validator("script_distribution")
    @classmethod
    def validate_distribution(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(score) for score in value.values()):
            raise ValueError("script distribution values must be finite")
        total = sum(value.values())
        if value and not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError("non-empty script distribution must sum to 1")
        return dict(sorted(value.items()))


def _unicode_script(character: str) -> str:
    codepoint = ord(character)
    name = unicodedata.name(character, "")
    if 0xAC00 <= codepoint <= 0xD7AF or 0x1100 <= codepoint <= 0x11FF:
        return "Hangul"
    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0x20000 <= codepoint <= 0x3134F
    ):
        return "Han"
    if 0x3040 <= codepoint <= 0x30FF or 0x31F0 <= codepoint <= 0x31FF:
        return "Hiragana_Katakana"
    if "LATIN" in name:
        return "Latin"
    if "CYRILLIC" in name:
        return "Cyrillic"
    if 0x0600 <= codepoint <= 0x06FF or 0x0750 <= codepoint <= 0x077F:
        return "Arabic"
    if 0x0900 <= codepoint <= 0x097F:
        return "Devanagari"
    if 0x0E00 <= codepoint <= 0x0E7F:
        return "Thai"
    return "Other"


def detect_script_distribution(text: str) -> dict[str, float]:
    """Return normalized Unicode-script evidence without guessing a language."""
    counts: dict[str, int] = {}
    for character in text:
        category = unicodedata.category(character)
        if not category.startswith(("L", "N")):
            continue
        script = _unicode_script(character)
        counts[script] = counts.get(script, 0) + 1
    total = sum(counts.values())
    if not total:
        return {}
    return {
        script: count / total for script, count in sorted(counts.items(), key=lambda item: item[0])
    }


def native_candidate(metrics: PageMetrics) -> bool:
    return (
        metrics.native_text_chars >= 100
        and metrics.invalid_unicode_ratio <= 0.005
        and metrics.replacement_char_ratio <= 0.001
        and metrics.native_reading_order_score >= 0.80
        and metrics.native_text_coverage >= 0.03
        and not (metrics.image_coverage > 0.75 and metrics.native_text_chars < 400)
    )


def native_requires_visual_cross_check(metrics: PageMetrics) -> bool:
    return (
        metrics.estimated_columns >= 2
        or metrics.table_density >= 0.20
        or metrics.formula_density >= 0.05
        or metrics.chart_probability >= 0.50
    )


def preflight_difficulty(metrics: PageMetrics) -> float:
    score = 0.0
    score += 22 if metrics.native_text_chars < 30 else 0
    score += 12 * min(1.0, metrics.image_coverage)
    score += 12 * min(1.0, metrics.table_density)
    score += 10 * min(1.0, metrics.formula_density * 4)
    score += 8 * min(1.0, metrics.chart_probability)
    score += 10 * min(1.0, abs(metrics.skew_degrees) / 8)
    score += 6 if metrics.rotation_degrees % 360 != 0 else 0
    score += 8 * min(1.0, metrics.blur_score)
    score += 6 * min(1.0, metrics.small_text_score)
    score += (
        6
        if len([value for value in metrics.script_distribution.values() if value > 0.1]) >= 2
        else 0
    )
    return min(100.0, score)


def classify_page(metrics: PageMetrics) -> PageTechnicalClass:
    if metrics.handwriting_probability >= 0.50:
        return PageTechnicalClass.HANDWRITTEN
    if metrics.rotation_degrees or abs(metrics.skew_degrees) >= 3.0:
        return PageTechnicalClass.ROTATED_OR_WARPED
    if metrics.table_density >= 0.20:
        return PageTechnicalClass.TABLE_HEAVY
    if metrics.formula_density >= 0.05:
        return PageTechnicalClass.FORMULA_HEAVY
    if metrics.chart_probability >= 0.50:
        return PageTechnicalClass.CHART_HEAVY
    if metrics.image_coverage >= 0.90 and metrics.native_text_chars < 30:
        return PageTechnicalClass.PHOTO_DOCUMENT
    if native_candidate(metrics):
        if native_requires_visual_cross_check(metrics):
            return PageTechnicalClass.NATIVE_COMPLEX
        return PageTechnicalClass.NATIVE_CLEAN
    if metrics.native_text_chars and metrics.image_coverage >= 0.25:
        return PageTechnicalClass.MIXED
    if metrics.native_text_chars < 30 and metrics.image_coverage >= 0.50:
        if preflight_difficulty(metrics) >= 50:
            return PageTechnicalClass.SCAN_COMPLEX
        return PageTechnicalClass.SCAN_TEXT
    return PageTechnicalClass.UNKNOWN
