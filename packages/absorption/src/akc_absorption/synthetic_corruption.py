"""Deterministic semantic-corruption mutations for detector/recovery experiments."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["CorruptionKind", "SyntheticCorruption", "generate_corruptions"]


class CorruptionKind(StrEnum):
    DIGIT = "digit"
    SIGN = "sign"
    UNIT = "unit"
    DATE = "date"
    CURRENCY = "currency"
    HEADER_CELL = "header_cell"
    ROW_COLUMN_SWAP = "row_column_swap"
    DROP = "drop"
    DUPLICATION = "duplication"
    NEARBY_PAGE_LEAKAGE = "nearby_page_leakage"


@dataclass(frozen=True, slots=True)
class SyntheticCorruption:
    kind: CorruptionKind
    seed: int
    original: str
    corrupted: str
    expected_failure_family: str
    changed: bool


def _replace_first(pattern: str, text: str, repl) -> str:
    return re.sub(pattern, repl, text, count=1, flags=re.I)


def generate_corruptions(
    text: str,
    *,
    seed: int,
    nearby_page_text: str = "",
) -> tuple[SyntheticCorruption, ...]:
    # A seeded PRNG is the requirement here, not a weakness: the corruptions
    # have to be reproducible from the seed for the experiment to mean
    # anything, and a cryptographic generator would make it unrepeatable.
    rng = random.Random(seed)  # noqa: S311
    mutations: list[tuple[CorruptionKind, str, str]] = []

    def digit(match: re.Match[str]) -> str:
        value = match.group(0)
        replacement = str((int(value) + rng.randint(1, 8)) % 10)
        return replacement

    mutations.append((CorruptionKind.DIGIT, _replace_first(r"\d", text, digit), "critical_token"))

    signed = _replace_first(
        r"(?<!\w)([-+])(?=\s*\d)", text, lambda m: "+" if m.group(1) == "-" else "-"
    )
    if signed == text:
        signed = _replace_first(r"(?<!\w)(\d)", text, r"-\1")
    mutations.append((CorruptionKind.SIGN, signed, "critical_token"))

    units = {"kg": "lb", "lb": "kg", "cm": "mm", "mm": "cm", "km": "m", "mhz": "ghz"}
    unit_mutated = text
    for before, after in units.items():
        candidate = _replace_first(rf"\b{before}\b", text, after)
        if candidate != text:
            unit_mutated = candidate
            break
    mutations.append((CorruptionKind.UNIT, unit_mutated, "critical_token"))

    def date_repl(match: re.Match[str]) -> str:
        y, m, d = match.groups()
        return f"{y}-{m}-{(int(d) % 28) + 1:02d}"

    date_mutated = _replace_first(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b", text, date_repl)
    mutations.append((CorruptionKind.DATE, date_mutated, "critical_token"))

    currency_mutated = _replace_first(r"\bUSD\b", text, "EUR")
    if currency_mutated == text:
        currency_mutated = _replace_first(r"\$", text, "€")
    mutations.append((CorruptionKind.CURRENCY, currency_mutated, "critical_token"))

    lines = text.splitlines()
    header_mutated = text
    if lines:
        header_mutated = "CORRUPTED_HEADER\n" + "\n".join(lines[1:])
    mutations.append((CorruptionKind.HEADER_CELL, header_mutated, "structure"))

    table_lines = [i for i, line in enumerate(lines) if "|" in line]
    swapped = list(lines)
    if len(table_lines) >= 2:
        a, b = table_lines[0], table_lines[1]
        swapped[a], swapped[b] = swapped[b], swapped[a]
    mutations.append((CorruptionKind.ROW_COLUMN_SWAP, "\n".join(swapped), "table_structure"))

    dropped = "\n".join(lines[:-1]) if len(lines) > 1 else ""
    mutations.append((CorruptionKind.DROP, dropped, "completeness"))

    duplicated = text + ("\n" + lines[-1] if lines else text)
    mutations.append((CorruptionKind.DUPLICATION, duplicated, "duplication"))

    leaked = text + ("\n" + nearby_page_text if nearby_page_text else "")
    mutations.append((CorruptionKind.NEARBY_PAGE_LEAKAGE, leaked, "cross_page"))

    return tuple(
        SyntheticCorruption(kind, seed, text, corrupted, family, corrupted != text)
        for kind, corrupted, family in mutations
    )