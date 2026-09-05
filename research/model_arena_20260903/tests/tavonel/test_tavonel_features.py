"""Pure feature functions, including the ones no fixture page exercises."""

from __future__ import annotations

import pytest
from arena.tavonel import features


def test_hallucinated_boilerplate_is_flagged_with_the_phrase_it_matched() -> None:
    computed = features.compute_text_features(
        "I cannot transcribe this image, but here is the transcription of what I see."
    )
    assert computed.hallucinated_boilerplate
    assert "i cannot" in computed.hallucinated_boilerplate_phrases
    assert "here is the transcription" in computed.hallucinated_boilerplate_phrases


def test_clean_prose_is_not_flagged_as_boilerplate() -> None:
    computed = features.compute_text_features("# Title\n\nThe cannonade lasted an hour.\n")
    assert not computed.hallucinated_boilerplate
    assert computed.hallucinated_boilerplate_phrases == ()


def test_language_distribution_is_script_based_and_sums_to_one() -> None:
    distribution = features.script_distribution("abc 한국어 漢字 Привет")
    assert distribution["letter_count"] == 3 + 3 + 2 + 6
    assert distribution["hangul"] > 0
    assert distribution["han"] > 0
    assert distribution["cyrillic"] > 0
    total = sum(value for key, value in distribution.items() if key != "letter_count")
    assert total == pytest.approx(1.0, abs=1e-6)


def test_language_distribution_of_text_without_letters_is_all_zero() -> None:
    distribution = features.script_distribution("123 456 ---")
    assert distribution["letter_count"] == 0
    assert distribution["latin"] == 0.0
    assert distribution["other"] == 0.0


def test_broken_text_counts_replacement_and_control_characters() -> None:
    computed = features.compute_text_features("ab�cd\x00ef")
    assert computed.unicode_replacement_count == 1
    assert computed.broken_text_ratio > 0.0


def test_html_table_validity_is_null_when_there_is_no_html_table() -> None:
    computed = features.compute_text_features("# Heading\n\nplain prose\n")
    assert computed.html_table_validity is None
    assert computed.html_table_issues is None


def test_html_table_validity_catches_an_unclosed_table() -> None:
    computed = features.compute_text_features("<table><tr><td>1</td></tr>")
    assert computed.html_table_validity is False
    assert "unbalanced_table_or_row_tags" in (computed.html_table_issues or ())


def test_html_table_validity_accepts_a_closed_table() -> None:
    computed = features.compute_text_features("<table><tr><td>1</td></tr></table>")
    assert computed.html_table_validity is True
    assert computed.html_table_issues == ()


def test_continuation_suspicion_sees_both_ends_of_a_fragment() -> None:
    starts_mid = features.compute_text_features("and then the committee agreed to the terms.")
    assert starts_mid.continuation_suspicion
    assert "starts_mid_sentence" in starts_mid.continuation_reasons

    ends_with_ellipsis = features.compute_text_features("The committee agreed to...")
    assert "ends_with_ellipsis" in ends_with_ellipsis.continuation_reasons


def test_truncation_reasons_are_named_not_blended() -> None:
    reasons = features.truncation_evidence(
        "| a | b |\n| 1 | 2", output_tokens_at_max=None
    )
    assert "ends_mid_table_row" in reasons
    assert "output_tokens_at_max" not in reasons


def test_token_cap_alone_can_signal_truncation() -> None:
    reasons = features.truncation_evidence("A complete sentence.", output_tokens_at_max=True)
    assert reasons == ("output_tokens_at_max",)


def test_empty_text_has_no_truncation_evidence() -> None:
    assert features.truncation_evidence("   \n", output_tokens_at_max=True) == ()


def test_formula_counting_does_not_double_count_display_math() -> None:
    assert features.count_formulas("$$x$$") == 1
    assert features.count_formulas("$x$ and $y$") == 2
    assert features.count_formulas("\\begin{equation}x\\end{equation}") == 1


def test_lcs_length_is_the_reading_order_proxy() -> None:
    assert features.lcs_length(["a", "b", "c"], ["a", "c", "b"]) == 2
    assert features.lcs_length(["a", "b"], ["a", "b"]) == 2
    assert features.lcs_length([], ["a"]) == 0


def test_ratios_are_rounded_so_a_record_hashes_the_same_everywhere() -> None:
    computed = features.compute_text_features("abc 123\n")
    for value in (computed.alpha_ratio, computed.digit_ratio, computed.text_density):
        assert value == round(value, 6)
