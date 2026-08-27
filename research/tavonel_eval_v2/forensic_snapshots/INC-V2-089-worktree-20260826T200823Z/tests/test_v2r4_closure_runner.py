"""The V2R4 traversal: its execution boundary and its INVARIANT_8 proof sourcing.

NOTHING HERE TOUCHES THE REAL COHORT. The measurement path refuses while a test
runner is loaded, and these tests assert that refusal rather than working around
it. What is exercised is the part of this module that is NEW DECISION-MAKING
rather than reused grading: which enumerator proofs establish which declared
population, and whether that mapping can go wrong silently.

Grading is not retested here. It is `v2r4_grading`'s, pinned by rung 4, and
covered by `test_v2r4_grading.py`.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import freeze_migration_closure_v2r4 as fz  # noqa: E402
import identity_change_migration_closure_v2r4 as runner  # noqa: E402
import v2r4_grading as grading  # noqa: E402


@pytest.fixture
def universe() -> dict[str, Any]:
    ws = fz.workspace()
    receipt = fz.base.latest_receipt(
        fz.base.stem_for(fz.base.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    assert receipt is not None, "rung 3 must be frozen for these tests to mean anything"
    return receipt


@pytest.fixture
def candidates(universe: dict[str, Any], tmp_path: Path):
    """A rewritable copy of the pinned artifact, re-pinned so the digest holds.

    Mutating the real one would corrupt a frozen rung. Mutating a copy WITHOUT
    re-pinning would only ever exercise the digest check, which is a different
    test -- and every red control below would pass for the wrong reason.
    """
    import hashlib

    def install(mutate) -> dict[str, Any]:
        source = NS.parents[1] / universe["manifest"]["path"]
        body = json.loads(source.read_text(encoding="utf-8"))
        mutate(body)
        target = tmp_path / "candidates.json"
        target.write_text(json.dumps(body), encoding="utf-8")
        forged = copy.deepcopy(universe)
        forged["manifest"] = {
            "path": str(target.resolve()).replace("\\", "/"),
            "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        return forged

    return install


# ---------------------------------------------------------------------------
# the execution boundary


def test_the_measurement_path_refuses_from_a_test():
    """Asserted rather than worked around. The V2R1 chain died because a stale
    test reached `run()` and traversed 300 pairs before crashing."""
    with (
        pytest.raises(runner.ClosureRefused, match="test runner is loaded"),
        runner._one_shot_entry_point(),
    ):
        runner.authorise_one_shot(fz.workspace())


def test_run_refuses_without_an_authorisation_before_opening_anything():
    with pytest.raises(runner.ClosureRefused, match="requires an ExecutionAuthorisation"):
        runner.run()


def test_a_hand_built_authorisation_is_not_accepted():
    """Compared by IDENTITY, so a well-shaped object built by hand is refused."""
    forged = runner.ExecutionAuthorisation(
        gate={"gate": "require_v2r4_execution_preconditions"}, minted_by="not_the_entry_point"
    )
    with pytest.raises(runner.ClosureRefused, match="not minted by this process"):
        runner.run(forged)


def test_an_authorisation_carrying_another_chains_gate_is_refused(monkeypatch):
    forged = runner.ExecutionAuthorisation(
        gate={"gate": "require_v2r3r1_execution_preconditions"}, minted_by="one_shot_entry_point"
    )
    monkeypatch.setattr(runner, "_MINTED", forged)
    with pytest.raises(runner.ClosureRefused, match="another chain"):
        runner.run(forged)


def test_the_default_action_is_not_the_measurement(capsys):
    """A run with no flag would otherwise be the whole closure by accident."""
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "NOT_EXECUTED"


def test_there_is_no_limit_or_sample_flag():
    """A limited run reads real outcomes from part of the cohort and is a PREVIEW
    whatever it does with them afterwards.

    Asked of the PARSER, not of the file's text. The first version grepped the
    source and matched the docstring sentence explaining that no such flag
    exists -- a control that would have gone red on the very prose promising the
    thing it was checking for, and green if that prose were deleted."""
    import argparse

    argv_seen: list[str] = []
    real = argparse.ArgumentParser.add_argument

    def record(self, *args, **kwargs):
        argv_seen.extend(a for a in args if isinstance(a, str) and a.startswith("--"))
        return real(self, *args, **kwargs)

    argparse.ArgumentParser.add_argument = record
    try:
        with pytest.raises(SystemExit):
            runner.main(["--help"])
    finally:
        argparse.ArgumentParser.add_argument = real

    assert argv_seen, "the entry point declared no flags at all; the probe missed"
    forbidden = {"--limit", "--sample", "--preview", "--force", "--dry-run", "--rescore"}
    assert forbidden.isdisjoint(argv_seen), f"declared: {sorted(set(argv_seen) & forbidden)}"
    assert "--execute" in argv_seen


# ---------------------------------------------------------------------------
# INVARIANT_8: where the proofs are read from
#
# The naive path -- `grading.disjointness_from(universe["disjointness"])` --
# refuses on this chain, because the universe rung is frozen by V1's
# `build_universe`, which computes three proofs under V1's own names, and V2R4
# declares seven. The whole point of these tests is that the replacement reads a
# PINNED source and still lets `require_disjointness_domain` decide.


def test_the_frozen_universe_block_alone_cannot_satisfy_the_declared_domain(universe):
    """The defect this sourcing exists for, asserted rather than described. Left
    unrepaired it refuses AFTER the whole cohort has been diffed."""
    with pytest.raises(grading.GradingRefused, match="not the same domain"):
        grading.disjointness_from(universe["disjointness"])


def test_every_declared_population_is_established_and_the_domain_is_equal(universe):
    built = runner.disjointness_input(universe)
    assert built["domain"]["equal"] is True
    assert built["violations"] == []
    assert set(built["per_population"]) == set(grading.REQUIRED_DISJOINTNESS)
    for population in grading.REQUIRED_DISJOINTNESS:
        assert built[population] is True


def test_the_domain_check_is_the_graders_own_and_not_a_second_copy():
    """A re-implemented set comparison is a second thing that can drift."""
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "grading.require_disjointness_domain(built)" in source


def test_the_retrospective_cohort_is_not_established_by_the_weak_proof_alone():
    """The enumerator's `retrospective_538` carries 14 comparable ids and says in
    its own `coverage` field that full coverage comes from `sfi1_spent` and
    `sfi2_spent`. Binding the declared population to it alone would satisfy the
    domain check with a fraction of the cohort actually compared."""
    assert runner.PROOF_SOURCES["from_the_538_pair_retrospective_cohort"] == (
        "retrospective_538",
        "sfi1_spent",
        "sfi2_spent",
    )


def test_a_population_bound_to_a_proof_that_is_absent_refuses(universe, candidates):
    forged = candidates(lambda body: body["disjointness"].pop("v2r3_and_v2r3r1_spent_300"))
    with pytest.raises(runner.ClosureRefused, match="absent from the pinned artifact"):
        runner.disjointness_input(forged)


def test_an_enumerator_proof_that_does_not_hold_becomes_a_violation(universe, candidates):
    def break_one(body: dict[str, Any]) -> None:
        body["disjointness"]["v2r1_spent"]["holds"] = False

    built = runner.disjointness_input(candidates(break_one))
    assert built["from_v2r1_universe"] is False
    assert any("from_v2r1_universe" in row["why"] for row in built["violations"])


def test_a_non_empty_overlap_becomes_a_violation_even_when_holds_is_true(
    universe, candidates
):
    """`holds` is the enumerator's own summary. A row that reports clean while
    carrying an overlap is exactly the disagreement worth catching."""

    def contaminate(body: dict[str, Any]) -> None:
        body["disjointness"]["v2r3_and_v2r3r1_spent_300"]["overlap"] = ["some:lineage"]

    built = runner.disjointness_input(candidates(contaminate))
    assert built["from_v2r3r1_universe"] is False
    assert any("from_v2r3r1_universe" in row["why"] for row in built["violations"])


def test_one_weak_proof_failing_fails_the_whole_population(universe, candidates):
    """`from_the_538_pair_retrospective_cohort` takes three proofs and needs ALL
    of them. A conjunction that passed on any one would be a population declared
    over three cohorts and checked against one."""

    def break_coverage(body: dict[str, Any]) -> None:
        body["disjointness"]["sfi2_spent"]["holds"] = False

    built = runner.disjointness_input(candidates(break_coverage))
    assert built["from_the_538_pair_retrospective_cohort"] is False


def test_the_universes_own_proof_must_agree_where_it_made_one(universe, candidates):
    """Two independent computations, both required. A mapping that quietly
    replaced the universe's proofs with the enumerator's would have removed a
    check while appearing to repair one."""
    forged = candidates(lambda body: None)
    forged["disjointness"]["from_the_v1_frozen_universe"]["holds"] = False
    built = runner.disjointness_input(forged)
    assert built["from_v1_universe"] is False
    assert any("the universe rung's own" in row["why"] for row in built["violations"])


def test_a_missing_universe_corroboration_blocks_rather_than_passing(universe, candidates):
    forged = candidates(lambda body: None)
    forged["disjointness"].pop("from_the_v1_frozen_universe")
    with pytest.raises(runner.ClosureRefused, match="not a corroboration"):
        runner.disjointness_input(forged)


def test_a_new_unconsumed_enumerator_proof_blocks(universe, candidates):
    """A proof nobody bound to a population is a population nobody declared."""

    def add(body: dict[str, Any]) -> None:
        body["disjointness"]["some_new_cohort"] = {"holds": True, "overlap": []}

    with pytest.raises(runner.ClosureRefused, match="proof set has moved"):
        runner.disjointness_input(candidates(add))


def test_a_vanished_unconsumed_proof_also_blocks(universe, candidates):
    """The other direction: a proof somebody stopped computing."""
    forged = candidates(lambda body: body["disjointness"].pop("sfi3_all"))
    with pytest.raises(runner.ClosureRefused, match="proof set has moved"):
        runner.disjointness_input(forged)


# ---------------------------------------------------------------------------
# the source is pinned


def test_a_drifted_candidates_artifact_refuses(universe, tmp_path):
    """Reading a proof out of an unpinned file to satisfy a frozen rung is the
    false-provenance seam this study keeps recording."""
    source = NS.parents[1] / universe["manifest"]["path"]
    target = tmp_path / "drifted.json"
    body = json.loads(source.read_text(encoding="utf-8"))
    body["disjointness"]["v2r1_spent"]["overlap"] = []
    target.write_text(json.dumps(body) + " ", encoding="utf-8")
    forged = copy.deepcopy(universe)
    forged["manifest"] = {
        "path": str(target.resolve()).replace("\\", "/"),
        "sha256": universe["manifest"]["sha256"],
    }
    with pytest.raises(runner.ClosureRefused, match="has changed since rung 3 pinned"):
        runner.disjointness_input(forged)


def test_an_unpinned_universe_receipt_refuses(universe):
    forged = copy.deepcopy(universe)
    forged.pop("manifest")
    with pytest.raises(runner.ClosureRefused, match="does not pin"):
        runner.disjointness_input(forged)


def test_the_pinned_digest_matches_the_artifact_on_disk_right_now(universe):
    """The live chain, not a fixture. If this goes red the frozen rung and the
    artifact it named have parted company."""
    assert runner.pinned_candidates(universe)["pair_count"] == universe["pair_count"]


# ---------------------------------------------------------------------------
# the traversal calls the PINNED grader, with the pinned grader's signature
#
# INC-V2-082. The first version called `grading.measure_pair` with the PARENT's
# argument list and `parent.measure_extra_clauses` beside it. It raised TypeError
# on pair 0 -- no outcome read, nothing sealed, corpus unspent -- but only because
# the mismatch happened to be in the arity. Had the parent's signature been a
# superset, it would have run to completion and diffed all 223 pairs TWICE, and
# the composition rung 4 sealed would have been silently re-derived here, in a
# module rung 4 does not pin.


def test_the_traversal_calls_the_pinned_graders_measure_pair_not_the_parents():
    """Bound to the real signature so a drift in either module is a red test
    rather than a TypeError during the one authorised execution."""
    import inspect

    expected = set(inspect.signature(grading.measure_pair).parameters)
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "grading.measure_pair(" in source
    assert "parent.measure_extra_clauses(" not in source, (
        "the traversal composes the clauses itself; that composition is the pinned "
        "grader's and re-deriving it here diffs every pair twice"
    )
    #: The two arguments the parent's signature does not carry, and the pair the
    #: pinned one returns. Named individually: asserting only the count would pass
    #: against a rename.
    assert {"declared_record", "level"} <= expected


def test_the_pinned_grader_returns_both_populations_and_the_traversal_unpacks_them():
    import inspect

    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "result, clauses = grading.measure_pair(" in source
    returns = inspect.signature(grading.measure_pair).return_annotation
    assert "tuple" in str(returns), (
        f"the pinned grader now returns {returns}; the traversal unpacks two values"
    )
