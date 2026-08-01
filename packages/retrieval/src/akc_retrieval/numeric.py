"""Fail-closed numeric answer verification against authority-bound facts."""

from __future__ import annotations

import decimal
import re
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from .models import VerificationState, WireModel

_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")


class NumericAnswerState(StrEnum):
    VERIFIED = "verified"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"


class NumericFactKey(WireModel):
    entity_id: Annotated[str, Field(min_length=1, max_length=240)]
    statement: Annotated[str, Field(min_length=1, max_length=240)]
    concept: Annotated[str, Field(min_length=1, max_length=240)]
    period_start: str | None = None
    period_end: str | None = None
    instant: str | None = None
    unit: Annotated[str, Field(min_length=1, max_length=40)]
    currency: Annotated[str, Field(min_length=3, max_length=12)] | None = None
    scale: int = 1
    dimensions_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_period_and_scale(self) -> NumericFactKey:
        if self.instant is not None and (
            self.period_start is not None or self.period_end is not None
        ):
            raise ValueError("instant and duration period are mutually exclusive")
        if self.instant is None and (self.period_start is None or self.period_end is None):
            raise ValueError("fact key requires an instant or complete duration period")
        if self.scale <= 0 or self.scale > 10**18:
            raise ValueError("scale must be a bounded positive power of ten")
        if self.scale != 1 and 10 ** (len(str(self.scale)) - 1) != self.scale:
            raise ValueError("scale must be a power of ten")
        return self


class NumericAuthorityFact(WireModel):
    stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    key: NumericFactKey
    value: Decimal
    source_block_ids: tuple[str, ...]
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    authority_type: Annotated[
        str,
        Field(pattern=r"^(official_api|xbrl|native_coordinates|source_image)$"),
    ]
    verification_state: VerificationState

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("numeric authority value must be finite")
        return value

    @field_validator("source_block_ids")
    @classmethod
    def evidence_required(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("numeric facts require unique source evidence")
        return value


class NumericAnswerVerification(WireModel):
    state: NumericAnswerState
    normalized_answer: Decimal | None = None
    authority_fact_id: str | None = None
    source_block_ids: tuple[str, ...] = ()
    ambiguity_count: Annotated[int, Field(ge=0)] = 0
    reason_codes: tuple[str, ...]
    emit_answer: bool = False

    @model_validator(mode="after")
    def enforce_output_gate(self) -> NumericAnswerVerification:
        if self.emit_answer != (self.state == NumericAnswerState.VERIFIED):
            raise ValueError("only verified numeric answers may be emitted")
        if self.emit_answer and (
            self.normalized_answer is None
            or self.authority_fact_id is None
            or not self.source_block_ids
            or self.ambiguity_count != 1
        ):
            raise ValueError("verified numeric answers require one authority fact and evidence")
        return self


def normalize_numeric_token(token: str) -> Decimal:
    candidate = token.strip().replace("\u00a0", "").replace(" ", "")
    negative_parentheses = candidate.startswith("(") and candidate.endswith(")")
    if negative_parentheses:
        candidate = candidate[1:-1]
    percent = candidate.endswith("%")
    if percent:
        candidate = candidate[:-1]
    candidate = candidate.replace(",", "")
    if not _DECIMAL_PATTERN.fullmatch(candidate):
        raise ValueError("answer token is not an exact decimal")
    try:
        value = Decimal(candidate)
    except decimal.InvalidOperation as exc:
        raise ValueError("answer token is not an exact decimal") from exc
    if negative_parentheses:
        value = -value
    if percent:
        value /= Decimal(100)
    if not value.is_finite():
        raise ValueError("answer token must be finite")
    return value


def verify_numeric_answer(
    token: str,
    *,
    expected_key: NumericFactKey,
    facts: Iterable[NumericAuthorityFact],
) -> NumericAnswerVerification:
    try:
        answer = normalize_numeric_token(token)
    except ValueError:
        return NumericAnswerVerification(
            state=NumericAnswerState.QUARANTINED,
            reason_codes=("numeric_token_invalid",),
        )
    matches = [fact for fact in facts if fact.key == expected_key]
    if not matches:
        return NumericAnswerVerification(
            state=NumericAnswerState.UNRESOLVED,
            normalized_answer=answer,
            reason_codes=("authority_fact_missing",),
        )
    scaled_values = {fact.value * fact.key.scale for fact in matches}
    if len(scaled_values) != 1:
        return NumericAnswerVerification(
            state=NumericAnswerState.UNRESOLVED,
            normalized_answer=answer,
            ambiguity_count=len(matches),
            reason_codes=("authority_fact_ambiguous",),
        )
    authority_value = scaled_values.pop()
    if answer != authority_value:
        return NumericAnswerVerification(
            state=NumericAnswerState.UNRESOLVED,
            normalized_answer=answer,
            ambiguity_count=len(matches),
            reason_codes=("numeric_value_mismatch",),
        )
    chosen = sorted(matches, key=lambda fact: (fact.authority_type, fact.stable_id))[0]
    return NumericAnswerVerification(
        state=NumericAnswerState.VERIFIED,
        normalized_answer=answer,
        authority_fact_id=chosen.stable_id,
        source_block_ids=chosen.source_block_ids,
        ambiguity_count=1,
        reason_codes=("authority_value_exact", "unit_period_context_exact"),
        emit_answer=True,
    )


__all__ = [
    "NumericAnswerState",
    "NumericAnswerVerification",
    "NumericAuthorityFact",
    "NumericFactKey",
    "normalize_numeric_token",
    "verify_numeric_answer",
]
