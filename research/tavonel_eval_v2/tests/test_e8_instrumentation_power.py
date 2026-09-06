"""E8's instrument must be shown to fire, and shown not to fire on clean input.

Under the founder's option (b) ruling E8 credits nothing when clean, so the only
thing that makes its held-out zero readable is prior proof that it CAN report
non-zero. These tests guard that proof.
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import execution_invariant as invariant  # noqa: E402
import prove_e8_instrumentation_power as prover  # noqa: E402
import score_sfi3  # noqa: E402


def test_every_injection_raises_at_every_stage():
    body = prover.run()
    assert body["injections_total"] == len(prover.INJECTIONS) * len(prover.STAGES)
    assert body["injections_not_raised"] == 0
    assert body["injections_missed"] == []


def test_the_controls_do_not_raise():
    """Without this, an unconditionally-raising check would satisfy the receipt.

    A gate that fires on everything is as useless as one that fires on nothing, and
    only the pair of results tells a real instrument from either.
    """
    body = prover.run()
    assert body["controls_total"] == len(prover.STAGES)
    assert body["control_false_positives"] == 0


def test_both_stages_are_injected():
    """An instrument proven only after execution leaves the path to ACTIVE unwatched."""
    assert set(prover.STAGES) == {
        invariant.STAGE_POST_EXECUTION,
        invariant.STAGE_PRE_ACTIVATION,
    }
    body = prover.run()
    for stage in prover.STAGES:
        raised = [r for r in body["results"] if r["stage"] == stage and r["raised"]]
        assert raised, stage


def test_the_violation_message_names_the_artifacts():
    """A count cannot be checked against a rebuild; a named artifact can."""
    body = prover.run()
    assert body["violating_artifacts_not_named"] == []


def test_the_injections_are_synthetic_and_not_the_fourteen_sfi2_cases():
    """A case that diagnosed a defect cannot certify the detector for it."""
    names = {
        artifact
        for _, required, _, carried in prover.INJECTIONS
        for artifact in (required | carried)
    }
    assert all(name.startswith(("section:", "chain:")) for name in names)
    assert not any("ecfr" in name or "github" in name for name in names)


def test_a_failed_proof_refuses_to_write_a_receipt(monkeypatch, capsys):
    """The receipt is what the scorer trusts, so it must never record a failure."""
    monkeypatch.setattr(
        prover,
        "INJECTIONS",
        (("cannot_violate", {"section:a"}, {"section:a"}, {"section:b"}),),
    )
    code = prover.main(["--write-receipt"])
    assert code == 4
    assert "NOT proven" in capsys.readouterr().err


def test_the_scorer_reads_this_receipt_and_fails_closed_without_it(monkeypatch, tmp_path):
    """No receipt means no PASS. An unvalidated instrument reporting zero is not evidence."""
    monkeypatch.setattr(score_sfi3, "NS", tmp_path)
    (tmp_path / "receipts").mkdir()
    power = score_sfi3.instrumentation_power()
    assert power["proven"] is False
    assert (
        score_sfi3.verdict_for(
            [], [], [], veto_violations=0, instrumentation_power_proven=power["proven"]
        )
        == "FAIL"
    )


def test_the_receipt_stem_the_prover_writes_is_the_stem_the_scorer_looks_for():
    """INC-V2-035 was exactly this mismatch, one seam over."""
    assert prover.STEM == score_sfi3.POWER_RECEIPT_STEM


def test_the_proof_declares_that_it_is_development_evidence():
    body = prover.run()
    assert body["split"] == "development"
    assert body["never_mixed_into_held_out_denominator"] is True
    assert body["what_this_does_not_establish"]
