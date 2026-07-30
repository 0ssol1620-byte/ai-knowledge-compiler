from __future__ import annotations

import hashlib
import json

import pytest
from akc_worker_document.preprocessing import (
    PREPROCESSING_VERSION,
    preprocess_inference_raster,
)
from akc_worker_document.worker import PageTransformManifest
from PIL import Image, ImageDraw
from pydantic import ValidationError


def _transform_digest(payload: dict[str, object]) -> str:
    value = dict(payload)
    value.pop("transform_sha256")
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def test_preprocessing_is_deterministic_preserves_input_and_records_every_step() -> None:
    source = Image.new("RGB", (640, 840), (242, 242, 242))
    draw = ImageDraw.Draw(source)
    for y in range(180, 660, 36):
        draw.rectangle((130, y, 510, y + 7), fill=(178, 178, 178))
    original = source.tobytes()

    first, first_metadata = preprocess_inference_raster(source)
    second, second_metadata = preprocess_inference_raster(source)
    try:
        assert source.tobytes() == original
        assert first.tobytes() == second.tobytes()
        assert first_metadata == second_metadata
        assert first_metadata["schema_version"] == PREPROCESSING_VERSION
        assert first_metadata["source_immutable"] is True
        assert set(first_metadata) == {
            "schema_version",
            "source_immutable",
            "input_dimensions_px",
            "oriented_dimensions_px",
            "output_dimensions_px",
            "orientation",
            "deskew",
            "border_crop",
            "contrast",
            "dewarp",
            "transform_sha256",
        }
        assert first_metadata["dewarp"] == {
            "applied": False,
            "method": "none",
            "reason": "no_calibrated_curvature_evidence_or_immutable_dewarp_model",
        }
        assert first_metadata["contrast"]["applied"] is True
        assert first_metadata["transform_sha256"] == _transform_digest(first_metadata)
        PageTransformManifest.model_validate(first_metadata)
    finally:
        first.close()
        second.close()
        source.close()


def test_projection_deskew_and_bounded_border_crop_apply_to_measured_geometry() -> None:
    source = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(source)
    for y in range(100, 700, 30):
        draw.rectangle((80, y, 520, y + 5), fill="black")
    skewed = source.rotate(
        3,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor="white",
    )

    processed, metadata = preprocess_inference_raster(skewed)
    try:
        assert metadata["deskew"]["applied"] is True
        assert metadata["deskew"]["angle_degrees"] == pytest.approx(-3.0, abs=0.5)
        assert metadata["deskew"]["score_after"] > metadata["deskew"]["score_before"]
        assert metadata["border_crop"]["applied"] is True
        crop_box = metadata["border_crop"]["crop_box_px"]
        assert isinstance(crop_box, list) and len(crop_box) == 4
        assert processed.width < skewed.width
        assert processed.height < skewed.height
    finally:
        processed.close()
        skewed.close()
        source.close()


def test_trusted_exif_orientation_is_applied_without_mutating_source() -> None:
    source = Image.new("RGB", (80, 140), "white")
    source.getexif()[274] = 6
    processed, metadata = preprocess_inference_raster(source)
    try:
        assert source.size == (80, 140)
        assert metadata["orientation"] == {
            "applied": True,
            "method": "exif_orientation_v1",
            "exif_orientation": 6,
            "operation": "rotate_90_clockwise",
            "angle_degrees": 90,
            "reason": "trusted_exif_orientation_applied",
        }
        assert metadata["oriented_dimensions_px"] == [140, 80]
    finally:
        processed.close()
        source.close()


def test_transform_contract_rejects_tampering() -> None:
    source = Image.new("RGB", (200, 300), "white")
    processed, metadata = preprocess_inference_raster(source)
    try:
        tampered = dict(metadata)
        tampered["output_dimensions_px"] = [1, 1]
        with pytest.raises(ValidationError, match="checksum"):
            PageTransformManifest.model_validate(tampered)
    finally:
        processed.close()
        source.close()
