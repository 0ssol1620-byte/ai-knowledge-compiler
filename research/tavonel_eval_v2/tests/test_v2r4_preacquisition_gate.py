"""The V2R4 pre-acquisition join gate. Founder ruling section G.

This gate stands immediately before the irreversible act, so the question these
tests answer is not "does it report READY" -- it is "can it report READY when it
should not". Every condition is driven red independently, and the gate is shown
to refuse on each one alone.

The suite row is exercised with `skip_suite=True` throughout, which makes that
one row FAIL by construction. Running the authoritative suite from inside the
authoritative suite would recurse; what is tested here is that skipping it is a
FAIL rather than a quiet pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import invariant_domain  # noqa: E402
import rehearse_v2r4_closure as rehearsal  # noqa: E402
import sfi3_root_reservation as reservation  # noqa: E402
import v2r4_grading as grading  # noqa: E402
import v2r4_preacquisition_gate as gate  # noqa: E402
import v2r4_semantics_delta as delta  # noqa: E402

SUITE_ROW = "authoritative_full_suite_green"


def _rows(**kwargs) -> dict[str, str]:
    body = gate.run(skip_suite=True, **kwargs)
    return {row["condition"]: row["verdict"] for row in body["rows"]}


def _verdict(name: str) -> str:
    """Exercise one condition, not all twelve and their multi-GB live artifacts.

    The old red controls called ``gate.run`` for every assertion.  That repeated
    the full V2R4 rehearsal and loaded the historical corpus dozens of times in
    one pytest process, reaching 35 GB.  A unit control for one row needs the one
    row; the all-twelve integration result is the immutable historical receipt.
    """
    check = dict(gate.CONDITIONS)[name]
    return gate._row(name, check)["verdict"]


def _lightweight_conditions(monkeypatch, *, failing: str | None = None) -> None:
    rows = tuple(
        (
            name,
            (lambda name=name: (_ for _ in ()).throw(gate.GateRefused("synthetic red")))
            if name == failing
            else (lambda: {"fixture": True}),
        )
        for name, _check in gate.CONDITIONS
    )
    monkeypatch.setattr(gate, "CONDITIONS", rows)


# ---------------------------------------------------------------------------
# shape


def test_the_gate_declares_exactly_the_twelve_conditions_the_ruling_names():
    assert len(gate.CONDITIONS) == 12
    gate._require_twelve()


def test_a_dropped_condition_refuses_rather_than_quietly_gating_on_eleven(monkeypatch):
    """A gate with a missing row reports READY on less evidence than authorised."""
    monkeypatch.setattr(gate, "CONDITIONS", gate.CONDITIONS[:-1])
    with pytest.raises(RuntimeError, match="names twelve"):
        gate._require_twelve()


def test_duplicate_condition_names_refuse(monkeypatch):
    monkeypatch.setattr(gate, "CONDITIONS", (*gate.CONDITIONS[:-1], gate.CONDITIONS[0]))
    with pytest.raises(RuntimeError, match="duplicate condition names"):
        gate._require_twelve()


def test_every_condition_name_is_distinct_and_ordered_as_the_ruling_lists_them():
    names = [name for name, _check in gate.CONDITIONS]
    assert names == [
        "invariant_domain_equality",
        "v2r4_full_eight_rehearsal",
        "every_invariant_reds_independently",
        "v2r4_allowed_delta_attestation",
        "sfi3_root_reservation_frozen",
        "v2r4_sfi3_root_separation",
        "i8_exclusion_domain_exact",
        "anti_blocker_audit_zero_blockers",
        "authoritative_full_suite_green",
        "gpu_spend_zero",
        "sfi3_fresh_payload_unopened",
        "no_prior_v2r4_measurement",
    ]


# ---------------------------------------------------------------------------
# the eleven that can be evaluated without recursing into the suite


#: THIS GATE IS PRE-ACQUISITION AND ACQUISITION HAS HAPPENED. It sealed
#: READY_FOR_ACQUISITION over 12/12, the corpus was fetched, and `c12` now
#: correctly refuses: "already holds acquired material, so this gate is no longer
#: PRE-acquisition." That refusal is the row doing its job.
#:
#: Two tests here asserted the gate's live verdict and went red when the chain
#: advanced past the moment they were written in -- the same class as the four in
#: `test_v2r4_frame.py`, INC-V2-079. They are split: the pre-acquisition answer is
#: driven at an EMPTY CORPUS, where it is the answer the row was written for, and
#: the live answer is asserted separately and in the opposite direction.
_PRE_ACQUISITION_ROW = "no_prior_v2r4_measurement"


@pytest.fixture
def before_acquisition(monkeypatch, tmp_path):
    """The chain as it stood when this gate ran for real: nothing fetched."""
    monkeypatch.setattr(gate, "CORPUS", tmp_path / "v2r4_corpus")
    monkeypatch.setattr(gate, "MEASUREMENT_GLOB", "fixture-before-v2r4-measurement--*.json")
    return tmp_path


def test_the_other_eleven_conditions_pass_before_acquisition(before_acquisition):
    """The real all-twelve run is preserved immutably; do not recompute it."""
    receipt = NS / "receipts" / (
        "identity-change-migration-closure-v2r4-preacquisition-gate--"
        "20260826T050451Z-55f0e4c41aff.json"
    )
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["verdict"] == gate.READY
    assert body["conditions_declared"] == body["conditions_passed"] == 12
    assert body["failed"] == []


def test_the_gate_refuses_once_the_corpus_has_been_acquired():
    """The other direction, on the live tree. A pre-acquisition gate that still
    reported READY after acquisition would be describing a moment that has
    passed, and §I's "corpus is spent" rule rests on it not doing that."""
    row = gate._row(_PRE_ACQUISITION_ROW, dict(gate.CONDITIONS)[_PRE_ACQUISITION_ROW])
    assert row["verdict"] != gate.PASS
    assert "no rescore is permitted" in row["error"]


def test_exactly_one_authoritative_v2r4_measurement_receipt_exists():
    """The live chain is closed; exactly-once now means one receipt, never zero."""
    found = sorted((NS / "receipts").glob(gate.MEASUREMENT_GLOB))
    assert [path.name for path in found] == [
        "identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json"
    ]


def test_skipping_the_suite_is_a_failure_not_a_pass(before_acquisition, monkeypatch):
    """"We did not check" and "it is green" are different answers."""
    _lightweight_conditions(monkeypatch)
    body = gate.run(skip_suite=True)
    assert body["verdict"] == gate.BLOCKED
    assert body["failed"] == [SUITE_ROW]
    row = next(r for r in body["rows"] if r["condition"] == SUITE_ROW)
    assert "not run" in row["error"]


# ---------------------------------------------------------------------------
# each condition drives the gate red on its own


def test_a_domain_mismatch_blocks(monkeypatch):
    monkeypatch.setattr(
        grading,
        "require_domain",
        lambda: {"declared": ["A"], "graded": ["B"], "schema_required": ["A"]},
    )
    assert _verdict("invariant_domain_equality") == gate.FAIL


def test_an_unrehearsable_scorer_blocks(monkeypatch):
    monkeypatch.setattr(rehearsal, "rehearse", lambda: {"verdict": "SOMETHING_ELSE"})
    assert _verdict("v2r4_full_eight_rehearsal") == gate.FAIL


def test_an_invariant_that_will_not_red_blocks(monkeypatch):
    """A scorer that cannot red an invariant has not been shown to grade it."""
    real = rehearsal.drive_red
    target = sorted(rehearsal.RED_DRIVERS)[0]

    def lame(invariant: str):
        body = dict(real(invariant))
        if invariant == target:
            body["target_verdict"] = invariant_domain.MET
        return body

    monkeypatch.setattr(rehearsal, "drive_red", lame)
    assert _verdict("every_invariant_reds_independently") == gate.FAIL


def test_collateral_damage_blocks_even_when_the_target_reds(monkeypatch):
    """Reddening seven bystanders proves the scorer breaks, not that it grades."""
    real = rehearsal.drive_red

    def messy(invariant: str):
        return {**real(invariant), "collateral_damage": ["INVARIANT_2_something"]}

    monkeypatch.setattr(rehearsal, "drive_red", messy)
    assert _verdict("every_invariant_reds_independently") == gate.FAIL


def test_a_missing_red_driver_blocks(monkeypatch):
    """Set equality against the EXECUTED graded domain, not a smaller loop."""
    trimmed = dict(rehearsal.RED_DRIVERS)
    trimmed.pop(sorted(trimmed)[0])
    monkeypatch.setattr(rehearsal, "RED_DRIVERS", trimmed)
    assert _verdict("every_invariant_reds_independently") == gate.FAIL


def test_a_broken_scientific_core_blocks(monkeypatch):
    monkeypatch.setattr(
        delta, "prove_allowed_delta", lambda: {"verdict": delta.VERDICT_REFUSED}
    )
    assert _verdict("v2r4_allowed_delta_attestation") == gate.FAIL


def test_an_unfrozen_reservation_blocks(monkeypatch):
    """Both studies bind it by path and sha256; a binding to nothing is not one."""
    monkeypatch.setattr(reservation, "latest_reservation", lambda receipts=None: None)
    assert _verdict("sfi3_root_reservation_frozen") == gate.FAIL


def test_a_tampered_reservation_blocks(monkeypatch):
    def refuse(stored):
        raise reservation.ReservationRefused("the stored reservation does not derive")

    monkeypatch.setattr(reservation, "verify", refuse)
    assert _verdict("sfi3_root_reservation_frozen") == gate.FAIL


def test_a_root_clash_blocks(monkeypatch):
    monkeypatch.setattr(
        gate.att,
        "prove_root_disjointness",
        lambda module="sources_v2r4": {"clashes": 1, "module": module},
    )
    assert _verdict("v2r4_sfi3_root_separation") == gate.FAIL


def test_a_root_reserved_for_sfi3_blocks(monkeypatch):
    def refuse():
        raise reservation.ReservationRefused("declares containers reserved for SFI3")

    monkeypatch.setattr(gate.att, "prove_sfi3_separation", refuse)
    assert _verdict("v2r4_sfi3_root_separation") == gate.FAIL


def test_reinstating_the_sfi3_exclusion_population_blocks(monkeypatch):
    """The circular gate, reintroduced. It must not be able to come back quietly."""
    real = grading.declared_populations
    monkeypatch.setattr(
        grading,
        "declared_populations",
        lambda protocol=None: (*real(protocol), "from_sfi3_material"),
    )
    assert _verdict("i8_exclusion_domain_exact") == gate.FAIL


def test_an_anti_blocker_finding_blocks(monkeypatch):
    monkeypatch.setattr(
        gate.anti_blocker_audit,
        "audit",
        lambda: {
            "blocker_count": 1,
            "verdict": "BLOCKED",
            "findings": [{"severity": "BLOCKER", "name": "x"}],
            "modules_scanned": [],
            "modules_absent": [],
        },
    )
    assert _verdict("anti_blocker_audit_zero_blockers") == gate.FAIL


def test_gpu_spend_blocks(monkeypatch, tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "gpu-successor-launch--20260826T000000Z-aaaaaaaaaaaa.json").write_text(
        '{"gpu_seconds": 120, "cost_usd": 4.0}', encoding="utf-8"
    )
    monkeypatch.setattr(gate, "NS", tmp_path)
    assert _verdict("gpu_spend_zero") == gate.FAIL


def test_an_opened_sfi3_corpus_blocks(monkeypatch, tmp_path):
    """SFI3 acquires only AFTER this study passes."""
    corpus = tmp_path / "sfi3_corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "SFI3_CORPUS", corpus)
    assert _verdict("sfi3_fresh_payload_unopened") == gate.FAIL


def test_an_existing_v2r4_measurement_blocks(monkeypatch, tmp_path):
    """A closure runs EXACTLY ONCE."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (
        receipts / "identity-change-migration-closure-v2r4--20260826T000000Z-bbbb.json"
    ).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "NS", tmp_path)
    assert _verdict("no_prior_v2r4_measurement") == gate.FAIL


def test_already_acquired_material_blocks(monkeypatch, tmp_path):
    """Once material is open, this is no longer a PRE-acquisition gate."""
    corpus = tmp_path / "v2r4_corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "CORPUS", corpus)
    assert _verdict("no_prior_v2r4_measurement") == gate.FAIL


# ---------------------------------------------------------------------------
# sealing


def test_the_gate_refuses_to_seal_a_blocked_verdict(monkeypatch):
    """A receipt is not a consolation prize for a gate that refused."""
    _lightweight_conditions(monkeypatch, failing="invariant_domain_equality")
    with pytest.raises(gate.GateRefused, match="Nothing is sealed"):
        gate.freeze(skip_suite=True)


def test_sealing_a_blocked_verdict_writes_nothing(monkeypatch):
    written: list[str] = []
    _lightweight_conditions(monkeypatch, failing="invariant_domain_equality")
    monkeypatch.setattr(
        gate, "write_immutable", lambda stem, *a, **k: written.append(stem) or {}
    )
    with pytest.raises(gate.GateRefused):
        gate.freeze(skip_suite=True)
    assert written == []


def test_a_failed_condition_reports_its_reason_rather_than_being_swallowed(monkeypatch):
    _lightweight_conditions(monkeypatch, failing="invariant_domain_equality")
    body = gate.run(skip_suite=True)
    for row in body["rows"]:
        if row["verdict"] == gate.FAIL:
            assert row["error"], f"{row['condition']} failed with no reason"


def test_the_verdict_is_the_and_of_every_row(monkeypatch):
    _lightweight_conditions(monkeypatch, failing="invariant_domain_equality")
    body = gate.run(skip_suite=True)
    assert (body["verdict"] == gate.READY) == (not body["failed"])
    assert body["conditions_passed"] == len(body["rows"]) - len(body["failed"])
