"""Differential cases over every dependency channel the executor exercises.

`SOURCE_FACT_IR_HELDOUT_V2` (SFI2) is a frozen FAIL: 14 confirmed selective
stale escapes on a held-out corpus that no development test had ever produced.
This file is that gap closed with synthetic, adversarial construction from the
channel vocabulary itself (`source_fact_ir/ir.py`) rather than from SFI2's own
14 pairs, which stay the forensic lane's fixture and are never imported here.

`compiler/channel_cases.py` builds each case from real production machinery
(`canonical_document`, `diff_documents`, `graph_for`, `plan_recompilation`,
`run_pair`, `build_all`). This file only asserts on what those cases produced.
See that module's docstring for the full channel-vocabulary mapping; the short
version, confirmed by running the two graphs against each other:

    executor's actual dependency-graph channels (compiler.selective_build.graph_for):
        SEMANTIC, STRUCTURAL            -- these have edges
        (nothing else -- LOCATOR, TEMPORAL, VISUAL, METADATA never appear)

    ir.py's named channel vocabulary:
        SEMANTIC, STRUCTURAL, REFERENTIAL, TEMPORAL, DESCRIPTIVE

So SEMANTIC and STRUCTURAL get full five-step proofs plus a multi-hop
propagation proof. REFERENTIAL, TEMPORAL and DESCRIPTIVE get cases that prove
the *diff* detects the change and then prove the executor drops it on the
floor -- named as findings, not smoothed over.

**A channel test that passes because nothing happened has not tested the
channel.** Per channel this file asserts, in order:

    1. the typed delta named the artifact -- the rebuild request exists
    2. POWER -- the scenario put a stale carry within reach at all, proven via
       `execution_invariant.observe_no_unexecuted_carry_forward`'s
       `could_have_exhibited` on the *correct* execution, before trusting that
       execution's clean result
    3. the rebuild was executed, not merely requested -- digest actually moved
    4. the stale artifact could not be carried -- absent from the carried set
    5. REFUSAL -- with execution evidence removed, `check_no_unexecuted_
       carry_forward` raises `InvariantViolation` rather than proceeding

Step 5 is the one that proves the guard is load-bearing: a guard nobody can
make fail is not a guard. `execution_invariant` is owned by a different lane.
It did not exist at all when this file was drafted, and landed mid-session
with `check_no_unexecuted_carry_forward` (steps 3-5 below run against it for
real) but not yet the observation-returning sibling
`observe_no_unexecuted_carry_forward` -> `CarryObservation` (`.stage`,
`.unexecuted_carry`, `.could_have_exhibited`) that step 2's power proof needs
-- a check that only raises produces no denominator and cannot be scored,
which is why that sibling exists. Step 2 is therefore its own test function
per channel, marked `skip` with `hasattr` until that sibling lands, so its
absence is visible as a skip rather than silently missing coverage or a hard
failure that would also hide the steps that already work.

For the three unexercised channels, step 1 already fails, so steps 2-5 cannot
run on a "correct execution" that never existed. What each of those cases
proves instead: the diff *does* detect the change (so the gap is not "nothing
happened"), the plan drops it silently (`plan.explain(...) == "no change
reached it"`), and -- checked separately -- this synthetic corpus's own
`build_all` artifact spec does not even encode the facet that changed, so no
stale-carry divergence is observable through these artifacts' bytes at all. A
richer artifact spec (one keyed by evidence anchor, effective time, or
language) is what would make the gap bite in a real corpus; SFI2's confirmed
escapes are exactly that shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "compiler")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from compiler import channel_cases as cc  # noqa: E402

invariant = pytest.importorskip(
    "execution_invariant",
    reason="execution_invariant.py is owned by another lane and had not landed "
    "when this file was written; see module docstring",
)

HAS_OBSERVE = hasattr(invariant, "observe_no_unexecuted_carry_forward")
needs_observe = pytest.mark.skipif(
    not HAS_OBSERVE,
    reason="execution_invariant.observe_no_unexecuted_carry_forward has not "
    "landed yet -- step 2 (power) cannot be proven without it",
)


def _assert_power(*, required: set[str], executed: set[str], carried: set[str], stage: str) -> None:
    """Step 2: power, measured where power can exist.

    This helper was first written to assert `could_have_exhibited is True` on the
    CORRECT execution. When the sibling landed, all three callers failed, and the
    failure was right: `run_pair`'s classification loop is
    `if artifact in planned: ... elif artifact in prior_state: ...`, which makes
    `required & carried` empty by construction. A clean run therefore has no
    power and honestly says so -- see INC-V2-036 and INC-V2-037.

    Asserting `True` there would have been unsatisfiable; asserting nothing would
    have let a powerless scenario certify a clean result. So power is asserted
    where it actually exists: the same scenario with the target's execution
    evidence removed. If the injected variant CAN exhibit a stale carry and the
    correct one does not, the correct one's cleanliness means something.

    The clean observation is still taken, and still required to be free of
    unexecuted carries -- a fixture that is already dirty is broken, not clean.

    The field is `violated`, not `unexecuted_carry` as the coordination note
    said. Two lanes named the same thing differently across a seam, which is
    INC-V2-035's shape exactly; `violated` is kept because it names the
    measurement rather than the property, which is the convention the executor
    summary already follows.
    """
    clean = invariant.observe_no_unexecuted_carry_forward(
        required_to_rebuild=required,
        executed=executed,
        carried_forward=carried,
        stage=stage,
    )
    assert set(clean.violated) == set(), (
        "the correct execution already has an unexecuted carry -- the fixture is "
        "broken, not clean"
    )
    assert clean.could_have_exhibited is False, (
        "the correct execution reports power at this seam. That contradicts the "
        "classification loop's structure, so either the loop changed or the "
        "observation is wrong -- both are findings, neither is a passing test"
    )

    #: the same scenario, with one artifact's execution evidence withdrawn.
    target = sorted(required)[0]
    injected = invariant.observe_no_unexecuted_carry_forward(
        required_to_rebuild=required,
        executed=set(executed) - {target},
        carried_forward=set(carried) | {target},
        stage=stage,
    )
    assert injected.could_have_exhibited is True, (
        "even with execution evidence removed this scenario could not exhibit a "
        "stale carry -- the guard cannot fire here and the clean result below "
        "would prove nothing"
    )
    assert target in set(injected.violated), (
        "the injected defect was not named. A count cannot be checked against a "
        "rebuild; a named artifact can"
    )


def _assert_refuses(
    *, required: set[str], executed: set[str], carried: set[str], stage: str
) -> None:
    """Step 5: with the target's execution evidence removed, the guard must
    actually raise. A guard nobody can make fail is not a guard. Runs against
    `check_no_unexecuted_carry_forward`, which is present now."""
    with pytest.raises(invariant.InvariantViolation):
        invariant.check_no_unexecuted_carry_forward(
            required_to_rebuild=required, executed=executed, carried_forward=carried, stage=stage
        )


# ---------------------------------------------------------------------------
# SEMANTIC -- exercised: has edges, seeds plan_recompilation's traversal.


def test_semantic_step1_rebuild_request_created() -> None:
    case = cc.semantic_case()
    assert case.target_artifact in case.result["affected_subgraph"]


@needs_observe
def test_semantic_step2_power() -> None:
    case = cc.semantic_case()
    _assert_power(
        required=set(case.result["affected_subgraph"]),
        executed=set(case.rebuilt),
        carried=set(case.carried),
        stage=invariant.STAGE_POST_EXECUTION,
    )


def test_semantic_step3_and_4_executed_and_not_carried() -> None:
    case = cc.semantic_case()
    # 3. actually executed -- digest moved, not merely relabelled
    assert case.target_artifact in case.rebuilt
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value
    # 4. stale artifact was not carried
    assert case.target_artifact not in case.carried


def test_semantic_step5_refuses_on_unexecuted_carry_forward() -> None:
    case = cc.semantic_case()
    required = set(case.result["affected_subgraph"])
    executed_defective = set(case.rebuilt) - {case.target_artifact}
    carried_defective = (set(case.carried) | {case.target_artifact}) - executed_defective
    _assert_refuses(
        required=required, executed=executed_defective, carried=carried_defective,
        stage=invariant.STAGE_POST_EXECUTION,
    )


# ---------------------------------------------------------------------------
# STRUCTURAL -- exercised: has edges, seeds the structural traversal branch.


def test_structural_step1_rebuild_request_created() -> None:
    case = cc.structural_case()
    assert case.target_artifact in case.plan.to_rebuild


@needs_observe
def test_structural_step2_power() -> None:
    case = cc.structural_case()
    _assert_power(
        required=set(case.plan.to_rebuild),
        executed=set(case.rebuilt),
        carried=set(case.carried),
        stage=invariant.STAGE_PRE_ACTIVATION,
    )


def test_structural_step3_and_4_executed_and_not_carried() -> None:
    case = cc.structural_case()
    assert case.target_artifact in case.rebuilt
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value
    assert case.target_artifact not in case.carried


def test_structural_step5_refuses_on_unexecuted_carry_forward() -> None:
    case = cc.structural_case()
    required = set(case.plan.to_rebuild)
    executed_defective = set(case.rebuilt) - {case.target_artifact}
    carried_defective = (set(case.carried) | {case.target_artifact}) - executed_defective
    _assert_refuses(
        required=required, executed=executed_defective, carried=carried_defective,
        stage=invariant.STAGE_PRE_ACTIVATION,
    )


# ---------------------------------------------------------------------------
# Multi-hop propagation over both exercised channels' traversal engine.


def test_multi_hop_transitive_closure_is_fully_rebuilt() -> None:
    case = cc.multi_hop_case()
    # Not just the first hop: the whole transitive closure, and the hop count
    # is asserted explicitly so a degenerate depth-1 traversal is visible
    # rather than silently passing because {"chain:A"} happens to be a subset
    # check elsewhere.
    depth_by_artifact = {t.artifact_id: t.depth for t in case.plan.targets}
    assert depth_by_artifact == {"chain:A": 1, "chain:B": 2, "chain:C": 3}
    assert set(case.plan.to_rebuild) == {"chain:A", "chain:B", "chain:C"}
    assert case.target_artifact == "chain:C"


def test_multi_hop_step1_deepest_hop_is_requested() -> None:
    case = cc.multi_hop_case()
    assert "chain:C" in set(case.plan.to_rebuild)


@needs_observe
def test_multi_hop_step2_power_of_a_correct_three_hop_execution() -> None:
    case = cc.multi_hop_case()
    required = set(case.plan.to_rebuild)
    _assert_power(
        required=required, executed=required, carried=set(),
        stage=invariant.STAGE_POST_EXECUTION,
    )


def test_multi_hop_step5_refuses_when_only_the_deepest_hop_is_skipped() -> None:
    """The most dangerous shape: A and B (hops 1 and 2) look correctly
    executed, and only C -- reached transitively through both -- silently
    carries forward. Steps 3/4 have no `build_all` digest to check for these
    synthetic `chain:*` artifacts (see `channel_cases.multi_hop_case`); this
    is the property that matters for propagation depth, and it is provable
    now with `check_no_unexecuted_carry_forward` alone."""
    case = cc.multi_hop_case()
    required = set(case.plan.to_rebuild)
    executed_defective = required - {"chain:C"}
    carried_defective = {"chain:C"}
    _assert_refuses(
        required=required, executed=executed_defective, carried=carried_defective,
        stage=invariant.STAGE_POST_EXECUTION,
    )


# ---------------------------------------------------------------------------
# REFERENTIAL -- unexercised. The diff detects the change (EVIDENCE_MOVED /
# ChangeChannel.LOCATOR); plan_recompilation never sees it as a seed, and
# graph_for never emits a LOCATOR-channel edge for it to travel on anyway.
# This is a real defect finding, reported rather than smoothed over: it is the
# same failure shape SFI2 exhibited -- a change detected and correctly typed,
# which then vanishes before seeding. The older gloss ("the typed delta named
# every moved artifact; the executor failed to rebuild them") was withdrawn by
# INC-V2-037: the cross-check's 191/191 covered only units already inside its
# own denominator. Reconstructed here from the channel definitions, not from
# SFI2's fixtures.


def test_referential_change_is_detected_by_the_diff() -> None:
    case = cc.referential_case()
    assert any(
        change.channel.value == "locator" for change in case.diff.changes
    ), "the diff must still see the moved reference even though nothing acts on it"


def test_referential_step1_a_rebuild_request_is_created() -> None:
    """Was a FINDING, is now a guard.

    Written as `..._FINDING_step1_no_rebuild_request_is_created`: the channel
    carried no edge, so `plan.explain` answered "no change reached it" and steps
    2-5 could not be attempted -- there was no correct execution to prove power
    on, because nothing had been requested. Channel closure connected the facet
    to the declarative contract, so the request now exists.
    """
    case = cc.referential_case()
    assert case.exercised
    assert case.target_artifact in case.plan.to_rebuild
    assert case.plan.explain(case.target_artifact) != "no change reached it"


def test_referential_the_artifact_spec_shows_the_divergence() -> None:
    """The second half, which the first cannot substitute for.

    Closing the edge alone would have left this failing: `build_all`'s
    `section:` spec was keyed on text and never read `evidence_id`, so a
    requested rebuild would have re-emitted identical bytes and an equivalence
    check would have called that agreement. The gap was "no edge" AND "no
    representation" one layer down, and both had to close.
    """
    case = cc.referential_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value


# ---------------------------------------------------------------------------
# TEMPORAL -- unexercised, same shape as REFERENTIAL: detected, never seeded.


def test_temporal_change_is_detected_by_the_diff() -> None:
    case = cc.temporal_case()
    assert any(change.channel.value == "temporal" for change in case.diff.changes)


def test_temporal_step1_a_rebuild_request_is_created() -> None:
    """See the referential pair above: same reversal, same reason."""
    case = cc.temporal_case()
    assert case.exercised
    assert case.target_artifact in case.plan.to_rebuild
    assert case.plan.explain(case.target_artifact) != "no change reached it"


def test_temporal_the_artifact_spec_shows_the_divergence() -> None:
    case = cc.temporal_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value


# ---------------------------------------------------------------------------
# DESCRIPTIVE -- unexercised, same shape again.


def test_descriptive_change_is_detected_by_the_diff() -> None:
    case = cc.descriptive_case()
    assert any(change.channel.value == "metadata" for change in case.diff.changes)


def test_descriptive_step1_a_rebuild_request_is_created() -> None:
    """See the referential pair above: same reversal, same reason."""
    case = cc.descriptive_case()
    assert case.exercised
    assert case.target_artifact in case.plan.to_rebuild
    assert case.plan.explain(case.target_artifact) != "no change reached it"


def test_descriptive_the_artifact_spec_shows_the_divergence() -> None:
    case = cc.descriptive_case()
    assert case.prior_value is not None and case.rebuilt_value is not None
    assert case.prior_value != case.rebuilt_value
