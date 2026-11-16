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
# Korean place value: a 천/백/십 term builds a section, a 만/억/조 unit scales the whole
# section ("5천5백만" = 5,500 x 10^4). A unit run is one optional small unit then one optional
# big unit ("천억" = 10^3 x 10^8); a run outside that grammar is not a number.
_KO_SMALL = {"십": Decimal(10), "백": Decimal(10) ** 2, "천": Decimal(10) ** 3}
_KO_BIG = {"만": Decimal(10) ** 4, "억": Decimal(10) ** 8, "조": Decimal(10) ** 12}
_KO_CHARS = "조억만천백십"
_KO_UNIT = "(?:[십백천]?[만억조]|[십백천])"
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
    rf"""(?<![0-9A-Za-z.,{_KO_CHARS}])(?P<sign>[-\u2212+△▲]|\()?\s*(?P<cp>{_CUR})?\s*
    (?P<body>{_NUM}\s*{_KO_UNIT}(?:\s*{_NUM}\s*{_KO_UNIT})*
            |{_NUM}(?:\s*(?:thousand|million|billion|trillion|bn)|[kmb](?![A-Za-z]))?)
    (?!\s*[{_KO_CHARS}])  # never stop inside a Korean unit run: whole token or no token
    (?P<pct>\s*%)?(?:\s*(?P<cs>{_CUR}))?(?P<close>\))?(?![0-9A-Za-z])""",
    re.VERBOSE | re.IGNORECASE,
)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_DATE_KO = re.compile(r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _cur(value: str | None) -> str | None:
    if not value:
        return None
    return _CURRENCY.get(value) or _CURRENCY.get(value.upper())


def _ko_amount(groups: list[tuple[Decimal, str]]) -> Decimal | None:
    """Place-value sum of ``(number, unit run)`` groups; None when places do not descend."""
    total = section = Decimal(0)
    big_bound: Decimal | None = None  # the previous big unit: everything after is smaller
    small_bound: Decimal | None = None  # the previous small unit inside this section
    for n, unit in groups:
        small = _KO_SMALL.get(unit[:1], Decimal(1))
        term = n * small
        if small_bound is not None and term >= small_bound:
            return None
        section += term
        small_bound = small
        if unit[-1:] in _KO_BIG:
            big = _KO_BIG[unit[-1]]
            if big_bound is not None and section * big >= big_bound:
                return None
            total, section, big_bound, small_bound = total + section * big, Decimal(0), big, None
    if big_bound is not None and section >= big_bound:
        return None
    return total + section


def _canon_number(m: re.Match[str]) -> tuple[str, str, str | None] | None:
    body = m["body"]
    try:
        groups = [
            (Decimal(digits.replace(",", "")), unit)
            for digits, unit in re.findall(
                rf"({_NUM})\s*({_KO_UNIT}|thousand|million|billion|trillion|bn|[kmb])?", body, re.I
            )
        ]
    except InvalidOperation:
        return None
    first_unit = groups[0][1]
    if first_unit and first_unit[-1] in _KO_CHARS:
        ko = _ko_amount(groups)
        if ko is None:
            return None
        total = ko
    else:
        ((n, unit),) = groups
        total = n * (_EN_SCALE[unit.lower()] if unit else Decimal(1))
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
    # ponytail: first anchor occurrence only, as a substring. A repeated label is not
    # disambiguated, and an anchor that is a prefix of an earlier label binds to that label
    # ("영업이익" hits "영업이익률 5.2%, 영업이익 1,234억" at 영업이익률). Gold must name an anchor
    # whose first occurrence is the field's own label; upgrade = anchor occurrence index.
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
