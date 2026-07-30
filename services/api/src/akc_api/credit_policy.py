"""Pure credit-ledger state transition policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

CreditEntryType = Literal[
    "grant",
    "reserve",
    "consume",
    "release",
    "refund",
    "adjust",
]


class CreditPolicyError(ValueError):
    def __init__(self, code: str, *, available: Decimal | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.available = available


@dataclass(frozen=True, slots=True)
class CreditState:
    balance: Decimal
    reserved: Decimal

    def __post_init__(self) -> None:
        if self.balance < 0 or self.reserved < 0 or self.reserved > self.balance:
            raise CreditPolicyError("credit_state_invariant_failed")

    @property
    def available(self) -> Decimal:
        return self.balance - self.reserved


def apply_credit_transition(
    state: CreditState,
    *,
    entry_type: str,
    credits: Decimal,
    from_reserved: bool = False,
) -> CreditState:
    amount = Decimal(credits)
    if amount <= 0:
        raise CreditPolicyError("credits_must_be_positive")

    balance = state.balance
    reserved = state.reserved
    if entry_type == "grant":
        balance += amount
    elif entry_type == "reserve":
        if state.available < amount:
            raise CreditPolicyError(
                "insufficient_credits",
                available=state.available,
            )
        reserved += amount
    elif entry_type == "consume":
        if reserved < amount:
            raise CreditPolicyError("consume_exceeds_reserved")
        reserved -= amount
        balance -= amount
    elif entry_type == "release":
        if reserved < amount:
            raise CreditPolicyError("release_exceeds_reserved")
        reserved -= amount
    elif entry_type == "refund":
        balance += amount
    elif entry_type == "adjust":
        if from_reserved:
            if reserved < amount:
                raise CreditPolicyError("adjust_exceeds_reserved")
            reserved -= amount
            balance -= amount
        else:
            if state.available < amount:
                raise CreditPolicyError("adjust_exceeds_available")
            balance -= amount
    else:
        raise CreditPolicyError("unsupported_credit_entry")
    return CreditState(balance=balance, reserved=reserved)


__all__ = [
    "CreditEntryType",
    "CreditPolicyError",
    "CreditState",
    "apply_credit_transition",
]
