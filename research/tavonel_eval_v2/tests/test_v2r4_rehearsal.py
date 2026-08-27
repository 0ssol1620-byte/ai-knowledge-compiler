"""The pre-freeze rehearsal, and the ways it could have been vacuous.

`tools/rehearse_v2r4_closure.py` exists to answer one question -- may this scorer
be frozen -- and the only honest answer requires both directions for all eight
invariants. This file drives the REHEARSAL red, which is a different job from the
rehearsal driving the SCORER red.

The failure this guards is one level up from INC-V2-067. That incident was an
instrument that graded one of eight. A rehearsal harness that exercised one of
eight, or that reported `held: true` for a driver which turned everything red, or
that quietly skipped an invariant it had no driver for, would have made the same
mistake in the place built to catch it.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "source_fact_ir")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import invariant_domain as dom  # noqa: E402
import rehearse_v2r4_closure as reh  # noqa: E402
import v2r4_grading as grading  # noqa: E402

CANON = dom.CANONICAL_INVARIANTS


# ---------------------------------------------------------------------------
# the rehearsal actually happened, in both directions, for all eight


def test_the_rehearsal_reports_the_scorer_rehearsable():
    body = reh.rehearse()
    assert body["verdict"] == reh.REHEARSABLE
    assert body["invariants_driven_red"] == 8
    assert body["red_directions_that_did_not_hold"] == []


def test_every_one_of_the_eight_is_driven_red_independently():
    body = reh.rehearse()
    driven = {row["invariant"]: row for row in body["red_directions"]}
    assert set(driven) == set(CANON)
    for name, row in driven.items():
        assert row["held"] is True, name
        assert row["target_verdict"] == dom.VIOLATED
        assert row["overall"] == dom.FAIL
        assert row["collateral_damage"] == [], (
            f"{name}'s driver also broke {row['collateral_damage']}; a driver that "
            "turns the whole result red proves something failed, not that this "
            "invariant can fail"
        )


def test_the_green_direction_is_a_real_pass():
    """Eight red directions and no green one would prove only that it can refuse."""
    green = reh.drive_green()
    assert green["held"] is True
    assert green["overall"] == dom.PASS
    assert green["not_met"] == []
    assert green["receipt_domain_held"] is True
    assert green["pairs_resolved"] > 0


def test_the_green_result_satisfies_the_receipt_contract():
    """The check INC-V2-067's own receipt could not have satisfied."""
    body = grading.grade(**reh.green_inputs())
    held = dom.require_receipt_domain(body)
    assert set(held["verdicts"]) == set(CANON)


# ---------------------------------------------------------------------------
# the driver domain -- set equality, obtained by execution


def test_the_driver_domain_equals_the_executed_grading_domain():
    held = reh.require_driver_domain()
    assert held["equal"] is True
    assert held["graded"] == held["driven"] == sorted(CANON)
    assert "never a count" in held["compared"]


def test_a_missing_driver_refuses_rather_than_rehearsing_seven(monkeypatch):
    """The shape of INC-V2-067, in the harness built to catch it."""
    drivers = dict(reh.RED_DRIVERS)
    dropped = drivers.pop(CANON[3])
    assert dropped is not None
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)
    with pytest.raises(reh.RehearsalRefused, match="graded but never driven red"):
        reh.require_driver_domain()


def test_a_driver_for_an_invariant_nothing_grades_refuses(monkeypatch):
    drivers = dict(reh.RED_DRIVERS)
    drivers["INVARIANT_9_an_invariant_no_scorer_grades"] = lambda inputs: inputs
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)
    with pytest.raises(reh.RehearsalRefused, match="driven but not graded"):
        reh.require_driver_domain()


def test_eight_wrong_names_do_not_pass_a_count(monkeypatch):
    """A count of eight is not a correspondence.

    Two sets of eight can disagree on every member, which is why nothing in the
    domain check compares lengths.
    """
    drivers = {f"INVARIANT_{n}_not_the_real_name": (lambda inputs: inputs) for n in range(1, 9)}
    assert len(drivers) == len(reh.RED_DRIVERS) == 8
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)
    with pytest.raises(reh.RehearsalRefused):
        reh.require_driver_domain()


def test_the_graded_side_is_executed_not_read_from_a_constant():
    """`graded_domain()` runs the grader; a tuple beside it is not evidence."""
    assert set(reh.require_driver_domain()["graded"]) == set(grading.graded_domain())


# ---------------------------------------------------------------------------
# the rehearsal can report a refusal -- it is not a check that only says yes


def test_a_driver_that_does_nothing_makes_its_red_direction_not_hold(monkeypatch):
    """The purest vacuity: a driver that changes no input at all."""
    drivers = dict(reh.RED_DRIVERS)
    drivers[CANON[0]] = lambda inputs: inputs
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)

    row = reh.drive_red(CANON[0])
    assert row["held"] is False
    assert row["target_verdict"] == dom.MET
    assert row["overall"] == dom.PASS


def test_a_driver_with_collateral_damage_does_not_hold(monkeypatch):
    """Turning two invariants red proves neither of them separately."""

    def sloppy(inputs):
        inputs["pairs"][0]["violations"]["INVARIANT_1"] = [{"why": "x"}]
        inputs["pairs"][0]["violations"]["INVARIANT_7"] = [{"why": "x"}]
        return inputs

    drivers = dict(reh.RED_DRIVERS)
    drivers[CANON[0]] = sloppy
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)

    row = reh.drive_red(CANON[0])
    assert row["held"] is False
    assert row["target_verdict"] == dom.VIOLATED
    assert row["collateral_damage"] == [CANON[6]]


def test_one_failing_red_direction_refuses_the_whole_rehearsal(monkeypatch):
    drivers = dict(reh.RED_DRIVERS)
    drivers[CANON[5]] = lambda inputs: inputs
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)

    body = reh.rehearse()
    assert body["verdict"] == reh.REFUSED
    assert body["red_directions_that_did_not_hold"] == [CANON[5]]


def test_a_green_direction_that_does_not_pass_refuses_the_whole_rehearsal(monkeypatch):
    broken = reh.green_inputs()
    broken["fold"]["violations"] = [{"why": "x"}]
    monkeypatch.setattr(reh, "green_inputs", lambda pair_count=3: copy.deepcopy(broken))

    body = reh.rehearse()
    assert body["verdict"] == reh.REFUSED
    assert body["green_direction"]["held"] is False


def test_an_empty_population_is_vacuous_and_does_not_hold(monkeypatch):
    monkeypatch.setattr(
        reh, "green_inputs", lambda pair_count=3: grading.null_grading_inputs()
    )
    green = reh.drive_green()
    assert green["held"] is False
    assert green["overall"] == dom.VACUOUS_FAIL


def test_an_unknown_invariant_has_no_driver_and_refuses():
    with pytest.raises(reh.RehearsalRefused, match="no red driver"):
        reh.drive_red("INVARIANT_99_nothing")


# ---------------------------------------------------------------------------
# no real material, ever


def test_every_synthetic_lineage_is_marked_as_one():
    inputs = reh.green_inputs()
    for key in ("pairs", "extra"):
        for row in inputs[key]:
            assert row["lineage_id"].startswith(reh.REHEARSAL_PREFIX)


def test_real_material_is_refused_rather_than_rehearsed_over():
    """A rehearsal over real material would spend it.

    An outcome observed here can never be prospective again, which is exactly
    what makes V2R3R1's 300 pairs unusable now.
    """
    inputs = reh.green_inputs()
    inputs["pairs"][0]["lineage_id"] = "ecfr:47:20:20.19"
    with pytest.raises(reh.RehearsalRefused, match="not synthetic"):
        reh._require_synthetic(inputs)


def test_the_extra_population_is_checked_too_not_only_the_pairs():
    """A guard that only watches one of two populations is half a guard."""
    inputs = reh.green_inputs()
    real = "git:some/repo:doc.md"
    inputs["pairs"][0]["lineage_id"] = real
    inputs["extra"][0]["lineage_id"] = real
    with pytest.raises(reh.RehearsalRefused, match="not synthetic"):
        reh._require_synthetic(inputs)


def test_the_rehearsal_declares_that_it_certifies_nothing():
    body = reh.rehearse()
    assert body["material"] == reh.MATERIAL
    assert "no denominator" in body["this_is_not_a_closure_result"]
    assert body["protocol_id"] == grading.PROTOCOL_ID


# ---------------------------------------------------------------------------
# the disjointness proofs the rehearsal builds


def test_the_clean_proofs_cover_the_declared_exclusion_set_exactly():
    assert set(reh.clean_proofs()) == set(grading.REQUIRED_DISJOINTNESS)


def test_invariant_8_is_driven_red_through_a_real_overlap_not_a_written_violation():
    """The honest driver for a disjointness invariant is a universe that overlaps.

    Hand-writing a violation row would exercise the aggregation and never the
    proof, and the proof is the part that could be wrong.
    """
    inputs = reh.RED_DRIVERS[CANON[7]](copy.deepcopy(reh.green_inputs()))
    overlaps = [row for row in inputs["disjointness"]["violations"] if row.get("overlap")]
    assert overlaps, "INVARIANT_8's driver produced no overlapping population"


# ---------------------------------------------------------------------------
# the CLI


def test_main_exits_zero_when_the_scorer_is_rehearsable(capsys):
    assert reh.main([]) == 0
    assert reh.REHEARSABLE in capsys.readouterr().out


def test_main_exits_non_zero_when_a_direction_does_not_hold(monkeypatch, capsys):
    drivers = dict(reh.RED_DRIVERS)
    drivers[CANON[2]] = lambda inputs: inputs
    monkeypatch.setattr(reh, "RED_DRIVERS", drivers)
    assert reh.main([]) == 4
    assert reh.REFUSED in capsys.readouterr().out


def test_main_writes_nothing_unless_asked(monkeypatch):
    """A rehearsal is run repeatedly while a scorer is being built.

    Writing an immutable receipt on every invocation would fill the evidence
    directory with drafts of a proof.
    """
    calls: list[str] = []
    monkeypatch.setattr(
        reh, "write_immutable", lambda stem, *a, **k: calls.append(stem) or {"receipt": "x"}
    )
    reh.main([])
    assert calls == []
