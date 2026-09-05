"""State machines: legal chains, refused shortcuts, and the STALLED rule."""

from __future__ import annotations

from itertools import pairwise

import pytest
from arena.constants import CONTROLLER_STATES, WORKER_STATES
from arena.core.states import (
    ALLOWED_CONTROLLER_TRANSITIONS,
    ALLOWED_WORKER_TRANSITIONS,
    ControllerState,
    IllegalTransition,
    WorkerState,
    allowed_transitions,
    is_terminal,
    transition,
)

CONTROLLER_CHAIN = [
    "DISCOVERED",
    "REGISTERED",
    "RUNTIME_BUILDING",
    "CANARY",
    "QUALIFIED",
    "QUEUED",
    "RUNNING",
    "OUTPUT_FROZEN",
    "SCORED",
    "REPORTED",
]

WORKER_CHAIN = [
    "PROVISIONING",
    "IMAGE_READY",
    "MODEL_LOADING",
    "WARMING",
    "READY",
    "BUSY",
    "READY",
    "DRAINING",
    "TERMINATED",
]


def test_enums_mirror_the_constants_exactly() -> None:
    assert tuple(member.value for member in ControllerState) == CONTROLLER_STATES
    assert tuple(member.value for member in WorkerState) == WORKER_STATES


def test_every_state_has_an_entry_in_its_allow_list() -> None:
    assert set(ALLOWED_CONTROLLER_TRANSITIONS) == set(ControllerState)
    assert set(ALLOWED_WORKER_TRANSITIONS) == set(WorkerState)


def test_the_masterplan_33_forward_chain_is_walkable() -> None:
    for source, target in pairwise(CONTROLLER_CHAIN):
        assert transition("controller", source, target) == target


def test_the_masterplan_34_worker_chain_is_walkable() -> None:
    for source, target in pairwise(WORKER_CHAIN):
        assert transition("worker", source, target) == target


@pytest.mark.parametrize("target", ["READY", "BUSY", "DRAINING", "MODEL_LOADING", "WARMING"])
def test_a_stalled_worker_never_returns_to_service(target: str) -> None:
    with pytest.raises(IllegalTransition):
        transition("worker", "STALLED", target)


@pytest.mark.parametrize("source", ["STALLED", "OOM", "CRASHED", "QUARANTINED"])
def test_an_abnormal_worker_may_only_be_terminated(source: str) -> None:
    assert allowed_transitions("worker")[source] == frozenset({"TERMINATED"})
    assert transition("worker", source, "TERMINATED") == "TERMINATED"


def test_terminal_states_have_no_exit() -> None:
    assert is_terminal("controller", "REPORTED")
    assert is_terminal("worker", "TERMINATED")
    assert not is_terminal("controller", "RUNNING")
    with pytest.raises(IllegalTransition):
        transition("worker", "TERMINATED", "READY")


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("DISCOVERED", "RUNNING"),
        ("QUEUED", "SCORED"),
        ("CANARY", "REPORTED"),
        ("OUTPUT_FROZEN", "RUNNING"),
        ("EVALUATOR_BLOCKED", "SCORED"),
    ],
)
def test_the_controller_cannot_skip_a_phase(source: str, target: str) -> None:
    with pytest.raises(IllegalTransition):
        transition("controller", source, target)


def test_a_failed_canary_goes_back_through_a_runtime_rebuild() -> None:
    assert transition("controller", "CANARY", "CANARY_FAILED") == "CANARY_FAILED"
    assert transition("controller", "CANARY_FAILED", "RUNTIME_BUILDING") == "RUNTIME_BUILDING"
    with pytest.raises(IllegalTransition):
        transition("controller", "CANARY_FAILED", "QUALIFIED")


def test_a_blocked_evaluator_is_retried_from_the_frozen_outputs() -> None:
    assert transition("controller", "OUTPUT_FROZEN", "EVALUATOR_BLOCKED") == "EVALUATOR_BLOCKED"
    assert transition("controller", "EVALUATOR_BLOCKED", "OUTPUT_FROZEN") == "OUTPUT_FROZEN"


def test_a_pause_resumes_only_onto_the_phase_it_left() -> None:
    for phase in ("CANARY", "QUEUED", "RUNNING"):
        assert transition("controller", "BUDGET_PAUSED", phase) == phase
    with pytest.raises(IllegalTransition):
        transition("controller", "BUDGET_PAUSED", "SCORED")


def test_a_self_transition_is_not_a_transition() -> None:
    with pytest.raises(IllegalTransition, match="to itself"):
        transition("controller", "RUNNING", "RUNNING")


@pytest.mark.parametrize(
    ("kind", "source", "target"),
    [
        ("controller", "READY", "BUSY"),
        ("worker", "RUNNING", "OUTPUT_FROZEN"),
        ("scheduler", "READY", "BUSY"),
        ("worker", "READY", "NOT_A_STATE"),
    ],
)
def test_unknown_machines_and_states_are_refused(kind: str, source: str, target: str) -> None:
    with pytest.raises(IllegalTransition):
        transition(kind, source, target)


def test_allowed_transitions_is_read_only_data() -> None:
    table = allowed_transitions("worker")
    assert isinstance(table["READY"], frozenset)
    with pytest.raises(TypeError):
        table["READY"] = frozenset()  # type: ignore[index]
