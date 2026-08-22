from __future__ import annotations

from pathlib import Path

import pytest
from evaluate_blind_quality_detection import (
    BlindSignals,
    _benchmark_of,
    apply_length_z,
    compute_signals,
    coverage_at_budget,
    evaluate,
    load_predictions,
    repetition_ratio,
    table_shape,
)


def _write(root: Path, suite: str, case: str, text: str) -> None:
    target = root / suite / "markdown-repeat-1"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{case}.md").write_text(text, encoding="utf-8")


def test_zero_byte_placeholders_are_not_treated_as_predictions(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-done", "real extracted content here")
    _write(baseline, "parsebench", "parsebench-unfinished", "")
    predictions, manifest = load_predictions([baseline])
    assert [case for _, case, _ in predictions] == ["parsebench-done"]
    assert manifest["merged_case_count"] == 1


def test_recovery_tree_supplies_the_cases_the_baseline_never_finished(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "collected-full"
    recovery = tmp_path / "collected-operational-retry"
    _write(baseline, "parsebench", "parsebench-done", "baseline content")
    _write(baseline, "parsebench", "parsebench-unfinished", "")
    _write(recovery, "parsebench", "parsebench-unfinished", "recovered content")
    predictions, manifest = load_predictions([baseline, recovery], expected_cases=2)
    texts = {case: text for _, case, text in predictions}
    assert texts["parsebench-unfinished"] == "recovered content"
    assert texts["parsebench-done"] == "baseline content"
    assert manifest["superseded_by_later_root"] == 0


def test_later_root_overrides_an_earlier_non_empty_prediction(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    _write(first, "parsebench", "parsebench-x", "older")
    _write(second, "parsebench", "parsebench-x", "newer")
    predictions, manifest = load_predictions([first, second])
    assert predictions[0][2] == "newer"
    assert manifest["superseded_by_later_root"] == 1


def test_expected_case_count_mismatch_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "collected-full"
    _write(root, "parsebench", "parsebench-only", "content")
    with pytest.raises(ValueError, match="expected 2"):
        load_predictions([root], expected_cases=2)


def test_unknown_benchmark_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot attribute"):
        _benchmark_of("mystery-bench-0001")


def test_repetition_ratio_ignores_ordinary_prose() -> None:
    words = [
        "the", "quick", "brown", "fox", "jumps", "over",
        "the", "lazy", "dog", "and", "then", "rests",
    ]
    assert repetition_ratio(words) == 0.0


def test_repetition_ratio_detects_a_decode_loop() -> None:
    loop = ["row", "one", "two", "three", "four", "five", "six", "seven"] * 12
    assert repetition_ratio(loop) > 0.5


def test_repetition_ratio_needs_enough_words_to_judge() -> None:
    assert repetition_ratio(["a", "b", "c"]) == 0.0


def test_table_shape_accepts_a_consistent_table() -> None:
    lines = [
        "| a | b | c |",
        "| - | - | - |",
        "| 1 | 2 | 3 |",
        "| 4 | 5 | 6 |",
    ]
    broken, ratio = table_shape(lines)
    assert broken is False
    assert ratio == 0.0


def test_table_shape_flags_a_row_that_lost_a_column() -> None:
    lines = [
        "| a | b | c |",
        "| - | - | - |",
        "| 1 | 2 | 3 |",
        "| 4 | 5 |",
        "| 7 | 8 | 9 |",
    ]
    broken, ratio = table_shape(lines)
    assert broken is True
    assert 0.0 < ratio <= 1.0


def test_html_table_with_consistent_rows_is_accepted() -> None:
    text = (
        "<table><tr><td>a</td><td>b</td></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "<tr><td>3</td><td>4</td></tr></table>"
    )
    broken, ratio = table_shape(text.splitlines(), text)
    assert broken is False
    assert ratio == 0.0


def test_html_table_missing_a_cell_is_flagged() -> None:
    text = (
        "<table><tr><td>a</td><td>b</td><td>c</td></tr>"
        "<tr><td>1</td><td>2</td><td>3</td></tr>"
        "<tr><td>4</td><td>5</td></tr></table>"
    )
    broken, ratio = table_shape(text.splitlines(), text)
    assert broken is True
    assert ratio > 0.0


def test_html_header_cells_count_as_cells() -> None:
    text = (
        "<table><tr><th>a</th><th>b</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
    )
    broken, _ = table_shape(text.splitlines(), text)
    assert broken is False


def test_pipe_and_html_tables_are_both_inspected() -> None:
    text = "| a | b |\n| - | - |\n| 1 |\n\n<table><tr><td>x</td></tr></table>"
    broken, _ = table_shape(text.splitlines(), text)
    assert broken is True


def test_empty_prediction_scores_maximum() -> None:
    signal = compute_signals("parsebench", "parsebench-x", "   \n  ")
    assert signal.empty_output is True
    assert signal.score() == 1.0


def test_clean_prediction_scores_low() -> None:
    text = (
        "# Annual Report\n\n"
        "The committee reviewed the harbour appropriations for the fiscal year "
        "and approved the recommended allocations without amendment.\n"
    )
    signal = compute_signals("parsebench", "parsebench-clean", text)
    assert signal.empty_output is False
    assert signal.score() < 0.25


def test_length_z_is_computed_within_each_benchmark() -> None:
    signals = [
        compute_signals("parsebench", f"parsebench-{i}", "word " * 100) for i in range(5)
    ]
    signals.append(compute_signals("parsebench", "parsebench-outlier", "word " * 5000))
    signals.append(compute_signals("olmocr-bench", "olmocr-bench-a", "word " * 10))
    rescored = apply_length_z(signals)
    outlier = next(s for s in rescored if s.case_id == "parsebench-outlier")
    lone = next(s for s in rescored if s.benchmark_id == "olmocr-bench")
    assert outlier.length_z > 1.5
    # A benchmark with a single case has no spread, so drift must not fire.
    assert lone.length_z == 0.0


def _signal(case: str, score_driver: str) -> BlindSignals:
    text = {
        "empty": "",
        "loop": "alpha beta gamma delta epsilon zeta eta theta " * 15,
        "clean": "The quarterly filing was accepted by the registrar on the stated date.",
    }[score_driver]
    return compute_signals("parsebench", case, text)


def test_coverage_at_budget_sums_only_the_selected_prefix() -> None:
    ranking = [("parsebench", "a"), ("parsebench", "b"), ("parsebench", "c")]
    counts = {("parsebench", "a"): 10, ("parsebench", "b"): 5, ("parsebench", "c"): 1}
    assert coverage_at_budget(ranking, counts, 2) == 15


def test_evaluate_reports_oracle_as_a_ceiling() -> None:
    signals = apply_length_z(
        [
            _signal("parsebench-bad", "empty"),
            _signal("parsebench-loop", "loop"),
            _signal("parsebench-ok1", "clean"),
            _signal("parsebench-ok2", "clean"),
        ]
    )
    counts = {
        ("parsebench", "parsebench-bad"): 40,
        ("parsebench", "parsebench-loop"): 20,
        ("parsebench", "parsebench-ok1"): 1,
        ("parsebench", "parsebench-ok2"): 0,
    }
    result = evaluate(signals, counts, [2])
    row = result["budgets"][0]
    assert row["oracle_failure_mass"] >= row["blind_failure_mass"]
    assert 0.0 <= row["blind_vs_oracle_efficiency"] <= 1.0
    assert result["total_official_failure_records"] == 61
    assert result["cases_with_official_failures"] == 3


def test_evaluate_counts_false_positives_against_passing_cases() -> None:
    signals = apply_length_z(
        [_signal("parsebench-bad", "empty"), _signal("parsebench-ok", "clean")]
    )
    counts = {("parsebench", "parsebench-bad"): 5}
    result = evaluate(signals, counts, [1])
    point = result["any_signal_operating_point"]
    assert point["true_positive"] == 1
    assert point["false_negative"] == 0
    assert point["precision"] <= 1.0


def test_verdict_reports_failure_when_length_alone_wins() -> None:
    # A long clean document with many failures and a short broken one with few is
    # exactly the confound the study exists to expose.
    long_clean = compute_signals(
        "parsebench", "parsebench-long", "The registrar accepted the filing. " * 300
    )
    short_broken = compute_signals("parsebench", "parsebench-short", "")
    signals = apply_length_z([long_clean, short_broken])
    counts = {
        ("parsebench", "parsebench-long"): 100,
        ("parsebench", "parsebench-short"): 1,
    }
    result = evaluate(signals, counts, [1])
    assert result["outcome"]["supported"] is False
    assert "length alone" in result["outcome"]["statement"]
    assert result["budgets"][0]["blind_beats_length_only"] is False


def test_verdict_reports_support_when_the_detector_wins() -> None:
    broken_and_heavy = compute_signals("parsebench", "parsebench-bad", "")
    long_clean = compute_signals(
        "parsebench", "parsebench-ok", "The registrar accepted the filing. " * 300
    )
    signals = apply_length_z([broken_and_heavy, long_clean])
    counts = {
        ("parsebench", "parsebench-bad"): 100,
        ("parsebench", "parsebench-ok"): 1,
    }
    result = evaluate(signals, counts, [1])
    assert result["outcome"]["supported"] is True
    assert result["budgets"][0]["blind_beats_length_only"] is True


def test_per_signal_discrimination_is_reported_for_every_signal() -> None:
    signals = apply_length_z(
        [
            compute_signals(
                "parsebench",
                "parsebench-a",
                "The registrar accepted the filing on the stated date without amendment.",
            ),
            compute_signals("parsebench", "parsebench-b", ""),
        ]
    )
    result = evaluate(signals, {("parsebench", "parsebench-b"): 3}, [1])
    per_signal = result["per_signal_discrimination"]
    assert "empty_output" in per_signal
    assert per_signal["empty_output"]["flagged"] == 1
    assert "probability_lift_over_corpus" in per_signal["empty_output"]


def test_score_is_bounded() -> None:
    worst = BlindSignals(
        benchmark_id="parsebench",
        case_id="x",
        char_count=100,
        word_count=20,
        empty_output=False,
        repetition_ratio=1.0,
        table_schema_failure=True,
        table_row_ragged_ratio=1.0,
        alpha_ratio=0.0,
        length_z=99.0,
        truncated_tail=True,
    )
    assert worst.score() == 1.0
