"""Field-exact scoring of critical values (numbers, dates, identifiers).

Gold lists ``critical_fields``: ``{"field_id", "kind": number|date|identifier, "value"}``.
A field is exact only when the candidate page text holds a token whose canonical form equals
the gold canonical form. Canonical form keeps sign, decimal value (scale words applied),
percent versus plain, and currency, so ``-5%`` is not ``5%``. Nothing is repaired or guessed:
an unparseable candidate token never matches, an unparseable gold value raises.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

KINDS = ("number", "date", "identifier")
_KO_SCALE = {
    "조": Decimal(10) ** 12,
    "억": Decimal(10) ** 8,
    "만": Decimal(10) ** 4,
    "천": Decimal(10) ** 3,
}
_EN_SCALE = {
    "k": Decimal(10) ** 3,
    "thousand": Decimal(10) ** 3,
    "m": Decimal(10) ** 6,
    "million": Decimal(10) ** 6,
    "b": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9,
    "billion": Decimal(10) ** 9,
    "trillion": Decimal(10) ** 12,
}
_CURRENCY = {
    "₩": "KRW",
    "원": "KRW",
    "KRW": "KRW",
    "$": "USD",
    "달러": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "엔": "JPY",
    "JPY": "JPY",
    "¥": "¥",
}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CUR = "|".join(sorted(map(re.escape, _CURRENCY), key=len, reverse=True))
_NUMBER = re.compile(
    rf"""(?<![\w.,])(?P<sign>[-\u2212+△▲]|\()?\s*(?P<cp>{_CUR})?\s*
    (?P<body>{_NUM}\s*[조억만천](?:\s*{_NUM}\s*[조억만천])*
            |{_NUM}(?:\s*(?:thousand|million|billion|trillion|bn|[kmb])(?![A-Za-z]))?)
    (?P<pct>\s*%)?(?:\s*(?P<cs>{_CUR}))?(?P<close>\))?(?![\w])""",
    re.VERBOSE | re.IGNORECASE,
)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_DATE_KO = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_ID_SPLIT = re.compile(r"[^0-9A-Za-z\-]+")


def _cur(value: str | None) -> str | None:
    if not value:
        return None
    return _CURRENCY.get(value) or _CURRENCY.get(value.upper())


def _canon_number(m: re.Match[str]) -> tuple[str, str, str | None] | None:
    body = m["body"]
    try:
        groups = re.findall(
            rf"({_NUM})\s*([조억만천]|thousand|million|billion|trillion|bn|[kmb])?", body, re.I
        )
        total = Decimal(0)
        for digits, unit in groups:
            scale = (_KO_SCALE.get(unit) or _EN_SCALE.get(unit.lower())) if unit else Decimal(1)
            total += Decimal(digits.replace(",", "")) * scale
    except InvalidOperation:
        return None
    sign = m["sign"]
    if sign == "(" and not m["close"]:
        sign = None
    if sign != "(" and m["close"]:
        return None  # stray close paren: not a clean token
    if sign in ("-", "\u2212", "△", "▲", "("):
        total = -total
    text = "0" if total == 0 else format(total.normalize(), "f")
    cp, cs = _cur(m["cp"]), _cur(m["cs"])
    if cp and cs and cp != cs:
        return None
    return text, "pct" if m["pct"] else "num", cp or cs


def _dates(text: str) -> set[str]:
    out: set[str] = set()
    for pat in (_DATE_ISO, _DATE_KO):
        for y, mo, d in pat.findall(unicodedata.normalize("NFKC", text)):
            try:
                out.add(date(int(y), int(mo), int(d)).isoformat())
            except ValueError:
                continue
    return out


def _identifier(token: str) -> str:
    return unicodedata.normalize("NFKC", token).replace("-", "").upper()


def canonical_values(kind: str, text: str) -> set[Any]:
    """Every canonical value of ``kind`` that ``text`` holds."""
    text = unicodedata.normalize("NFKC", text).replace("\u2212", "-") if kind == "number" else text
    if kind == "number":
        found = (_canon_number(m) for m in _NUMBER.finditer(text))
        return {c for c in found if c is not None}
    if kind == "date":
        return _dates(text)
    if kind == "identifier":
        return {_identifier(t) for t in _ID_SPLIT.split(text) if t.strip("-")}
    raise ValueError(f"kind {kind!r} not in {KINDS}")


def gold_value(field: dict[str, Any]) -> Any:
    kind, raw = field.get("kind"), field.get("value")
    if kind not in KINDS or not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"critical field {field.get('field_id')!r}: kind/value invalid")
    values = canonical_values(kind, raw)
    if len(values) != 1:
        raise ValueError(
            f"critical field {field.get('field_id')!r}: value {raw!r} is not one {kind}"
        )
    return next(iter(values))


@dataclass(frozen=True)
class CriticalScore:
    n: int
    exact: int
    mismatched: tuple[str, ...]


def score_critical_fields(gold_fields: list[dict[str, Any]], candidate_text: str) -> CriticalScore:
    held: dict[str, set[Any]] = {}
    bad: list[str] = []
    for f in gold_fields:
        want = gold_value(f)
        have = held.setdefault(f["kind"], canonical_values(f["kind"], candidate_text))
        if want not in have:
            bad.append(str(f["field_id"]))
    return CriticalScore(len(gold_fields), len(gold_fields) - len(bad), tuple(bad))
