"""Deterministic conservative speculation policy (blueprint 2026-09-08 §20-§21).

This is the §21 table as data and nothing else. There is no learned policy here:
§20 puts learned speculation behind shadow mode, and §64 behind promotion
evidence that does not exist yet. Lanes are symbolic (§21 closing note): the
concrete route for a lane is bound later from the tenant's ready routes, so
this table asserts no model capability.
"""

from __future__ import annotations

from enum import StrEnum

from akc_cir import ContractModel

from .execution_plan import ExecutionLane, VerificationPolicy


class SpeculationClass(StrEnum):
    """The §21 rows, verbatim and exhaustive."""

    NATIVE_CLEAN = "native_clean"
    ORDINARY_SCAN = "ordinary_scan"
    HIGH_RISK_TEXT = "high_risk_text"
    FORMULA_HEAVY = "formula_heavy"
    CRITICAL_FINANCIAL_TABLE = "critical_financial_table"
    REGULAR_TABLE = "regular_table"
    CHART_HEAVY = "chart_heavy"
    DEGRADED_PHOTO = "degraded_photo"
    CROSS_PAGE_TABLE = "cross_page_table"
    HANDWRITING = "handwriting"
    SEC_FILING = "sec_filing"
    OPENDART_FINANCE = "opendart_finance"


class SpeculationPolicy(ContractModel):
    """One §21 row.

    `parallel_peers` false means the peer lane is entered on escalation only,
    not launched speculatively.
    """

    speculation_class: SpeculationClass
    primary_lanes: tuple[ExecutionLane, ...]
    peer_lanes: tuple[ExecutionLane, ...] = ()
    parallel_peers: bool = False
    dependency_group: bool = False
    verification: VerificationPolicy = VerificationPolicy.NONE


_L = ExecutionLane
_V = VerificationPolicy

#: §21 initial parallel policy. Conservative by construction: nothing here sends
#: every page to every model, and no row was learned from outcome data.
INITIAL_SPECULATION_POLICY: dict[SpeculationClass, SpeculationPolicy] = {
    policy.speculation_class: policy
    for policy in (
        SpeculationPolicy(
            speculation_class=SpeculationClass.NATIVE_CLEAN,
            primary_lanes=(_L.NATIVE,),
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.ORDINARY_SCAN,
            primary_lanes=(_L.FAST_VISUAL,),
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.HIGH_RISK_TEXT,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.PEER_VISUAL,),
            parallel_peers=True,
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.FORMULA_HEAVY,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.PEER_VISUAL,),
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.CRITICAL_FINANCIAL_TABLE,
            primary_lanes=(_L.AUTHORITY, _L.NATIVE),
            peer_lanes=(_L.FAST_VISUAL, _L.PEER_VISUAL),
            parallel_peers=True,
            verification=_V.AUTHORITY_MATCH,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.REGULAR_TABLE,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.PEER_VISUAL,),
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.CHART_HEAVY,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.CHART_SPECIALIST,),
            parallel_peers=True,
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.DEGRADED_PHOTO,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.PEER_VISUAL, _L.DEGRADED_SCAN_SPECIALIST),
            parallel_peers=True,
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.CROSS_PAGE_TABLE,
            primary_lanes=(_L.FAST_VISUAL,),
            peer_lanes=(_L.PEER_VISUAL,),
            dependency_group=True,
            verification=_V.PEER_AGREEMENT,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.HANDWRITING,
            primary_lanes=(_L.DEGRADED_SCAN_SPECIALIST,),
            peer_lanes=(_L.HUMAN_REVIEW,),
            verification=_V.HUMAN_REVIEW,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.SEC_FILING,
            primary_lanes=(_L.AUTHORITY, _L.NATIVE),
            peer_lanes=(_L.FAST_VISUAL,),
            parallel_peers=True,
            verification=_V.AUTHORITY_MATCH,
        ),
        SpeculationPolicy(
            speculation_class=SpeculationClass.OPENDART_FINANCE,
            primary_lanes=(_L.AUTHORITY,),
            peer_lanes=(_L.FAST_VISUAL,),
            parallel_peers=True,
            verification=_V.AUTHORITY_MATCH,
        ),
    )
}


class UnknownSpeculationClassError(ValueError):
    """Raised instead of guessing a policy for an unrecognised class."""


def speculate(speculation_class: SpeculationClass | str) -> SpeculationPolicy:
    """Return the §21 row for a class. Refuses anything the table does not name."""
    try:
        key = SpeculationClass(speculation_class)
    except ValueError as exc:
        raise UnknownSpeculationClassError(
            f"no §21 speculation policy for {speculation_class!r}"
        ) from exc
    return INITIAL_SPECULATION_POLICY[key]


__all__ = [
    "INITIAL_SPECULATION_POLICY",
    "SpeculationClass",
    "SpeculationPolicy",
    "UnknownSpeculationClassError",
    "speculate",
]
