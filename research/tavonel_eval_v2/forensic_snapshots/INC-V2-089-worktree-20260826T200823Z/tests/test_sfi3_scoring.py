"""The SFI3 scorer's refusals, tested as refusals.

Two of these tests exist because of specific failures that already happened and
were not caught by the tests written to catch them.

`test_a_missing_block_raises_rather_than_reporting_skipped` is INC-V2-035. The
SFI2 scorer read the E5 block under the endpoint's protocol name, found nothing,
and reported `SKIPPED_NEVER_EXERCISED` — "no judged supported pair could have
exhibited it" — while 14 confirmed escapes sat in the receipt beside it. The seam
test written to catch that accepted SKIPPED as a valid outcome, so the mismatch
satisfied its own gate.

`test_e8_fails_when_a_required_stage_was_never_observed` is INC-V2-036. An
endpoint watched at one stage and unwatched at another reports a clean number
while leaving the path it was created to guard unobserved.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import score_sfi3  # noqa: E402
from score_sfi1 import FAILED, MET, SKIPPED  # noqa: E402


def _block(*, exercising: int = 10, violations: int = 0, names: tuple = ()) -> dict:
    return {
        "pairs_that_could_have_exhibited": exercising,
        "gate_power": bool(exercising),
        "confirmed": list(names),
        "divergent": list(names),
        "carried": list(names),
        "pairs_with_confirmed_escape": violations,
        "pairs_divergent": violations,
        "pairs_with_unexecuted_carry": violations,
        "pairs_with_silent_disappearance": violations,
        "silent": list(names),
    }


def _executor(**overrides) -> dict:
    summary = {
        "E5_confirmed_selective_stale_escape": _block(),
        "E6_exact_selective_vs_clean_equivalence": _block(),
        "E8_rebuild_required_carried_without_execution": {
            **_block(),
            "stages_checked": list(score_sfi3.STAGES_REQUIRED),
        },
        "E9_detected_change_without_rebuild_request": _block(),
    }
    summary.update(overrides)
    return summary


# --------------------------------------------------------------------------
# the contract between the scorer and the executor


def test_every_block_this_scorer_reads_is_declared_in_one_table():
    """No key is read from an executor summary except through EXECUTOR_BLOCKS.

    A scorer that reaches into a summary in one place and declares its keys in
    another is how the endpoint name and the block name drifted apart unnoticed.
    """
    declared = {summary_key for _, summary_key, _, _ in score_sfi3.EXECUTOR_BLOCKS}
    assert declared == set(_executor())
    endpoints = {endpoint for endpoint, _, _, _ in score_sfi3.EXECUTOR_BLOCKS}
    assert endpoints == set(score_sfi3.EXECUTOR_ENDPOINTS)


def test_the_endpoint_name_and_the_block_name_are_allowed_to_differ():
    """And the table is what reconciles them.

    E5 and E8 name a property ("no confirmed escape"); the executor names a
    measurement ("confirmed escape"). E6's two names coincide by accident, which
    is precisely why assuming they all coincided went unnoticed for a whole run.
    """
    pairs = {endpoint: key for endpoint, key, _, _ in score_sfi3.EXECUTOR_BLOCKS}
    assert pairs["E5_no_confirmed_selective_stale_escape"] != (
        "E5_no_confirmed_selective_stale_escape"
    )
    assert pairs["E8_no_rebuild_required_artifact_carried_without_execution"] != (
        "E8_no_rebuild_required_artifact_carried_without_execution"
    )
    assert pairs["E6_exact_selective_vs_clean_equivalence"] == (
        "E6_exact_selective_vs_clean_equivalence"
    )


@pytest.mark.parametrize(
    "missing",
    [key for _, key, _, _ in score_sfi3.EXECUTOR_BLOCKS],
)
def test_a_missing_block_raises_rather_than_reporting_skipped(missing):
    """INC-V2-035. A key the executor does not write is a contract break.

    Reporting it as SKIPPED is a scorer describing its own bug as a property of
    the cohort — and SKIPPED is a plausible-looking outcome that no reader would
    question, which is what let it survive a scored run.
    """
    summary = _executor()
    del summary[missing]
    with pytest.raises(score_sfi3.ContractBroken) as raised:
        score_sfi3.score_executor(summary)
    assert missing in str(raised.value)


@pytest.mark.parametrize(
    "missing", ["pairs_that_could_have_exhibited", "gate_power", "pairs_with_confirmed_escape"]
)
def test_a_missing_key_inside_a_block_raises_rather_than_defaulting(missing):
    """Defaulting an absent count to zero is the same defect one level deeper.

    `block.get(key, 0)` would turn a contract break into a clean MET, which is
    strictly worse than the false SKIPPED that was actually shipped.
    """
    summary = _executor()
    del summary["E5_confirmed_selective_stale_escape"][missing]
    with pytest.raises(score_sfi3.ContractBroken):
        score_sfi3.score_executor(summary)


# --------------------------------------------------------------------------
# gate power


def test_an_endpoint_nothing_could_have_violated_is_skipped_not_met():
    summary = _executor(E5_confirmed_selective_stale_escape=_block(exercising=0))
    verdicts = score_sfi3.score_executor(summary)
    assert verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] == SKIPPED


def test_gate_power_false_is_skipped_even_when_the_denominator_is_positive():
    """A denominator the executor itself declines to vouch for is not power."""
    block = _block(exercising=40)
    block["gate_power"] = False
    verdicts = score_sfi3.score_executor(_executor(E6_exact_selective_vs_clean_equivalence=block))
    assert verdicts["E6_exact_selective_vs_clean_equivalence"]["verdict"] == SKIPPED


def test_violations_are_reported_with_their_named_cases():
    """A count cannot be checked against a rebuild; a named artifact can."""
    summary = _executor(
        E5_confirmed_selective_stale_escape=_block(violations=2, names=("a.md", "b.md"))
    )
    row = score_sfi3.score_executor(summary)["E5_no_confirmed_selective_stale_escape"]
    assert row["verdict"] == FAILED
    assert row["cases"] == ["a.md", "b.md"]


# --------------------------------------------------------------------------
# E8 and its two stages


def test_e8_clean_is_a_veto_clearance_and_never_a_met():
    """Founder ruling, option (b). E8 credits nothing when clean.

    MET is a claim that an endpoint was put at risk and survived. E8 was not put at
    risk — its seam is structurally closed — so reporting MET would manufacture
    positive evidence from an instrument that could not have fired.
    """
    row = score_sfi3.score_executor(_executor())[score_sfi3.SAFETY_VETO_ENDPOINT]
    assert row["verdict"] == score_sfi3.VETO_CLEAR
    assert row["verdict"] != MET


def test_e8_never_reports_skipped_however_powerless_it_is():
    """SKIPPED would fail the study for a reason that says nothing about the system."""
    block = {
        **_block(exercising=0),
        "stages_checked": list(score_sfi3.STAGES_REQUIRED),
    }
    row = score_sfi3.score_executor(
        _executor(E8_rebuild_required_carried_without_execution=block)
    )[score_sfi3.SAFETY_VETO_ENDPOINT]
    assert row["verdict"] == score_sfi3.VETO_CLEAR
    assert row["natural_gate_power"] is False


def test_e8_violations_still_veto():
    block = {
        **_block(violations=1, names=("stale.md",)),
        "stages_checked": list(score_sfi3.STAGES_REQUIRED),
    }
    row = score_sfi3.score_executor(
        _executor(E8_rebuild_required_carried_without_execution=block)
    )[score_sfi3.SAFETY_VETO_ENDPOINT]
    assert row["verdict"] == FAILED


def test_e8_is_not_in_the_pass_contributing_endpoints():
    assert score_sfi3.SAFETY_VETO_ENDPOINT not in score_sfi3.PRIMARY_ENDPOINTS
    assert set(score_sfi3.PRIMARY_ENDPOINTS) | {score_sfi3.SAFETY_VETO_ENDPOINT} == set(
        score_sfi3.ENDPOINTS
    )
    assert len(score_sfi3.PRIMARY_ENDPOINTS) == 8


@pytest.mark.parametrize("dropped", score_sfi3.STAGES_REQUIRED)
def test_e8_fails_when_a_required_stage_was_never_observed(dropped):
    """INC-V2-036, in the form the scorer can still catch.

    Not SKIPPED — the endpoint WAS exercised, at one stage, and reported clean.
    Calling that met would certify a path nothing looked at, and the second stage
    exists specifically so one scheduler defect cannot reach ACTIVE state.
    """
    block = {
        **_block(),
        "stages_checked": [s for s in score_sfi3.STAGES_REQUIRED if s != dropped],
    }
    row = score_sfi3.score_executor(
        _executor(E8_rebuild_required_carried_without_execution=block)
    )["E8_no_rebuild_required_artifact_carried_without_execution"]
    assert row["verdict"] == FAILED
    assert dropped in row["stages_missing"]


def test_e8_with_no_stages_at_all_fails_rather_than_passing_silently():
    block = {**_block(), "stages_checked": []}
    row = score_sfi3.score_executor(
        _executor(E8_rebuild_required_carried_without_execution=block)
    )["E8_no_rebuild_required_artifact_carried_without_execution"]
    assert row["verdict"] == FAILED


def test_both_stages_are_required_and_the_list_is_not_empty():
    """A guard whose required-stage list could be emptied is not a guard."""
    assert set(score_sfi3.STAGES_REQUIRED) == {"post_execution", "pre_activation"}


# --------------------------------------------------------------------------
# the verdict rule


def test_a_skipped_endpoint_fails_the_study_exactly_as_a_violated_one_does():
    """Zero violations everywhere is still not a PASS if an endpoint went unexercised.

    This drives `verdict_for`, the same function `main` uses. A test that
    restated the rule would pass while the shipped rule said something else.
    """
    rows = [{"family": f"f{i % 3}", **_fact_row()} for i in range(220)]
    verdicts = score_sfi3.score(
        rows, _executor(E5_confirmed_selective_stale_escape=_block(exercising=0))
    )
    assert verdicts["E5_no_confirmed_selective_stale_escape"]["verdict"] == SKIPPED

    failed = [n for n, r in verdicts.items() if r["verdict"] == FAILED]
    skipped = [n for n, r in verdicts.items() if r["verdict"] == SKIPPED]
    gates = score_sfi3.cohort_gates(rows)
    assert not failed, "no endpoint was violated in this fixture"
    assert gates["pairs_met"] and gates["families_met"]
    assert (
        score_sfi3.verdict_for(
            failed, skipped, [], veto_violations=0, instrumentation_power_proven=True
        )
        == "FAIL"
    )


def _verdict(failed=(), skipped=(), short=(), *, veto=0, power=True) -> str:
    return score_sfi3.verdict_for(
        list(failed),
        list(skipped),
        list(short),
        veto_violations=veto,
        instrumentation_power_proven=power,
    )


def test_a_clean_fully_exercised_cohort_is_the_only_thing_that_passes():
    """The counterpart. Without it, the rule above could be `always FAIL`."""
    assert _verdict() == "PASS"
    assert _verdict(failed=["E2..."]) == "FAIL"
    assert _verdict(short=["pairs"]) == "FAIL"


def test_an_e8_violation_vetoes_an_otherwise_perfect_study():
    """Not tradeable. No number of met endpoints buys back a stale carry."""
    assert _verdict(veto=1) == "FAIL"


def test_an_unproven_e8_instrument_fails_even_with_zero_violations():
    """A detector nobody made fire, reporting zero, is not a safety result.

    E8's clean readings carry no power of their own, so the only thing that makes
    a zero meaningful is prior proof that the instrument CAN report non-zero.
    """
    assert _verdict(power=False) == "FAIL"
    assert _verdict(power=True) == "PASS"


def test_the_veto_arguments_are_required_so_they_cannot_be_forgotten():
    """The cheapest way to pass a gate must never be to forget it exists."""
    import inspect

    signature = inspect.signature(score_sfi3.verdict_for)
    for name in ("veto_violations", "instrumentation_power_proven"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_e5_e6_and_e9_may_not_be_skipped():
    assert set(score_sfi3.MAY_NOT_BE_SKIPPED) == {
        "E5_no_confirmed_selective_stale_escape",
        "E6_exact_selective_vs_clean_equivalence",
        "E9_every_detected_typed_change_creates_a_rebuild_request",
    }
    for endpoint in score_sfi3.MAY_NOT_BE_SKIPPED:
        assert endpoint in score_sfi3.PRIMARY_ENDPOINTS


def test_the_cohort_floor_is_not_lowered_to_reach_a_verdict():
    assert score_sfi3.COHORT_FLOOR_PAIRS == 200
    assert score_sfi3.FAMILIES_REQUIRED == 3
    thin = [{"family": "only", **_fact_row()} for _ in range(199)]
    gates = score_sfi3.cohort_gates(thin)
    assert not gates["pairs_met"] and not gates["families_met"]


def test_all_nine_endpoints_appear_in_the_scored_order():
    assert len(score_sfi3.ENDPOINTS) == 9
    assert set(score_sfi3.FACT_ENDPOINTS) | set(score_sfi3.EXECUTOR_ENDPOINTS) == set(
        score_sfi3.ENDPOINTS
    )


def test_scoring_refuses_when_the_protocol_is_not_frozen(monkeypatch, tmp_path):
    """A scorer that runs against a draft produces a number whose rules can move."""
    monkeypatch.setattr(score_sfi3, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    with pytest.raises(score_sfi3.NotFrozen):
        score_sfi3.frozen_protocol()


def _fact_row() -> dict:
    """A pair that exercises every fact endpoint and violates none."""
    return {endpoint: (0, True) for endpoint in score_sfi3.FACT_ENDPOINTS}


def test_the_fact_endpoints_are_read_the_same_way_v1_and_v2_read_them():
    """Imported, not restated. Three studies stay comparable across two rewrites."""
    import score_sfi1
    import score_sfi2

    assert score_sfi3.endpoint_rows is score_sfi1.endpoint_rows
    assert score_sfi3.summary is score_sfi1.summary
    assert score_sfi2.FACT_ENDPOINTS == score_sfi3.FACT_ENDPOINTS


def test_the_executor_block_table_is_a_superset_of_sfi2s():
    """V3 adds an endpoint; it does not quietly redefine the two it inherits."""
    import score_sfi2

    inherited = {(e, k, v, n) for e, k, v, n in score_sfi2.REBUILD_BLOCKS}
    assert inherited <= set(score_sfi3.EXECUTOR_BLOCKS)
    #: V3 adds exactly two: E8 (the safety veto) and E9 (the seeding endpoint).
    added = set(score_sfi3.EXECUTOR_BLOCKS) - inherited
    assert {endpoint for endpoint, _, _, _ in added} == {
        score_sfi3.SAFETY_VETO_ENDPOINT,
        "E9_every_detected_typed_change_creates_a_rebuild_request",
    }


def test_scoring_does_not_mutate_the_executor_summary_it_was_given():
    summary = _executor()
    before = copy.deepcopy(summary)
    score_sfi3.score_executor(summary)
    assert summary == before


# --------------------------------------------------------------------------
# the protocol and the scorer must agree
#
# The protocol DECLARES the pass arithmetic; the scorer IMPLEMENTS it. Nothing
# checked that they said the same thing, which is INC-V2-035's seam one level up:
# there, an endpoint's protocol name and its executor block name drifted apart and
# a whole run scored the difference as an unexercised endpoint. A protocol that
# said "nine endpoints" beside a scorer that scored eight would be the same class
# of defect, and it would report a clean number.


def _protocol() -> dict:
    import yaml

    return yaml.safe_load(
        (NS / "protocols" / "SOURCE_FACT_IR_HELDOUT_V3.yaml").read_text(encoding="utf-8")
    )


def test_the_protocol_and_the_scorer_declare_the_same_endpoints():
    assert set(_protocol()["endpoints"]) == set(score_sfi3.ENDPOINTS)


def test_the_protocol_and_the_scorer_agree_on_the_cohort_floor():
    """Neither may be lowered without the other visibly disagreeing."""
    rule = _protocol()["pass_rule"]
    assert rule["cohort_floor_pairs"] == score_sfi3.COHORT_FLOOR_PAIRS
    assert rule["families_required"] == score_sfi3.FAMILIES_REQUIRED


def test_the_protocol_and_the_scorer_agree_that_e8_is_a_veto():
    """Founder ruling option (b), asserted on both sides of the seam."""
    endpoint = _protocol()["endpoints"][score_sfi3.SAFETY_VETO_ENDPOINT]
    assert endpoint["contributes_to_pass_arithmetic"] is False
    assert score_sfi3.SAFETY_VETO_ENDPOINT not in score_sfi3.PRIMARY_ENDPOINTS


def test_the_protocol_and_the_scorer_agree_on_what_may_not_be_skipped():
    declared = " ".join(_protocol()["pass_rule"]["no_skip"])
    for endpoint in score_sfi3.MAY_NOT_BE_SKIPPED:
        #: E5 / E6 / E9 — the protocol names them by short id in prose.
        assert endpoint.split("_")[0] in declared, endpoint


def test_the_protocol_is_still_a_draft():
    """This suite must never be the thing that lets a freeze happen by accident."""
    assert _protocol()["status"] == "DRAFT_NOT_FROZEN"


# ---------------------------------------------------------------------------
# The rule and the instrument name the same endpoints
#
# INC-V2-067 in its SFI3 form. The V2R3R1 chain froze a pass rule naming eight
# invariants and shipped an instrument that graded one; the receipt looked
# complete because nothing compared the rule to the instrument. The SFI3 freezer
# counted `len(endpoints)`, and a count is not a correspondence -- two lists of
# nine can disagree on every member.
# ---------------------------------------------------------------------------


def test_the_scorer_grades_exactly_what_the_protocol_declares():
    assert score_sfi3.require_declared_endpoints() == tuple(sorted(score_sfi3.ENDPOINTS))


def test_an_endpoint_the_protocol_declares_and_the_scorer_cannot_grade_refuses(monkeypatch):
    """Reported as absent from a study that promised it."""
    monkeypatch.setattr(
        score_sfi3,
        "declared_endpoints",
        lambda: tuple(sorted((*score_sfi3.ENDPOINTS, "E10_a_new_promise"))),
    )
    with pytest.raises(score_sfi3.ContractBroken, match="declared but not graded"):
        score_sfi3.require_declared_endpoints()


def test_an_endpoint_the_scorer_grades_and_the_protocol_omits_refuses(monkeypatch):
    """A number with no rule behind it."""
    monkeypatch.setattr(
        score_sfi3, "declared_endpoints", lambda: tuple(sorted(score_sfi3.ENDPOINTS))[1:]
    )
    with pytest.raises(score_sfi3.ContractBroken, match="graded but not declared"):
        score_sfi3.require_declared_endpoints()


def test_a_same_sized_but_different_endpoint_set_refuses(monkeypatch):
    """The check the freezer's `len(endpoints)` could not make.

    Nine declared, nine graded, and one of them a different endpoint. A count
    passes this; a correspondence does not.
    """
    swapped = list(sorted(score_sfi3.ENDPOINTS))
    swapped[-1] = "E9_something_else_entirely"
    monkeypatch.setattr(score_sfi3, "declared_endpoints", lambda: tuple(sorted(swapped)))
    with pytest.raises(score_sfi3.ContractBroken) as error:
        score_sfi3.require_declared_endpoints()
    assert "declared but not graded" in str(error.value)
    assert "graded but not declared" in str(error.value)


def test_the_borrowed_verdict_labels_still_say_what_sfi3_thinks():
    assert score_sfi3.require_shared_verdict_vocabulary() == {
        "MET": MET,
        "FAILED": FAILED,
        "SKIPPED": SKIPPED,
    }


def test_a_verdict_label_that_moved_upstream_refuses(monkeypatch):
    """SFI1 is spent; nothing stops its constants moving.

    These exact strings are written into a frozen receipt, so a label that
    changed there would relabel this study's verdicts with no change here.
    """
    monkeypatch.setattr(score_sfi3, "SKIPPED", "SKIPPED")
    with pytest.raises(score_sfi3.ContractBroken, match="imported from score_sfi1"):
        score_sfi3.require_shared_verdict_vocabulary()


def test_both_checks_run_before_the_freeze_receipt_is_located(monkeypatch):
    """Not decoration on a path that only the happy case reaches.

    `frozen_protocol` is the door every real scoring run goes through, and the
    two checks fire before it even looks for a receipt -- so a chain with no
    freeze at all still reports the contract mismatch rather than `NotFrozen`,
    which would send a reader looking for the wrong problem.
    """
    monkeypatch.setattr(score_sfi3, "SKIPPED", "SKIPPED")
    with pytest.raises(score_sfi3.ContractBroken):
        score_sfi3.frozen_protocol()


def test_exactly_once_guard_refuses_any_prior_authoritative_score(tmp_path):
    prior = tmp_path / "sfi3-execution-correctness--prior.json"
    prior.write_text("{not even complete json", encoding="utf-8")
    with pytest.raises(score_sfi3.AlreadyScored, match="scored exactly once"):
        score_sfi3.require_no_authoritative_score(tmp_path)


def test_exactly_once_guard_does_not_select_a_newest_score(tmp_path):
    for name in ("older", "newer"):
        (tmp_path / f"sfi3-execution-correctness--{name}.json").write_text(
            "{}", encoding="utf-8"
        )
    with pytest.raises(score_sfi3.AlreadyScored) as error:
        score_sfi3.require_no_authoritative_score(tmp_path)
    assert "older" in str(error.value) and "newer" in str(error.value)


def test_scoring_requires_the_workers_exact_reservation_binding():
    expected = {"handoff": "receipts/exact.json", "handoff_sha256": "sha256:abc"}
    assert score_sfi3.require_acquisition_binding(
        {"reservation_binding": expected}, expected
    ) == expected
    with pytest.raises(score_sfi3.ContractBroken, match="differs"):
        score_sfi3.require_acquisition_binding(
            {"reservation_binding": {**expected, "handoff_sha256": "sha256:wrong"}},
            expected,
        )


def test_scoring_refuses_an_acquisition_without_a_reservation_binding():
    with pytest.raises(score_sfi3.ContractBroken, match="no verified reservation_binding"):
        score_sfi3.require_acquisition_binding({}, {"held": True})


def test_one_acquisition_has_one_deterministic_score_authority_slot():
    digest = "sha256:" + "a" * 64
    assert score_sfi3.authoritative_score_run_id(digest) == "sfi3-score-" + "a" * 24
    assert score_sfi3.authoritative_score_run_id(digest) == (
        score_sfi3.authoritative_score_run_id(digest)
    )
    with pytest.raises(score_sfi3.ContractBroken, match="single score authority"):
        score_sfi3.authoritative_score_run_id("sha256:not-a-digest")
