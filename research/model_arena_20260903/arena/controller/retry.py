"""Retry policy — masterplan section 15.9, as data.

The masterplan's own sentence is the design constraint:

    "같은 deterministic runtime error를 100번 retry하는 것이 가장 비싼 실패 패턴이다."

So every rule carries the table row it came from. An error class the table does
not mention gets ``max_retries=0`` with an explicit reason, never an invented
allowance — fail closed rather than guess that a new failure mode is transient.

Lane A1 may publish ``arena.core.errors.RETRY_POLICY``. If it exists it is
authoritative and this module adopts it; :func:`policy_source` says which.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from arena.constants import ERROR_CLASSES

__all__ = [
    "RETRY_POLICY",
    "WORKER_LOST",
    "RetryAction",
    "RetryDecision",
    "RetryRule",
    "decide",
    "policy_source",
    "rule_for",
]

WORKER_LOST: Final = "WORKER_LOST"
"""Pseudo class for the MP 15.9 "worker lost" row: the pod vanished mid-job."""

POLICY_SOURCE_CORE: Final = "arena.core.errors.RETRY_POLICY"
POLICY_SOURCE_LOCAL: Final = "arena.controller.retry.RETRY_POLICY"


class RetryAction:
    """What the controller does after this failure, beyond re-queueing."""

    NONE: Final = "none"
    BACKOFF: Final = "backoff_and_retry"
    OTHER_REPLICA: Final = "retry_on_other_replica"
    RESPECT_RETRY_AFTER: Final = "respect_retry_after"
    REQUEUE_SAME_ID: Final = "requeue_same_job_id"
    REDUCE_CONCURRENCY: Final = "reduce_concurrency_then_retry"
    DRAIN_WORKER: Final = "drain_worker_and_fix_runtime"
    QUARANTINE_RUNTIME: Final = "quarantine_runtime"
    QUARANTINE_SOURCE: Final = "quarantine_source"
    QUARANTINE_JOB: Final = "quarantine_job"
    EVALUATOR_SIDE_FIX: Final = "evaluator_side_fix"


@dataclass(frozen=True, slots=True)
class RetryRule:
    error_class: str
    max_retries: int
    action: str
    mp_row: str
    backoff_seconds: tuple[float, ...] = ()
    respect_retry_after: bool = False

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")

    @property
    def quarantines(self) -> bool:
        """Does exhausting this rule quarantine rather than merely fail?

        Read structurally from the action text rather than from an identity
        comparison against this module's constants: when lane A1's table is
        adopted the action is A1's prose ("quarantine the runtime", "quarantine
        the source sample"), and a controller that only recognised its own
        constants would silently stop quarantining anything.
        """

        return "quarantine" in self.action.casefold()


# Lane A1 states a backoff *kind*; the controller needs a schedule. This is the
# one translation between the two shapes, kept in one place so a change to
# either side is a single edit rather than a scatter of magic numbers.
_BACKOFF_SCHEDULES: Final[Mapping[str, tuple[float, ...]]] = {
    "none": (0.0,),
    "exponential_jitter": (2.0, 8.0, 30.0),
    "retry_after": (5.0, 20.0, 60.0),
}


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    rule: RetryRule
    delay_seconds: float
    reason: str


# Masterplan section 15.9, row for row. Nothing here is inferred.
_RULES: Final = (
    RetryRule("INFRA_NETWORK", 3, RetryAction.BACKOFF, "transient network", (2.0, 8.0, 30.0)),
    RetryRule(
        "RATE_LIMIT",
        3,
        RetryAction.RESPECT_RETRY_AFTER,
        "429/rate limit",
        (5.0, 20.0, 60.0),
        respect_retry_after=True,
    ),
    RetryRule(
        "INFRA_CAPACITY", 3, RetryAction.OTHER_REPLICA, "provider capacity", (5.0, 15.0, 45.0)
    ),
    RetryRule(WORKER_LOST, 2, RetryAction.REQUEUE_SAME_ID, "worker lost", (0.0, 5.0)),
    RetryRule("CUDA_OOM", 1, RetryAction.REDUCE_CONCURRENCY, "OOM", (0.0,)),
    RetryRule("OUTPUT_MALFORMED", 1, RetryAction.NONE, "malformed one-off response", (0.0,)),
    RetryRule(
        "OUTPUT_EMPTY", 1, RetryAction.QUARANTINE_JOB, "deterministic schema failure", (0.0,)
    ),
    RetryRule(
        "OUTPUT_TRUNCATED", 1, RetryAction.QUARANTINE_JOB, "deterministic schema failure", (0.0,)
    ),
    RetryRule(
        "OUTPUT_REPETITION", 1, RetryAction.QUARANTINE_JOB, "deterministic schema failure", (0.0,)
    ),
    RetryRule("DEPENDENCY", 0, RetryAction.DRAIN_WORKER, "dependency/import error"),
    RetryRule("MODEL_LOAD", 0, RetryAction.DRAIN_WORKER, "model load failure"),
    RetryRule("TENSOR_SHAPE", 0, RetryAction.QUARANTINE_RUNTIME, "repeated tensor-shape error"),
    RetryRule("CHECKSUM", 0, RetryAction.QUARANTINE_SOURCE, "corrupt source"),
    RetryRule("EVALUATOR", 0, RetryAction.EVALUATOR_SIDE_FIX, "GT/evaluator error"),
)

_NO_ROW: Final = "no masterplan 15.9 row; fail closed"

RETRY_POLICY: Final[Mapping[str, RetryRule]] = {
    **{
        error_class: RetryRule(error_class, 0, RetryAction.QUARANTINE_JOB, _NO_ROW)
        for error_class in ERROR_CLASSES
    },
    **{rule.error_class: rule for rule in _RULES},
}


def _core_policy() -> Mapping[str, RetryRule] | None:
    """Adopt lane A1's table when it exists, translated into this shape.

    A1 owns the section 15.9 table and states a backoff *kind*
    (``none`` / ``exponential_jitter`` / ``retry_after``); the controller needs
    a concrete schedule, so the kind is expanded through
    :data:`_BACKOFF_SCHEDULES`. Every number A1 states -- ``max_retries``,
    ``action``, ``mp_row`` -- is taken verbatim; nothing is overridden here.

    ``WORKER_LOST`` is a controller-side pseudo class (a pod that vanished is
    not an error the worker reported), so the local rule for it is kept
    alongside A1's rows rather than dropped.
    """

    try:
        from arena.core import errors as core_errors
    except ImportError:
        return None
    policy = getattr(core_errors, "RETRY_POLICY", None)
    if not isinstance(policy, Mapping) or not policy:
        return None
    adopted: dict[str, RetryRule] = {}
    for key, value in policy.items():
        name = str(key)
        max_retries = getattr(value, "max_retries", None)
        if not isinstance(max_retries, int) or isinstance(max_retries, bool):
            # An unexpected shape is not silently half-adopted.
            return None
        kind = str(getattr(value, "backoff", "none"))
        schedule = getattr(value, "backoff_seconds", None)
        adopted[name] = RetryRule(
            error_class=name,
            max_retries=max_retries,
            action=str(getattr(value, "action", RetryAction.NONE)),
            mp_row=str(getattr(value, "mp_row", "arena.core.errors")),
            backoff_seconds=(
                tuple(float(item) for item in schedule)
                if schedule
                else _BACKOFF_SCHEDULES.get(kind, (0.0,))
            ),
            respect_retry_after=kind == "retry_after",
        )
    adopted.setdefault(WORKER_LOST, RETRY_POLICY[WORKER_LOST])
    return adopted


def policy_source() -> str:
    return POLICY_SOURCE_LOCAL if _core_policy() is None else POLICY_SOURCE_CORE


def rule_for(error_class: str) -> RetryRule:
    policy = _core_policy() or RETRY_POLICY
    rule = policy.get(error_class)
    if rule is not None:
        return rule
    if error_class not in ERROR_CLASSES and error_class != WORKER_LOST:
        raise ValueError(f"error_class {error_class!r} is outside the taxonomy")
    return RetryRule(error_class, 0, RetryAction.QUARANTINE_JOB, _NO_ROW)


def decide(
    error_class: str,
    *,
    retry_count: int,
    retry_after_seconds: float | None = None,
) -> RetryDecision:
    """Should this failed job be retried, and after how long?"""

    rule = rule_for(error_class)
    if retry_count >= rule.max_retries:
        return RetryDecision(
            retry=False,
            rule=rule,
            delay_seconds=0.0,
            reason=(
                f"{error_class}: {rule.mp_row} allows {rule.max_retries} retries, "
                f"{retry_count} already spent"
            ),
        )
    if rule.backoff_seconds:
        index = min(retry_count, len(rule.backoff_seconds) - 1)
        delay = rule.backoff_seconds[index]
    else:
        delay = 0.0
    honours_retry_after = (
        rule.respect_retry_after or rule.action == RetryAction.RESPECT_RETRY_AFTER
    )
    if honours_retry_after and retry_after_seconds is not None:
        delay = max(delay, retry_after_seconds)
    return RetryDecision(
        retry=True,
        rule=rule,
        delay_seconds=delay,
        reason=f"{error_class}: {rule.mp_row} allows retry {retry_count + 1}/{rule.max_retries}",
    )
