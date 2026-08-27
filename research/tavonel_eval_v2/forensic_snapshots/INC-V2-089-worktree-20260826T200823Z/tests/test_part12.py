"""Route A — the value-bearing cohort, frozen before it was allowed to look.

The pressure this file guards against is specific. The previous preflight failed
for want of 180 questions, and every rule that would have supplied them cheaply
is written down here as a thing that did not move: the scorer's patterns, the
token budget, the 190 floor, the declared family shares, the two property
shapes. A cohort that reaches the floor by relaxing one of these would be a
worse result than the failure it replaced.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "acquisition"))
sys.path.insert(0, str(NS / "endpoint"))
sys.path.insert(0, str(NS / "tools"))

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V1.yaml"
FREEZE = sorted((NS / "receipts").glob("value-bearing-cohort-v1-freeze--*.json"))
EXTRACTOR = sorted((NS / "receipts").glob("value-fact-freeze--*.json"))
LEDGER = NS / "incident_ledger.md"

PROTOCOL_SHA = "sha256:a4a2b568d3d04b475ea9edccf28f588c6d349852e960a55f608500c049d0e68e"

#: The scorer as MODEL_ENDPOINT_V1 froze it, before Route A existed.
SCORER_SHA = "sha256:" + hashlib.sha256(
    (NS / "endpoint" / "value_scorer.py").read_bytes()
).hexdigest()


@pytest.fixture(scope="module")
def freeze() -> dict:
    assert FREEZE, "the protocol was not frozen"
    return json.loads(FREEZE[-1].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def extractor() -> dict:
    assert EXTRACTOR, "the extractor was not frozen"
    return json.loads(EXTRACTOR[-1].read_text(encoding="utf-8"))


# --- frozen before anything was measured --------------------------------------


def test_the_protocol_matches_its_freeze_receipt(freeze: dict) -> None:
    digest = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    assert "sha256:" + digest == PROTOCOL_SHA
    assert freeze["protocol_sha256"] == PROTOCOL_SHA
    assert freeze["frozen_before_any_result"] is True


def test_the_extractor_was_frozen_before_any_candidate_list(extractor: dict) -> None:
    assert extractor["frozen_before_any_fresh_candidate_list"] is True
    assert extractor["frozen_before_any_acquisition"] is True
    assert extractor["verdict"] == "FROZEN"


def test_the_extractor_controls_pass_in_all_three_directions(extractor: dict) -> None:
    gate = extractor["gates"]["G_VBC1_VALUE_FACT_CONTROLS"]
    assert gate["passed"] is True
    assert (gate["positive"], gate["negative"], gate["adversarial"]) == (True, True, True)
    assert gate["count"] >= 13


# --- the scorer did not move ---------------------------------------------------


def test_the_scorer_is_byte_identical_to_the_frozen_one(extractor: dict) -> None:
    assert extractor["component_sha256"]["value_scorer"] == SCORER_SHA
    assert extractor["gates"]["G_VBC1_SCORER_UNCHANGED"]["passed"] is True


def test_no_value_kind_was_added_to_reach_the_floor() -> None:
    from value_fact import VALUE_KINDS  # noqa: PLC0415

    assert set(VALUE_KINDS) == {
        "iso_date",
        "numeric",
        "version_chain",
        "percentage",
        "currency",
        "identifier",
    }


def test_the_scorer_controls_still_pass() -> None:
    from value_scorer import run_controls  # noqa: PLC0415

    assert run_controls()["all_agree"] is True


def test_the_protocol_forbids_widening_the_patterns() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "widening the value patterns to reach 190" in text
    assert "BYTE-IDENTICAL TO THE FROZEN VERSION" in text


# --- nothing else was relaxed either -------------------------------------------


def test_the_floor_and_the_budget_are_unchanged() -> None:
    from context_builder import TOTAL_PROMPT_TOKENS  # noqa: PLC0415

    text = PROTOCOL.read_text(encoding="utf-8")
    assert TOTAL_PROMPT_TOKENS == 4096
    assert "hard_floor: 190" in text
    assert "total_prompt_tokens: 4096" in text
    assert "raising 4096 to rescue a preflight" in text


def test_the_soft_target_is_not_a_statistical_floor() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "soft_target: 250-300" in text
    assert "soft_target_is_not_a_statistical_floor: true" in text


def test_the_family_shares_were_declared_before_acquisition() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "git_docs: 0.40" in text
    assert "explicitly_not_based_on" in text
    assert "P4i's eligibility yield per family" in text


def test_the_taxonomy_has_exactly_the_two_declared_shapes(extractor: dict) -> None:
    from value_fact import PROPERTY_TAXONOMY  # noqa: PLC0415

    shapes = {entry["shape"] for entry in PROPERTY_TAXONOMY}
    assert shapes == {"table_row_by_column", "key_value_row"}
    assert {entry["shape"] for entry in extractor["property_taxonomy"]} == shapes


# --- INC-V2-018: question identity ---------------------------------------------


def test_the_question_id_is_content_addressed_over_the_declared_inputs() -> None:
    from value_fact import question_id  # noqa: PLC0415

    base = ("git_docs", "doc:a", "v1", "v2", "atom:1", "Flags/(3)#1", "Q1_REVISED_VALUE", "prop:x")
    same = question_id(*base)
    assert same == question_id(*base)
    for position in range(len(base)):
        changed = list(base)
        changed[position] = changed[position] + "!"
        assert question_id(*changed) != same, position


def test_the_property_id_is_what_separates_a_repeated_anchor_path() -> None:
    """The exact collision INC-V2-018 recorded: one anchor, two properties."""
    from value_fact import question_id  # noqa: PLC0415

    common = ("regulation_ecfr", "doc:a", "v1", "v2", "atom:1", "§ 50.2/(3)#1", "Q1_REVISED_VALUE")
    assert question_id(*common, "prop:one") != question_id(*common, "prop:two")


def test_one_duplicate_stops_the_run() -> None:
    from value_fact import injective  # noqa: PLC0415

    assert injective(["a", "b", "c"])["injective"] is True
    got = injective(["a", "b", "a"])
    assert got["injective"] is False
    assert got["duplicates"] == ["a"]
    assert (got["rows"], got["unique"]) == (3, 2)


def test_the_property_id_survives_a_row_moving() -> None:
    from value_fact import property_id  # noqa: PLC0415

    first = property_id("doc:a", ["Flags"], "--timeout", "Default")
    assert first == property_id("doc:a", ["Flags"], "--timeout", "Default")
    assert first != property_id("doc:a", ["Limits"], "--timeout", "Default")


# --- the extractor refuses what it must ----------------------------------------


def test_a_renamed_key_is_not_a_changed_value() -> None:
    from value_fact import PROPERTY_NOT_STABLE, value_facts  # noqa: PLC0415

    before = "| Option | Default |\n| --- | --- |\n| --timeout | 30 |\n"
    after = "| Option | Default |\n| --- | --- |\n| --request-timeout | 60 |\n"
    got = value_facts("doc:a", before, after, ".md")
    assert not got["facts"]
    assert any(row["code"] == PROPERTY_NOT_STABLE for row in got["rejected"])


def test_a_cell_holding_two_values_binds_none() -> None:
    from value_fact import sole_value  # noqa: PLC0415

    assert sole_value("5 to 15") is None
    assert sole_value("between 5 and 10") is None
    assert sole_value("2.15.0") == ("version_chain", "2.15.0")


def test_dominance_is_span_containment_not_string_containment() -> None:
    from value_fact import dominant_tokens  # noqa: PLC0415

    assert dominant_tokens("2.14.1") == {"2.14.1"}
    assert dominant_tokens("5 to 15") == {"5", "15"}


def test_a_label_carrying_a_value_is_refused() -> None:
    from value_fact import label_is_usable  # noqa: PLC0415

    assert label_is_usable("--query.lookback-delta") is True
    assert label_is_usable("Limit for tier 2") is False


def test_the_generated_question_never_states_a_value() -> None:
    from value_fact import question_is_blind_to_the_value, question_query  # noqa: PLC0415

    fact = {
        "property_label": "--query.lookback-delta",
        "column_label": "Default",
        "current_value": "9",
        "superseded_value": "5",
    }
    query = question_query(fact)
    assert "9" not in query and "5" not in query
    assert question_is_blind_to_the_value(query, fact)["blind"] is True


def test_an_atom_with_a_second_changed_number_is_refused() -> None:
    from value_fact import atom_contrast_is_single  # noqa: PLC0415

    fact = {"current_value": "9", "superseded_value": "5"}
    noisy = atom_contrast_is_single(fact, "lookback 9 retention 30", "lookback 5 retention 15")
    clean = atom_contrast_is_single(fact, "lookback is 9", "lookback is 5")
    assert noisy["single_contrast"] is False
    assert clean["single_contrast"] is True


# --- freshness ------------------------------------------------------------------


def test_the_probe_lists_are_disjoint_from_p4i() -> None:
    from fetch_vbc1_probe import disjoint_from_p4i  # noqa: PLC0415

    got = disjoint_from_p4i()
    assert got["disjoint"] is True, got["overlaps"]


def test_the_probe_declares_itself_burned() -> None:
    from sources_vbc1_probe import PROBE  # noqa: PLC0415

    assert PROBE["burned_after_use"] is True
    assert PROBE["not_the_confirmatory_cohort"] is True
    assert "P4i" in PROBE["disjoint_from"]


def test_the_protocol_excludes_the_ten_survivors_by_name() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "ten_survivors_excluded" in text
    assert "G_VBC1_FRESH_LINEAGES" in text


# --- the record -----------------------------------------------------------------


def test_the_identity_defect_is_in_the_ledger() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    assert "INC-V2-018" in text
    assert "G_VBC1_QUESTION_ID_INJECTIVE" in text
    assert "PRIOR RESULTS UNMODIFIED" in text


def test_the_prior_results_were_not_recomputed() -> None:
    """296 stays 296 and the failed preflight stays failed."""
    p4i = json.loads(sorted((NS / "receipts").glob("p4i--*.json"))[-1].read_text(encoding="utf-8"))
    assert p4i["totals"]["locally_complete_q1"] == 296
    preflight = json.loads(
        sorted((NS / "receipts").glob("model-endpoint-preflight--*.json"))[-1].read_text(
            encoding="utf-8"
        )
    )
    assert preflight["verdict"] == "FAIL"
    assert preflight["totals"]["final_frozen_cohort"] == 10


def test_route_b_is_not_a_rescue() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "NOT DISCARDED, NOT A RESCUE" in text
    assert "separate secondary study" in " ".join(text.split())
    assert "semantic judge or" in text


def test_no_gpu_and_no_spend_anywhere_in_route_a(extractor: dict, freeze: dict) -> None:
    assert extractor["gpu_seconds"] == 0
    assert extractor["estimated_cost_usd"] == 0.0
    assert not sorted((NS / "receipts").glob("*stage-1*.json"))


# --- the probe -------------------------------------------------------------------

PROBE_RESULT = sorted((NS / "receipts").glob("vbc1-probe-result--*.json"))


@pytest.fixture(scope="module")
def probe() -> dict:
    assert PROBE_RESULT, "the probe did not run"
    return json.loads(PROBE_RESULT[-1].read_text(encoding="utf-8"))


def test_the_probe_measured_zero_and_the_zero_is_preserved(probe: dict) -> None:
    assert probe["question_count"] == 0
    assert probe["cohort"]["documents"] == 45
    assert probe["questions_by_family"] == {}


def test_the_zero_is_not_an_extractor_failure(probe: dict) -> None:
    """174 properties were read and paired. They simply did not move."""
    excluded = probe["excluded_by_reason"]
    assert excluded["VALUE_UNCHANGED"] == 154
    assert excluded["PROPERTY_NOT_STABLE"] == 20
    assert excluded["VALUE_UNCHANGED"] + excluded["PROPERTY_NOT_STABLE"] == 174


def test_nothing_reached_the_coverage_step(probe: dict) -> None:
    """The binding constraint is upstream of everything the last two failures were about."""
    for reason in ("COVERAGE_INCOMPLETE", "ATOM_NOT_LOCATED", "AMBIGUOUS_VALUE_FACT"):
        assert probe["excluded_by_reason"].get(reason, 0) == 0, reason


def test_the_injectivity_gate_holds_on_the_probe(probe: dict) -> None:
    assert probe["question_id_injective"]["injective"] is True


def test_the_probe_is_recorded_as_burned(probe: dict) -> None:
    assert probe["probe"]["burned"] is True
    assert probe["probe"]["not_the_confirmatory_cohort"] is True


def test_the_yield_figure_gates_nothing(probe: dict) -> None:
    assert probe["yield"]["questions_per_document"] == 0.0
    assert "gates nothing" in probe["yield"]["note"]


def test_no_confirmatory_acquisition_was_started() -> None:
    assert not sorted((NS / "receipts").glob("vbc1-cohort--*.json"))
    assert not sorted((NS / "receipts").glob("vbc1-preflight--*.json"))


def test_the_probe_finding_is_in_the_ledger() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    assert "INC-V2-019" in text
    assert "revision-pair sampling" in text
    assert "It is not an extractor failure" in text
