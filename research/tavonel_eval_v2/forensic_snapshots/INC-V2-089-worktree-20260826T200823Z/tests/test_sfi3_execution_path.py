"""The SFI3 execution path: worker guards, E8/E9 aggregation, and the rehearsal.

INC-V2-043 is the reason this file exists. The freeze gate reported
`may_freeze: True` with all nineteen scientific conditions green while the
worker did not exist and `summarise` emitted neither the E8 nor the E9 block.
The failure would have appeared at the scorer, which runs after acquisition —
the step that spends a corpus that cannot be re-collected.

Every test here asserts a property rather than today's answer, and each endpoint
assertion is paired with an injection proving it can come back red. An endpoint
that cannot fail has not been measured.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler", "acquisition", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import compiler.channel_cases as cc  # noqa: E402
import compiler.rebuild_equivalence as reb  # noqa: E402
import freeze_sfi3_protocol as gate  # noqa: E402
import rehearse_sfi3_execution as rehearsal  # noqa: E402
import score_sfi3  # noqa: E402
import sfi3_worker as worker  # noqa: E402

E8_BLOCK = "E8_rebuild_required_carried_without_execution"
E9_BLOCK = "E9_detected_change_without_rebuild_request"
E8_ENDPOINT = "E8_no_rebuild_required_artifact_carried_without_execution"
E9_ENDPOINT = "E9_every_detected_typed_change_creates_a_rebuild_request"



@pytest.fixture
def under_ns():
    """A scratch directory INSIDE the repository tree.

    pytest's `tmp_path` lives on C: while this repository is on D:, and
    `common.rel()` computes a repo-relative path -- it raises ValueError across
    drives. Patching `rel` away in tests would make them pass while deleting the
    exact path handling every real run depends on, so the fixture moves instead.
    """
    import shutil
    import tempfile

    root = NS / "artifacts" / "development" / "_scratch_execution_path"
    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=root))
    yield scratch
    shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# helpers


def _judged(before_body: str, after_body: str, source_id: str = "test:pair"):
    """One real pair through real production judging."""
    before_raw = cc.markdown(cc.BODY_ALPHA, before_body)
    after_raw = cc.markdown(cc.BODY_ALPHA, after_body)
    return reb.judge_pair(
        before_document=cc.document(before_raw, "v1", source_id=source_id),
        after_document=cc.document(after_raw, "v2", source_id=source_id),
        before_raw=before_raw,
        after_raw=after_raw,
        before_facts=[],
        after_facts=[],
    )


def _semantic_pair():
    return _judged(cc.BODY_BETA, cc.BODY_BETA + " An added sentence that changes it.")


# ---------------------------------------------------------------------------
# E8 aggregation


def test_e8_block_exists_and_the_scorer_can_read_it():
    """The block whose absence INC-V2-043 is about."""
    summary = reb.summarise([_semantic_pair()])
    assert E8_BLOCK in summary
    assert score_sfi3.score_executor(summary)[E8_ENDPOINT]["verdict"] is not None


def test_e8_is_observed_at_both_declared_stages():
    """An invariant watched at one of its two stages reports zero violations
    while leaving the other path unwatched, which is a failure of the instrument
    rather than an absence of defects."""
    summary = reb.summarise([_semantic_pair()])
    for stage in score_sfi3.STAGES_REQUIRED:
        assert stage in summary[E8_BLOCK]["stages_checked"], stage


def test_e8_reports_no_natural_gate_power_and_says_so():
    """The honest reading of a structurally closed seam.

    `run_pair`'s classification loop appends an artifact to `rebuilt` XOR
    `carried`, so required-to-rebuild and carried-forward cannot intersect and
    the invariant could not have fired. Reporting that as `gate_power: False`
    is what stops a clean E8 being read as positive evidence — which is exactly
    why the founder made E8 a veto that credits nothing.
    """
    summary = reb.summarise([_semantic_pair()])
    assert summary[E8_BLOCK]["gate_power"] is False
    assert summary[E8_BLOCK]["pairs_that_could_have_exhibited"] == 0


def test_e8_clean_reading_is_veto_clear_not_met():
    """MET would claim the endpoint was put at risk and survived. It was not."""
    verdicts = score_sfi3.score_executor(reb.summarise([_semantic_pair()]))
    assert verdicts[E8_ENDPOINT]["verdict"] == score_sfi3.VETO_CLEAR


def test_e8_surfaces_a_violation_by_name_when_one_is_injected():
    """The power test for the aggregation itself.

    Without this, every assertion above is satisfiable by a summariser that
    reports zeros unconditionally.
    """
    verdict = _semantic_pair()
    injected = dataclasses.replace(
        verdict,
        carry_observations=(
            {
                "stage": "post_execution",
                "violated": ["section:u:injected"],
                "could_have_exhibited": True,
            },
            {"stage": "pre_activation", "violated": [], "could_have_exhibited": True},
        ),
    )
    summary = reb.summarise([injected])
    assert summary[E8_BLOCK]["pairs_with_unexecuted_carry"] == 1
    assert summary[E8_BLOCK]["gate_power"] is True
    #: named, never counted alone — a count cannot be checked against a rebuild.
    assert summary[E8_BLOCK]["carried"][0]["artifacts"] == ["section:u:injected"]
    assert score_sfi3.score_executor(summary)[E8_ENDPOINT]["verdict"] == score_sfi3.FAILED


# ---------------------------------------------------------------------------
# E9 aggregation


def test_e9_block_exists_and_the_scorer_can_read_it():
    summary = reb.summarise([_semantic_pair()])
    assert E9_BLOCK in summary
    assert score_sfi3.score_executor(summary)[E9_ENDPOINT]["verdict"] is not None


def test_e9_has_gate_power_on_a_pair_that_could_have_disappeared():
    """The denominator means "a silent disappearance was reachable here", not
    "this pair was judged" and not "a violation occurred"."""
    summary = reb.summarise([_semantic_pair()])
    assert summary[E9_BLOCK]["gate_power"] is True
    assert summary[E9_BLOCK]["pairs_that_could_have_exhibited"] == 1


def test_e9_has_no_gate_power_on_a_pair_with_no_typed_change():
    """A pair where nothing changed must not enter the denominator. Inflating it
    is how an untested endpoint reports as well-tested."""
    unchanged = _judged(cc.BODY_BETA, cc.BODY_BETA, source_id="test:unchanged")
    summary = reb.summarise([unchanged])
    assert summary[E9_BLOCK]["pairs_that_could_have_exhibited"] == 0


def test_e9_expected_side_is_the_contract_not_the_planner():
    """Stated in the block, and asserted here so it cannot be quietly changed.

    `RecompilationPlan.to_rebuild` is `dict.fromkeys(stale + unresolved)`, so a
    planner-derived expectation compared against the planner is an algebraic
    identity that passes whatever the executor does.
    """
    summary = reb.summarise([_semantic_pair()])
    source = summary[E9_BLOCK]["expected_side_source"]
    assert "dependency_contract" in source
    assert "Never RecompilationPlan.to_rebuild" in source


def test_e9_surfaces_a_silent_disappearance_by_name_when_one_is_injected():
    verdict = _semantic_pair()
    injected = dataclasses.replace(
        verdict,
        e9_closure={
            **dict(verdict.e9_closure or {}),
            "silent": ["section:u:vanished"],
            "could_have_exhibited": True,
        },
    )
    summary = reb.summarise([injected])
    assert summary[E9_BLOCK]["pairs_with_silent_disappearance"] == 1
    assert summary[E9_BLOCK]["silent"][0]["artifacts"] == ["section:u:vanished"]
    assert score_sfi3.score_executor(summary)[E9_ENDPOINT]["verdict"] == score_sfi3.FAILED


def test_an_unresolved_facet_change_is_reported_explicitly():
    """The founder's wording: missing dependent / NO_DEPENDENT / UNRESOLVED must
    each be explicit. An unresolved change that vanished from the report would
    be the silent disappearance the endpoint exists to catch, one level up."""
    verdict = _semantic_pair()
    injected = dataclasses.replace(
        verdict,
        e9_closure={
            **dict(verdict.e9_closure or {}),
            "unresolved_facet_changes": [{"change_channel": "visual"}],
        },
    )
    summary = reb.summarise([injected])
    assert summary[E9_BLOCK]["pairs_with_an_unresolved_facet_change"] == 1


# ---------------------------------------------------------------------------
# the worker's guards


def test_the_worker_refuses_to_acquire_without_a_freeze_receipt(monkeypatch, tmp_path):
    """Checked in the worker rather than the scorer, because by the time the
    scorer runs the corpus has already been spent."""
    monkeypatch.setattr(worker, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    with pytest.raises(worker.NotFrozen):
        worker.require_frozen_protocol()


def test_the_worker_refuses_when_the_protocol_moved_after_its_freeze(monkeypatch, tmp_path):
    """A run under edited rules is not the run that was authorised."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / f"{worker.FREEZE_STEM}--20260824T000000Z-abc.json").write_text(
        json.dumps({"protocol_sha256": "sha256:not-the-current-one"}), encoding="utf-8"
    )
    monkeypatch.setattr(worker, "NS", tmp_path)
    with pytest.raises(worker.NotFrozen, match="has moved since it was frozen"):
        worker.require_frozen_protocol()


def test_the_worker_refuses_to_overwrite_an_existing_acquisition(tmp_path):
    """There is no correct way to acquire this cohort twice: the first run spent
    it. Two artifacts at one path would make it unsayable which run the score
    describes."""
    target = tmp_path / "sfi3_acquisition.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(worker.AlreadyWritten):
        worker.require_single_writer(target)


def test_a_fresh_path_is_accepted_so_the_single_writer_guard_is_not_always_red(tmp_path):
    worker.require_single_writer(tmp_path / "not_there_yet.json")


def test_the_worker_and_the_driver_agree_on_the_admission_constants():
    """The imported driver decides admission. If its constants diverged from
    this study's, the run would collect one cohort while the declaration named
    another, and nothing downstream could see the difference."""
    worker.require_shared_admission_constants()


def test_the_admission_constant_check_can_fail(monkeypatch):
    """The premise of the test above."""
    monkeypatch.setattr(worker.frame_module, "MAX_PAYLOAD_BYTES", 1)
    with pytest.raises(RuntimeError, match="does not share"):
        worker.require_shared_admission_constants()


def test_the_worker_freeze_stem_matches_the_gate_that_writes_it():
    """The coupling the worker's docstring names. The gate cannot import the
    worker (its readiness check reads the worker's path), so the two spellings
    are asserted equal here instead of one importing the other — INC-V2-035 is
    what two spellings of one contract cost."""
    assert worker.FREEZE_STEM == gate.STEM


def test_build_summary_excludes_pairs_outside_the_admitted_cohort():
    """A verdict for a rejected lineage describes a pair that is not in the
    study; counting one would let a rejected pair make an endpoint met."""

    class _Judge:
        def __init__(self) -> None:
            self.verdicts = [_semantic_pair()]
            self.errors: list = []

    summary = worker.build_summary(_Judge(), {"admitted": []})
    assert summary["pairs_judged_supported"] == 0
    assert summary["pairs_judged_outside_the_admitted_cohort"] == 1


# ---------------------------------------------------------------------------
# the rehearsal


def test_the_rehearsal_carries_a_development_cohort_end_to_end():
    body = rehearsal.rehearse()
    assert body["verdict"] == "PASS"
    assert body["opened_fresh_payload"] is False
    readable = set(body["positive_path"]["endpoints_readable"])
    for endpoint, _block, _count, _names in score_sfi3.EXECUTOR_BLOCKS:
        assert endpoint in readable, endpoint


def test_the_rehearsal_fixtures_put_e9_at_risk():
    """A rehearsal whose fixtures could not have exhibited the failure proves
    the path runs, not that it watches."""
    assert rehearsal.rehearse()["positive_path"]["E9_gate_power"] is True


def test_the_rehearsal_runs_negative_controls():
    body = rehearsal.rehearse()
    assert body["negative_controls_passed"] == len(body["negative_controls"])
    assert body["negative_controls_passed"] >= 8


def test_the_rehearsal_fails_loudly_if_a_defect_stops_being_caught(monkeypatch):
    """The rehearsal's own power test.

    If the scorer ever stopped refusing a corrupted summary, the negative
    controls must fail rather than quietly passing. Simulated by making the
    scorer accept everything.
    """
    monkeypatch.setattr(score_sfi3, "score_executor", lambda summary: {})
    with pytest.raises(rehearsal.RehearsalFailed):
        rehearsal.negative_controls()


def test_every_rehearsal_fixture_named_for_an_edit_actually_edits_something():
    """A fixture that does not differ is not the case it is named for.

    `case_only_edit` shipped as `beta[0].upper() + beta[1:]` while BODY_BETA
    already began with a capital, so it produced a byte-identical revision: a
    second "unchanged" pair wearing the name of the exact edit INC-V2-037 is
    about. The rehearsal still reported PASS, because nothing asked whether the
    fixture was doing anything. Fixing it raised E9's exercising pairs from 1
    to 2, which is how much the rehearsal had been silently under-watching.
    """
    degenerate = [
        label for label, before, after in rehearsal._fixture_pairs()
        if label != "unchanged" and before == after
    ]
    assert not degenerate, degenerate


def test_the_unchanged_fixture_really_is_unchanged():
    """The negative half of the pair above: the control must stay a control."""
    pairs = {label: (b, a) for label, b, a in rehearsal._fixture_pairs()}
    before, after = pairs["unchanged"]
    assert before == after


def test_the_rehearsal_does_not_use_the_fourteen_sfi2_forensic_cases():
    """They are development regression fixtures for the identity/change repair
    and may not certify SFI3 — the founder's ruling, asserted rather than
    trusted to a comment."""
    labels = [label for label, _b, _a in rehearsal._fixture_pairs()]
    assert labels
    for label in labels:
        assert "sfi2" not in label.lower()
        assert not label.startswith(("git:", "ecfr:"))


# ---------------------------------------------------------------------------
# the gate's readiness condition


def test_the_readiness_condition_is_not_satisfied_by_files_alone(monkeypatch, tmp_path):
    """The founder's ruling on INC-V2-043, made executable: a gate must not pass
    merely because files exist. With no rehearsal receipt the condition blocks
    even though every required file is present."""
    monkeypatch.setattr(gate, "_latest_receipt", lambda stem: None)
    row = gate._post_freeze_pipeline_exists()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "file existence is not readiness" in row["detail"]


def test_the_readiness_condition_blocks_a_rehearsal_with_no_negative_controls(
    monkeypatch, under_ns
):
    """A rehearsal that only ever succeeds proves the path can run and nothing
    about whether it can fail."""
    receipt = under_ns / "rehearsal.json"
    receipt.write_text(
        json.dumps(
            {
                "verdict": "PASS",
                "opened_fresh_payload": False,
                "negative_controls_passed": 0,
                "positive_path": {
                    "endpoints_readable": [e for e, _b, _c, _n in score_sfi3.EXECUTOR_BLOCKS],
                    "E9_gate_power": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_latest_receipt", lambda stem: receipt)
    row = gate._post_freeze_pipeline_exists()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "no negative controls" in row["detail"]


def test_the_readiness_condition_blocks_a_rehearsal_that_opened_the_corpus(
    monkeypatch, under_ns
):
    """Rehearsing by spending the thing being rehearsed for is not a rehearsal."""
    receipt = under_ns / "rehearsal.json"
    receipt.write_text(
        json.dumps(
            {
                "verdict": "PASS",
                "opened_fresh_payload": True,
                "negative_controls_passed": 8,
                "positive_path": {
                    "endpoints_readable": [e for e, _b, _c, _n in score_sfi3.EXECUTOR_BLOCKS],
                    "E9_gate_power": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_latest_receipt", lambda stem: receipt)
    row = gate._post_freeze_pipeline_exists()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "spends the corpus" in row["detail"]


def test_the_readiness_condition_blocks_a_rehearsal_with_no_e9_power(monkeypatch, under_ns):
    receipt = under_ns / "rehearsal.json"
    receipt.write_text(
        json.dumps(
            {
                "verdict": "PASS",
                "opened_fresh_payload": False,
                "negative_controls_passed": 8,
                "positive_path": {
                    "endpoints_readable": [e for e, _b, _c, _n in score_sfi3.EXECUTOR_BLOCKS],
                    "E9_gate_power": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "_latest_receipt", lambda stem: receipt)
    row = gate._post_freeze_pipeline_exists()
    assert row["verdict"] == gate.CONDITION_FAILED
    assert "put E9 at risk" in row["detail"]


def test_the_readiness_condition_passes_against_the_real_repository():
    """The green direction, so the red ones above are not vacuously satisfied."""
    assert gate._post_freeze_pipeline_exists()["verdict"] == gate.CONDITION_MET
