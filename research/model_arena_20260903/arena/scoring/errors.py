"""Failures this lane can produce, separated the way the campaign reasons.

An *operational* failure (the evaluator process died, its output file is
absent) is not a *semantic* failure (the model scored badly). Masterplan
section 16 keeps them apart everywhere else in the campaign, and scoring is
where the two are easiest to confuse: a crashed evaluator that is written
down as ``0.0`` looks exactly like a model that produced nothing.
"""

from __future__ import annotations

__all__ = [
    "EvaluatorBlockedError",
    "InputError",
    "LayoutError",
    "ProvenanceError",
    "QaGateError",
    "ScoringError",
]


class ScoringError(RuntimeError):
    """Base class for every failure raised by ``arena.scoring``."""


class InputError(ScoringError):
    """A campaign file this lane reads is missing, malformed or inconsistent."""


class QaGateError(ScoringError):
    """The masterplan section 44 gate is missing or red for this output set."""


class LayoutError(ScoringError):
    """Canonical output cannot be laid out the way an evaluator expects."""


class EvaluatorBlockedError(ScoringError):
    """The official evaluator did not produce a result.

    ``stderr_tail`` is carried so the caller can persist the operational
    evidence. The absence of a score is recorded as ``EVALUATOR_BLOCKED``;
    it is never recorded as a zero.
    """

    def __init__(
        self,
        message: str,
        *,
        stderr_tail: str = "",
        returncode: int | None = None,
        timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail
        self.returncode = returncode
        self.timed_out = timed_out


class ProvenanceError(ScoringError):
    """A score row cannot be walked back to the bytes it came from."""
