"""Authority-first numeric acceptance policy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class NumericAuthorityDecision:
    accepted: bool
    normalized_value: Decimal | None
    reason_code: str


def verify_authority_number(candidate: str, authority: str | None) -> NumericAuthorityDecision:
    if authority is None:
        return NumericAuthorityDecision(False, None, "authority_missing")
    try:
        candidate_value = Decimal(candidate.replace(",", "").strip())
        authority_value = Decimal(authority.replace(",", "").strip())
    except InvalidOperation:
        return NumericAuthorityDecision(False, None, "numeric_parse_failed")
    if candidate_value != authority_value:
        return NumericAuthorityDecision(False, authority_value, "authority_numeric_mismatch")
    return NumericAuthorityDecision(True, authority_value, "authority_numeric_matched")


__all__ = ["NumericAuthorityDecision", "verify_authority_number"]
