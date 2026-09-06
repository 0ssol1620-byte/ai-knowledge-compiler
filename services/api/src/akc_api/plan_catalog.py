"""Canonical commercial plan names and enforceable entitlement metadata."""

from __future__ import annotations

from dataclasses import dataclass

CANONICAL_PLAN_CODES = frozenset({"evaluation", "developer", "team", "scale", "enterprise"})
_ALIASES = {
    "free": "evaluation",
    "personal": "developer",
    "pro": "developer",
    "studio": "team",
}


@dataclass(frozen=True, slots=True)
class PlanEntitlement:
    code: str
    display_name: str
    monthly_price_usd: int | None
    included_standard_pages: int | None
    workspaces: int | None
    seats: int | None
    active_connectors: int | None
    api_access: bool
    mcp_access: bool
    commercially_qualified: bool


PLAN_ENTITLEMENTS = {
    "evaluation": PlanEntitlement("evaluation", "Evaluation", 0, 500, 1, 1, 0, False, False, True),
    "developer": PlanEntitlement("developer", "Developer", 29, 500, 1, 1, 1, True, True, True),
    "team": PlanEntitlement("team", "Team", 99, 2_500, 3, 5, 5, True, True, True),
    "scale": PlanEntitlement("scale", "Scale", None, None, None, None, None, True, True, False),
    "enterprise": PlanEntitlement(
        "enterprise",
        "Enterprise",
        None,
        None,
        None,
        None,
        None,
        True,
        True,
        False,
    ),
}


def canonical_plan_code(value: str) -> str:
    normalized = value.strip().casefold()
    canonical = _ALIASES.get(normalized, normalized)
    return canonical if canonical in CANONICAL_PLAN_CODES else "evaluation"


def plan_entitlement(value: str) -> PlanEntitlement:
    return PLAN_ENTITLEMENTS[canonical_plan_code(value)]
