"""Deterministic inference-raster preprocessing with auditable decisions."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, cast

from PIL import Image, ImageOps, ImageStat

PREPROCESSING_VERSION = "akc-page-preprocessing-1.0.0"

_EXIF_ORIENTATION = 274
_EXIF_OPERATIONS = {
    1: "identity",
    2: "flip_horizontal",
    3: "rotate_180",
    4: "flip_vertical",
    5: "transpose",
    6: "rotate_90_clockwise",
    7: "transverse",
    8: "rotate_270_clockwise",
}
_EXIF_ANGLE = {1: 0, 2: 0, 3: 180, 4: 0, 5: 270, 6: 90, 7: 90, 8: 270}


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _otsu_threshold(image: Image.Image) -> int:
    histogram = image.histogram()
    total = sum(histogram)
    if total <= 0:
        return 127
    weighted_total = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    maximum_variance = -1.0
    threshold = 127
    for index, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += index * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_total - background_sum) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean)
            * (background_mean - foreground_mean)
        )
        if variance > maximum_variance:
            maximum_variance = variance
            threshold = index
    return threshold


def _analysis_sample(image: Image.Image, *, max_edge: int = 800) -> Image.Image:
    sample = image.convert("L")
    sample.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return sample


def _projection_score(binary: Image.Image, angle_degrees: float) -> float:
    rotated = binary.rotate(
        angle_degrees,
        resample=Image.Resampling.BILINEAR,
        expand=False,
        fillcolor=255,
    )
    try:
        projection = rotated.resize((1, rotated.height), Image.Resampling.BOX)
        try:
            darkness = [255 - value for value in projection.tobytes()]
        finally:
            projection.close()
    finally:
        rotated.close()
    if not darkness:
        return 0.0
    mean = sum(darkness) / len(darkness)
    return sum((value - mean) ** 2 for value in darkness) / len(darkness)


def _deskew_decision(image: Image.Image) -> tuple[float, dict[str, object]]:
    sample = _analysis_sample(image)
    try:
        threshold = _otsu_threshold(sample)
        binary = sample.point(lambda value: 0 if value <= threshold else 255, mode="L")
        try:
            foreground_ratio = binary.tobytes().count(0) / (binary.width * binary.height)
            if not 0.01 <= foreground_ratio <= 0.55:
                return 0.0, {
                    "applied": False,
                    "method": "bounded_projection_profile_v1",
                    "angle_degrees": 0.0,
                    "score_before": 0.0,
                    "score_after": 0.0,
                    "foreground_ratio": round(foreground_ratio, 6),
                    "reason": "foreground_ratio_outside_safe_text_range",
                }
            baseline = _projection_score(binary, 0.0)
            candidates = [step / 2 for step in range(-10, 11)]
            scored = [(angle, _projection_score(binary, angle)) for angle in candidates]
            best_angle, best_score = max(scored, key=lambda item: (item[1], -abs(item[0])))
            improvement = (best_score - baseline) / max(baseline, 1e-9)
            applied = abs(best_angle) >= 0.5 and improvement >= 0.08
            return (best_angle if applied else 0.0), {
                "applied": applied,
                "method": "bounded_projection_profile_v1",
                "angle_degrees": round(best_angle if applied else 0.0, 3),
                "score_before": round(baseline, 6),
                "score_after": round(best_score, 6),
                "foreground_ratio": round(foreground_ratio, 6),
                "reason": (
                    "projection_improvement_above_threshold"
                    if applied
                    else "projection_improvement_below_safe_threshold"
                ),
            }
        finally:
            binary.close()
    finally:
        sample.close()


def _border_crop_decision(
    image: Image.Image,
) -> tuple[tuple[int, int, int, int] | None, dict[str, object]]:
    sample = _analysis_sample(image, max_edge=1000)
    try:
        threshold = min(245, max(150, _otsu_threshold(sample) + 24))
        foreground = sample.point(lambda value: 255 if value < threshold else 0, mode="L")
        try:
            sample_box = foreground.getbbox()
        finally:
            foreground.close()
        if sample_box is None:
            return None, {
                "applied": False,
                "method": "foreground_bbox_v1",
                "crop_box_px": None,
                "retained_area_ratio": 1.0,
                "reason": "no_foreground_detected",
            }
        scale_x = image.width / sample.width
        scale_y = image.height / sample.height
        left = max(0, math.floor(sample_box[0] * scale_x))
        top = max(0, math.floor(sample_box[1] * scale_y))
        right = min(image.width, math.ceil(sample_box[2] * scale_x))
        bottom = min(image.height, math.ceil(sample_box[3] * scale_y))
        pad_x = max(4, round(image.width * 0.012))
        pad_y = max(4, round(image.height * 0.012))
        box = (
            max(0, left - pad_x),
            max(0, top - pad_y),
            min(image.width, right + pad_x),
            min(image.height, bottom + pad_y),
        )
        retained = ((box[2] - box[0]) * (box[3] - box[1])) / (image.width * image.height)
        removed_margin = max(
            box[0],
            box[1],
            image.width - box[2],
            image.height - box[3],
        )
        applied = (
            box[0] < box[2]
            and box[1] < box[3]
            and 0.55 <= retained <= 0.985
            and removed_margin >= max(8, round(min(image.size) * 0.01))
        )
        return (box if applied else None), {
            "applied": applied,
            "method": "foreground_bbox_v1",
            "crop_box_px": list(box) if applied else None,
            "retained_area_ratio": round(retained if applied else 1.0, 6),
            "reason": (
                "bounded_background_border_removed"
                if applied
                else "crop_candidate_outside_safe_bounds"
            ),
        }
    finally:
        sample.close()


def _contrast_decision(image: Image.Image) -> tuple[bool, dict[str, object]]:
    sample = _analysis_sample(image)
    try:
        stats = ImageStat.Stat(sample)
        standard_deviation = float(stats.stddev[0])
        minimum, maximum = cast(tuple[float, float], sample.getextrema())
        dynamic_range = round(maximum - minimum)
    finally:
        sample.close()
    applied = 4.0 <= standard_deviation < 35.0 and dynamic_range >= 12
    return applied, {
        "applied": applied,
        "method": "bounded_autocontrast_1pct_v1",
        "stddev_before": round(standard_deviation, 6),
        "dynamic_range_before": dynamic_range,
        "reason": (
            "low_contrast_nonblank_raster" if applied else "contrast_outside_conditional_window"
        ),
    }


def preprocess_inference_raster(image: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    """Return a derived raster and bounded metadata; never mutate ``image``."""

    input_width, input_height = image.size
    try:
        exif_orientation = int(image.getexif().get(_EXIF_ORIENTATION, 1))
    except (AttributeError, TypeError, ValueError):
        exif_orientation = 1
    if exif_orientation not in _EXIF_OPERATIONS:
        exif_orientation = 1
    oriented = ImageOps.exif_transpose(image).convert("RGB")
    oriented_width, oriented_height = oriented.size
    orientation_applied = exif_orientation != 1
    orientation = {
        "applied": orientation_applied,
        "method": "exif_orientation_v1" if orientation_applied else "trusted_metadata_only_v1",
        "exif_orientation": exif_orientation,
        "operation": _EXIF_OPERATIONS[exif_orientation],
        "angle_degrees": _EXIF_ANGLE[exif_orientation],
        "reason": (
            "trusted_exif_orientation_applied"
            if orientation_applied
            else "no_trusted_orientation_signal"
        ),
    }

    deskew_angle, deskew = _deskew_decision(oriented)
    if deskew["applied"]:
        deskewed = oriented.rotate(
            deskew_angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor="white",
        )
        oriented.close()
    else:
        deskewed = oriented

    crop_box, border_crop = _border_crop_decision(deskewed)
    if crop_box is not None:
        cropped = deskewed.crop(crop_box)
        deskewed.close()
    else:
        cropped = deskewed

    apply_contrast, contrast = _contrast_decision(cropped)
    if apply_contrast:
        processed = ImageOps.autocontrast(cropped, cutoff=1)
        cropped.close()
    else:
        processed = cropped

    metadata: dict[str, Any] = {
        "schema_version": PREPROCESSING_VERSION,
        "source_immutable": True,
        "input_dimensions_px": [input_width, input_height],
        "oriented_dimensions_px": [oriented_width, oriented_height],
        "output_dimensions_px": [processed.width, processed.height],
        "orientation": orientation,
        "deskew": deskew,
        "border_crop": border_crop,
        "contrast": contrast,
        "dewarp": {
            "applied": False,
            "method": "none",
            "reason": "no_calibrated_curvature_evidence_or_immutable_dewarp_model",
        },
    }
    metadata["transform_sha256"] = _canonical_sha256(metadata)
    return processed, metadata


__all__ = ["PREPROCESSING_VERSION", "preprocess_inference_raster"]
