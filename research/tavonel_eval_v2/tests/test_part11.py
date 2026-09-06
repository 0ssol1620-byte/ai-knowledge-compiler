"""The model endpoint — frozen before the run, and the run that did not start.

The preflight failed, and a failing preflight is the one place where tests earn
the most: it is exactly when there is pressure to widen a pattern, raise a
budget or lower a floor and call the result a pass. Each test below pins one
thing that was not moved.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(NS / "endpoint"))
sys.path.insert(0, str(NS / "tools"))

PROTOCOL = NS / "protocols" / "MODEL_ENDPOINT_V1.yaml"
PREFLIGHT = sorted((NS / "receipts").glob("model-endpoint-preflight--*.json"))
LEDGER = NS / "incident_ledger.md"

#: The protocol as frozen before the first model input was materialized.
PROTOCOL_SHA = "sha256:2b0487c41076fee00dfc9eae6265881c0d6918a9a66f5337b35130000b1172f4"


@pytest.fixture(scope="module")
def receipt() -> dict:
    assert PREFLIGHT, "no preflight receipt"
    return json.loads(PREFLIGHT[-1].read_text(encoding="utf-8"))


# --- the protocol was frozen first --------------------------------------------


def test_the_protocol_is_byte_identical_to_what_was_frozen() -> None:
    digest = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    assert "sha256:" + digest == PROTOCOL_SHA


def test_the_receipt_names_the_protocol_it_ran_under(receipt: dict) -> None:
    assert receipt["provenance"]["protocol_sha256"] == PROTOCOL_SHA


def test_the_preflight_ran_exactly_once(receipt: dict) -> None:
    assert len(PREFLIGHT) == 1, [path.name for path in PREFLIGHT]


# --- the verdict, unmodified ---------------------------------------------------


def test_the_verdict_is_fail(receipt: dict) -> None:
    assert receipt["verdict"] == "FAIL"
    failed = {name for name, gate in receipt["gates"].items() if not gate["passed"]}
    assert failed == {"G_ME1_COHORT_FLOOR", "G_ME1_TRUNCATION"}


def test_no_gpu_was_started(receipt: dict) -> None:
    assert receipt["gpu_seconds"] == 0
    assert receipt["estimated_cost_usd"] == 0.0
    assert receipt["gates"]["G_ME1_NO_GPU_YET"]["passed"] is True
    assert not sorted((NS / "receipts").glob("model-endpoint-stage*.json"))


def test_the_floor_was_not_lowered_to_meet_the_cohort(receipt: dict) -> None:
    gate = receipt["gates"]["G_ME1_COHORT_FLOOR"]
    assert gate["floor"] == 190
    assert gate["final_cohort"] == 10
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "cohort_floor" in text
    assert "at least 190 Q1 questions" in text


def test_the_token_budget_was_not_raised_to_rescue_truncation(receipt: dict) -> None:
    from context_builder import TOTAL_PROMPT_TOKENS  # noqa: PLC0415

    assert TOTAL_PROMPT_TOKENS == 4096
    assert receipt["context_budget"]["total_prompt_tokens"] == 4096
    assert receipt["gates"]["G_ME1_TRUNCATION"]["ceiling"] == 0.25


def test_the_cohort_collapsed_on_distinguishability_not_on_machinery(receipt: dict) -> None:
    """The instrument gates all pass. What fails is the corpus."""
    reasons = receipt["excluded_by_reason"]
    assert reasons["VALUES_NOT_DISTINGUISHABLE"] == 274
    assert reasons["TARGET_EVIDENCE_LOST_TO_TRUNCATION"] == 12
    for name in (
        "G_ME1_MODEL_PINNED",
        "G_ME1_PROMPT_CARRIES_NO_ARM_LABEL",
        "G_ME1_SCHEDULE_BALANCED",
        "G_ME1_SCORER_CONTROLS",
        "G_ME1_CONTEXT_VALIDITY",
        "G_ME1_INPUTS_MATERIALIZED",
    ):
        assert receipt["gates"][name]["passed"] is True, name


def test_local_coverage_completeness_is_not_endpoint_eligibility(receipt: dict) -> None:
    """296 questions were locally complete. 10 can be answered right or wrong."""
    assert receipt["totals"]["candidates_regenerated"] == 296
    assert receipt["totals"]["final_frozen_cohort"] == 10


# --- the model pin -------------------------------------------------------------


def test_the_tokenizer_is_the_attested_one_by_digest_and_by_behaviour(receipt: dict) -> None:
    model = receipt["model"]
    assert model["revision"] == "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9"
    assert model["tokenizer_file_sha256"] == model["tokenizer_file_sha256_attested"]
    assert model["chat_template_matches"] is True
    assert model["behaviour_probe"]["observed_tokens"] == 20
    assert model["behaviour_probe"]["matches"] is True


def test_the_library_reporting_difference_is_recorded_not_hidden(receipt: dict) -> None:
    model = receipt["model"]
    assert model["vocab_size_here"] != model["vocab_size_attested"]
    assert model["tokenizer_class_here"] != model["tokenizer_class_attested"]
    assert "file digest and the behaviour probe" in model["vocab_size_note"]


# --- the scorer ----------------------------------------------------------------


def test_the_scorer_controls_all_pass_in_three_directions() -> None:
    from value_scorer import run_controls  # noqa: PLC0415

    got = run_controls()
    assert got["all_agree"] is True
    assert got["three_directions"]["passed"] is True
    assert len(got["results"]) == 8


def test_both_and_no_match_are_failures() -> None:
    from value_scorer import BOTH, NO_MATCH, classify  # noqa: PLC0415

    recited = classify("It was 35, now 50.", ["50"], ["35"])
    assert recited["class"] == BOTH
    assert recited["primary_success"] is False
    refused = classify("not stated", ["50"], ["35"])
    assert refused["class"] == NO_MATCH
    assert refused["primary_success"] is False


def test_a_marker_must_look_like_a_value_not_merely_differ() -> None:
    """The pattern set is what the cohort collapse depended on; widening it would
    have cleared the floor and destroyed the endpoint at the same time."""
    from value_scorer import markers  # noqa: PLC0415

    prose = markers("the agency shall promptly notify", "the agency must notify without delay")
    assert prose["distinguishable"] is False
    assert "NO_DISTINGUISHING_CURRENT_VALUE" in prose["reasons"]

    valued = markers("the limit is 50 ppm", "the limit is 35 ppm")
    assert valued["distinguishable"] is True
    assert valued["current"] == ["50"]
    assert valued["superseded"] == ["35"]


def test_normalisation_does_not_merge_genuinely_different_values() -> None:
    from value_scorer import SUPERSEDED_ONLY, classify  # noqa: PLC0415

    assert classify("42.05 USD", ["42.50"], ["42.05"])["class"] == SUPERSEDED_ONLY


def test_a_substring_is_not_a_value_match() -> None:
    from value_scorer import NO_MATCH, classify  # noqa: PLC0415

    assert classify("the identifier is 4200", ["42"], ["35"])["class"] == NO_MATCH


# --- the prompt and the schedule ------------------------------------------------


def test_the_prompt_template_carries_no_arm_revision_or_currency_label() -> None:
    from context_builder import SYSTEM_PROMPT, prompt_carries_no_arm_label  # noqa: PLC0415

    got = prompt_carries_no_arm_label(SYSTEM_PROMPT, "")
    assert got["clean"] is True
    assert got["found"] == []


def test_the_question_frame_is_constant_across_questions() -> None:
    from context_builder import QUESTION_FRAME, prompt_parts  # noqa: PLC0415

    first = prompt_parts("alpha", ["[1] p\nx"])[1]
    second = prompt_parts("beta", ["[1] p\nx"])[1]
    assert first.replace("alpha", "Q") == second.replace("beta", "Q")
    assert "{query}" in QUESTION_FRAME


def test_the_arms_are_not_run_as_four_blocks(receipt: dict) -> None:
    from context_builder import ARMS, schedule, schedule_balance  # noqa: PLC0415

    got = schedule(["q%03d" % index for index in range(40)])
    balance = schedule_balance(got)
    assert balance["balanced"] is True
    assert balance["max_position_spread"] == 0
    for order in got.values():
        assert sorted(order) == sorted(ARMS)
    assert receipt["gates"]["G_ME1_SCHEDULE_BALANCED"]["passed"] is True


def test_the_schedule_depends_on_ids_alone() -> None:
    from context_builder import schedule  # noqa: PLC0415

    ids = ["q%03d" % index for index in range(12)]
    assert schedule(ids) == schedule(list(reversed(ids)))


def test_nothing_is_re_ranked_or_summarised_to_fit_the_budget() -> None:
    from context_builder import fit_to_budget  # noqa: PLC0415

    atoms = [{"atom_id": str(i), "path": "p", "text": "word " * 40} for i in range(20)]
    got = fit_to_budget("q", atoms, lambda system, user: len((system + user).split()), budget=200)
    kept = len(got["context_atom_ids"])
    assert got["context_atom_ids"] == [atom["atom_id"] for atom in atoms[:kept]]
    assert got["truncated"] is True
    assert got["dropped_count"] == 20 - kept


def test_the_append_only_arm_is_exempt_from_the_context_validity_filter(receipt: dict) -> None:
    """The two revisions crowding each other out is the intervention."""
    gate = receipt["gates"]["G_ME1_CONTEXT_VALIDITY"]
    assert "append_only_stale_capable" not in gate["single_revision_arms"]
    assert "part of the intervention" in gate["append_only_excluded_because"]


# --- terminology and claim boundary ---------------------------------------------


def test_the_corpus_is_not_called_untouched(receipt: dict) -> None:
    assert receipt["split"] == "MODEL-ENDPOINT CONFIRMATORY — MODEL OUTCOMES UNSEEN"
    assert "not an untouched confirmatory corpus" in receipt["split_note"]
    assert "untouched confirmatory corpus" in PROTOCOL.read_text(encoding="utf-8")


def test_the_assay_sensitivity_gate_carries_no_p_value(receipt: dict) -> None:
    gate = receipt["assay_sensitivity_gate"]
    assert gate["p_value"] is None
    assert gate["kind"].startswith("VALIDITY GATE")
    assert "never sequentially" in gate["evaluated"]
    assert ">= 0.15" in gate["predicate"]
    assert "materially" not in gate["predicate"]


def test_exactly_one_hypothesis_test_is_declared(receipt: dict) -> None:
    primary = json.dumps(receipt["primary_test"])
    assert "compiled_current" in primary
    assert "append_only_stale_capable" in primary
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "no_other_hypothesis_tests" in text
    assert "forbidden: any additional p-value" in text


def test_the_programme_status_did_not_advance(receipt: dict) -> None:
    assert receipt["programme_status"].startswith("PARTIAL")
    assert "ENDPOINT NOT YET ESTABLISHED" in receipt["programme_status"]


def test_the_failure_is_recorded_in_the_ledger() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    assert "INC-V2-017" in text
    assert "MODEL_ENDPOINT_INFEASIBLE_ON_THIS_COHORT" in text
    assert "The scorer was **not** loosened" in text
