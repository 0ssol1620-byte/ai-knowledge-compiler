from pathlib import Path

from evaluate_omnidoc_repeats import render_config


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
