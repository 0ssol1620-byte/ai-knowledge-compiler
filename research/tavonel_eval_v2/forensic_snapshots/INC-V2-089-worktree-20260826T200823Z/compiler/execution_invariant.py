#!/usr/bin/env python3
"""Fail-stop guard against reusing a rebuild-required artifact whose rebuild
was never actually executed.

SOURCE_FACT_IR_HELDOUT_V2 found 14 confirmed selective stale escapes. Its
typed cross-check reported clean, but only over its own downstream
denominator: 191 of 191 pairs that had already entered the cross-check named
every artifact that check could see, zero under-invalidated there. That does
NOT mean the typed dependency delta named every artifact that actually
moved -- the cross-check's denominator sits downstream of change detection,
and a defect upstream of it is invisible to it. INC-V2-037 found that defect
upstream, in change detection: identity equivalence reused as change
equivalence. It is not an execution defect, and the forensic trace confirmed
the seam this module guards was never where the 14 cases broke -- the
scheduler cannot drop a member of ``required_to_rebuild`` and the
classification loop structurally guarantees planned intersect carried is
empty for those 14 cases. This module's invariant is a fail-stop veto on a
seam the forensic found closed, not a diagnosis of what was open. It stays,
expressed once so both call sites in ``selective_build.py`` share the same
definition:

    required_to_rebuild ∩ (carried_forward - executed) == ∅

A rebuild-required artifact may be reused only after its declared rebuild was
actually executed. "Declared" (appearing in ``required_to_rebuild``, i.e. the
plan) is not "executed" -- a scheduler that planned a rebuild and skipped it
must not be able to satisfy this check by pointing at the plan.

Fail-stop: this raises. There is no flag, argument or environment variable
that downgrades a violation to a warning, and none should be added.
"""

from __future__ import annotations

from dataclasses import dataclass

STAGE_POST_EXECUTION = "post_execution"
STAGE_PRE_ACTIVATION = "pre_activation"


class InvariantViolation(RuntimeError):
    """A rebuild-required artifact was reused without its rebuild being executed."""


def check_no_unexecuted_carry_forward(
    *,
    required_to_rebuild: set[str],
    executed: set[str],
    carried_forward: set[str],
    stage: str,
) -> None:
    """Raise ``InvariantViolation`` when
    ``required_to_rebuild & (carried_forward - executed)`` is non-empty.

    An artifact satisfies this check only by appearing in ``executed``.
    Appearing in ``required_to_rebuild`` (the plan) proves nothing about what
    actually ran; appearing in ``carried_forward`` without also appearing in
    ``executed`` means the prior, pre-change value reached this stage in
    place of a proven rebuild.
    """
    unexecuted_carry_forward = carried_forward - executed
    violations = sorted(required_to_rebuild & unexecuted_carry_forward)
    if violations:
        raise InvariantViolation(
            f"[{stage}] {len(violations)} artifact(s) required to rebuild "
            f"reached this stage as an unexecuted carry-forward (reused "
            f"without their rebuild being executed): {violations}"
        )


@dataclass(frozen=True, slots=True)
class CarryObservation:
    """The non-raising sibling of a ``check_no_unexecuted_carry_forward`` call:
    a record of what was checked, not just whether it passed.

    ``could_have_exhibited`` is the field that keeps a clean observation from
    being read as more than it is. It answers a different question than
    "did it violate": was there even an artifact that was both
    required-to-rebuild and carried-forward at all, before ``executed`` is
    consulted? If ``required_to_rebuild`` and ``carried_forward`` never
    intersect, this call could not have raised no matter what the caller
    passed as ``executed`` -- the check had no opportunity to fail, and a
    clean result proves nothing about the seam it sits at. Reporting such a
    call as an unqualified "0 violations" would be exactly the class of
    declaration-nobody-reads-against-the-behaviour this module exists to
    rule out.
    """

    stage: str
    required_to_rebuild: frozenset[str]
    executed: frozenset[str]
    carried_forward: frozenset[str]
    violated: frozenset[str]
    could_have_exhibited: bool

    @property
    def violation_count(self) -> int:
        return len(self.violated)

    def as_record(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "required_to_rebuild_count": len(self.required_to_rebuild),
            "carried_forward_count": len(self.carried_forward),
            "executed_count": len(self.executed),
            "violation_count": len(self.violated),
            "violated": sorted(self.violated),
            "could_have_exhibited": self.could_have_exhibited,
        }


def observe_no_unexecuted_carry_forward(
    *,
    required_to_rebuild: set[str],
    executed: set[str],
    carried_forward: set[str],
    stage: str,
) -> CarryObservation:
    """Compute the same predicate as ``check_no_unexecuted_carry_forward``
    without raising, and record whether this call was even in a position to
    catch a violation.

    This does not replace the raising check -- it is called alongside it so
    a clean run leaves behind a count (and a power flag) instead of only the
    absence of an exception.
    """
    required = frozenset(required_to_rebuild)
    carried = frozenset(carried_forward)
    executed_set = frozenset(executed)
    violated = required & (carried - executed_set)
    return CarryObservation(
        stage=stage,
        required_to_rebuild=required,
        executed=executed_set,
        carried_forward=carried,
        violated=violated,
        could_have_exhibited=bool(required & carried),
    )
