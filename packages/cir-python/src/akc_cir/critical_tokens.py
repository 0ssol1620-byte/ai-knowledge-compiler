"""Critical-token preservation verifier for silent semantic corruption.

The verifier is intentionally narrow: it does not judge prose quality. It checks
tokens whose small OCR/parser mutation can change a fact while leaving the output
fluent -- numbers, signs, units, dates, currencies, identifiers and explicitly
named table cells.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .inspection import DetectorSignal, EvidenceChannel, FailureCode

__all__ = [
    "CriticalTokenKind",
    "CriticalTokenMismatch",
    "CriticalTokenReport",
    "verify_critical_tokens",
]


class CriticalTokenKind(StrEnum):
    NUMBER = "number"
    SIGN = "sign"
    UNIT = "unit"
    DATE = "date"
    CURRENCY = "currency"
    IDENTIFIER = "identifier"
    TABLE_CELL = "table_cell"


_DATE = re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|‰)?")
_SIGNED = re.compile(r"(?<!\w)([-+])\s*\d+(?:[.,]\d+)?")
_CURRENCY = re.compile(r"(?:[$€£¥₩]\s*[-+]?\d[\d,.]*|\b(?:USD|KRW|EUR|GBP|JPY|CNY)\b)", re.I)
_UNIT = re.compile(
    r"\b(?:mm|cm|m|km|mg|g|kg|lb|lbs|oz|ml|l|ms|s|sec|min|h|hr|hz|khz|mhz|ghz|v|kv|w|kw|°c|°f|dpi|px|ppm|bps|kbps|mbps|gbps)\b",
    re.I,
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold()).replace(",", "")


def _counter(pattern: re.Pattern[str], text: str) -> Counter[str]:
    return Counter(_norm(match.group(0)) for match in pattern.finditer(text))


@dataclass(frozen=True, slots=True)
class CriticalTokenMismatch:
    kind: CriticalTokenKind
    token: str
    source_count: int
    output_count: int
    risk: float
    detail: str


@dataclass(frozen=True, slots=True)
class CriticalTokenReport:
    mismatches: tuple[CriticalTokenMismatch, ...]
    checked_kinds: tuple[CriticalTokenKind, ...]

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def risk(self) -> float:
        return max((item.risk for item in self.mismatches), default=0.0)

    def as_detector_signal(self) -> DetectorSignal | None:
        if self.passed:
            return None
        return DetectorSignal(
            code=FailureCode.F17_NATIVE_RENDER_DISAGREEMENT,
            score=self.risk,
            detail=(
                f"critical-token preservation failed for {len(self.mismatches)} token(s): "
                + ", ".join(f"{m.kind.value}:{m.token}" for m in self.mismatches[:6])
            ),
            raw={
                "critical_token_mismatches": len(self.mismatches),
                "critical_token_max_risk": self.risk,
            },
            evidence_channel=EvidenceChannel.KNOWLEDGE,
            independence_group="critical-token-verifier",
        )


_RISK = {
    CriticalTokenKind.NUMBER: 0.86,
    CriticalTokenKind.SIGN: 0.95,
    CriticalTokenKind.UNIT: 0.84,
    CriticalTokenKind.DATE: 0.90,
    CriticalTokenKind.CURRENCY: 0.92,
    CriticalTokenKind.IDENTIFIER: 0.88,
    CriticalTokenKind.TABLE_CELL: 0.94,
}


def _compare_counters(
    kind: CriticalTokenKind,
    source: Counter[str],
    output: Counter[str],
) -> list[CriticalTokenMismatch]:
    mismatches: list[CriticalTokenMismatch] = []
    for token in sorted(set(source) | set(output)):
        if source[token] == output[token]:
            continue
        mismatches.append(
            CriticalTokenMismatch(
                kind=kind,
                token=token,
                source_count=source[token],
                output_count=output[token],
                risk=_RISK[kind],
                detail=(
                    f"{kind.value} multiplicity changed: "
                    f"source={source[token]} output={output[token]}"
                ),
            )
        )
    return mismatches


def verify_critical_tokens(
    source_text: str,
    output_text: str,
    *,
    expected_identifiers: Sequence[str] = (),
    source_table_cells: Mapping[str, str] | None = None,
    output_table_cells: Mapping[str, str] | None = None,
) -> CriticalTokenReport:
    mismatches: list[CriticalTokenMismatch] = []
    # Dates/currencies/signs are checked first then removed from the generic
    # interpretation only conceptually; duplicate findings are useful because a
    # changed "$-10" is both a sign and currency integrity failure.
    patterns = (
        (CriticalTokenKind.DATE, _DATE),
        (CriticalTokenKind.CURRENCY, _CURRENCY),
        (CriticalTokenKind.SIGN, _SIGNED),
        (CriticalTokenKind.UNIT, _UNIT),
        (CriticalTokenKind.NUMBER, _NUMBER),
    )
    for kind, pattern in patterns:
        mismatches.extend(
            _compare_counters(kind, _counter(pattern, source_text), _counter(pattern, output_text))
        )

    for identifier in expected_identifiers:
        token = _norm(identifier)
        source_count = _norm(source_text).count(token)
        output_count = _norm(output_text).count(token)
        if source_count != output_count:
            mismatches.append(
                CriticalTokenMismatch(
                    CriticalTokenKind.IDENTIFIER,
                    identifier,
                    source_count,
                    output_count,
                    _RISK[CriticalTokenKind.IDENTIFIER],
                    "expected identifier multiplicity changed",
                )
            )

    source_cells = source_table_cells or {}
    output_cells = output_table_cells or {}
    for cell in sorted(set(source_cells) | set(output_cells)):
        before = _norm(source_cells.get(cell, ""))
        after = _norm(output_cells.get(cell, ""))
        if before == after:
            continue
        mismatches.append(
            CriticalTokenMismatch(
                CriticalTokenKind.TABLE_CELL,
                cell,
                int(bool(before)),
                int(bool(after)),
                _RISK[CriticalTokenKind.TABLE_CELL],
                f"critical table cell changed: {cell}",
            )
        )

    return CriticalTokenReport(
        tuple(mismatches),
        (
            *(kind for kind, _ in patterns),
            CriticalTokenKind.IDENTIFIER,
            CriticalTokenKind.TABLE_CELL,
        ),
    )