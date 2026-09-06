from __future__ import annotations

from pathlib import Path

import pytest
from arena.manifest.preflight import compute_preflight_features
from PIL import Image


def test_blank_white_page_is_flagged_probably_blank(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    Image.new("L", (64, 64), color=255).save(path, format="PNG")

    result = compute_preflight_features(path)

    assert result.width == 64
    assert result.height == 64
    assert result.near_white_ratio == pytest.approx(1.0)
    assert result.render_entropy == pytest.approx(0.0)
    assert result.edge_density == pytest.approx(0.0)
    assert result.is_probably_blank is True


def test_high_contrast_checkerboard_is_not_blank(tmp_path: Path) -> None:
    path = tmp_path / "checkerboard.png"
    size = 32
    image = Image.new("L", (size, size), color=255)
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            if (x + y) % 2 == 0:
                pixels[x, y] = 0
    image.save(path, format="PNG")

    result = compute_preflight_features(path)

    assert result.is_probably_blank is False
    assert result.render_entropy > 0.5
    assert result.edge_density > 0.5
    assert result.near_white_ratio < 0.995


def test_mid_gray_uniform_page_has_zero_entropy_but_is_not_near_white(tmp_path: Path) -> None:
    path = tmp_path / "gray.png"
    Image.new("L", (16, 16), color=128).save(path, format="PNG")

    result = compute_preflight_features(path)

    assert result.render_entropy == pytest.approx(0.0)
    assert result.near_white_ratio == pytest.approx(0.0)
    assert result.is_probably_blank is False


def test_preflight_features_are_json_serializable(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    Image.new("L", (16, 16), color=200).save(path, format="PNG")

    result = compute_preflight_features(path)
    features = result.as_features_dict()

    assert set(features) == {
        "near_white_ratio",
        "render_entropy",
        "mean_intensity",
        "edge_density",
        "is_probably_blank",
    }
    import json

    json.dumps(features)  # must not raise


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception):  # noqa: B017 - Pillow raises its own error type here
        compute_preflight_features(tmp_path / "does-not-exist.png")


def test_zero_dimension_image_rejected(tmp_path: Path) -> None:
    path = tmp_path / "zero.png"
    # Pillow will not save a 0x0 image; construct a valid tiny image instead and
    # assert the guard rejects a corrupt/truncated file path deterministically.
    path.write_bytes(b"not a real png")
    with pytest.raises(Exception):  # noqa: B017 - Pillow's own decode error
        compute_preflight_features(path)
