"""The arms, the scorer and the statistics have to fail when they should.

Each module computes a control inside its own run --- `fairness_control`,
`scoring_control`, `statistics_control` --- and those are asserted here rather
than re-implemented, because re-implementing a control tests a copy of it. What
this file adds is the failure path for each claim the modules make, plus the two
defects their controls already caught, pinned so neither returns quietly:

- `1,450` scored wrong against `1450` because the normalizer split on the
  thousands separator
- a shared context budget can drop the oracle unit, which turns a
  context-window artefact into what reads as a representation result. RAW no
  longer shares that budget after the 2026-08-20 decision; the retrieval arms
  still do, and the test moved with it

The modules are scripts rather than package modules, so they are loaded by path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research/experiments/H1-W6-SAME-INTELLIGENCE-01"


def load(relative: str, name: str) -> Any:
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def arms() -> Any:
    return load("research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/arms_v8.py",
                "t_arms_v8")


@pytest.fixture(scope="module")
def scoring() -> Any:
    return load("research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/scoring_v8.py",
                "t_scoring_v8")


SHARED = {
    "model_identity": {"name": "pinned-at-freeze"},
    "decoding": {"temperature": 0.0},
    "answer_schema": "answer|abstained|evidence_present",
    "subject_routing": "stage_0",
    "scorer": "scoring_v8.score_answer",
    "top_k": 5,
    "context_budget_tokens": 3000,
    "question_set_sha256": "sha256:deadbeef",
}

SHARED_PARAMETERS = sorted(SHARED)


def make_units(arms: Any) -> list[Any]:
    out = []
    for i in range(3):
        out.append(arms.Unit(
            text=f"the population of the city was {1200 + i} people according to the "
                 "earlier census report published at that time",
            revision="before", revision_id=1, path="before.wikitext", index=i,
            valid_from="2023-01-01T00:00:00Z", valid_to="2024-01-01T00:00:00Z"))
    for i in range(3):
        out.append(arms.Unit(
            text=f"the population of the city was {1450 + i} people according to the "
                 "current census report published more recently",
            revision="after", revision_id=2, path="after.wikitext", index=i,
            valid_from="2024-01-01T00:00:00Z", valid_to=None))
    return out


def clean_configs(arms: Any) -> dict[str, dict[str, Any]]:
    return {a: dict(SHARED, temporal_metadata_supplied=(a == "TAVONEL")) for a in arms.ARMS}


# --- fairness contract ------------------------------------------------------

def test_the_shipped_fairness_control_separates(arms):
    assert arms.fairness_control(SHARED)["separates"]


def test_a_clean_four_arm_configuration_holds(arms):
    assert arms.fairness_contract(clean_configs(arms))["holds"]


@pytest.mark.parametrize("key", SHARED_PARAMETERS)
def test_any_shared_parameter_differing_between_arms_is_a_violation(arms, key):
    configs = clean_configs(arms)
    configs["BASIC_RAG"][key] = "something-else"
    result = arms.fairness_contract(configs)
    assert not result["holds"]
    assert any(f["kind"] == "SHARED_PARAMETER_DIFFERS" and f["parameter"] == key
               for f in result["findings"])


def test_a_baseline_carrying_temporal_metadata_is_a_violation(arms):
    """Temporal metadata is the variable under test; only TAVONEL may carry it."""
    configs = clean_configs(arms)
    configs["BASIC_RAG"]["temporal_metadata_supplied"] = True
    assert not arms.fairness_contract(configs)["holds"]


def test_tavonel_without_temporal_metadata_is_also_a_violation(arms):
    """Two-sided, or the contract only polices one direction."""
    configs = clean_configs(arms)
    configs["TAVONEL"]["temporal_metadata_supplied"] = False
    assert not arms.fairness_contract(configs)["holds"]


@pytest.mark.parametrize("arm", ["BASIC_RAG_PLUS", "TAVONEL"])
def test_extra_intelligence_is_refused_for_baseline_and_for_tavonel(arms, arm):
    configs = clean_configs(arms)
    configs[arm]["uses_external_model_beyond_shared"] = True
    assert not arms.fairness_contract(configs)["holds"]


def test_a_missing_arm_is_a_violation(arms):
    configs = {a: c for a, c in clean_configs(arms).items() if a != "BASIC_RAG_PLUS"}
    assert not arms.fairness_contract(configs)["holds"]


# --- adapters ---------------------------------------------------------------

def test_only_tavonel_puts_validity_and_provenance_into_the_context(arms):
    pool = make_units(arms)
    for arm, fn in arms.ADAPTERS.items():
        kwargs = {"model_context_tokens": 4000} if arm == "RAW" else {}
        context = fn(pool, "what is the population of the city", {0}, **kwargs).as_context()
        assert ("valid from" in context) == (arm == "TAVONEL"), arm


def test_tavonel_prefers_the_current_revision_over_the_superseded_one(arms):
    """Same retriever, same units; valid-time ordering is the only difference."""
    pool = make_units(arms)
    assert arms.tavonel_arm(pool, "what is the population of the city",
                            {0}).units[0].revision == "after"


def test_tavonel_as_of_selects_the_revision_valid_at_that_time(arms):
    pool = make_units(arms)
    assert arms.tavonel_arm(pool, "what is the population of the city", {0},
                            as_of="2023-06-01T00:00:00Z").units[0].revision == "before"


def test_rm3_expands_the_query_and_is_deterministic(arms):
    pool = make_units(arms)
    docs = [arms.tokens(u.text) for u in pool]
    index = arms.BM25(docs)
    query = arms.tokens("population city")
    first = arms.rm3_expand(index, query, docs)
    assert first == arms.rm3_expand(index, query, docs)
    assert len(first) > len(query)


def test_raw_receives_whole_documents_in_revision_order_without_retrieval(arms):
    pool = make_units(arms)
    evidence = arms.raw_arm(pool, "a query with no shared terms whatsoever", {0},
                            model_context_tokens=4000)
    assert evidence.units[0].revision == "before"
    assert evidence.units_available == len(pool)
    assert not evidence.truncated
    assert evidence.units_omitted == 0


def test_raw_refuses_to_run_before_the_model_context_is_known(arms):
    """No silent fallback to the retrieval budget.

    Falling back would rebuild the budget-limited floor that the 2026-08-20
    decision removes, and the result would read as a representation finding.
    """
    with pytest.raises(arms.RawContextOverflow, match="MODEL_CONTEXT_TOKENS is not set"):
        arms.raw_arm(make_units(arms), "what is the population", {0})


def test_raw_records_overflow_rather_than_truncating(arms):
    """RAW_CONTEXT_OVERFLOW: the pair does not fit, and it is not quietly cut."""
    with pytest.raises(arms.RawContextOverflow, match="RAW_CONTEXT_OVERFLOW"):
        arms.raw_arm(make_units(arms), "what is the population", {0},
                     model_context_tokens=10)


def test_raw_does_not_share_the_retrieval_budget(arms):
    """The asymmetry is deliberate and must be visible in the evidence record."""
    evidence = arms.raw_arm(make_units(arms), "what is the population", {0},
                            model_context_tokens=4000)
    assert evidence.budget_tokens == 4000
    assert evidence.budget_tokens != arms.CONTEXT_BUDGET_TOKENS
    assert arms.RAW_BUDGET_POLICY == "RAW_GETS_WHOLE_DOCUMENT_BUDGET"


def test_the_retrieval_budget_reports_when_it_drops_the_oracle(arms, monkeypatch):
    """The §6b defect, on the arms that still share a budget.

    RAW no longer shares it --- it overflows instead of truncating --- but the
    retrieval arms do, and a budget that silently removes the answer would still
    turn a context effect into what reads as a representation result.
    """
    monkeypatch.setattr(arms, "CONTEXT_BUDGET_TOKENS", 12)
    evidence = arms.basic_rag_arm(make_units(arms), "earlier census report", {3, 4, 5})
    assert evidence.truncated
    assert evidence.units_omitted > 0
    assert evidence.oracle_omitted_by_truncation


def test_an_untruncated_arm_does_not_claim_the_oracle_was_dropped(arms):
    evidence = arms.basic_rag_arm(make_units(arms),
                                  "what is the population of the city", {0})
    assert not evidence.oracle_omitted_by_truncation


# --- scorer -----------------------------------------------------------------

def test_the_shipped_scoring_control_separates(scoring):
    assert scoring.scoring_control()["separates"]


@pytest.mark.parametrize(("a", "b"), [("1,450", "1450"), ("1450", "1,450")])
def test_a_thousands_separator_does_not_change_the_answer(scoring, a, b):
    """The defect the scorer's own control caught before any arm ran."""
    assert scoring.normalize(a) == scoring.normalize(b)


def test_different_numbers_are_still_different(scoring):
    """The fix must not collapse distinct values into one."""
    assert scoring.normalize("1,450") != scoring.normalize("1,200")


def test_right_answer_from_the_stale_revision_is_not_temporally_correct(scoring):
    outcome = scoring.score_answer(
        response={"answer": "1,450"}, gold_current="1,450", gold_as_of_before="1,200",
        answerable=True, cited_revision="before", oracle_revision="after")
    assert outcome.answer_correct
    assert outcome.right_answer_stale_evidence
    assert not outcome.temporal_correct


def test_abstention_cannot_win_in_either_direction(scoring):
    common = {"gold_current": "1,450", "gold_as_of_before": "1,200",
              "oracle_revision": "after"}
    answerable = scoring.score_answer(
        response={"abstained": True, "answer": None}, answerable=True,
        cited_revision=None, **common)
    undetermined = scoring.score_answer(
        response={"abstained": True, "answer": None}, answerable=False,
        cited_revision=None, **common)
    guess = scoring.score_answer(
        response={"answer": "1,450"}, answerable=False, cited_revision="after", **common)
    assert not answerable.abstention_appropriate
    assert undetermined.abstention_appropriate
    assert guess.unsupported_assertion


def test_an_unchanged_value_is_not_counted_as_a_stale_answer(scoring):
    """When both revisions carry the same value the question cannot separate them."""
    outcome = scoring.score_answer(
        response={"answer": "same"}, gold_current="same", gold_as_of_before="same",
        answerable=True, cited_revision="before", oracle_revision="after")
    assert not outcome.stale_answer


# --- statistics -------------------------------------------------------------

def test_the_shipped_statistics_control_separates(scoring):
    assert scoring.statistics_control()["separates"]


def test_identical_arms_produce_no_effect_and_no_significance(scoring):
    vector = [True] * 30 + [False] * 30
    result = scoring.paired_comparison("A", "B", vector, list(vector))
    assert result["absolute_effect"] == 0.0
    assert result["mcnemar_exact_p"] == 1.0
    assert result["discordant_pairs"]["total"] == 0


def test_every_comparison_reports_more_than_a_p_value(scoring):
    """p < 0.05 on 4 discordant pairs and on 400 must not look identical."""
    result = scoring.paired_comparison("A", "B", [True, False], [False, False])
    for key in ("absolute_effect", "paired_difference_ci95", "discordant_pairs",
                "concordant_pairs", "n_pairs"):
        assert key in result


def test_mismatched_vector_lengths_are_refused(scoring):
    with pytest.raises(ValueError, match="equal-length"):
        scoring.paired_comparison("A", "B", [True], [True, False])


def test_holm_ranks_by_p_and_widens_the_threshold_as_it_descends(scoring):
    result = scoring.holm({"a": 0.001, "b": 0.9, "c": 0.002})
    assert result["results"]["a"]["significant"]      # 0.001 <= 0.05/3
    assert result["results"]["c"]["significant"]      # 0.002 <= 0.05/2
    assert not result["results"]["b"]["significant"]  # 0.9 > 0.05


def test_holm_is_step_down_so_one_failure_ends_the_family(scoring):
    """The smallest p failing must sink every later hypothesis, however small."""
    result = scoring.holm({"a": 0.03, "b": 0.031, "c": 0.9})
    assert not result["results"]["a"]["significant"]  # 0.03 > 0.05/3
    assert not result["results"]["b"]["significant"]  # sunk by a, not by its own p
    assert not result["results"]["c"]["significant"]


def test_the_development_model_is_marked_as_not_a_real_model(arms):
    """Its output must never be mistakable for an endpoint."""
    model = arms.ExtractiveDevelopmentModel(lambda _q: ["x"])
    assert model.identity["is_real_model"] is False
    assert model.is_real_model is False


def test_the_development_arm_run_receipt_declares_what_it_is_not():
    import json
    path = EXP / "receipts/v8-development-arm-run-2026-08-19.json"
    if not path.exists():
        pytest.skip("the development arm run has not been produced")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["run_class"] == "DEVELOPMENT_ONLY"
    assert receipt["controls"]["all_separate"]
    assert receipt["fairness_contract"]["holds"]
    assert receipt["shared_configuration"]["model_identity"]["is_real_model"] is False
