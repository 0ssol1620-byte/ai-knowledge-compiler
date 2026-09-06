"""``arena.reports.narrative``: [RESULT] left blank when data is absent."""

from __future__ import annotations

from arena.reports.common import TableSpec, na_reason, to_cell
from arena.reports.narrative import build_executive_summary_ko, build_methodology
from arena.reports.tables_core import LEADERBOARD_HEADER


def _empty_leaderboard() -> TableSpec:
    return TableSpec(
        header=LEADERBOARD_HEADER,
        rows=[
            {column: na_reason("no data") for column in LEADERBOARD_HEADER}
            | {"System": to_cell("model_x")}
        ],
    )


def _empty_document_type_breakdown() -> TableSpec:
    return TableSpec(
        header=("model_key", "benchmark", "document_type", "mean_metric", "sample_count", "reason"),
        rows=[],
    )


def _empty_tavonel_routes() -> TableSpec:
    return TableSpec(
        header=("variant", "is_oracle", "opus_usage_pct", "reason"),
        rows=[
            {
                "variant": to_cell("A_base"),
                "is_oracle": to_cell(False),
                "reason": na_reason("x"),
            }
        ],
    )


def test_executive_summary_leaves_result_when_no_data() -> None:
    text = build_executive_summary_ko(
        leaderboard=_empty_leaderboard(),
        document_type_breakdown=_empty_document_type_breakdown(),
        tavonel_routes=_empty_tavonel_routes(),
    )
    assert "[RESULT]" in text
    # every one of the masterplan 48 slots that has no data must stay literal
    assert text.count("[RESULT]") >= 3


def _leaderboard_row(*, system: str, sec_per_page: float) -> dict[str, object]:
    row: dict[str, object] = {c: na_reason("x") for c in LEADERBOARD_HEADER}
    row["System"] = to_cell(system)
    row["sec_per_page"] = to_cell(sec_per_page)
    return row


def test_executive_summary_fills_slot_when_data_present() -> None:
    leaderboard = TableSpec(
        header=LEADERBOARD_HEADER,
        rows=[
            _leaderboard_row(system="fast_model", sec_per_page=0.5),
            _leaderboard_row(system="slow_model", sec_per_page=5.0),
        ],
    )
    text = build_executive_summary_ko(
        leaderboard=leaderboard,
        document_type_breakdown=_empty_document_type_breakdown(),
        tavonel_routes=_empty_tavonel_routes(),
    )
    assert "fast_model" in text
    assert "가장 빠른 모델" in text


def test_executive_summary_always_has_negative_results_section() -> None:
    text = build_executive_summary_ko(
        leaderboard=_empty_leaderboard(),
        document_type_breakdown=_empty_document_type_breakdown(),
        tavonel_routes=_empty_tavonel_routes(),
    )
    assert "Negative results" in text


def test_executive_summary_never_blends_benchmarks_into_one_number() -> None:
    text = build_executive_summary_ko(
        leaderboard=_empty_leaderboard(),
        document_type_breakdown=_empty_document_type_breakdown(),
        tavonel_routes=_empty_tavonel_routes(),
    )
    assert "ParseBench:" in text
    assert "OmniDoc:" in text
    assert "olmOCR:" in text


def test_methodology_states_single_run_caveats() -> None:
    text = build_methodology(evaluator_registry=None)
    assert "deterministic" in text  # named as something NOT claimed
    assert "완전히 deterministic" in text or "fully deterministic" in text.lower()
    assert "single run" in text.lower()


def test_methodology_names_opus_experiment_correctly() -> None:
    text = build_methodology(evaluator_registry=None)
    # The canonical label appears as its own quoted line...
    assert "> Claude Opus 5 - Claude Code subscription surface" in text
    # ...and the sentence that names the forbidden alternative also forbids it.
    forbidden_sentence = next(
        line for line in text.splitlines() if "Claude Opus 5 API benchmark" in line
    )
    assert "never" in forbidden_sentence.lower()


def test_methodology_lists_evaluator_pins_when_present() -> None:
    text = build_methodology(
        evaluator_registry={"evaluators": {"parsebench": {"main_pin": "abc123"}}}
    )
    assert "parsebench" in text
    assert "abc123" in text


def test_methodology_missing_evaluator_registry_says_so() -> None:
    text = build_methodology(evaluator_registry=None)
    assert "evaluator_registry.json was not found" in text
