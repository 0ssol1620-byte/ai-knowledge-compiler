"""P4i — the run that cleared both gates, and the reasons it is believable.

296 eligible Q1 against a floor of 190 is a good number, and a good number is
exactly when the record has to be checkable. Every test here answers one form of
"did you get there by moving something you promised not to move".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "acquisition"))
sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "tools"))

RESULT = sorted((NS / "receipts").glob("p4i--*.json"))
COHORT = sorted((NS / "receipts").glob("p4i-cohort-manifest--*.json"))
PROTOCOL = NS / "protocols" / "P4i_cohort_expansion.yaml"
P4H = NS / "protocols" / "P4h_cohort_expansion.yaml"
PROPOSAL_V1 = NS / "MODEL_STUDY_PROPOSAL_2026-08-22.md"
PROPOSAL_V2 = NS / "MODEL_STUDY_PROPOSAL_v2_2026-08-22.md"

#: The instrument that produced 174 on P4g.
COMPOSITE_174 = "sha256:0ed844f6eb83e8b342f6790a772099c8ebec4c80c525cdf721b59a54df10fe2a"


@pytest.fixture(scope="module")
def result() -> dict:
    assert RESULT, "no P4i result receipt"
    return json.loads(RESULT[-1].read_text(encoding="utf-8"))


# --- the figure ---------------------------------------------------------------


def test_the_cohort_was_scored_exactly_once(result: dict) -> None:
    """Two runs died before writing. Neither produced a figure, so neither counts."""
    assert len(RESULT) == 1, [path.name for path in RESULT]
    assert result["gates"]["G_P4I_SCORED_ONCE"]["passed"] is True


def test_the_recorded_figure(result: dict) -> None:
    assert result["totals"]["locally_complete_q1"] == 296
    assert result["totals"]["q1_questions"] == 1564
    assert result["totals"]["questions_scored"] == 5686
    assert result["cohort"]["documents"] == 511


def test_every_gate_passed(result: dict) -> None:
    assert result["verdict"] == "PASS"
    failed = {n: g for n, g in result["gates"].items() if not g["passed"]}
    assert not failed, failed


def test_breadth_and_power_are_separate_gates(result: dict) -> None:
    """INC-V2-016: welding a document count to a question count is what broke P4h."""
    breadth = result["gates"]["G_P4I_BREADTH"]
    assert breadth["documents_admitted"] == 511
    assert breadth["breadth_floor"] == 400
    assert breadth["acquisition_target"] == 550
    assert breadth["passed"] is True

    decision = result["decision_gate"]
    assert decision["hard_minimum_eligible_Q1"] == 190
    assert decision["eligible_Q1"] == 296
    assert decision["meets_floor"] is True


def test_falling_short_of_the_acquisition_target_did_not_fail_the_gate(result: dict) -> None:
    """511 < 550, and that is explicitly not a failure."""
    breadth = result["gates"]["G_P4I_BREADTH"]
    assert breadth["documents_admitted"] < breadth["acquisition_target"]
    assert breadth["passed"] is True


def test_the_spread_requirement_is_met_by_more_than_one_family(result: dict) -> None:
    assert result["decision_gate"]["spread_requirement_met"] is True
    assert len(result["decision_gate"]["families_with_eligible_Q1"]) >= 2


# --- nothing was moved to get there -------------------------------------------


def test_the_instrument_is_the_one_that_produced_174(result: dict) -> None:
    identity = result["instrument_identity"]
    assert identity["composite"] == COMPOSITE_174
    assert identity["matches"] is True
    assert result["gates"]["G_P4I_INSTRUMENT_UNCHANGED"]["passed"] is True


def test_there_is_no_escape_clause_on_the_identity_gate(result: dict) -> None:
    """P4g needed one for INC-V2-013. P4i must not carry the habit forward."""
    gate = result["gates"]["G_P4I_INSTRUMENT_UNCHANGED"]
    assert "explained_by" not in gate
    assert gate["passed"] is True


def test_class_and_style_are_still_unresolved() -> None:
    from markup_policy import EXTERNAL_DEPENDENCY, UNRESOLVED  # noqa: PLC0415
    from markup_semantics import blocks_completeness, classify_attribute  # noqa: PLC0415

    for name in ("class", "style"):
        got = classify_attribute(name)
        assert got["state"] == UNRESOLVED, name
        assert got["facet"] == EXTERNAL_DEPENDENCY
        assert blocks_completeness(got["state"])


def test_class_still_blocks_in_the_scored_cohort(result: dict) -> None:
    """It is not merely declared unresolved; it is still refusing questions."""
    assert result["unresolved_drivers"]["attr:class"] == 2629
    assert result["witness_failures_by_reason"]["UNRESOLVED_SOURCE_FACT_IN_CLOSURE"] == 2716


def test_the_quota_was_not_reweighted_toward_the_families_that_score(result: dict) -> None:
    import sources_p4i  # noqa: PLC0415

    quota = sources_p4i.FAMILY_QUOTA
    assert (quota["git_docs"], quota["regulation_ecfr"]) == (165, 165)
    assert (quota["encyclopedia_wikipedia"], quota["sec_edgar"]) == (165, 55)
    assert result["gates"]["G_P4I_MIX_NOT_REWEIGHTED"]["passed"] is True


def test_the_quotas_are_never_called_p4g_realized_proportions(result: dict) -> None:
    import sources_p4i  # noqa: PLC0415

    assert "NOT P4g's realized proportions" in result["cohort"]["family_quota_is"]
    assert sources_p4i.P4G_ADMITTED_MIX["git_docs"] == 98
    assert sources_p4i.P4G_ADMITTED_MIX["encyclopedia_wikipedia"] == 114


def test_a_family_that_yielded_nothing_is_still_in_the_record(result: dict) -> None:
    assert result["cohort"]["family_counts"]["sec_edgar"] == 16
    assert result["q1_by_family"]["sec_edgar"] == 56
    assert result["locally_complete_q1_by_family"].get("sec_edgar", 0) == 0
    assert result["gates"]["G_P4I_NO_NARROWING"]["passed"] is True


def test_position_is_still_not_the_limitation(result: dict) -> None:
    assert result["location_unverifiable_spans"] == 0


# --- acquisition accounting ---------------------------------------------------


def test_every_rejection_carries_a_declared_code(result: dict) -> None:
    import sources_p4i  # noqa: PLC0415

    manifest = json.loads(
        (NS / "artifacts" / "development" / "p4i_cohort.json").read_text(encoding="utf-8")
    )
    declared = set(sources_p4i.ADMISSION_FAILURE_CODES)
    assert {item["code"] for item in manifest["rejected"]} <= declared
    assert result["gates"]["G_P4I_ADMISSION_ACCOUNTED"]["passed"] is True


def test_source_exhaustion_is_distinguishable_from_a_broken_fetcher(result: dict) -> None:
    """The whole point of the codes: scarcity and failure look identical in a total."""
    by_code = result["cohort"]["rejected_by_code"]
    assert by_code["SOURCE_EXHAUSTION"] == 4490
    assert by_code["PAYLOAD_UNAVAILABLE"] == 6
    assert by_code["LISTING_FAILED"] == 3


def test_the_candidate_lists_and_reserve_order_were_frozen_first(result: dict) -> None:
    import sources_p4i  # noqa: PLC0415

    order = sources_p4i.CONSUMPTION_ORDER
    assert order["frozen_before_any_fetch"] is True
    assert order["frozen_before_any_eligibility_result"] is True
    for family in ("git_docs", "regulation_ecfr", "encyclopedia_wikipedia", "sec_edgar"):
        assert order[family], family
    assert result["gates"]["G_P4I_SELECTION_BLIND"]["passed"] is True


def test_over_selection_truncates_by_declared_order_not_by_outcome() -> None:
    import sources_p4i  # noqa: PLC0415

    over = sources_p4i.OVER_SELECTION
    assert over["factor"] == 1.5
    assert "declared order" in over["truncation"]
    assert "no coverage, eligibility or retrieval figure exists" in over["not_by_outcome"]


def test_the_cohort_receipt_agrees_with_the_result(result: dict) -> None:
    assert COHORT
    body = json.loads(COHORT[-1].read_text(encoding="utf-8"))
    assert body["document_count"] == result["cohort"]["documents"] == 511
    assert body["meets_breadth_floor"] is True
    assert body["gpu_seconds"] == 0


# --- P4h, and the cost of the run ---------------------------------------------


def test_p4h_was_preserved_unmodified_and_never_executed() -> None:
    """It produced no result, so superseding it discards no evidence."""
    assert "G_P4H_SCALE" in P4H.read_text(encoding="utf-8")
    assert not sorted((NS / "receipts").glob("p4h--*.json"))
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "supersedes: P4h_cohort_expansion" in text
    assert "SUPERSEDED_BEFORE_EXECUTION" in text
    assert "INC-V2-016" in text


def test_nothing_was_spent_and_no_gpu_was_authorised(result: dict) -> None:
    assert result["gpu_seconds"] == 0
    assert result["estimated_cost_usd"] == 0.0
    assert result["gpu_authorised_by_this_result"] is False
    assert "never executed before founder approval" in result["decision_gate"]["gpu"]


def test_the_outcome_is_a_proposal_not_a_launch(result: dict) -> None:
    assert result["decision_gate"]["outcome"] == "RESUBMIT_MODEL_STUDY_PROPOSAL_WITH_REAL_NUMBERS"


# --- the proposal -------------------------------------------------------------


def test_the_v1_proposal_is_preserved_with_its_do_not_run_recommendation() -> None:
    text = PROPOSAL_V1.read_text(encoding="utf-8")
    assert "This design should not be run as written" in text
    assert "eligible and Q1** | **5**" in text


def test_the_v2_proposal_carries_the_real_numbers_and_asks_rather_than_acts() -> None:
    text = PROPOSAL_V2.read_text(encoding="utf-8")
    assert "AWAITING FOUNDER APPROVAL" in text
    assert "No GPU has run" in text
    assert "296" in text and "511" in text
    assert "0.9977" in text
    assert COMPOSITE_174 in text


def test_the_v2_proposal_does_not_lower_anything() -> None:
    text = PROPOSAL_V2.read_text(encoding="utf-8")
    assert "hard minimum eligible Q1** | **190**" in text
    assert "not lowered to 174" in text
    assert "attr:class" in text


def test_exact_power_at_the_reported_n() -> None:
    from mcnemar_power import power, required_n  # noqa: PLC0415

    assert required_n() == 173
    assert round(power(190), 4) == 0.967
    assert round(power(296), 4) == 0.9977


def test_the_predecessors_were_not_rescored(result: dict) -> None:
    assert set(result["predecessors_not_rescored"]) >= {"P0d", "P4e", "P4g", "SOURCE_LOCALITY_V2"}
    assert len(sorted((NS / "receipts").glob("p4g--*.json"))) == 1
    assert result["programme_status"].startswith("PARTIAL")
