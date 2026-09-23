"""SRP-1: the second-reader agreement / abstention rule pre-registered in ADR-007.

Every input here is synthetic text. Nothing reads a campaign tree, a score or
an answer key.
"""

from __future__ import annotations

import itertools

import pytest
from arena.tavonel import second_reader_policy as srp
from arena.tavonel.second_reader_policy import ReaderOutput


def _reference_levenshtein(left: str, right: str) -> int:
    prev = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        cur = [i]
        for j, b in enumerate(right, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1]


def _primary(text: str, **kwargs: object) -> ReaderOutput:
    return ReaderOutput("paddleocr_vl_1_6", "rev-a", text, **kwargs)  # type: ignore[arg-type]


def _second(text: str, **kwargs: object) -> ReaderOutput:
    return ReaderOutput("ovisocr2", "rev-b", text, **kwargs)  # type: ignore[arg-type]


CLEAN = "# Quarterly Report\n\nRevenue rose twelve percent in the third quarter.\n"

_SAMPLES = [
    "", "a", "ab", "ba", "abc", "kitten", "sitting", "flaw", "lawn", "한국어 문서", "한국 문서들"
]


@pytest.mark.parametrize(("left", "right"), list(itertools.product(_SAMPLES, repeat=2)))
def test_bounded_levenshtein_is_exact_within_the_bound_and_saturates_above(
    left: str, right: str
) -> None:
    exact = _reference_levenshtein(left, right)
    for bound in range(0, 9):
        expected = exact if exact <= bound else bound + 1
        assert srp.bounded_levenshtein(left, right, bound) == expected, (left, right, bound)


def test_bounded_levenshtein_on_long_strings_with_scattered_edits() -> None:
    base = "".join(chr(ord("a") + (i * 7) % 26) for i in range(400))
    edited = list(base)
    for index in (3, 50, 51, 199, 350):
        edited[index] = "#"
    other = "".join(edited[:120]) + "".join(edited[125:])  # five more edits: a deletion run
    exact = _reference_levenshtein(base, other)
    assert srp.bounded_levenshtein(base, other, exact) == exact
    assert srp.bounded_levenshtein(base, other, exact - 1) == exact
    assert srp.bounded_levenshtein(base, other, 40) == exact


def test_bounded_levenshtein_refuses_a_negative_bound() -> None:
    with pytest.raises(ValueError):
        srp.bounded_levenshtein("a", "b", -1)


def test_identical_outputs_are_accepted_with_zero_distance() -> None:
    verdict = srp.decide(_primary(CLEAN), _second(CLEAN))
    assert verdict.decision == srp.ACCEPT
    assert verdict.reasons == ("readers_agree",)
    assert verdict.edit_distance == 0


def test_case_and_whitespace_do_not_count_as_disagreement() -> None:
    noisy = "#  quarterly   REPORT\n\n\nRevenue rose twelve percent in the third quarter.\n"
    assert srp.decide(_primary(CLEAN), _second(noisy)).decision == srp.ACCEPT


def test_the_threshold_is_inclusive_and_decided_in_integers() -> None:
    base = "a" * 100
    at_line = "b" * 10 + "a" * 90
    past_line = "b" * 11 + "a" * 89
    at = srp.decide(_primary(base), _second(at_line))
    past = srp.decide(_primary(base), _second(past_line))
    assert (at.decision, at.edit_distance, at.edit_bound) == (srp.ACCEPT, 10, 10)
    assert (past.decision, past.edit_distance, past.edit_bound) == (srp.ABSTAIN, None, 10)
    assert past.reasons == ("readers_disagree",)


def test_a_short_page_needs_an_exact_match() -> None:
    # nine characters: floor(0.9) = 0, so a single edit is already disagreement
    verdict = srp.decide(_primary("revenue 1"), _second("revenue 7"))
    assert (verdict.decision, verdict.edit_bound) == (srp.ABSTAIN, 0)


def test_the_decision_does_not_depend_on_which_side_is_primary() -> None:
    left, right = CLEAN, CLEAN.replace("twelve", "eleven")
    forward = srp.decide(_primary(left), _second(right))
    backward = srp.decide(_primary(right), _second(left))
    assert (forward.decision, forward.edit_distance) == (backward.decision, backward.edit_distance)


def test_both_empty_is_not_agreement() -> None:
    verdict = srp.decide(_primary(""), _second("   \n"))
    assert verdict.decision == srp.ABSTAIN
    assert verdict.reasons == ("primary_empty_output", "second_empty_output")
    assert verdict.edit_distance is None and verdict.edit_bound is None


def test_one_empty_side_abstains() -> None:
    verdict = srp.decide(_primary(CLEAN), _second(""))
    assert (verdict.decision, verdict.reasons) == (srp.ABSTAIN, ("second_empty_output",))


def test_structural_truncation_abstains_even_when_both_readers_match() -> None:
    cut = CLEAN + "\n```python\nprint(1)\n"
    verdict = srp.decide(_primary(cut), _second(cut))
    assert verdict.decision == srp.ABSTAIN
    assert verdict.reasons == ("primary_truncation_suspected", "second_truncation_suspected")


def test_token_cap_abstains_but_an_unknown_cap_does_not() -> None:
    capped = srp.decide(_primary(CLEAN, output_tokens_at_max=True), _second(CLEAN))
    unknown = srp.decide(_primary(CLEAN, output_tokens_at_max=None), _second(CLEAN))
    assert capped.reasons == ("primary_truncation_suspected",)
    assert unknown.decision == srp.ACCEPT


def test_ending_mid_sentence_alone_is_not_a_strong_signal() -> None:
    heading_only = "# Revenue by region"
    assert srp.decide(_primary(heading_only), _second(heading_only)).decision == srp.ACCEPT


def test_boilerplate_abstains_even_when_both_readers_say_it() -> None:
    chatter = "I'm sorry, I cannot read this image.\n"
    verdict = srp.decide(_primary(chatter), _second(chatter))
    assert verdict.reasons == (
        "primary_hallucinated_boilerplate",
        "second_hallucinated_boilerplate",
    )


def test_an_oversized_page_is_refused_not_truncated() -> None:
    huge = "word " * (srp.MAX_COMPARE_CHARS // 4)
    verdict = srp.decide(_primary(huge), _second(huge))
    assert verdict.decision == srp.ABSTAIN
    assert verdict.reasons == ("primary_too_long_to_compare", "second_too_long_to_compare")
    assert verdict.edit_distance is None


def test_the_same_reader_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="same model"):
        srp.decide(_primary(CLEAN), ReaderOutput("paddleocr_vl_1_6", "rev-a", CLEAN))


def test_a_different_revision_of_the_same_model_is_not_an_independent_reader() -> None:
    other_revision = ReaderOutput("paddleocr_vl_1_6", "rev-z", CLEAN)
    with pytest.raises(ValueError, match="same model"):
        srp.decide(_primary(CLEAN), other_revision)


@pytest.mark.parametrize(("reader_id", "revision"), [("", "rev-b"), ("ovisocr2", "")])
def test_an_unpinned_reader_is_refused(reader_id: str, revision: str) -> None:
    with pytest.raises(ValueError, match="pinned"):
        srp.decide(_primary(CLEAN), ReaderOutput(reader_id, revision, CLEAN))


def test_the_verdict_never_names_a_substitute_output() -> None:
    record = srp.decide(_primary(CLEAN), _second("entirely different text here")).as_dict()
    assert record["decision"] in {srp.ACCEPT, srp.ABSTAIN}
    assert record["policy_version"] == srp.POLICY_VERSION
    assert record["threshold"]["calibrated"] is False
    assert not {"winner", "selected_output", "chosen_reader"} & set(record)


def test_policy_parameters_pin_the_threshold_as_uncalibrated() -> None:
    params = srp.policy_parameters()
    assert params["threshold"]["value"] == 0.1
    assert params["threshold"]["calibrated"] is False
    assert "ends_mid_sentence" not in params["strong_truncation_signals"]
