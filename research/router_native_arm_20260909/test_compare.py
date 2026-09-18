import pytest

from research.router_native_arm_20260909.compare_spent import bind_rows, summarize


def rule(key, pdf="a", bucket="text", passed=True):
    return {"test_id": key, "pdf": pdf, "page": 1, "type": "present",
            "source_jsonl": bucket, "passed": passed}


def test_missing_rows_stay_false_and_order_is_canonical():
    canonical = [rule("1"), rule("2")]
    assert bind_rows(canonical, [rule("2")]) == ([False, True], 1)


@pytest.mark.parametrize("rows", [[rule("1"), rule("1")], [rule("unknown")],
                                  [rule("1", pdf="wrong")], [rule("1", passed="false")]])
def test_incompatible_results_refuse(rows):
    with pytest.raises(ValueError):
        bind_rows([rule("1")], rows)


def test_page_oracle_does_not_pick_different_models_for_rules_on_same_page():
    result = summarize([rule("1"), rule("2")], {"native": [True, False], "model": [False, True]})
    assert result["diagnostic_page_oracle_with_native"] == 0.5
    assert result["runtime_router_score"] is None


def test_bucket_weighting_does_not_let_large_buckets_dominate():
    result = summarize([rule("1"), rule("2"), rule("3", pdf="b", bucket="table")],
                       {"native": [True, True, False], "model": [False, False, True]})
    assert result["fixed_scores"] == {"native": 0.5, "model": 0.5}
    assert result["diagnostic_page_oracle_with_native"] == 1.0
