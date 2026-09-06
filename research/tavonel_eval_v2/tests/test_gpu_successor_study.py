"""Tests for `protocols/GPU_SUCCESSOR_STUDY_V1.yaml` and `paper/PROVENANCE_PAPER_SECTION.md`.

No network, no GPU. Seven things this file guards:

1. the protocol parses as YAML and carries every section it declares
2. it cannot be read as authorising a run without a V2 PASS — the precondition
   exists and is a hard gate, not a suggestion
3. the cost-cap arithmetic refuses an over-cap configuration
4. eligibility does NOT require a between-revision value transition
5. the closed exact-value endpoint (`MODEL_ENDPOINT_V1` / `STOP-V2-005`) is
   named as forbidden
6. the proposed claim rows in the paper section parse as YAML and satisfy
   `build_claim_matrix.REQUIRED` / `build_claim_matrix.SPLITS`, and contain no
   forbidden phrase from `CLAIM_MATRIX.yaml`
7. no sentence in the paper section asserts an unproven positive without a
   provisional marker
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import gpu_successor_preflight as gsp  # noqa: E402

PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V1.yaml"
PAPER_SECTION = NS / "paper" / "PROVENANCE_PAPER_SECTION.md"
CLAIM_MATRIX = NS / "paper" / "CLAIM_MATRIX.yaml"


def _load_protocol() -> dict[str, Any]:
    return yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))


def _forbidden_phrases_from_matrix() -> list[tuple[str, str]]:
    matrix = yaml.safe_load(CLAIM_MATRIX.read_text(encoding="utf-8"))
    return [
        (entry["id"], phrase)
        for entry in matrix["forbidden_claims"]
        for phrase in entry["phrases"]
    ]


# ---------------------------------------------------------------------------
# 1. the protocol parses and carries every section it declares
# ---------------------------------------------------------------------------


def test_protocol_file_exists_and_parses_as_yaml():
    assert PROTOCOL.exists()
    body = _load_protocol()
    assert isinstance(body, dict)


REQUIRED_TOP_LEVEL_SECTIONS = (
    "schema",
    "protocol_id",
    "study_id",
    "version",
    "authored",
    "status",
    "relates_to",
    "agreement_with_preflight",
    "preconditions",
    "model",
    "runtime",
    "arms_axis",
    "arms",
    "eligibility",
    "cohort",
    "cost_cap",
    "scoring",
    "anti_fitting",
    "forbidden",
    "authorization",
)


@pytest.mark.parametrize("section", REQUIRED_TOP_LEVEL_SECTIONS)
def test_protocol_declares_every_required_section(section):
    body = _load_protocol()
    assert section in body, f"protocol is missing declared section {section!r}"


def test_protocol_status_is_draft_not_frozen():
    """The workstream does not freeze its own protocol. The orchestrator does."""
    body = _load_protocol()
    assert body["status"] == "DRAFT_NOT_FROZEN"


def test_protocol_id_and_study_id_are_distinct_and_both_present():
    body = _load_protocol()
    assert body["protocol_id"] == "GPU_SUCCESSOR_STUDY_V1"
    assert body["study_id"]


# ---------------------------------------------------------------------------
# 2. cannot be read as authorising a run without a V2 PASS
# ---------------------------------------------------------------------------


def test_preconditions_gate_on_a_fresh_held_out_source_fact_ir_pass():
    body = _load_protocol()
    gate_ids = [gate["id"] for gate in body["preconditions"]["gates"]]
    assert "G_SUCC_HELD_OUT_SOURCE_FACT_IR_PASS" in gate_ids
    held_out_gate = next(
        gate
        for gate in body["preconditions"]["gates"]
        if gate["id"] == "G_SUCC_HELD_OUT_SOURCE_FACT_IR_PASS"
    )
    assert "PASS" in held_out_gate["requires"]
    assert "held_out" in held_out_gate["requires"]
    assert "BLOCK" in held_out_gate["on_failure"]


def test_preconditions_gate_on_the_preflight_itself_being_ready():
    body = _load_protocol()
    gate_ids = [gate["id"] for gate in body["preconditions"]["gates"]]
    assert "G_SUCC_PREFLIGHT_READY" in gate_ids


def test_no_gate_reports_ready_or_pass_when_absence_is_declared():
    """Structural check: every precondition gate's on_failure is a BLOCK, not a
    conditional pass. A protocol with a gate that can be silently skipped is
    not really gated."""
    body = _load_protocol()
    for gate in body["preconditions"]["gates"]:
        assert "on_failure" in gate
        assert "BLOCK" in gate["on_failure"], f"{gate['id']} does not hard-block on failure"


def test_authorizes_no_run_by_itself_even_if_gates_pass():
    body = _load_protocol()
    assert "authorizes_no_run_by_itself" in body
    text = body["authorizes_no_run_by_itself"].casefold()
    assert "frozen" in text
    assert "draft" in text


def test_source_fact_ir_heldout_v1_is_explicitly_excluded_as_a_satisfying_receipt():
    """SOURCE_FACT_IR_HELDOUT_V1 itself is FAIL and frozen never-to-be-rescored.
    The protocol must not let its own presence look like the gate is satisfied."""
    body = _load_protocol()
    relates = body["relates_to"]["SOURCE_FACT_IR_HELDOUT_V1"]
    assert "FAIL" in relates["state"]
    assert "never" in relates["state"].casefold() or "never" in relates.get("rule", "").casefold()
    held_out_gate = next(
        gate
        for gate in body["preconditions"]["gates"]
        if gate["id"] == "G_SUCC_HELD_OUT_SOURCE_FACT_IR_PASS"
    )
    assert "`SOURCE_FACT_IR_HELDOUT_V1`" in held_out_gate["on_failure"]
    assert "FAIL" in held_out_gate["on_failure"]
    #: V2 joined V1 on that list: SFI2 is frozen, FAIL and spent, and the GPU
    #: route's retired `sfi2-native-provenance` stem search could never have
    #: succeeded. Neither predecessor may satisfy this gate.
    assert "`SOURCE_FACT_IR_HELDOUT_V2`" in held_out_gate["on_failure"]


def test_the_actual_preflight_tool_still_blocks_with_no_acceptance(tmp_path):
    """This protocol claims G_SUCC_PREFLIGHT_READY composes the real preflight's
    acceptance gates. Prove the real tool still enforces them, so the claim is
    not just a comment.

    Two gates now, not one, and neither substitutes for the other: the SFI3
    acceptance says the study passed, the four-link acceptance says the cohort
    about to run is followable. Naming no receipt at all is a hard block rather
    than a reason to go looking -- the retired stem search is not replaced by
    another search.
    """
    result = gsp.run(
        manifest=tmp_path / "no-such-manifest.json",
        model_pin={},
        runtime_image_digest="repo/image@sha256:" + "0" * 64,
    )
    assert result["verdict"] == "BLOCKED"
    assert "G_GSP_SFI3_ACCEPTANCE_PASS" in result["blocking_gates"]
    assert "G_GSP_FOUR_LINK_ACCEPTANCE_PASS" in result["blocking_gates"]


# ---------------------------------------------------------------------------
# 3. cost-cap arithmetic refuses an over-cap configuration
# ---------------------------------------------------------------------------


def _cost(cohort_size: int, *, params: dict[str, Any]) -> dict[str, float]:
    """Reimplements the formula this protocol declares in `cost_cap.formula`,
    independently of `gpu_successor_preflight.estimate_cost`, so a defect
    shared between the two would not hide from this test."""
    arms = params["arms"]
    repeats = params["determinism_repeats"]
    tokens_per_item = params["prompt_tokens"] + params["max_new_tokens"]
    total_calls = cohort_size * arms * repeats
    total_tokens = total_calls * tokens_per_item
    seconds = total_tokens / params["declared_throughput_tokens_per_second"]
    hours = seconds / 3600.0
    cost_usd = hours * params["declared_gpu_hourly_rate_usd"]
    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "hours": hours,
        "usd": cost_usd,
    }


def test_cost_cap_declared_parameters_are_present():
    body = _load_protocol()
    params = body["cost_cap"]["declared_parameters"]
    for key in (
        "arms",
        "determinism_repeats",
        "prompt_tokens",
        "max_new_tokens",
        "declared_throughput_tokens_per_second",
        "declared_gpu_hourly_rate_usd",
    ):
        assert key in params


def test_floor_cohort_fits_under_the_cap():
    body = _load_protocol()
    floor = body["cohort"]["floor"]
    params = body["cost_cap"]["declared_parameters"]
    cap_hours = body["cost_cap"]["hard_cap_gpu_hours"]
    cap_usd = body["cost_cap"]["hard_cap_usd"]
    result = _cost(floor, params=params)
    assert result["hours"] <= cap_hours
    assert result["usd"] <= cap_usd


def test_worked_examples_in_the_protocol_recompute_correctly():
    """The protocol shows its arithmetic in `worked_examples`. Recompute each
    one independently and check the protocol did not just assert a number."""
    body = _load_protocol()
    params = body["cost_cap"]["declared_parameters"]
    for example in body["cost_cap"]["worked_examples"]:
        result = _cost(example["cohort_size"], params=params)
        if "total_calls" in example:
            assert result["total_calls"] == example["total_calls"]
        if "total_tokens" in example:
            assert result["total_tokens"] == example["total_tokens"]
        if "estimated_gpu_hours" in example:
            assert result["hours"] == pytest.approx(example["estimated_gpu_hours"], abs=1e-6)
        if "estimated_cost_usd" in example:
            assert result["usd"] == pytest.approx(example["estimated_cost_usd"], abs=1e-6)


def test_an_over_cap_worked_example_exists_and_is_marked_refused():
    body = _load_protocol()
    examples = body["cost_cap"]["worked_examples"]
    over_cap = [example for example in examples if example.get("within_cap") is False]
    assert over_cap, "the protocol must include at least one over-cap example"
    for example in over_cap:
        params = body["cost_cap"]["declared_parameters"]
        result = _cost(example["cohort_size"], params=params)
        cap_hours = body["cost_cap"]["hard_cap_gpu_hours"]
        cap_usd = body["cost_cap"]["hard_cap_usd"]
        exceeds = result["hours"] > cap_hours or result["usd"] > cap_usd
        assert exceeds, "an example marked within_cap: false must actually exceed a cap"


def test_cost_cap_matches_gpu_successor_preflight_module_constants():
    """The protocol's declared cap must not contradict the live preflight tool."""
    body = _load_protocol()
    assert body["cost_cap"]["hard_cap_gpu_hours"] == pytest.approx(gsp.CAP_GPU_HOURS)
    assert body["cost_cap"]["hard_cap_usd"] == pytest.approx(gsp.CAP_USD)
    params = body["cost_cap"]["declared_parameters"]
    assert params["determinism_repeats"] == gsp.DETERMINISM_REPEATS
    assert params["prompt_tokens"] == gsp.ESTIMATED_PROMPT_TOKENS
    assert params["max_new_tokens"] == gsp.MAX_NEW_TOKENS


def test_real_preflight_estimate_cost_agrees_with_the_protocols_own_arithmetic():
    """Cross-check against the actual `gpu_successor_preflight.estimate_cost`
    function at the protocol's declared floor, so 'agrees with the preflight,
    not contradicts it' is verified against live code, not restated."""
    body = _load_protocol()
    floor = body["cohort"]["floor"]
    real = gsp.estimate_cost(cohort_size=floor)
    declared = _cost(floor, params=body["cost_cap"]["declared_parameters"])
    assert real["estimated_gpu_hours"] == pytest.approx(declared["hours"], abs=1e-6)
    assert real["estimated_cost_usd"] == pytest.approx(declared["usd"], abs=1e-6)
    assert real["within_cap"] is True


def test_refusal_rule_is_stated_as_arithmetic_not_discretion():
    body = _load_protocol()
    text = body["cost_cap"]["refusal_is_arithmetic_not_judgement"].casefold()
    assert "within_hours_cap" in text
    assert "within_usd_cap" in text


# ---------------------------------------------------------------------------
# 4. eligibility does not require a between-revision value transition
# ---------------------------------------------------------------------------


def test_eligibility_declares_no_value_transition_required():
    body = _load_protocol()
    eligibility = body["eligibility"]
    never = " ".join(eligibility["never_required"]).casefold()
    assert "value transition" in never or "differ" in never
    assert "value transition" in never


def test_eligibility_all_required_contains_no_between_revision_value_comparison():
    """Structural check on the positive predicate: none of the required
    eligibility conditions may name a value comparison ACROSS two revisions."""
    body = _load_protocol()
    forbidden_fragments = ("value moved", "value differs between", "value transition")
    for condition in body["eligibility"]["all_required"]:
        lowered = condition.casefold()
        for fragment in forbidden_fragments:
            assert fragment not in lowered, (
                f"eligibility condition smuggles a value transition: {condition!r}"
            )


def test_eligibility_agrees_with_preflight_flag_name_and_value():
    body = _load_protocol()
    agreement = body["agreement_with_preflight"]["requires_value_transition_between_revisions"]
    assert agreement["this_protocol"] is False
    assert gsp.REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS is False
    assert agreement["this_protocol"] == gsp.REQUIRES_VALUE_TRANSITION_BETWEEN_REVISIONS


def test_eligible_kinds_agree_with_preflight_and_do_not_grow_beyond_it():
    body = _load_protocol()
    declared = set(body["agreement_with_preflight"]["eligible_kinds"]["this_protocol"])
    assert declared == set(gsp.ELIGIBLE_KINDS)


def test_cohort_floor_agrees_with_preflight_constant():
    body = _load_protocol()
    assert body["cohort"]["floor"] == gsp.COHORT_FLOOR
    assert body["agreement_with_preflight"]["cohort_floor"]["this_protocol"] == gsp.COHORT_FLOOR


def test_why_this_avoids_scarcity_names_the_closed_studys_actual_numbers():
    """Guards against a rewritten section quietly losing the specific evidence
    this design's scarcity-avoidance argument rests on."""
    body = _load_protocol()
    text = body["eligibility"]["why_this_avoids_the_closed_endpoints_scarcity"]
    assert "2,271" in text
    assert "three" in text or "3" in text


# ---------------------------------------------------------------------------
# 5. the closed exact-value endpoint is named as forbidden
# ---------------------------------------------------------------------------


def test_forbidden_block_names_the_closed_endpoint_and_stop_record():
    body = _load_protocol()
    forbidden = body["forbidden"]
    closed = forbidden["closed_exact_value_endpoint"]
    assert closed["protocol"] == "MODEL_ENDPOINT_V1"
    assert closed["stop_record"] == "STOP-V2-005"


def test_forbidden_block_agrees_with_preflight_forbidden_constants():
    body = _load_protocol()
    agreement = body["agreement_with_preflight"]
    assert agreement["forbidden_endpoint_id"]["this_protocol"] == gsp.FORBIDDEN_ENDPOINT_ID
    assert agreement["forbidden_stop_record"]["this_protocol"] == gsp.FORBIDDEN_STOP_RECORD


def test_this_study_does_not_revive_the_closed_endpoints_scorer_classes():
    """Import the real closed scorer's classes rather than trusting a copy."""
    sys.path.insert(0, str(NS / "endpoint"))
    import value_scorer

    body = _load_protocol()
    scorer_classes = set(body["scoring"]["scorer_classes"])
    assert scorer_classes.isdisjoint(set(value_scorer.CLASSES))
    assert scorer_classes.isdisjoint(set(gsp.FORBIDDEN_SCORER_CLASSES))


def test_no_successor_cohort_to_chase_the_190_floor_is_quoted():
    body = _load_protocol()
    text = body["forbidden"]["no_successor_cohort_to_chase_the_190_floor"]
    assert "190" in text
    assert "chase" in text.casefold()


def test_forbidden_phrases_list_overlaps_the_shared_matrix_vocabulary():
    body = _load_protocol()
    protocol_phrases = {phrase.casefold() for phrase in body["forbidden"]["phrases"]}
    matrix_phrases = {phrase.casefold() for _id, phrase in _forbidden_phrases_from_matrix()}
    assert protocol_phrases & matrix_phrases, (
        "the protocol's forbidden phrase list should share vocabulary with "
        "CLAIM_MATRIX.yaml's forbidden_claims, not invent a disconnected list"
    )


def test_authorization_neither_verdict_permits_reviving_the_closed_endpoint():
    body = _load_protocol()
    neither = " ".join(body["authorization"]["neither_pass_nor_fail_authorises"]).casefold()
    assert "model_endpoint_v1" in neither


def test_authorization_pass_and_fail_and_neither_are_all_declared():
    body = _load_protocol()
    authorization = body["authorization"]
    for key in ("pass_authorises", "fail_authorises", "neither_pass_nor_fail_authorises"):
        assert key in authorization
        assert authorization[key], f"{key} must not be empty"


def test_fail_is_a_reportable_finding_not_a_reason_to_rerun():
    body = _load_protocol()
    fail_text = " ".join(body["authorization"]["fail_authorises"]).casefold()
    assert "held-out finding" in fail_text or "held out finding" in fail_text
    rerun_clause = body["authorization"][
        "a_fail_does_not_authorize_widening_eligibility_and_rerunning"
    ]
    assert "fitting" in rerun_clause.casefold()


# ---------------------------------------------------------------------------
# 6. proposed claim rows parse and satisfy build_claim_matrix.py
# ---------------------------------------------------------------------------


def _extract_proposed_rows() -> list[dict[str, Any]]:
    text = PAPER_SECTION.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)\n```", text, re.S)
    assert blocks, "no fenced yaml block found in the paper section"
    rows: list[dict[str, Any]] = []
    for block in blocks:
        parsed = yaml.safe_load(block)
        assert "claims" in parsed
        rows.extend(parsed["claims"])
    return rows


def test_proposed_rows_parse_and_start_at_c24():
    rows = _extract_proposed_rows()
    assert len(rows) >= 1
    ids = [row["id"] for row in rows]
    assert ids[0] == "C-24"
    # ids are sequential C-24, C-25, ... with no gap or repeat
    numbers = [int(identifier.split("-")[1]) for identifier in ids]
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def test_proposed_rows_carry_every_field_build_claim_matrix_requires():
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        missing = [field for field in matrix.REQUIRED if field not in row]
        assert not missing, f"{row.get('id')} missing {missing}"


def test_proposed_rows_declare_a_split_matrix_recognises():
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        assert row["split"] in matrix.SPLITS, f"{row['id']} has undeclared split {row['split']!r}"


def test_proposed_rows_use_the_pending_receipt_established_status_pairing():
    """build_claim_matrix.py requires this exact pairing for anything unproven,
    and every proposed row here is unproven."""
    import build_claim_matrix as matrix

    rows = _extract_proposed_rows()
    for row in rows:
        assert row["receipt"] == matrix.PENDING
        assert row["status"] == "NOT_YET_ESTABLISHED"


def test_proposed_rows_wording_contains_no_forbidden_phrase():
    forbidden = _forbidden_phrases_from_matrix()
    rows = _extract_proposed_rows()
    for row in rows:
        lowered = str(row["wording"]).casefold()
        hits = [(fid, phrase) for fid, phrase in forbidden if phrase.casefold() in lowered]
        assert not hits, f"{row['id']} wording contains forbidden phrase(s): {hits}"


def test_proposed_rows_are_either_unclaimed_or_adopted_unchanged():
    """Adoption is the success case, not a collision.

    This was written as "no proposed id may already exist", which was right for
    the moment it was written and wrong one step later: the orchestrator adopted
    C-24 to C-27 into the matrix, and the test then failed *because the proposal
    had been accepted*. That is a test bound to a moment rather than to a
    property, the same shape as the three stale assertions the V1 integration
    rewrote.

    The property is: an id is either not in the matrix yet, or it is in the
    matrix bound to the same protocol the proposal named. What must never happen
    is a proposed row and an adopted row of the same id describing different
    studies.
    """
    matrix_body = yaml.safe_load(CLAIM_MATRIX.read_text(encoding="utf-8"))
    adopted = {claim["id"]: claim for claim in matrix_body["claims"]}
    for row in _extract_proposed_rows():
        found = adopted.get(row["id"])
        if found is None:
            continue
        assert found["protocol"] == row["protocol"], (
            f"{row['id']} is adopted in CLAIM_MATRIX.yaml under protocol "
            f"{found['protocol']!r} but proposed here under {row['protocol']!r}"
        )


def test_proposed_rows_protocol_field_names_the_v2_successor_not_the_frozen_v1():
    rows = _extract_proposed_rows()
    for row in rows:
        assert row["protocol"] != "SOURCE_FACT_IR_HELDOUT_V1", (
            f"{row['id']} must not bind to the frozen FAIL protocol, which must "
            "never be rescored"
        )


# ---------------------------------------------------------------------------
# 7. no unmarked unproven-positive assertion in the paper section's own prose
# ---------------------------------------------------------------------------

#: Phrases that would assert the fresh held-out study's own result, positively,
#: as though it had already happened. None of these may appear in prose (a
#: sentence outside a fenced code block) anywhere in this section, marker or
#: not — mirroring the sibling SOURCE_FACT_IR paper section's guard, which
#: writes around the sentence shape entirely rather than hedging it.
_COMPLETION_TRIGGERS = (
    "the repair passed",
    "sfh1 passed",
    "sfh1 was repeated and passed",
    "is source-faithful",
    "resolves the failure",
    "confirms the repair",
    "proves the repair",
    "the repair works",
    "establishes source faithfulness",
    "source_fact_ir passed",
    "source_fact_ir is proven",
    "source_fact_ir holds",
    "the span-map eliminates",
    "the span-map has eliminated",
    "v2 passed",
    "v2 has passed",
)


def _prose_paragraphs(text: str) -> list[str]:
    """Paragraphs with fenced code blocks removed. The proposed YAML rows are
    explicitly NOT_YET_ESTABLISHED / PENDING and are not prose assertions."""
    without_code = re.sub(r"```.*?```", "", text, flags=re.S)
    return [block for block in without_code.split("\n\n") if block.strip()]


def test_no_completion_trigger_phrase_appears_in_prose_at_all():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    for paragraph in _prose_paragraphs(text):
        lowered = paragraph.casefold()
        for trigger in _COMPLETION_TRIGGERS:
            assert trigger not in lowered, (
                f"unmarked completion claim {trigger!r} found in paragraph: {paragraph[:200]!r}"
            )


def test_checker_actually_catches_a_bad_sentence():
    """Prove the guard above is not vacuous."""
    bad_text = (
        "Some heading\n\n"
        "The span-map eliminates every retrospective search failure on the "
        "fresh cohort and the repair passed cleanly.\n\n"
        "A second, unrelated paragraph.\n"
    )
    paragraphs = _prose_paragraphs(bad_text)
    caught = any(
        trigger in paragraph.casefold()
        for paragraph in paragraphs
        for trigger in _COMPLETION_TRIGGERS
    )
    assert caught, "the checker failed to catch a deliberately bad sentence"


def test_provisional_marker_present_before_the_forward_looking_section():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    assert text.count("PROVISIONAL") >= 2
    forward_looking = text.index("What the fresh held-out study must show")
    nearest_marker_before = text.rfind("PROVISIONAL", 0, forward_looking + 400)
    assert nearest_marker_before != -1
    assert nearest_marker_before < forward_looking + 400


def test_paper_section_declares_ip_gate_closed_and_internal_only():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    assert "INTERNAL DRAFT" in text
    assert "IP gate CLOSED" in text
    assert "No arXiv" in text


def test_paper_section_explains_the_category_error_not_a_tuning_problem():
    text = PAPER_SECTION.read_text(encoding="utf-8").casefold()
    assert "category error" in text
    assert "tuning" in text


def test_paper_section_explains_insert_is_the_only_unsourced_path():
    text = PAPER_SECTION.read_text(encoding="utf-8")
    assert "`insert`" in text
    assert "only" in text.casefold()
    assert "deliberate" in text.casefold()


def test_paper_section_covers_what_a_fail_would_mean():
    text = PAPER_SECTION.read_text(encoding="utf-8").casefold()
    assert "what a fail would mean" in text
