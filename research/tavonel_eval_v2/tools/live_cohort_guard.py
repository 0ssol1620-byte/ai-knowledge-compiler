#!/usr/bin/env python3
"""Refuse a live-cohort entry point that is called from a test runner.

The anti-blocker audit reports three tools as `real-cohort access reachable from
pytest`: `preflight_sfi3_roots`, `gpu_successor_preflight` and
`v2r4_preacquisition_gate`. Each exposes a `run()` that reaches out to real
roots, and each is importable by any test that names it. As the audit puts it,
an accidental import was the only thing standing between a stray call and a live
traversal.

The failure this prevents is not a crash. A stray traversal *succeeds*: it walks
the real roots, spends real request budget against real endpoints, and -- worst
-- it observes. This study's whole method rests on doing that exactly once,
under a frozen protocol, with the result recorded. A test that quietly performed
one would be indistinguishable afterwards from one that did not.

Deliberately an exception rather than a no-op return. A guard that returned an
empty result would let a test believe it had run a preflight and got nothing,
which is the same class of defect as a forensic set that quietly shrinks.

Why the check is `sys.modules` and not an environment variable: `pytest` appears
in `sys.modules` for the whole process once the runner has imported it, so it is
true during collection as well as during a test. `PYTEST_CURRENT_TEST` is set
only while a test executes, which would leave module-level and fixture-level
calls unguarded -- and a call at import time is exactly the accident being
guarded against.

`allow_under_test` exists for the controls that must prove this refusal fires
and that the guarded function still works when it does not. Without it, no test
could reach `run()` at all and the guard's own positive control would be
impossible to write.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

#: Set only by `allow_under_test`. Module state rather than a parameter so a
#: caller cannot pass it by accident.
_ALLOWED = False


class LiveCohortRefused(RuntimeError):
    """A cohort-touching entry point was called from a test runner."""


def under_test() -> bool:
    """True when a test runner has been imported into this process."""
    return "pytest" in sys.modules or "unittest" in sys.modules


def refuse_under_test(entry: str) -> None:
    """Raise if `entry` is being called from a test runner.

    Call it as the FIRST statement of the entry point, before any request is
    issued, so a refusal costs nothing and leaves no partial observation.
    """
    if _ALLOWED or not under_test():
        return
    raise LiveCohortRefused(
        f"{entry} touches a live cohort and was called from a test runner. "
        "A stray traversal here would spend real request budget against real "
        "endpoints and would OBSERVE, which this study may do only once under a "
        "frozen protocol. Use live_cohort_guard.allow_under_test() if a control "
        "genuinely needs to reach this entry point."
    )


@contextmanager
def allow_under_test() -> Iterator[None]:
    """Permit a guarded entry point for the duration of the block."""
    global _ALLOWED
    previous, _ALLOWED = _ALLOWED, True
    try:
        yield
    finally:
        _ALLOWED = previous
