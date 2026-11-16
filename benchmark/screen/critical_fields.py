"""Field-exact scoring of critical values (numbers, dates, identifiers).

Gold lists ``critical_fields``: ``{"field_id", "kind": number|date|identifier, "value",
"anchor"}``. ``anchor`` is the label text that precedes the value on the page. A field is
exact only when the first value of its kind after the first occurrence of the anchor in the
candidate text has the gold canonical form, so swapped values and values that merely occur
elsewhere on the page are not exact. A gold field without an anchor is refused.
Canonical form keeps sign, decimal value (scale words applied), percent versus plain, and
currency, so ``-5%`` is not ``5%``. Nothing is repaired or guessed: an unparseable candidate
token never matches, an unparseable gold value raises.
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
_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d|,\d)"
_CUR = "|".join(sorted(map(re.escape, _CURRENCY), key=len, reverse=True))
_NUMBER = re.compile(
    rf"""(?<![0-9A-Za-z.,])(?P<sign>[-\u2212+△▲]|\()?\s*(?P<cp>{_CUR})?\s*
    (?P<body>{_NUM}\s*[조억만천](?:\s*{_NUM}\s*[조억만천])*
            |{_NUM}(?:\s*(?:thousand|million|billion|trillion|bn)|[kmb](?![A-Za-z]))?)
    (?P<pct>\s*%)?(?:\s*(?P<cs>{_CUR}))?(?P<close>\))?(?![0-9A-Za-z])""",
    re.VERBOSE | re.IGNORECASE,
)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_DATE_KO = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


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
            scale = _KO_SCALE.get(unit) or _EN_SCALE[unit.lower()] if unit else Decimal(1)
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


def _identifier(token: str) -> str:
    return unicodedata.normalize("NFKC", token).replace("-", "").upper()


def _ordered(kind: str, text: str) -> list[tuple[int, Any]]:
    """``(offset, canonical value)`` of every ``kind`` value in ``text``, in page order."""
    text = unicodedata.normalize("NFKC", text).replace(chr(0x2212), "-")
    if kind == "number":
        found = [(m.start(), _canon_number(m)) for m in _NUMBER.finditer(text)]
        return [(o, c) for o, c in found if c is not None]
    if kind == "date":
        out: list[tuple[int, Any]] = []
        for pat in (_DATE_ISO, _DATE_KO):
            for m in pat.finditer(text):
                try:
                    out.append((m.start(), date(*(int(g) for g in m.groups())).isoformat()))
                except ValueError:
                    continue
        return sorted(out)
    if kind == "identifier":
        return [
            (m.start(), _identifier(m[0]))
            for m in re.finditer(r"[0-9A-Za-z\-]+", text)
            if m[0].strip("-")
        ]
    raise ValueError(f"kind {kind!r} not in {KINDS}")


def canonical_values(kind: str, text: str) -> set[Any]:
    """Every canonical value of ``kind`` that ``text`` holds."""
    return {v for _, v in _ordered(kind, text)}


def _anchor(field: dict[str, Any]) -> str:
    anchor = field.get("anchor")
    if not isinstance(anchor, str) or not unicodedata.normalize("NFKC", anchor).strip():
        raise ValueError(f"critical field {field.get('field_id')!r}: anchor is required")
    return unicodedata.normalize("NFKC", anchor).strip()


def gold_value(field: dict[str, Any]) -> Any:
    kind, raw = field.get("kind"), field.get("value")
    if kind not in KINDS or not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"critical field {field.get('field_id')!r}: kind/value invalid")
    _anchor(field)
    values = canonical_values(kind, raw)
    if len(values) != 1:
        raise ValueError(
            f"critical field {field.get('field_id')!r}: value {raw!r} is not one {kind}"
        )
    return next(iter(values))


def value_after_anchor(field: dict[str, Any], text: str) -> Any | None:
    """First value of the field's kind after the first occurrence of its anchor, or None."""
    text = unicodedata.normalize("NFKC", text).replace(chr(0x2212), "-")
    hit = re.search(re.escape(_anchor(field)), text, re.IGNORECASE)
    if hit is None:
        return None
    # ponytail: first anchor occurrence only; a repeated label is not disambiguated.
    tail = text[hit.end() :]
    return next((v for _, v in _ordered(field["kind"], tail)), None)


@dataclass(frozen=True)
class CriticalScore:
    n: int
    exact: int
    mismatched: tuple[str, ...]


def score_critical_fields(gold_fields: list[dict[str, Any]], candidate_text: str) -> CriticalScore:
    bad = [
        str(f["field_id"])
        for f in gold_fields
        if gold_value(f) != value_after_anchor(f, candidate_text)
    ]
    return CriticalScore(len(gold_fields), len(gold_fields) - len(bad), tuple(bad))
