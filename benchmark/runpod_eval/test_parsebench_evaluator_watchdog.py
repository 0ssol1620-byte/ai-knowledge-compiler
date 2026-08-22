from __future__ import annotations

from parsebench_evaluator_watchdog import has_pathological_formatting_query


def test_punctuation_only_formatting_query_is_guarded() -> None:
    assert has_pathological_formatting_query(
        {"test_rules": [{"type": "is_bold", "text": "*"}]},
        r"\*" * 80,
    )
    assert has_pathological_formatting_query(
        {"test_rules": [{"type": "is_title", "text": "**"}]},
        "*" * 80,
    )


def test_normal_formatting_queries_and_other_rules_are_not_guarded() -> None:
    assert not has_pathological_formatting_query(
        {"test_rules": [{"type": "is_bold", "text": "Revenue"}]},
        "*" * 80,
    )
    assert not has_pathological_formatting_query(
        {"test_rules": [{"type": "missing_specific_word", "text": "*"}]},
        "*" * 80,
    )
    assert not has_pathological_formatting_query(
        {"test_rules": [{"type": "is_bold", "text": "*"}]},
        "ordinary **bold** content",
    )
