import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import gpu_successor_v2_inference as inference


def _arm(success: bool, stable: bool = True) -> dict:
    first = "ANSWER_MATCHES_CURRENT" if success else "ANSWER_OTHER"
    second = first if stable else "ANSWER_REFUSED"
    return {"repetitions": [{"class": first}, {"class": second}]}


def _items(n: int = 450) -> list[dict]:
    rows = []
    for index in range(n):
        rows.append(
            {
                "lineage_id": f"L{index:03d}",
                "arms": {
                    "CURRENT_TYPED": _arm(index < 270),
                    "STALE_TYPED": _arm(index < 225),
                    "CURRENT_TEXT_ONLY": _arm(index < 248),
                },
            }
        )
    return rows


def test_exact_mcnemar_known_values():
    assert inference.exact_mcnemar_p_value(0, 0) == 1.0
    assert inference.exact_mcnemar_p_value(5, 0) == pytest.approx(0.0625)
    assert inference.exact_mcnemar_p_value(10, 10) == 1.0


def test_three_arm_analysis_uses_one_lineage_once_and_not_repeats():
    body = inference.analyze(_items())
    assert body["currency"]["n"] == 450
    assert body["currency"]["risk_difference"] == pytest.approx(0.1)
    assert body["representation_superiority"]["risk_difference"] == pytest.approx(22 / 450)
    assert body["currency"]["deterministic_repeats_counted_as_independent"] is False


def test_paired_ci_is_deterministic_and_contains_estimate():
    first = inference.deterministic_paired_bootstrap_risk_difference_ci(b=45, c=0, n=450)
    second = inference.deterministic_paired_bootstrap_risk_difference_ci(b=45, c=0, n=450)
    assert first == second
    assert first[0] <= 0.1 <= first[1]


def test_refuses_below_target_or_duplicate_lineage():
    with pytest.raises(inference.InferenceRefused, match="target 450"):
        inference.analyze(_items(449))
    rows = _items()
    rows[-1]["lineage_id"] = rows[0]["lineage_id"]
    with pytest.raises(inference.InferenceRefused, match="unique"):
        inference.analyze(rows)


def test_unstable_repeat_is_diagnostic_not_extra_observation():
    rows = _items()
    rows[0]["arms"]["CURRENT_TYPED"] = _arm(True, stable=False)
    body = inference.analyze(rows)
    assert body["currency"]["unstable_lineages"] == 1
    assert body["currency"]["n"] == 450
