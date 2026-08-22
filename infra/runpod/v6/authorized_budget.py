"""Absolute, reservation-first RunPod campaign budget.

Expected-cost alerts are useful observability, but they are not an authorization
boundary.  This module enforces the user's absolute campaign ceiling before a
provider write can reserve paid capacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from benchmark.v6.contracts import ContractError, canonical_sha256

_MONEY_QUANTUM: Final = Decimal("0.000001")


def _money(value: Decimal | str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("budget amount must be a decimal") from exc
    if not amount.is_finite():
        raise ContractError("budget amount must be finite")
    return amount.quantize(_MONEY_QUANTUM)


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    allocation_id: str
    maximum_cost_usd: Decimal


class AuthorizedSpendBudget:
    """Reserve worst-case cost before dispatch and reject cap overflow."""

    def __init__(self, *, campaign_id: str, hard_cap_usd: Decimal | str) -> None:
        if not campaign_id.strip():
            raise ContractError("campaign_id is required")
        cap = _money(hard_cap_usd)
        if cap <= 0:
            raise ContractError("hard_cap_usd must be positive")
        self.campaign_id = campaign_id
        self.hard_cap_usd = cap
        self._reservations: dict[str, Decimal] = {}
        self._settled: dict[str, Decimal] = {}

    @property
    def reserved_usd(self) -> Decimal:
        return sum(self._reservations.values(), Decimal("0")).quantize(_MONEY_QUANTUM)

    @property
    def settled_usd(self) -> Decimal:
        return sum(self._settled.values(), Decimal("0")).quantize(_MONEY_QUANTUM)

    @property
    def remaining_usd(self) -> Decimal:
        return (self.hard_cap_usd - self.reserved_usd - self.settled_usd).quantize(
            _MONEY_QUANTUM
        )

    def reserve(
        self, *, allocation_id: str, maximum_cost_usd: Decimal | str
    ) -> BudgetReservation:
        normalized = allocation_id.strip()
        if not normalized:
            raise ContractError("allocation_id is required")
        if normalized in self._reservations or normalized in self._settled:
            raise ContractError("budget allocation_id must be unique")
        maximum = _money(maximum_cost_usd)
        if maximum <= 0:
            raise ContractError("maximum_cost_usd must be positive")
        if maximum > self.remaining_usd:
            raise ContractError("authorized RunPod hard cap would be exceeded")
        self._reservations[normalized] = maximum
        return BudgetReservation(normalized, maximum)

    def release(self, allocation_id: str) -> None:
        if allocation_id not in self._reservations:
            raise ContractError("cannot release an unknown budget reservation")
        del self._reservations[allocation_id]

    def settle(self, *, allocation_id: str, actual_cost_usd: Decimal | str) -> None:
        if allocation_id not in self._reservations:
            raise ContractError("cannot settle an unknown budget reservation")
        actual = _money(actual_cost_usd)
        if actual < 0:
            raise ContractError("actual_cost_usd cannot be negative")
        maximum = self._reservations.pop(allocation_id)
        if actual > maximum:
            self._settled[allocation_id] = actual
            raise ContractError("provider cost exceeded its authorized reservation")
        self._settled[allocation_id] = actual

    def report(self) -> dict[str, object]:
        report: dict[str, object] = {
            "schema": "folynta.runpod-authorized-budget.v1",
            "campaign_id": self.campaign_id,
            "hard_cap_usd": str(self.hard_cap_usd),
            "reserved_usd": str(self.reserved_usd),
            "settled_usd": str(self.settled_usd),
            "remaining_usd": str(self.remaining_usd),
            "reservations": {
                key: str(value) for key, value in sorted(self._reservations.items())
            },
            "settlements": {
                key: str(value) for key, value in sorted(self._settled.items())
            },
            "hard_cap_enforced_before_provider_write": True,
        }
        report["report_sha256"] = canonical_sha256(report)
        return report


__all__ = ["AuthorizedSpendBudget", "BudgetReservation"]
