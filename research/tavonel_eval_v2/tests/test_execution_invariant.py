"""Tests for the fail-stop guard against unexecuted carry-forward.

``compiler/execution_invariant.py`` exists because SOURCE_FACT_IR_HELDOUT_V2
found 14 cases where the typed dependency delta correctly named every
artifact that needed to rebuild, and the executor still emitted a
carried-forward (stale) value for some of them anyway. Two things have to be
proven here, not just one:

1. The invariant function itself is correct in isolation: it raises exactly
   when ``required_to_rebuild & (carried_forward - executed)`` is non-empty,
   names the offending keys and the stage, and has no bypass.
2. It is actually wired into ``compiler/selective_build.py`` at both the
   post-execution and pre-activation call sites -- not merely present in the
   file with dead imports.

The current classification loop in ``run_pair`` is written so that
``planned`` and ``carried`` are disjoint by construction (an artifact goes
into ``rebuilt`` XOR ``carried``, never both), so it cannot produce a real
violation today. That is the intended state -- these two checks are a
regression guard against a *future* refactor reintroducing the class of bug
the 14 SFI2 escapes were, not a demonstration that today's code is broken.
To prove the wired call sites do raise on a genuine violation (not just that
an unreachable check exists), a handful of tests here simulate the shape of
that defect by monkeypatching the exact name ``selective_build`` imported.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "compiler"))

import execution_invariant as ei  # noqa: E402
import selective_build as selective  # noqa: E402


def document(source_id: str, units: list[tuple[list[str], str]]) -> dict:
    records = [
        {
            "explicit_path": path,
            "heading": path[-1],
            "ordinal": index,
            "text": text,
            "text_sha256": "sha256:unused-in-this-test",
        }
        for index, (path, text) in enumerate(units)
    ]
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": "git_docs",
        "source_id": source_id,
        "version_id": "v",
        "version_time": {"valid_from": None, "known_at": None},
        "source_digest": "sha256:" + str(abs(hash(json.dumps(records)))),
        "license": "test",
        "units": records,
        "structure": {
            "order": ["/".join(record["explicit_path"]) for record in records],
            "block_count": len(records),
        },
    }


# --- the function in isolation ----------------------------------------------


def test_clean_state_does_not_raise() -> None:
    ei.check_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a", "section:b"},
        executed={"section:a", "section:b"},
        carried_forward=set(),
        stage=ei.STAGE_POST_EXECUTION,
    )


def test_carried_forward_that_was_also_executed_does_not_raise() -> None:
    """An artifact may legitimately appear in both ``executed`` and
    ``carried_forward`` bookkeeping (e.g. rebuilt then also reported as
    reused elsewhere); what matters is that it is NOT only carried-forward.
    """
    ei.check_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed={"section:a"},
        carried_forward={"section:a"},
        stage=ei.STAGE_POST_EXECUTION,
    )


def test_carried_forward_with_nothing_required_does_not_raise() -> None:
    ei.check_no_unexecuted_carry_forward(
        required_to_rebuild=set(),
        executed=set(),
        carried_forward={"section:untouched"},
        stage=ei.STAGE_PRE_ACTIVATION,
    )


def test_required_and_carried_without_execution_raises() -> None:
    with pytest.raises(ei.InvariantViolation) as excinfo:
        ei.check_no_unexecuted_carry_forward(
            required_to_rebuild={"section:only-in-violation"},
            executed=set(),
            carried_forward={"section:only-in-violation"},
            stage=ei.STAGE_POST_EXECUTION,
        )
    message = str(excinfo.value)
    assert "section:only-in-violation" in message
    assert ei.STAGE_POST_EXECUTION in message


def test_pre_activation_stage_name_appears_in_message() -> None:
    with pytest.raises(ei.InvariantViolation) as excinfo:
        ei.check_no_unexecuted_carry_forward(
            required_to_rebuild={"structure-map:doc"},
            executed=set(),
            carried_forward={"structure-map:doc"},
            stage=ei.STAGE_PRE_ACTIVATION,
        )
    assert ei.STAGE_PRE_ACTIVATION in str(excinfo.value)


def test_only_the_unexecuted_artifact_is_named_not_the_executed_one() -> None:
    """Partial overlap: one required artifact was executed, another wasn't.
    Only the offending one belongs in the message.
    """
    with pytest.raises(ei.InvariantViolation) as excinfo:
        ei.check_no_unexecuted_carry_forward(
            required_to_rebuild={"section:already-executed", "section:escaped-artifact"},
            executed={"section:already-executed"},
            carried_forward={"section:already-executed", "section:escaped-artifact"},
            stage=ei.STAGE_POST_EXECUTION,
        )
    message = str(excinfo.value)
    assert "section:escaped-artifact" in message
    assert "section:already-executed" not in message


def test_multiple_violations_all_named() -> None:
    with pytest.raises(ei.InvariantViolation) as excinfo:
        ei.check_no_unexecuted_carry_forward(
            required_to_rebuild={"section:c", "section:a", "section:b"},
            executed=set(),
            carried_forward={"section:a", "section:b", "section:c"},
            stage=ei.STAGE_POST_EXECUTION,
        )
    message = str(excinfo.value)
    assert "section:a" in message
    assert "section:b" in message
    assert "section:c" in message
    assert "3 artifact(s)" in message


def test_artifact_required_but_never_carried_forward_does_not_raise() -> None:
    """Required and executed, never carried forward at all: unremarkable."""
    ei.check_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed={"section:a"},
        carried_forward=set(),
        stage=ei.STAGE_POST_EXECUTION,
    )


def test_invariant_violation_is_a_runtime_error() -> None:
    assert issubclass(ei.InvariantViolation, RuntimeError)


def test_stage_constants_are_the_contracted_strings() -> None:
    assert ei.STAGE_POST_EXECUTION == "post_execution"
    assert ei.STAGE_PRE_ACTIVATION == "pre_activation"


def test_no_bypass_parameter_exists_in_the_signature() -> None:
    params = set(inspect.signature(ei.check_no_unexecuted_carry_forward).parameters)
    assert params == {"required_to_rebuild", "executed", "carried_forward", "stage"}


def test_unknown_keyword_argument_is_rejected_not_silently_accepted() -> None:
    with pytest.raises(TypeError):
        ei.check_no_unexecuted_carry_forward(  # type: ignore[call-arg]
            required_to_rebuild={"section:a"},
            executed=set(),
            carried_forward={"section:a"},
            stage=ei.STAGE_POST_EXECUTION,
            force=True,
        )


def test_environment_variable_cannot_downgrade_the_violation_to_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No environment variable is read by the check at all -- setting every
    plausible bypass name still raises.
    """
    for name in (
        "SKIP_EXECUTION_INVARIANT",
        "EXECUTION_INVARIANT_DISABLE",
        "AKC_SKIP_INVARIANTS",
        "TAVONEL_NO_FAIL_STOP",
    ):
        monkeypatch.setenv(name, "1")
    with pytest.raises(ei.InvariantViolation):
        ei.check_no_unexecuted_carry_forward(
            required_to_rebuild={"section:a"},
            executed=set(),
            carried_forward={"section:a"},
            stage=ei.STAGE_POST_EXECUTION,
        )


# --- wired into compiler/selective_build.py ---------------------------------


def _reorder_pair() -> tuple[dict, dict]:
    units = [
        (["A"], "the first section body, long enough to be admitted as a unit"),
        (["B"], "the second section body, long enough to be admitted as a unit"),
        (["C"], "the third section body, long enough to be admitted as a unit"),
        (["D"], "the fourth section body, long enough to be admitted as a unit"),
    ]
    before = document("test:invariant-reorder", units)
    after = document("test:invariant-reorder", [units[2], units[3], units[0], units[1]])
    return before, after


def test_wiring_clean_path_is_unaffected() -> None:
    """Requirement: build_all/run_pair unchanged on the non-violating path."""
    before, after = _reorder_pair()
    result = selective.run_pair(before, after)
    full = selective.build_all(after)
    assert result["state"] == full, "selective state must still equal the full rebuild"
    assert result["structural_change_present"]
    assert result["selective_rebuild_set"], "fixture must exercise the rebuilt branch"
    assert result["carried_forward_set"], "fixture must exercise the carried-forward branch"


def test_wiring_invokes_both_stages_in_order_with_real_data() -> None:
    """Proves the wiring is live code, not a dead import: both call sites in
    ``run_pair`` fire, in order, with the stage constants specified in the
    contract.
    """
    calls: list[tuple[str, frozenset[str], frozenset[str], frozenset[str]]] = []
    real_check = selective.check_no_unexecuted_carry_forward

    def recording_check(*, required_to_rebuild, executed, carried_forward, stage):
        calls.append(
            (
                stage,
                frozenset(required_to_rebuild),
                frozenset(executed),
                frozenset(carried_forward),
            )
        )
        return real_check(
            required_to_rebuild=required_to_rebuild,
            executed=executed,
            carried_forward=carried_forward,
            stage=stage,
        )

    selective.check_no_unexecuted_carry_forward = recording_check
    try:
        before, after = _reorder_pair()
        selective.run_pair(before, after)
    finally:
        selective.check_no_unexecuted_carry_forward = real_check

    assert [call[0] for call in calls] == [ei.STAGE_POST_EXECUTION, ei.STAGE_PRE_ACTIVATION]
    for _, required, _executed, _carried in calls:
        assert required, "the reorder fixture must actually require a rebuild"


def test_wiring_raises_on_a_simulated_post_execution_scheduler_defect() -> None:
    """The classification loop cannot produce a real violation today (an
    artifact goes into ``rebuilt`` XOR ``carried``, never both, by
    construction of the if/elif). To prove the wired call site itself is a
    live fail-stop and not inert wiring, this reproduces the shape of the
    SFI2 finding by monkeypatching the exact name ``selective_build``
    imported: one artifact the plan required to rebuild is moved from
    ``executed`` to ``carried_forward`` before the real check runs, at the
    post-execution stage specifically.
    """
    real_check = selective.check_no_unexecuted_carry_forward

    def defect_at_post_execution(*, required_to_rebuild, executed, carried_forward, stage):
        if stage == ei.STAGE_POST_EXECUTION and required_to_rebuild:
            escaped = next(iter(required_to_rebuild))
            executed = executed - {escaped}
            carried_forward = carried_forward | {escaped}
        return real_check(
            required_to_rebuild=required_to_rebuild,
            executed=executed,
            carried_forward=carried_forward,
            stage=stage,
        )

    selective.check_no_unexecuted_carry_forward = defect_at_post_execution
    try:
        before, after = _reorder_pair()
        with pytest.raises(ei.InvariantViolation) as excinfo:
            selective.run_pair(before, after)
        assert ei.STAGE_POST_EXECUTION in str(excinfo.value)
    finally:
        selective.check_no_unexecuted_carry_forward = real_check


# --- CarryObservation / observe_no_unexecuted_carry_forward ----------------


def test_observe_reports_no_power_when_required_and_carried_never_intersect() -> None:
    """The disjoint-by-construction case: nothing required was ever carried
    forward, regardless of what ``executed`` says. This call could not have
    raised no matter what -- ``could_have_exhibited`` must say so plainly
    rather than reporting an unqualified clean pass.
    """
    observation = ei.observe_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed={"section:a"},
        carried_forward={"section:b"},
        stage=ei.STAGE_POST_EXECUTION,
    )
    assert observation.could_have_exhibited is False
    assert observation.violated == frozenset()
    assert observation.violation_count == 0


def test_observe_reports_power_and_no_violation_when_covered_by_execution() -> None:
    """Required overlaps carried-forward (the check had an opportunity to
    fail) but every such artifact was also executed, so it did not.
    """
    observation = ei.observe_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed={"section:a"},
        carried_forward={"section:a"},
        stage=ei.STAGE_PRE_ACTIVATION,
    )
    assert observation.could_have_exhibited is True
    assert observation.violated == frozenset()
    assert observation.violation_count == 0


def test_observe_reports_power_and_violation_together() -> None:
    observation = ei.observe_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed=set(),
        carried_forward={"section:a"},
        stage=ei.STAGE_POST_EXECUTION,
    )
    assert observation.could_have_exhibited is True
    assert observation.violated == frozenset({"section:a"})
    assert observation.violation_count == 1


def test_observe_as_record_shape() -> None:
    observation = ei.observe_no_unexecuted_carry_forward(
        required_to_rebuild={"section:a"},
        executed=set(),
        carried_forward={"section:a"},
        stage=ei.STAGE_POST_EXECUTION,
    )
    record = observation.as_record()
    assert record == {
        "stage": ei.STAGE_POST_EXECUTION,
        "required_to_rebuild_count": 1,
        "carried_forward_count": 1,
        "executed_count": 0,
        "violation_count": 1,
        "violated": ["section:a"],
        "could_have_exhibited": True,
    }


def test_observe_and_check_agree_on_the_violation_predicate() -> None:
    """The raising check and the observation must be the same predicate,
    computed twice, not two different definitions that happen to usually
    agree.
    """
    cases = [
        (set(), set(), set()),
        ({"a"}, {"a"}, set()),
        ({"a"}, set(), {"a"}),
        ({"a", "b"}, {"a"}, {"a", "b"}),
        ({"a", "b", "c"}, set(), {"a", "b", "c"}),
    ]
    for required, executed, carried in cases:
        observation = ei.observe_no_unexecuted_carry_forward(
            required_to_rebuild=required,
            executed=executed,
            carried_forward=carried,
            stage=ei.STAGE_POST_EXECUTION,
        )
        raised = False
        try:
            ei.check_no_unexecuted_carry_forward(
                required_to_rebuild=required,
                executed=executed,
                carried_forward=carried,
                stage=ei.STAGE_POST_EXECUTION,
            )
        except ei.InvariantViolation:
            raised = True
        assert raised == bool(observation.violated)


# --- CarryObservation wired into compiler/selective_build.py ---------------


def test_wiring_clean_path_carry_observations_are_present_and_have_no_power() -> None:
    """On the reorder fixture -- a natural pair with both rebuilt and
    carried-forward artifacts -- ``run_pair`` must report two observations,
    one per stage, and both must honestly read ``could_have_exhibited=False``:
    the classification loop's disjointness means neither call site had an
    opportunity to catch anything on this pair, which is the correct reading
    of a currently-closed seam, not a bug in the observation.
    """
    before, after = _reorder_pair()
    result = selective.run_pair(before, after)
    observations = result["carry_observations"]
    assert [o["stage"] for o in observations] == [
        ei.STAGE_POST_EXECUTION,
        ei.STAGE_PRE_ACTIVATION,
    ]
    for observation in observations:
        assert observation["could_have_exhibited"] is False
        assert observation["violation_count"] == 0
        assert observation["required_to_rebuild_count"] > 0, (
            "fixture must actually require a rebuild for the absence of power "
            "to be a meaningful statement"
        )


def test_wiring_raise_still_fires_before_observation_on_a_simulated_defect() -> None:
    """The raising check runs before the observation at each call site, so a
    genuine violation still stops the world -- the observation does not
    quietly downgrade it to a count.
    """
    real_check = selective.check_no_unexecuted_carry_forward

    def defect_at_post_execution(*, required_to_rebuild, executed, carried_forward, stage):
        if stage == ei.STAGE_POST_EXECUTION and required_to_rebuild:
            escaped = next(iter(required_to_rebuild))
            executed = executed - {escaped}
            carried_forward = carried_forward | {escaped}
        return real_check(
            required_to_rebuild=required_to_rebuild,
            executed=executed,
            carried_forward=carried_forward,
            stage=stage,
        )

    selective.check_no_unexecuted_carry_forward = defect_at_post_execution
    try:
        before, after = _reorder_pair()
        with pytest.raises(ei.InvariantViolation):
            selective.run_pair(before, after)
    finally:
        selective.check_no_unexecuted_carry_forward = real_check


def test_wiring_raises_on_a_simulated_pre_activation_scheduler_defect() -> None:
    """Same simulated defect, but only injected at the pre-activation stage,
    to prove the two call sites are independent -- a defect that only shows
    up right before activation is still caught even if the post-execution
    check upstream saw clean data.
    """
    real_check = selective.check_no_unexecuted_carry_forward

    def defect_at_pre_activation(*, required_to_rebuild, executed, carried_forward, stage):
        if stage == ei.STAGE_PRE_ACTIVATION and required_to_rebuild:
            escaped = next(iter(required_to_rebuild))
            executed = executed - {escaped}
            carried_forward = carried_forward | {escaped}
        return real_check(
            required_to_rebuild=required_to_rebuild,
            executed=executed,
            carried_forward=carried_forward,
            stage=stage,
        )

    selective.check_no_unexecuted_carry_forward = defect_at_pre_activation
    try:
        before, after = _reorder_pair()
        with pytest.raises(ei.InvariantViolation) as excinfo:
            selective.run_pair(before, after)
        assert ei.STAGE_PRE_ACTIVATION in str(excinfo.value)
    finally:
        selective.check_no_unexecuted_carry_forward = real_check
