"""Field-exact scoring of critical values (numbers, dates, identifiers).

Gold lists ``critical_fields``: ``{"field_id", "kind": number|date|identifier, "value",
"anchor"}``. ``anchor`` is the label text that precedes the value on the page. A field is
exact only when the first token of its kind after the first occurrence of the anchor in the
candidate text has the gold canonical form, so swapped values and values that merely occur
elsewhere on the page are not exact. A gold field without an anchor is refused.
Canonical form keeps sign, decimal value (scale words applied), percent versus plain, and
currency, so ``-5%`` is not ``5%``. Nothing is repaired or guessed: an unparseable candidate
token never matches and is not skipped over, and a gold value that is not exactly one clean
token, and nothing else, raises.

Numbers are read by a hand-written scanner over a closed character set. Folding is an explicit
table (fullwidth digits and punctuation, Unicode minus); there is no NFKC. A digit is ``0-9``
only. A token may touch only the ends of the text, ASCII whitespace, listed ASCII punctuation
or Hangul (a particle: "5억을"). Any other character touching a token refuses the whole token,
so a token is read whole or refused, never short, and every ASCII digit lies in an accepted or
a refused token. Arithmetic is exact to ``_PREC`` significant digits; a value that would round
is refused. Every scan is linear in the text, so hostile output cannot stall a run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Any

KINDS = ("number", "date", "identifier")

# The only folds: each width or minus variant becomes the ASCII character it stands for.
_FOLD = str.maketrans(
    {
        **{chr(0xFF10 + d): str(d) for d in range(10)},
        "\uff0c": ",",
        "\uff0e": ".",
        "\uff0d": "-",
        "\uff05": "%",
        "\uff08": "(",
        "\uff09": ")",
        "\u2212": "-",  # minus sign
        "\uff04": "$",
        "\uffe6": "\u20a9",  # fullwidth won sign
        "\uffe5": "\u00a5",  # fullwidth yen sign
        "\uffe1": "\u00a3",  # fullwidth pound sign
    }
)

_WS = frozenset(" \t\n\r")
_SPACE = frozenset(" ")
_DIGIT = frozenset("0123456789")
_ASCII_LETTER = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
# Joins digit runs into something that is not one number: "1-5", "1/2", "1'000", "1..5".
_JOIN = frozenset("-+.,'_~/")
# ASCII punctuation a token may touch on either side.
_PUNCT = frozenset('!"#&*:;<=>?@[\\]^`{|}')
_SIGN = {"-": True, "+": False, "△": True, "▲": True}  # sign -> negative

# Korean place value: a 천/백/십 term builds a section, a 만/억/조 unit scales the whole
# section ("5천5백만" = 5,500 x 10^4). A unit run is one optional small unit then one optional
# big unit ("천억" = 10^3 x 10^8); a run outside that grammar is not a number.
_KO_SMALL = {"십": Decimal(10), "백": Decimal(10) ** 2, "천": Decimal(10) ** 3}
_KO_BIG = {"만": Decimal(10) ** 4, "억": Decimal(10) ** 8, "조": Decimal(10) ** 12}
_KO_CHARS = frozenset("조억만천백십")
_EN_WORDS = ("thousand", "million", "billion", "trillion", "bn")
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
_CUR_KEYS = sorted(_CURRENCY, key=len, reverse=True)
_CUR_FIRST = frozenset({k[0] for k in _CURRENCY} | {k[0].lower() for k in _CURRENCY})
_START = _DIGIT | _CUR_FIRST | {"("} | set(_SIGN)
# Values are exact to this many significant digits; one that would round is refused.
_PREC = 100
_EXACT = Context(prec=_PREC, traps=[Inexact, InvalidOperation, Overflow, DivisionByZero])
_NEXT_WS = re.compile("[ \t\n\r]")


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def _hangul(c: str) -> bool:
    return "\uac00" <= c <= "\ud7a3" or "\u1100" <= c <= "\u11ff"  # syllables, jamo


def _clean_left(text: str, i: int, extra: str = "") -> bool:
    """May a token start at ``i``: what precedes it separates words, never joins them."""
    if i == 0:
        return True
    c = text[i - 1]
    return c in _WS or c in _PUNCT or c in extra or (_hangul(c) and c not in _KO_CHARS)


def _clean_right(text: str, j: int, extra: str = "") -> bool:
    """May a token end at ``j``. A joiner run after it ("5.", "1,234, and") is punctuation
    only when a separator follows, never a digit, a letter or an unlisted character."""
    n, k = len(text), j
    while k < n and text[k] in _JOIN:
        k += 1
    if k == n:
        return True
    c = text[k]
    return c in _WS or c in _PUNCT or c in extra or _hangul(c)


def _next_ws(text: str, k: int) -> int:
    m = _NEXT_WS.search(text, k)
    return m.start() if m else len(text)


def _skip(text: str, k: int, chars: frozenset[str] = _WS) -> int:
    while k < len(text) and text[k] in chars:
        k += 1
    return k


def _currency_at(text: str, k: int) -> tuple[str, int] | None:
    if k >= len(text) or text[k] not in _CUR_FIRST:
        return None
    for key in _CUR_KEYS:
        end = k + len(key)
        seg = text[k:end]
        # A code reads in any case; a letter glued after it then refuses the token ("5 USDx").
        if key.isascii() and key.isalpha():
            if seg.isascii() and seg.upper() == key:
                return _CURRENCY[key], end
        elif seg == key:
            return _CURRENCY[key], end
    return None


def _num(text: str, k: int) -> tuple[int, str] | None:
    """Digits at ``k`` (``text[k]`` is a digit) as ``(end, digits without commas)``.

    ``1-3 digits (,ddd)+`` or a plain run, then an optional ``.digits``. None when the number
    runs on into another digit group ("1,23", "1.2.3", "1,2345"): never read as a prefix.
    """
    n = len(text)
    j = _skip(text, k, _DIGIT)
    if j - k <= 3:
        while j + 3 < n and text[j] == "," and all(c in _DIGIT for c in text[j + 1 : j + 4]):
            j += 4
    if j + 1 < n and text[j] == "." and text[j + 1] in _DIGIT:
        j = _skip(text, j + 1, _DIGIT)
    if j < n and (text[j] in _DIGIT or (text[j] in ".," and j + 1 < n and text[j + 1] in _DIGIT)):
        return None
    return j, text[k:j].replace(",", "")


def _ko_unit(text: str, k: int) -> int:
    if k < len(text) and text[k] in _KO_SMALL:
        k += 1
    if k < len(text) and text[k] in _KO_BIG:
        k += 1
    return k


def _body(text: str, k: int) -> tuple[int, list[tuple[str, str]]] | None:
    """Korean unit groups ("1조 2,345억") or one number with an English scale ("3 million")."""
    first = _num(text, k)
    if first is None:
        return None
    j, digits = first
    s = _skip(text, j, _SPACE)
    u = _ko_unit(text, s)
    if u > s:
        groups = [(digits, text[s:u])]
        j = u
        while True:
            s = _skip(text, j, _SPACE)
            nxt = _num(text, s) if s < len(text) and text[s] in _DIGIT else None
            if nxt is None:
                return j, groups
            s = _skip(text, nxt[0], _SPACE)
            u = _ko_unit(text, s)
            if u == s:
                return j, groups
            groups.append((nxt[1], text[s:u]))
            j = u
    s = _skip(text, j)
    for word in _EN_WORDS:
        seg = text[s : s + len(word)]
        if seg.isascii() and seg.lower() == word:
            return s + len(word), [(digits, word)]
    glued_letter = j + 1 < len(text) and text[j + 1] in _ASCII_LETTER
    if j < len(text) and text[j] in "kmbKMB" and not glued_letter:
        return j + 1, [(digits, text[j].lower())]
    return j, [(digits, "")]


def _ko_amount(groups: list[tuple[Decimal, str]]) -> Decimal | None:
    """Place-value sum of ``(number, unit run)`` groups; None when places do not descend.

    Places are compared as places, not as terms, so a fraction cannot hide a repeated place
    ("5억 0.5억"), and only the last group may carry a fraction: a fraction spills into the
    places after it ("1.5억5천만" would count the 5천만 place twice).
    """
    if any(n != n.to_integral_value() for n, _ in groups[:-1]):
        return None
    total = section = Decimal(0)
    big_bound: Decimal | None = None  # the previous big unit: everything after is smaller
    small_bound: Decimal | None = None  # the previous small unit inside this section
    for n, unit in groups:
        small = _KO_SMALL.get(unit[:1], Decimal(1))
        term = n * small
        if small_bound is not None and (small >= small_bound or term >= small_bound):
            return None
        section += term
        small_bound = small
        if unit[-1:] in _KO_BIG:
            big = _KO_BIG[unit[-1]]
            if big_bound is not None and (big >= big_bound or section * big >= big_bound):
                return None
            total, section, big_bound, small_bound = total + section * big, Decimal(0), big, None
    if big_bound is not None and section >= big_bound:
        return None
    return total + section


def _amount(groups: list[tuple[str, str]], negative: bool) -> str | None:
    """Exact decimal text of the groups; None when they are not one value or would round."""
    try:
        with localcontext(_EXACT):
            nums = [(Decimal(d), unit) for d, unit in groups]
            if nums[0][1][-1:] in _KO_CHARS:
                ko = _ko_amount(nums)
                if ko is None:
                    return None
                total = ko
            else:
                ((n, unit),) = nums
                total = n * _EN_SCALE[unit] if unit else +n
            if negative:
                total = -total
            return "0" if total == 0 else format(total.normalize(), "f")
    except DecimalException:
        return None


def _number_at(text: str, i: int) -> tuple[int, Any] | None:
    """The token starting at ``i`` as ``(end, canonical value or None when refused)``.

    None when no digit follows the sign, paren or currency at ``i``: not a number at all.
    Once a digit is reached the token is read whole or refused.
    """
    n = len(text)
    k, opened, negative = i, False, False
    if text[k] == "(":
        opened, k = True, _skip(text, k + 1)
    elif text[k] in _SIGN:
        negative, k = _SIGN[text[k]], _skip(text, k + 1)
    prefix = _currency_at(text, k)
    if prefix:
        k = _skip(text, prefix[1])
    if k >= n or text[k] not in _DIGIT:
        return None
    body = _body(text, k)
    if body is None:
        return k + 1, None
    end, groups = body
    # A bare digit group after a spaced Korean group ("12억 3456만 7898" is not 12억 3456만),
    # or a unit the grammar did not take ("5억억", "1.5 천 억", "5\n억").
    if text[end - 1] in _KO_CHARS:
        s = _skip(text, end, _SPACE)
        if end < s < n and text[s] in _DIGIT:
            return s + 1, None
    after = _skip(text, end)
    if after < n and text[after] in _KO_CHARS:
        return after + 1, None
    pct = after < n and text[after] == "%"
    if pct:
        end = after + 1
    suffix = _currency_at(text, _skip(text, end))
    if suffix:
        end = suffix[1]
    if opened:
        close = _skip(text, end)
        if close < n and text[close] == ")":
            end, negative = close + 1, True
    elif end < n and text[end] == ")":
        return end + 1, None  # a close paren with no open
    if not _clean_right(text, end) or (prefix and suffix and prefix[0] != suffix[0]):
        return end, None
    value = _amount(groups, negative)
    if value is None:
        return end, None
    currency = prefix[0] if prefix else suffix[0] if suffix else None
    return end, (value, "pct" if pct else "num", currency)


def _numbers(text: str) -> list[tuple[int, int, Any]]:
    out: list[tuple[int, int, Any]] = []
    n, i = len(text), 0
    while i < n:
        c = text[i]
        if c not in _START:
            i += 1
        elif not _clean_left(text, i):
            if c in _DIGIT:  # a digit is never skipped: glued to a word, it is refused
                out.append((i, i + 1, None))
                i = _next_ws(text, i)
            else:
                i += 1
        elif (tok := _number_at(text, i)) is None:
            i += 1
        else:
            end, value = tok
            out.append((i, end, value))
            # Nothing restarts inside a refused token: the rest of its word goes with it.
            i = end if value is not None else _next_ws(text, end)
    return out


_W = "[ \t\n\r]*+"
_DATE = re.compile(
    rf"([0-9]{{4}}){_W}[-/.]{_W}([0-9]{{1,2}}){_W}[-/.]{_W}([0-9]{{1,2}})"
    rf"|([0-9]{{4}}){_W}년{_W}([0-9]{{1,2}}){_W}월{_W}([0-9]{{1,2}}){_W}일"
)
_DATE_SHAPE = re.compile(rf"[0-9]{{4}}{_W}[-/.년]")
_DIGIT_RUN = re.compile("[0-9]+")
_IDENT = re.compile("[0-9A-Za-z-]+")


def _dates(text: str) -> list[tuple[int, int, Any]]:
    """Every date-shaped run (four digits, then a date separator), read whole or refused."""
    out: list[tuple[int, int, Any]] = []
    for run in _DIGIT_RUN.finditer(text):
        k = run.start()
        if run.end() - k != 4:
            continue
        m = _DATE.match(text, k)
        if m is None:
            if _DATE_SHAPE.match(text, k):
                out.append((k, run.end(), None))
            continue
        value = None
        if _clean_left(text, k, "()") and _clean_right(text, m.end(), "()"):
            y, mo, d = (int(g) for g in (m[1] or m[4], m[2] or m[5], m[3] or m[6]))
            try:
                value = date(y, mo, d).isoformat()
            except ValueError:
                value = None
        out.append((k, m.end(), value))
    return out


def _identifiers(text: str) -> list[tuple[int, int, Any]]:
    def clean(k: int) -> bool:
        return k < 0 or k >= len(text) or text[k].isascii() or _hangul(text[k])

    return [
        (m.start(), m.end(), m[0].replace("-", "").upper())
        if clean(m.start() - 1) and clean(m.end())
        else (m.start(), m.end(), None)
        for m in _IDENT.finditer(text)
        if m[0].strip("-")
    ]


def _ordered(kind: str, text: str) -> list[tuple[int, int, Any]]:
    """``(start, end, canonical value)`` of every ``kind`` token in ``text``, in page order.

    A refused token stays in the list with value None, so it is never skipped over.
    """
    text = _fold(text)
    if kind == "number":
        return _numbers(text)
    if kind == "date":
        return _dates(text)
    if kind == "identifier":
        return _identifiers(text)
    raise ValueError(f"kind {kind!r} not in {KINDS}")


def canonical_values(kind: str, text: str) -> set[Any]:
    """Every canonical value of ``kind`` that ``text`` holds (refused tokens left out)."""
    return {v for _, _, v in _ordered(kind, text) if v is not None}


def _anchor(field: dict[str, Any]) -> str:
    anchor = field.get("anchor")
    if not isinstance(anchor, str) or not _fold(anchor).strip():
        raise ValueError(f"critical field {field.get('field_id')!r}: anchor is required")
    return _fold(anchor).strip()


def gold_value(field: dict[str, Any]) -> Any:
    """The canonical value of a gold field whose value, ASCII whitespace aside, is exactly one
    clean token and nothing else ("5 apples" is not 5); anything else raises."""
    kind, raw = field.get("kind"), field.get("value")
    if kind not in KINDS or not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"critical field {field.get('field_id')!r}: kind/value invalid")
    _anchor(field)
    value = raw.strip(" \t\n\r")
    tokens = _ordered(kind, value)
    if len(tokens) != 1 or tokens[0][2] is None or tokens[0][:2] != (0, len(value)):
        raise ValueError(
            f"critical field {field.get('field_id')!r}: value {raw!r} is not one {kind}"
        )
    return tokens[0][2]


def value_after_anchor(field: dict[str, Any], text: str) -> Any | None:
    """Value of the first token of the field's kind after its anchor; None if refused or none."""
    text = _fold(text)
    hit = re.search(re.escape(_anchor(field)), text, re.IGNORECASE)
    if hit is None:
        return None
    # ponytail: first anchor occurrence only, as a substring. A repeated label is not
    # disambiguated, and an anchor that is a prefix of an earlier label binds to that label
    # ("영업이익" hits "영업이익률 5.2%, 영업이익 1,234억" at 영업이익률). Gold must name an anchor
    # whose first occurrence is the field's own label; upgrade = anchor occurrence index.
    tail = text[hit.end() :]
    return next((v for _, _, v in _ordered(field["kind"], tail)), None)


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
