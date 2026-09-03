"""The v8 leakage and baseline gates have to fail when they should.

Each gate computes a positive control inside its own run and writes it into its
receipt, which is the right place for it --- a receipt whose control did not
separate is not citable. It is not a test: it runs only when someone runs the
gate, and CI never sees it. So every detecting path here is paired with the
near-identical input that must *not* fire.

Two of these tests exist because the gate was wrong the first time. The minimal
leak mutant injected a numeral the template had already licensed and caught 663
of 711 rather than 711; the oracle matcher used the retrieval tokenizer, which
maps a numeric value to the empty set, and the empty set is a subset of every
unit. Both are pinned below so neither can come back quietly.

The gates are scripts rather than package modules, so they are loaded by path.
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
def taint() -> Any:
    return load("research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/taint_gate_v8.py",
                "t_taint_v8")


@pytest.fixture(scope="module")
def residual() -> Any:
    return load("research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/residual_overlap_v8.py",
                "t_residual_v8")


@pytest.fixture(scope="module")
def entity() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/entity_conditioned_gate_v8.py",
        "t_entity_v8")


ITEM = {
    "subject": "Stone Mountain Memorial half dollar",
    "attribute": "country",
    "date": "2023-02-10",
    "oracle": "The coin was struck at the Philadelphia Mint in 1925 and its obverse "
              "depicts two Confederate generals on horseback.",
}


# --- 2A structural taint gate ----------------------------------------------

def test_the_reference_builder_emits_nothing_the_declared_inputs_cannot_explain(taint):
    for template_id in taint.TEMPLATES:
        query = taint.render(subject=ITEM["subject"], attribute=ITEM["attribute"],
                             date=ITEM["date"], template_id=template_id)
        assert taint.taint_of(query, subject=ITEM["subject"], attribute=ITEM["attribute"],
                              date=ITEM["date"]) == set()


@pytest.mark.parametrize("mutant", sorted(["single_oracle_token", "passage_paraphrase",
                                           "value_appended"]))
def test_every_mutant_is_caught(taint, mutant):
    result = taint.evaluate(taint.MUTANTS[mutant], [ITEM])
    assert not result["passes"]
    assert result["tainted_queries"] == len(taint.TEMPLATES)


def test_the_clean_builder_passes_the_same_evaluator_the_mutants_fail(taint):
    """The evaluator has to distinguish, not merely reject everything."""
    assert taint.evaluate(taint._clean, [ITEM])["passes"]


def test_the_minimal_leak_mutant_injects_a_token_no_declared_input_supplies(taint):
    """The 663-of-711 defect: the injected token was sometimes a date numeral.

    A date numeral is licensed by the `as_of` template, so flagging it would be
    wrong and not flagging it is not a miss. A mutant that injects a non-leak
    measures the gate's tolerance rather than its sensitivity.
    """
    item = dict(ITEM, oracle="Population was 1925 in 2023 according to the census.")
    query = taint.MUTANTS["single_oracle_token"](
        subject=item["subject"], attribute=item["attribute"], date=item["date"],
        template_id="as_of", oracle=item["oracle"])
    injected = taint.tokens(query) - taint.tokens(
        taint.render(subject=item["subject"], attribute=item["attribute"],
                     date=item["date"], template_id="as_of"))
    assert injected
    assert not (injected & taint.tokens(item["date"]))


def test_a_token_in_the_query_but_not_in_the_oracle_is_not_reported_as_leakage(taint):
    """Overstating what the gate observes is its own defect.

    An unexplained token found nowhere in the source is a different failure, and
    calling it leakage would claim an observation the gate did not make.
    """
    def builder(*, subject, attribute, date, template_id, oracle):
        return (taint.render(subject=subject, attribute=attribute, date=date,
                             template_id=template_id) + " zzzunrelatedzzz")
    assert builder is not taint._clean
    assert taint.evaluate(builder, [ITEM])["passes"]


# --- 2B residual overlap ----------------------------------------------------

def test_a_token_is_credited_to_exactly_one_provenance(residual, taint):
    query = taint.render(subject="Illinois", attribute="Illinois state",
                         date="2023-02-10", template_id="as_of")
    parts = residual.label(query, subject="Illinois", attribute="Illinois state",
                           date="2023-02-10", literals=taint.LITERALS)
    seen: set[str] = set()
    for group in parts.values():
        assert not (group & seen), "a token was credited twice"
        seen |= group
    assert seen == residual.tokens(query)


def test_structured_intent_is_reported_and_the_residual_is_the_gate(residual, taint):
    """v7's 0.750 raw overlap decomposes to structured intent, residual 0."""
    query = taint.render(subject=ITEM["subject"], attribute=ITEM["attribute"],
                         date=ITEM["date"], template_id="current")
    oracle = f"{ITEM['subject']} is a coin. {ITEM['oracle']}"
    m = residual.measure(query, oracle, subject=ITEM["subject"], attribute=ITEM["attribute"],
                         date=ITEM["date"], literals=taint.LITERALS)
    assert m["raw_overlap"] > 0.0
    assert m["structured_intent_overlap"] == pytest.approx(m["raw_overlap"])
    assert m["residual_overlap"] == 0.0


def test_an_injected_oracle_token_raises_the_residual_above_the_frozen_ceiling(residual, taint):
    query = taint.render(subject=ITEM["subject"], attribute=ITEM["attribute"],
                         date=ITEM["date"], template_id="current")
    m = residual.measure(f"{query} philadelphia", ITEM["oracle"], subject=ITEM["subject"],
                         attribute=ITEM["attribute"], date=ITEM["date"],
                         literals=taint.LITERALS)
    assert m["residual_overlap"] > residual.ceiling_from(0.0)


@pytest.mark.parametrize(("value", "expected"), [(0.0, 0.05), (0.01, 0.1), (0.05, 0.1),
                                                 (0.06, 0.15), (0.5, 0.55)])
def test_the_calibration_rule_is_a_function_of_the_distribution(residual, value, expected):
    """Round up to the next 0.05, plus 0.05 headroom -- not a hand-picked number."""
    assert residual.ceiling_from(value) == pytest.approx(expected)


# --- 1/3 entity-conditioned baseline gate -----------------------------------

def test_a_numeric_value_is_not_matched_by_the_retrieval_tokenizer(entity):
    """Why the value matcher is used for identity and the retrieval one is not.

    `validate_baseline.tokens` requires a leading letter, so a year tokenizes to
    the empty set --- and the empty set is a subset of every unit, which makes
    both oracle localization and separability degenerate.
    """
    base = load("research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/validate_baseline.py",
                "t_base_v8")
    v7gate = load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/gate_question_set_v7.py",
        "t_v7gate_v8")
    assert set(base.tokens("1925")) == set()
    assert set(base.tokens("1925")) <= set(base.tokens("wholly unrelated prose"))
    assert v7gate.value_tokens("1925") == {"1925"}
    assert not v7gate.value_tokens("1925") <= v7gate.value_tokens("wholly unrelated prose")


def test_entropy_is_zero_for_one_candidate_and_one_for_an_indistinguishable_field(entity):
    assert entity.normalized_entropy([1.0]) == 0.0
    assert entity.normalized_entropy([2.0, 2.0, 2.0]) == pytest.approx(1.0)


def test_a_decided_ranking_has_lower_entropy_than_a_flat_one(entity):
    assert entity.normalized_entropy([9.0, 0.1, 0.1]) < entity.normalized_entropy(
        [1.0, 0.9, 1.1])


def test_every_gate_bound_carries_a_stated_reason(entity):
    for name, bound in entity.BOUNDS.items():
        assert bound["why"].strip(), f"{name} has no rationale"


def test_the_retired_metric_is_declared_with_its_reason_not_silently_dropped(entity):
    """§3 requires the reason on the record, because a quiet swap reads as a fix."""
    source = (EXP / "scripts/entity_conditioned_gate_v8.py").read_text(encoding="utf-8")
    assert "RETIRED_FROM_PRIMARY_GATE" in source
    assert "same_document_top_1_share" in source


def test_the_separability_amendment_is_flagged_as_made_after_a_failure(entity):
    """A construct correction made after seeing FAIL is declared, not absorbed."""
    bound = entity.BOUNDS["before_after_separable_share"]
    assert bound["amended_after_a_development_failure"] is True
    assert "not a threshold relaxed" in bound["amendment"]
    assert "new_value_absent_from_before_revision_share" in entity.BOUNDS


def test_the_displaced_measurement_is_still_reported_and_is_not_gated(entity):
    kept = entity.BOUNDS["new_value_absent_from_before_revision_share"]
    assert kept["floor"] is None and kept["ceiling"] is None
    assert "REPORTED, NOT GATED" in kept["why"]


# --- receipts ---------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "v8-structural-taint-gate-dev-2026-08-19.json",
    "v8-residual-calibration-dev-2026-08-19.json",
    "v8-entity-conditioned-gate-dev-2026-08-19.json",
])
def test_every_v8_development_receipt_declares_it_is_not_an_endpoint(name):
    import json
    path = EXP / "receipts" / name
    if not path.exists():
        pytest.skip(f"{name} has not been produced")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["run_class"] == "DEVELOPMENT_ONLY"
    assert receipt["external_gpu_cost_usd"] == 0.0
    assert receipt["network_access"] is False


# --- v8 question generator admission ----------------------------------------

@pytest.fixture(scope="module")
def gen() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/build_question_set_v8.py",
        "t_gen_v8")


@pytest.fixture(scope="module")
def value_tokens() -> Any:
    return load(
        "research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/gate_question_set_v7.py",
        "t_v7gate_gen").value_tokens


@pytest.mark.parametrize(("old", "new"), [
    ("Sir", "[[Sir]]"),
    ("[[George M. Bibb|George Bibb]]", "[[George M. Bibb]]"),
    ("Canada <br /> United States", "[[Canada]]<br />[[United States]]"),
    ("[[Suzuka Circuit]]<br>[[Japan]]", "[[Suzuka Circuit]]<br />[[Japan]]"),
])
def test_a_markup_only_edit_is_not_a_revision_sensitive_question(gen, value_tokens, old, new):
    """The v7 defect: raw wikitext differs, the answer does not."""
    assert old != new
    assert gen.classify_change(old, new, value_tokens) == "MARKUP_ONLY"


@pytest.mark.parametrize(("old", "new"), [
    ("1,200", "1,450"),
    ("[[Chicago]], Illinois", "[[Boston]], Massachusetts"),
    ("Democratic", "Republican"),
    ("1925", "1926"),
])
def test_a_real_value_change_is_still_admitted(gen, value_tokens, old, new):
    """The filter must not reject everything -- that would be worse than v7."""
    assert gen.classify_change(old, new, value_tokens) == "SEMANTIC"


def test_an_identical_value_is_unchanged_not_markup_only(gen, value_tokens):
    assert gen.classify_change("[[Sir]]", "[[Sir]]", value_tokens) == "UNCHANGED"


def test_the_admission_control_separates_and_uses_observed_shapes(gen, value_tokens):
    control = gen.admission_control(value_tokens)
    assert control["separates"]
    assert control["markup_only_all_rejected"] and control["semantic_all_admitted"]
    assert control["markup_only_cases"] and control["semantic_cases"]


def test_the_development_run_reproduces_the_96_markup_only_exclusions():
    """Two independent code paths agree on the same 96, or the number is not a fact."""
    import json
    path = EXP / "receipts/question-set-v8-dev-2026-08-19.json"
    if not path.exists():
        pytest.skip("the v8 development question set has not been built")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["run_class"] == "DEVELOPMENT_ONLY"
    assert receipt["excluded"]["markup_only_primary_eligible"] == 96
    assert receipt["admission_control"]["separates"]
    assert receipt["counts_by_class"]["revision_sensitive"] == 194


def test_a_holdout_build_refuses_a_corpus_that_overlaps_development_titles(gen, tmp_path):
    """§6: the holdout is untouched, checked against the seal rather than recalled."""
    import json
    seal = EXP / "receipts/v7-development-seal-2026-08-19.json"
    if not seal.exists():
        pytest.skip("the v7 seal is not present")
    titles = (json.loads(seal.read_text(encoding="utf-8"))
              .get("development_titles_excluded_from_v8", {}).get("titles") or [])
    if not titles:
        pytest.skip("the seal records no development titles")
    acq = tmp_path / "acq.json"
    acq.write_text(json.dumps({"records": [{"title": titles[0]}]}), encoding="utf-8")
    out = tmp_path / "out.json"
    argv = ["build_question_set_v8.py", "--acquisition", str(acq), "--output", str(out),
            "--run-class", "HOLDOUT_CONFIRMATORY"]
    old = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit) as excinfo:
            gen.main()
    finally:
        sys.argv = old
    assert "development data" in str(excinfo.value)
    assert not out.exists()
