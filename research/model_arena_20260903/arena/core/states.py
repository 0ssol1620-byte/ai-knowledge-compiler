"""Controller and worker state machines (masterplan sections 33 and 34).

Both machines are explicit allow-lists. There is no "any state may move to
any state" escape hatch, and :func:`transition` raises rather than logging a
warning, because the event log built from these transitions is the only
record of what the campaign actually did.

The one rule the masterplan states in prose is enforced structurally here:
a ``STALLED`` worker never returns to ``READY`` or ``BUSY``. Its only exit is
``TERMINATED``. The same holds for ``OOM``, ``CRASHED`` and ``QUARANTINED``
(masterplan section 34).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from arena.constants import CONTROLLER_STATES, WORKER_STATES

__all__ = [
    "ALLOWED_CONTROLLER_TRANSITIONS",
    "ALLOWED_TRANSITIONS",
    "ALLOWED_WORKER_TRANSITIONS",
    "ControllerState",
    "IllegalTransition",
    "StateMachineKind",
    "WorkerState",
    "allowed_transitions",
    "is_terminal",
    "transition",
]


class IllegalTransition(ValueError):
    """Raised when a state change is not in the machine's allow-list."""


class StateMachineKind(StrEnum):
    CONTROLLER = "controller"
    WORKER = "worker"


class ControllerState(StrEnum):
    """Masterplan section 33, mirrored from ``arena.constants``."""

    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    RUNTIME_BUILDING = "RUNTIME_BUILDING"
    CANARY = "CANARY"
    QUALIFIED = "QUALIFIED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    OUTPUT_FROZEN = "OUTPUT_FROZEN"
    SCORED = "SCORED"
    REPORTED = "REPORTED"
    CANARY_FAILED = "CANARY_FAILED"
    RUNTIME_QUARANTINED = "RUNTIME_QUARANTINED"
    BUDGET_PAUSED = "BUDGET_PAUSED"
    SUBSCRIPTION_PAUSED = "SUBSCRIPTION_PAUSED"
    SOURCE_QUARANTINED = "SOURCE_QUARANTINED"
    EVALUATOR_BLOCKED = "EVALUATOR_BLOCKED"


class WorkerState(StrEnum):
    """Masterplan section 34, mirrored from ``arena.constants``."""

    PROVISIONING = "PROVISIONING"
    IMAGE_READY = "IMAGE_READY"
    MODEL_LOADING = "MODEL_LOADING"
    WARMING = "WARMING"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    TERMINATED = "TERMINATED"
    STALLED = "STALLED"
    OOM = "OOM"
    CRASHED = "CRASHED"
    QUARANTINED = "QUARANTINED"


for _enum, _constant, _label in (
    (ControllerState, CONTROLLER_STATES, "CONTROLLER_STATES"),
    (WorkerState, WORKER_STATES, "WORKER_STATES"),
):
    if tuple(member.value for member in _enum) != _constant:  # pragma: no cover
        raise RuntimeError(
            f"arena.core.states.{_enum.__name__} drifted from arena.constants.{_label}; "
            "the constants file is the single source of truth"
        )
del _enum, _constant, _label


_C = ControllerState
_W = WorkerState

# Forward chain plus the failure states of masterplan section 33. A failure
# state is not terminal on its own: a quarantined runtime can be rebuilt and
# a paused campaign can resume, but only back onto the phase it left.
ALLOWED_CONTROLLER_TRANSITIONS: Final[Mapping[ControllerState, frozenset[ControllerState]]] = (
    MappingProxyType(
        {
            _C.DISCOVERED: frozenset({_C.REGISTERED}),
            _C.REGISTERED: frozenset({_C.RUNTIME_BUILDING, _C.RUNTIME_QUARANTINED}),
            _C.RUNTIME_BUILDING: frozenset({_C.CANARY, _C.RUNTIME_QUARANTINED}),
            _C.CANARY: frozenset(
                {
                    _C.QUALIFIED,
                    _C.CANARY_FAILED,
                    _C.RUNTIME_QUARANTINED,
                    _C.BUDGET_PAUSED,
                    _C.SUBSCRIPTION_PAUSED,
                }
            ),
            _C.QUALIFIED: frozenset({_C.QUEUED, _C.RUNTIME_QUARANTINED, _C.BUDGET_PAUSED}),
            _C.QUEUED: frozenset(
                {
                    _C.RUNNING,
                    _C.BUDGET_PAUSED,
                    _C.SUBSCRIPTION_PAUSED,
                    _C.RUNTIME_QUARANTINED,
                }
            ),
            _C.RUNNING: frozenset(
                {
                    _C.OUTPUT_FROZEN,
                    _C.RUNTIME_QUARANTINED,
                    _C.SOURCE_QUARANTINED,
                    _C.BUDGET_PAUSED,
                    _C.SUBSCRIPTION_PAUSED,
                }
            ),
            _C.OUTPUT_FROZEN: frozenset({_C.SCORED, _C.EVALUATOR_BLOCKED}),
            _C.SCORED: frozenset({_C.REPORTED}),
            _C.REPORTED: frozenset(),
            # Failure states and their single documented way back.
            _C.CANARY_FAILED: frozenset({_C.RUNTIME_BUILDING}),
            _C.RUNTIME_QUARANTINED: frozenset({_C.RUNTIME_BUILDING}),
            _C.BUDGET_PAUSED: frozenset({_C.CANARY, _C.QUEUED, _C.RUNNING}),
            _C.SUBSCRIPTION_PAUSED: frozenset({_C.CANARY, _C.QUEUED, _C.RUNNING}),
            # The bad source is quarantined; the run continues on the rest.
            _C.SOURCE_QUARANTINED: frozenset({_C.RUNNING}),
            # Scoring is retried from the frozen outputs, never from new inference.
            _C.EVALUATOR_BLOCKED: frozenset({_C.OUTPUT_FROZEN}),
        }
    )
)

ALLOWED_WORKER_TRANSITIONS: Final[Mapping[WorkerState, frozenset[WorkerState]]] = MappingProxyType(
    {
        _W.PROVISIONING: frozenset({_W.IMAGE_READY, _W.CRASHED, _W.TERMINATED}),
        _W.IMAGE_READY: frozenset({_W.MODEL_LOADING, _W.CRASHED, _W.TERMINATED}),
        _W.MODEL_LOADING: frozenset({_W.WARMING, _W.OOM, _W.STALLED, _W.CRASHED, _W.TERMINATED}),
        _W.WARMING: frozenset(
            {_W.READY, _W.OOM, _W.STALLED, _W.CRASHED, _W.QUARANTINED, _W.TERMINATED}
        ),
        _W.READY: frozenset({_W.BUSY, _W.DRAINING, _W.STALLED, _W.CRASHED, _W.TERMINATED}),
        _W.BUSY: frozenset(
            {
                _W.READY,
                _W.DRAINING,
                _W.STALLED,
                _W.OOM,
                _W.CRASHED,
                _W.QUARANTINED,
                _W.TERMINATED,
            }
        ),
        _W.DRAINING: frozenset({_W.TERMINATED, _W.CRASHED}),
        # Masterplan section 34: an abnormal worker is never handed a new job.
        _W.STALLED: frozenset({_W.TERMINATED}),
        _W.OOM: frozenset({_W.TERMINATED}),
        _W.CRASHED: frozenset({_W.TERMINATED}),
        _W.QUARANTINED: frozenset({_W.TERMINATED}),
        _W.TERMINATED: frozenset(),
    }
)

ALLOWED_TRANSITIONS: Final[Mapping[StateMachineKind, Mapping[str, frozenset[str]]]] = (
    MappingProxyType(
        {
            StateMachineKind.CONTROLLER: MappingProxyType(
                {
                    state.value: frozenset(target.value for target in targets)
                    for state, targets in ALLOWED_CONTROLLER_TRANSITIONS.items()
                }
            ),
            StateMachineKind.WORKER: MappingProxyType(
                {
                    state.value: frozenset(target.value for target in targets)
                    for state, targets in ALLOWED_WORKER_TRANSITIONS.items()
                }
            ),
        }
    )
)


def _resolve_kind(kind: StateMachineKind | str) -> StateMachineKind:
    try:
        return StateMachineKind(kind)
    except ValueError as exc:
        raise IllegalTransition(
            f"unknown state machine {kind!r}; expected 'controller' or 'worker'"
        ) from exc


def _resolve_state(kind: StateMachineKind, value: str, field: str) -> str:
    enum_cls: type[StrEnum] = (
        ControllerState if kind is StateMachineKind.CONTROLLER else WorkerState
    )
    try:
        return str(enum_cls(value))
    except ValueError as exc:
        raise IllegalTransition(f"{field} {value!r} is not a {kind.value} state") from exc


def allowed_transitions(kind: StateMachineKind | str) -> Mapping[str, frozenset[str]]:
    """The allow-list for one machine, keyed by state value."""

    return ALLOWED_TRANSITIONS[_resolve_kind(kind)]


def is_terminal(kind: StateMachineKind | str, state: str) -> bool:
    """True when the state has no outgoing transition at all."""

    resolved_kind = _resolve_kind(kind)
    resolved_state = _resolve_state(resolved_kind, state, "state")
    return not ALLOWED_TRANSITIONS[resolved_kind][resolved_state]


def transition(kind: StateMachineKind | str, from_state: str, to_state: str) -> str:
    """Validate one state change and return ``to_state``.

    Raises :class:`IllegalTransition` for an unknown machine, an unknown state,
    a self-transition (which is not a transition and would pollute the event
    log) or a move that the allow-list does not contain.
    """

    resolved_kind = _resolve_kind(kind)
    source = _resolve_state(resolved_kind, from_state, "from_state")
    target = _resolve_state(resolved_kind, to_state, "to_state")
    if source == target:
        raise IllegalTransition(
            f"{resolved_kind.value} state {source} to itself is not a transition"
        )
    allowed = ALLOWED_TRANSITIONS[resolved_kind][source]
    if target not in allowed:
        raise IllegalTransition(
            f"{resolved_kind.value} may not move {source} -> {target}; "
            f"allowed from {source}: {sorted(allowed) or 'none (terminal)'}"
        )
    return target
