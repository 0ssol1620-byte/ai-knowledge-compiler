from pathlib import Path

import pytest
from evaluate_omnidoc_repeats import render_config, require_exact_page_count


def test_render_config_is_partial_and_keeps_paths_explicit(tmp_path: Path) -> None:
    ground_truth = tmp_path / "gt.json"
    prediction = tmp_path / "markdown-repeat-1"

    rendered = render_config(
        ground_truth=ground_truth,
        prediction=prediction,
        workers=3,
    )

    assert "metric: [Edit_dist, CDM]" not in rendered
    assert "display_formula:\n      metric: [Edit_dist]" in rendered
    assert "metric: [TEDS, Edit_dist]" in rendered
    assert "match_workers: 3" in rendered
    assert ground_truth.resolve().as_posix() in rendered
    assert prediction.resolve().as_posix() in rendered


def test_page_count_must_match_frozen_prediction_directory(tmp_path: Path) -> None:
    prediction = tmp_path / "markdown-repeat-1"
    prediction.mkdir()
    (prediction / "a.md").write_text("a", encoding="utf-8")
    (prediction / "b.md").write_text("b", encoding="utf-8")
    assert require_exact_page_count({"match_debug": {"page_count": 2}}, prediction) == 2
    with pytest.raises(ValueError, match="expected 2, received 3"):
        require_exact_page_count({"match_debug": {"page_count": 3}}, prediction)
