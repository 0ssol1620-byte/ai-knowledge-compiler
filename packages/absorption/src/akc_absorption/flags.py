"""`ABSORB_*` gates. All default false, all shadow only.

Contract §0.1: no challenger touches a production write path, and challenger
execution sits behind a flag that is off unless someone turned it on for an
experiment run. The flag is the runtime half of that; the structural half is
that this package is not in the wheel at all (see `README.md`).

A flag being on never means the challenger's answer is authoritative. It means
the challenger is allowed to *compute* an answer, which an experiment harness
then records beside the current one. Promotion is the six gates in §0.5, not a
flag flip.
"""

from __future__ import annotations

import os

__all__ = [
    "ABSORB_ALIGNMENT_DIFF",
    "ABSORB_RETRIEVAL_FIXTURE",
    "AbsorptionFlagError",
    "flag_enabled",
    "require_flag",
]

#: EXP-0101 — alignment-first heterogeneous diff challenger.
ABSORB_ALIGNMENT_DIFF = "ABSORB_ALIGNMENT_DIFF"

#: EXP-0103 — adaptive multi-granular retrieval fixture construction.
ABSORB_RETRIEVAL_FIXTURE = "ABSORB_RETRIEVAL_FIXTURE"

#: Only these spellings turn a flag on. Anything else -- including "yes", "on"
#: and the empty string -- is off, because a flag that guards a shadow path
#: should fail towards off when its value is unexpected.
_TRUE = frozenset({"1", "true", "TRUE", "True"})


class AbsorptionFlagError(RuntimeError):
    """Raised when a challenger entry point runs with its flag off.

    Deliberately not a silent no-op return. A challenger that quietly does
    nothing looks in a log exactly like a challenger that ran and found no
    difference, and the repository's no-silent-fallback rule exists to stop
    that reading.
    """


def flag_enabled(name: str, env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(name, "") in _TRUE


def require_flag(name: str, env: dict[str, str] | None = None) -> None:
    if not flag_enabled(name, env):
        raise AbsorptionFlagError(
            f"{name} is not set. This is a shadow-only absorption challenger; "
            "it runs under an experiment harness that sets the flag, never as "
            "part of a production path."
        )
