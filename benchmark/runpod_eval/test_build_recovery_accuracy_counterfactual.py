"""The roll-up behind the campaign's headline number was assembled by hand.

Three things came out of replacing it with a generator: the two fields binding
it to the summaries it summarises were null, the per-type breakdown could go
silently empty when a key was renamed, and one field named "relative_score_delta"
held the gap over the *without* score -- the larger of the two arithmetics that
name could mean.
"""

from __future__ import annotations

import json

import pytest
from build_recovery_accuracy_counterfactual import build


def _summary(
    *,
    score: float,
    failures: int,
    ci: tuple[float, float],
    revision: str = "cfa88c1e",
    manifest: str = "sha256:aaa",
    inputs: int = 1403,
    tests: int = 8413,
    per_jsonl: dict[str, float] | None = None,
    type_breakdown: dict[str, float] | None = None,
) -> dict[str, object]:
    return {
        "overall_score": score,
        "confidence_interval_95": list(ci),
        "rule_failure_count": failures,
        "evaluator_revision": revision,
        "source_manifest_sha256": manifest,
        "input_count": inputs,
        "test_count": tests,
        "per_jsonl": {
            name: {"pass_rate": rate}
            for name, rate in (per_jsonl or {"baseline": 0.99}).items()
        },
        "type_breakdown": {
            name: {"pass_rate": rate}
            for name, rate in (type_breakdown or {"absent": 0.9453}).items()
        },
    }


def _write(tmp_path, name: str, payload: dict[str, object]):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _pair(tmp_path, **overrides):
    high = _write(
        tmp_path,
        "with.json",
        _summary(score=0.8060, failures=1276, ci=(0.7962, 0.8157), **overrides),
    )
    low = _write(
        tmp_path,
        "without.json",
        _summary(score=0.5370, failures=3818, ci=(0.5262, 0.5493)),
    )
    return high, low


def test_both_sides_carry_the_hash_of_the_summary_they_came_from(tmp_path) -> None:
    high, low = _pair(tmp_path)

    payload = build(high, low, emptied_documents=582)

    assert payload["with_recovery"]["summary_sha256"].startswith("sha256:")
    assert payload["without_recovery"]["summary_sha256"].startswith("sha256:")
    assert (
        payload["with_recovery"]["summary_sha256"]
        != payload["without_recovery"]["summary_sha256"]
    )


def test_the_two_relative_readings_are_named_separately(tmp_path) -> None:
    high, low = _pair(tmp_path)

    payload = build(high, low, emptied_documents=582)

    # 0.2690 / 0.8060 and 0.2690 / 0.5370. Both true, different sentences.
    assert payload["score_share_lost_without_recovery"] == 0.3337
    assert payload["score_uplift_over_no_recovery"] == 0.5009
    assert "relative_score_delta" not in payload


def test_absolute_delta_and_extra_failures_come_from_the_summaries(tmp_path) -> None:
    high, low = _pair(tmp_path)

    payload = build(high, low, emptied_documents=582)

    assert payload["absolute_score_delta"] == 0.269
    assert payload["additional_rule_failures_without_recovery"] == 2542


def test_non_overlapping_intervals_are_recorded_not_asserted(tmp_path) -> None:
    high, low = _pair(tmp_path)
    assert build(high, low, emptied_documents=582)["confidence_intervals_overlap"] is False


def test_overlapping_intervals_are_reported_as_overlapping(tmp_path) -> None:
    high = _write(tmp_path, "with.json", _summary(score=0.60, failures=10, ci=(0.50, 0.70)))
    low = _write(tmp_path, "without.json", _summary(score=0.58, failures=12, ci=(0.55, 0.65)))

    assert build(high, low, emptied_documents=1)["confidence_intervals_overlap"] is True


def test_a_differing_evaluator_revision_is_not_a_single_variable_comparison(tmp_path) -> None:
    high = _write(
        tmp_path, "with.json", _summary(score=0.80, failures=1, ci=(0.79, 0.81), revision="aaa")
    )
    low = _write(
        tmp_path, "without.json", _summary(score=0.53, failures=2, ci=(0.52, 0.54), revision="bbb")
    )

    with pytest.raises(ValueError, match="single-variable"):
        build(high, low, emptied_documents=1)


def test_a_differing_source_manifest_is_refused(tmp_path) -> None:
    high = _write(
        tmp_path, "with.json", _summary(score=0.8, failures=1, ci=(0.79, 0.81), manifest="sha256:a")
    )
    low = _write(
        tmp_path,
        "without.json",
        _summary(score=0.53, failures=2, ci=(0.52, 0.54), manifest="sha256:b"),
    )

    with pytest.raises(ValueError, match="source_manifest_sha256"):
        build(high, low, emptied_documents=1)


def test_a_renamed_breakdown_fails_instead_of_emitting_an_empty_section(tmp_path) -> None:
    payload = _summary(score=0.8, failures=1, ci=(0.79, 0.81))
    del payload["type_breakdown"]
    high = _write(tmp_path, "with.json", payload)
    low = _write(tmp_path, "without.json", _summary(score=0.53, failures=2, ci=(0.52, 0.54)))

    with pytest.raises(KeyError, match="type_breakdown"):
        build(high, low, emptied_documents=1)


def test_a_slice_present_on_only_one_side_is_refused(tmp_path) -> None:
    high = _write(
        tmp_path,
        "with.json",
        _summary(score=0.8, failures=1, ci=(0.79, 0.81), per_jsonl={"a": 0.9, "b": 0.8}),
    )
    low = _write(
        tmp_path,
        "without.json",
        _summary(score=0.53, failures=2, ci=(0.52, 0.54), per_jsonl={"a": 0.5}),
    )

    with pytest.raises(ValueError, match="same slices"):
        build(high, low, emptied_documents=1)


def test_the_absent_test_caveat_quotes_the_measured_rates(tmp_path) -> None:
    """Removing recovery makes 'absent' tests easier, and that has to travel."""
    high = _write(
        tmp_path,
        "with.json",
        _summary(score=0.8, failures=1, ci=(0.79, 0.81), type_breakdown={"absent": 0.9453}),
    )
    low = _write(
        tmp_path,
        "without.json",
        _summary(score=0.53, failures=2, ci=(0.52, 0.54), type_breakdown={"absent": 0.9635}),
    )

    caveat = build(high, low, emptied_documents=1)["caveat_absent_tests"]

    assert "0.9453 -> 0.9635" in caveat


def test_the_receipt_hash_covers_the_payload(tmp_path) -> None:
    high, low = _pair(tmp_path)

    first = build(high, low, emptied_documents=582)
    second = build(high, low, emptied_documents=583)

    assert first["receipt_sha256"] != second["receipt_sha256"]
    assert build(high, low, emptied_documents=582)["receipt_sha256"] == first["receipt_sha256"]


def test_score_inflation_stays_disallowed(tmp_path) -> None:
    high, low = _pair(tmp_path)
    assert build(high, low, emptied_documents=582)["score_inflation_allowed"] is False
