"""Authoritative customer-facing page pricing for Knowledge Compile."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

STANDARD_PAGE_RATE_USD = Decimal("0.04")
ROUTED_PAGE_RATE_USD = Decimal("0.06")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class CustomerChargeQuote:
    minimum_usd: Decimal
    estimated_usd: Decimal
    maximum_usd: Decimal


def customer_charge_quote(*, total_pages: int, native_pages: int) -> CustomerChargeQuote:
    """Return the launch page-price quote without exposing internal compute units."""
    safe_total = max(0, int(total_pages))
    safe_native = min(safe_total, max(0, int(native_pages)))
    routed_pages = safe_total - safe_native
    return CustomerChargeQuote(
        minimum_usd=(Decimal(safe_total) * STANDARD_PAGE_RATE_USD).quantize(_CENT),
        estimated_usd=(
            Decimal(safe_native) * STANDARD_PAGE_RATE_USD
            + Decimal(routed_pages) * ROUTED_PAGE_RATE_USD
        ).quantize(_CENT),
        maximum_usd=(Decimal(safe_total) * ROUTED_PAGE_RATE_USD).quantize(_CENT),
    )


def capped_customer_charge(*, calculated_usd: Decimal, approved_maximum_usd: Decimal) -> Decimal:
    """Honor the customer-approved maximum; any excess is absorbed, never billed."""
    return min(max(Decimal("0"), calculated_usd), approved_maximum_usd).quantize(_CENT)
