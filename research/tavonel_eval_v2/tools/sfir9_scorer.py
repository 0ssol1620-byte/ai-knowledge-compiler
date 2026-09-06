#!/usr/bin/env python3
"""Capacity, scored so that a stop can never be reported as a measurement.

SFIR7 recorded twenty of fifty roots as measured when the instrument had merely
run out of frontier budget. The count it produced was not wrong about what it had
seen; it was wrong about what it had *not* seen, and it presented the difference
as if there were none. That is the failure this module is built around.

**Every root is exhausted, stopped, or refused, and the three are never merged.**
A root whose frontier emptied has been measured: its candidate count is the count.
A root that stopped -- rate window, storage budget, segment boundary -- has a
count that is a floor and nothing more. A root refused on identity contributes
nothing at all and is not in the denominator either, because it was never
measured.

**So the total is two numbers, not one.** A lower bound that is certain, and a
completeness statement saying how much of the cohort produced it. When every root
is exhausted the two coincide and the count is exact. When any root stopped, the
lower bound is honest and the exact figure does not exist.

**And the verdict has three outcomes, not two.** More candidates can only push a
count up, so a lower bound already above the threshold settles the question --
PASS holds no matter what the stopped roots would have added. Below the threshold
with roots still stopped settles nothing: that is `MEASURED_NOT_SEALABLE`, and it
is a result rather than a failure to produce one. FAIL is reserved for a complete
census that fell short, which is the only situation in which falling short is
something the population has told us.

**The criterion is read, never recomputed.** `sfir9_protocol` owns `C >= 750` and
`Q = min(1000, floor(0.8 C)) >= 600`. Nothing here restates them, and nothing here
adjusts them after seeing a total. Under the registered constants those two
conditions induce the same boundary; the protocol keeps both registered anyway,
and this module applies both rather than quietly dropping the redundant one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import sfir9_identity_logic as identity
import sfir9_protocol as protocol_module

SCHEMA = "tavonel.sfir9.scorer.v1"

#: A root whose frontier emptied. Its count is a measurement.
EXHAUSTED = "FRONTIER_EXHAUSTED"

#: A root that ran out of something. Its count is a floor.
STOPPED = "STOPPED_BEFORE_EXHAUSTION"

#: A root whose numeric identity did not match. It was never measured, so it is
#: not in the numerator and not in the denominator.
REFUSED = "REPOSITORY_IDENTITY_REFUSED"

DISPOSITIONS = frozenset({EXHAUSTED, STOPPED, REFUSED})

#: Verdicts. `PASS` is a verdict name, not a credential -- the linter's
#: hardcoded-secret rule matches on the identifier alone.
PASS = "CAPACITY_CRITERION_MET"  # noqa: S105
FAIL = "CAPACITY_CRITERION_NOT_MET"
NOT_SEALABLE = "MEASURED_NOT_SEALABLE"

UNKNOWN_DISPOSITION = "REFUSED_UNDECLARED_ROOT_DISPOSITION"
DUPLICATE_ROOT = "REFUSED_DUPLICATE_ROOT_IN_CENSUS"
NOT_IN_ROSTER = "REFUSED_ROOT_OUTSIDE_THE_ROSTER"
CANDIDATES_ON_A_REFUSED_ROOT = "REFUSED_CANDIDATES_FROM_AN_UNIDENTIFIED_ROOT"


class ScoringRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def pool_digest(keys: Any) -> str:
    """Digest of a candidate pool by membership, never by arrival.

    A separate function rather than an inline `sorted()` at the call site,
    because at the call site the argument is a set and the sort is unobservable:
    CPython iterates two sets with the same members identically, so removing it
    would change nothing any control could see. Given an ordered input the sort
    is the whole behaviour, and a control can hold it to that.
    """
    return _digest(sorted(list(key) for key in keys))


def eligible(path: str) -> bool:
    """Whether a path is the kind of file the pool definition counts.

    The extensions come from the frozen protocol, so widening the pool after
    seeing a disappointing total would move the protocol digest and be visible.
    """
    lowered = path.lower()
    return any(lowered.endswith(suffix) for suffix in protocol_module.CANDIDATE_EXTENSIONS)


@dataclass(frozen=True, slots=True)
class RootResult:
    """What one root produced, and whether it finished producing it."""

    host_uuid: str
    disposition: str
    candidates: tuple[identity.CandidateIdentity, ...] = ()

    def measured(self) -> bool:
        return self.disposition == EXHAUSTED

    def counted(self) -> bool:
        """Whether the root is in the denominator at all."""
        return self.disposition in {EXHAUSTED, STOPPED}

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_uuid": self.host_uuid,
            "disposition": self.disposition,
            "candidate_count": len(self.candidates),
            "count_is_exact": self.measured(),
        }


def score(
    results: Any,
    *,
    roster_host_uuids: Any,
    roster_digest: str,
    protocol: protocol_module.Protocol,
) -> dict[str, Any]:
    """Count what was found, say what was not, and apply the frozen criterion."""
    roster = {identity.normalize_host_uuid(value) for value in roster_host_uuids}

    seen: set[str] = set()
    per_root: list[dict[str, Any]] = []
    pool: set[tuple[str, str, str]] = set()
    ineligible = 0

    for result in results:
        host_uuid = identity.normalize_host_uuid(result.host_uuid)
        if result.disposition not in DISPOSITIONS:
            raise ScoringRefused(
                UNKNOWN_DISPOSITION,
                f"{result.disposition!r} is not a declared root disposition. A root "
                "whose outcome nothing can interpret must not be silently counted "
                f"as either measured or stopped. Declared: {sorted(DISPOSITIONS)}.",
            )
        if host_uuid in seen:
            raise ScoringRefused(
                DUPLICATE_ROOT,
                f"repository {host_uuid} appears twice in the census. One repository "
                "measured twice is one repository.",
            )
        if host_uuid not in roster:
            raise ScoringRefused(
                NOT_IN_ROSTER,
                f"repository {host_uuid} is not in the sealed roster, so whatever it "
                "produced is not evidence about this cohort.",
            )
        if result.disposition == REFUSED and result.candidates:
            raise ScoringRefused(
                CANDIDATES_ON_A_REFUSED_ROOT,
                f"repository {host_uuid} was refused on identity and still carries "
                "candidates. Those came from whatever answered the address, which is "
                "not the repository the roster selected.",
            )

        seen.add(host_uuid)
        for candidate in result.candidates:
            if not eligible(candidate.path):
                ineligible += 1
                continue
            pool.add(candidate.key())
        per_root.append(result.as_dict())

    counted = [r for r in results if r.counted()]
    exhausted = [r for r in results if r.measured()]
    stopped = [r for r in results if r.disposition == STOPPED]
    refused = [r for r in results if r.disposition == REFUSED]

    lower_bound = len(pool)
    census_complete = not stopped and bool(counted)
    exact = lower_bound if census_complete else None

    quota = protocol_module.quota_for(lower_bound)
    criterion_met = protocol_module.meets_criterion(lower_bound)

    if criterion_met:
        verdict = PASS
        why = (
            "the certain lower bound already meets the criterion. More candidates "
            "can only raise a count, so what the stopped roots would have added "
            "cannot change this."
        )
    elif census_complete:
        verdict = FAIL
        why = (
            "every root in the cohort was traversed to exhaustion and the total fell "
            "short. This is what the population says, not what the instrument "
            "managed."
        )
    else:
        verdict = NOT_SEALABLE
        why = (
            f"{len(stopped)} of {len(counted)} roots stopped before their frontier "
            "emptied, and the certain lower bound is below the criterion. The exact "
            "total does not exist, so neither a pass nor a fail can be sealed. This "
            "is a result, not a failure to produce one."
        )

    return {
        "schema": SCHEMA,
        "roster_digest": roster_digest,
        "protocol_digest": protocol.digest(),
        "capacity": {
            "certain_lower_bound": lower_bound,
            "exact_count": exact,
            "count_is_exact": census_complete,
            "quota_from_the_lower_bound": quota,
        },
        "completeness": {
            "roster_size": len(roster),
            "roots_in_the_census": len(seen),
            "roots_in_the_denominator": len(counted),
            "roots_traversed_to_exhaustion": len(exhausted),
            "roots_stopped_before_exhaustion": len(stopped),
            "roots_refused_on_identity": len(refused),
            "census_complete": census_complete,
            "why_refused_roots_are_in_neither": (
                "a root whose numeric id did not match was never measured, so it "
                "belongs in no numerator and no denominator. Putting it in the "
                "denominator would report a completeness the study never attempted."
            ),
        },
        "criterion": {
            "minimum_c": protocol_module.MINIMUM_C,
            "minimum_q": protocol_module.MINIMUM_Q,
            "quota_cap": protocol_module.MAXIMUM_Q,
            "read_from": "sfir9_protocol",
            "both_registered_conditions_applied": True,
            "note_on_redundancy": (
                "under the registered constants the two conditions induce the same "
                "boundary, because 600 / 0.8 is exactly 750. The protocol retains "
                "both registered conditions and both are applied here."
            ),
        },
        "verdict": verdict,
        "why": why,
        "per_root": per_root,
        "ineligible_paths_seen": ineligible,
        "pool_definition": {
            "extensions": list(protocol_module.CANDIDATE_EXTENSIONS),
            "read_from": "sfir9_protocol",
            "deduplicated_by": ["repository_numeric_id", "path", "blob_sha"],
        },
        "candidate_pool_digest": pool_digest(pool),
        "what_a_lower_bound_is_not": (
            "an estimate. No stopped root's count is extrapolated, scaled, or "
            "averaged into the total. SFIR7 reported twenty stopped roots as "
            "measured and the resulting figure was not a lower bound of anything "
            "stated."
        ),
    }
