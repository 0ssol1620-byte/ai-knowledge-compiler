"""Failure types for the TAVONEL replay lane.

Every one of these is fatal by design. This lane never degrades to a partial
answer: a missing input is reported and the command stops, because a route
decision computed from half its evidence is worse than no route decision.
"""

from __future__ import annotations


class TavonelError(RuntimeError):
    """Base class for every failure raised by ``arena.tavonel``."""


class GtBoundaryViolation(TavonelError):
    """A read was attempted against a root this lane must never open."""


class MissingInputError(TavonelError):
    """A required frozen input (receipt, output, manifest row) is absent."""


class IntegrityError(TavonelError):
    """A stored hash does not match the bytes on disk."""


class FreezeOrderError(TavonelError):
    """The masterplan section 2.2 order (freeze routes before scoring) was broken."""


class PolicyError(TavonelError):
    """A policy was asked for something its parameters cannot answer."""


__all__ = [
    "FreezeOrderError",
    "GtBoundaryViolation",
    "IntegrityError",
    "MissingInputError",
    "PolicyError",
    "TavonelError",
]
