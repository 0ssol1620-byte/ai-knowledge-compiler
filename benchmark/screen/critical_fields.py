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

Numbers, dates and identifiers are read by hand-written linear scanners over a closed
character set; no regular expression reads or delimits a token. Folding is an explicit table
(fullwidth digits, punctuation and currency signs, Unicode minus); there is no NFKC. A digit is
``0-9`` only. A token ends only where, past a run of ASCII punctuation and Hangul particles
("5억을", "1,234, and"), the text ends or ASCII whitespace follows; a digit, a letter, a unit or
an unlisted character there refuses it ("5:3", "12가3456"). Parts of a number or a date join
across ASCII spaces only, so past those spaces neither side may hold an unlisted character,
which could hide a part, nor (for numbers) a Korean unit the grammar did not take, and after a
unit or scale word only a word that cannot be a further part may follow. Every digit run is a
number or date token, read or refused, never skipped. So the first token after an anchor is
read whole or refused, never short, and a refused token is listed, never dropped, so a later
token is never read in its place. Arithmetic is exact to ``_PREC``
significant digits; a value that would round is refused. Every scan is linear in the text,
so hostile output cannot stall a run.
"""

from __future__ import annotations

import string
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
        "\uff0b": "+",
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
_ASCII_LETTER = frozenset(string.ascii_letters)
# Joins digit runs into something that is not one number: "1-5", "1/2", "1'000", "1..5".
_JOIN = frozenset("-+.,'_~/")
# ASCII punctuation a token may start after.
_PUNCT = frozenset('!"#&*:;<=>?@[\\]^`{|}')
_ASCII_PUNCT = frozenset(string.punctuation)
_SIGN = {"-": True, "+": False, "△": True, "▲": True}  # sign -> negative
# Non-ASCII characters a token may hold (after folding); every other one is unlisted.
_LISTED = frozenset("△▲₩€£¥")

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

_DATE_SEP = frozenset("-/.")
# An identifier is letters, digits and hyphens; any other ASCII punctuation between two such
# runs joins them into something that is not one identifier ("INV_2024", "v1.2.3").
_ID_CHARS = _DIGIT | _ASCII_LETTER | {"-"}
_ID_JOIN = frozenset(string.punctuation) - {"-"}


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def _hangul(c: str) -> bool:
    return "\uac00" <= c <= "\ud7a3"  # syllables only; a lone jamo is unlisted


def _unlisted(c: str) -> bool:
    return not (c.isascii() or _hangul(c) or c in _LISTED)


def _clean_left(text: str, i: int, extra: str = "") -> bool:
    """May a token start at ``i``: what precedes it separates words, never joins them."""
    if i == 0:
        return True
    c = text[i - 1]
    return c in _WS or c in _PUNCT or c in extra or (_hangul(c) and c not in _KO_CHARS)


def _soft(c: str) -> bool:
    """ASCII punctuation or a particle: a token may touch a run of these only where the run
    itself ends the word."""
    return c in _ASCII_PUNCT or (_hangul(c) and c not in _KO_CHARS)


def _clean_right(text: str, j: int) -> bool:
    """May a token end at ``j``: past a run of ASCII punctuation and particles ("5.",
    "1,234, and", "5억원이다.") lies an end or ASCII whitespace, never a digit, a letter, a
    unit or an unlisted character ("5:3", "5억가3", "5.억")."""
    n, k = len(text), j
    while k < n and _soft(text[k]):
        k += 1
    return k == n or text[k] in _WS


def _apart(text: str, i: int, j: int, refuse: frozenset[str] = frozenset()) -> bool:
    """Do the ASCII spaces around ``text[i:j]`` really end it. Signs, groups, scale words,
    percent and currency join a token across them, so the first character past them on either
    side (and past a joiner run and spaces on the right, "5 .만", "5. 만") must not be
    unlisted, where such a part could hide ("12억 \\u200b3456만", "\\u02d7 5"), nor a
    ``refuse`` character."""
    left = i
    while left > 0 and text[left - 1] == " ":
        left -= 1
    right = _skip(text, j, _SPACE)
    past = _skip(text, _skip(text, right, _JOIN), _SPACE)
    near = (text[left - 1 : left], text[right : right + 1], text[past : past + 1])
    return not any(c and (_unlisted(c) or c in refuse) for c in near)


def _skip(text: str, k: int, chars: frozenset[str] = _WS) -> int:
    while k < len(text) and text[k] in chars:
        k += 1
    return k


def _word_end(text: str, k: int) -> int:
    """The next ASCII whitespace at or after ``k``: where a refused token's word ends."""
    while k < len(text) and text[k] not in _WS:
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
    s = _skip(text, j, _SPACE)
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


def _ends_scaled(text: str, s: int, english: bool) -> bool:
    """Is ``text[s]``, the first character past the spaces after a scaled token, something
    other than a further part of it: an opening paren, a currency, an English word after an
    English scale, or a run of punctuation and particles that ends the word."""
    c = text[s]
    return (
        c == "("
        or _currency_at(text, s) is not None
        or (english and c in _ASCII_LETTER)
        or _clean_right(text, s)
    )


def _number_at(text: str, i: int) -> tuple[int, Any] | None:
    """The token starting at ``i`` as ``(end, canonical value or None when refused)``.

    None when no digit follows the sign, paren or currency at ``i``: not a number at all.
    Once a digit is reached the token is read whole or refused.
    """
    n = len(text)
    k, opened, negative = i, False, False
    if text[k] == "(":
        opened, k = True, _skip(text, k + 1, _SPACE)
    elif text[k] in _SIGN:
        negative, k = _SIGN[text[k]], _skip(text, k + 1, _SPACE)
    prefix = _currency_at(text, k)
    if prefix:
        k = _skip(text, prefix[1], _SPACE)
    if k >= n or text[k] not in _DIGIT:
        return None
    body = _body(text, k)
    if body is None:
        return k + 1, None
    end, groups = body
    # Past the spaces after a unit or scale word, a further part may follow ("12억 3456만
    # 7898" is not 12억 3456만, "3 million 500 thousand" is not 3 million), so only a word
    # that cannot be one may stand there; anything else refuses the token ("12억 l456만").
    unit = groups[-1][1]
    s = _skip(text, end, _SPACE)
    if unit and end < s < n and not _ends_scaled(text, s, unit in _EN_SCALE):
        return s + 1, None
    # A unit the grammar did not take ("5억억", "1.5 천 억", "5\n억").
    after = _skip(text, end)
    if after < n and text[after] in _KO_CHARS:
        return after + 1, None
    spaced = _skip(text, end, _SPACE)
    pct = spaced < n and text[spaced] == "%"
    if pct:
        end = spaced + 1
    suffix = _currency_at(text, _skip(text, end, _SPACE))
    if suffix:
        end = suffix[1]
    if opened:
        close = _skip(text, end, _SPACE)
        if close >= n or text[close] != ")":
            return close, None  # an open paren with no close: the sign is unknown ("(5\n)")
        end, negative = close + 1, True
    elif end < n and text[end] in ")+-":
        return end + 1, None  # a close paren with no open, or a trailing sign ("5-")
    if (
        not _clean_right(text, end)
        or not _apart(text, i, end, _KO_CHARS)
        or (prefix and suffix and prefix[0] != suffix[0])
    ):
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
                end = _word_end(text, i)
                out.append((i, end, None))
                i = end
            else:
                i += 1
        elif (tok := _number_at(text, i)) is None:
            i += 1
        else:
            end, value = tok
            # Nothing restarts inside a refused token: the rest of its word goes with it.
            if value is None:
                end = _word_end(text, end)
            out.append((i, end, value))
            i = end
    return out


def _date_at(text: str, i: int, j: int) -> tuple[int, Any]:
    """The date whose year is the four digits ``text[i:j]``, as ``(end, ISO date or None)``.

    ``YYYY s M s D`` with ``s`` one of ``- / .``, or ``YYYY년 M월 D일``; ASCII spaces may stand
    between parts. Anything else after the year refuses the token where the grammar stopped.
    """
    n = len(text)
    k = _skip(text, j, _SPACE)
    marks = "년월일" if k < n and text[k] == "년" else ""
    parts = [int(text[i:j])]
    for step in range(2):
        k = _skip(text, k, _SPACE)
        if k >= n or (text[k] != marks[step] if marks else text[k] not in _DATE_SEP):
            return k, None
        k = _skip(text, k + 1, _SPACE)
        e = _skip(text, k, _DIGIT)
        if not 1 <= e - k <= 2:
            return e, None
        parts.append(int(text[k:e]))
        k = e
    if marks:
        k = _skip(text, k, _SPACE)
        if k >= n or text[k] != "일":
            return k, None
        k += 1
    if not (_clean_left(text, i, "()") and _clean_right(text, k) and _apart(text, i, k)):
        return k, None
    try:
        return k, date(*parts).isoformat()
    except ValueError:
        return k, None


def _dates(text: str) -> list[tuple[int, int, Any]]:
    """Every digit run is a date token, read whole or refused, never dropped.

    A digit is never skipped, as in numbers: only a four-digit year that the date grammar
    reads to its end gives a value, and every other run ("12024-03-05", "2024_03_05",
    "05.03.2024", "24.03.05", "20240305", "제3기") is a refused token, so a later date is
    never read in its place.
    """
    out: list[tuple[int, int, Any]] = []
    n, i = len(text), 0
    while i < n:
        if text[i] not in _DIGIT:
            i += 1
            continue
        j = _skip(text, i, _DIGIT)
        end, value = _date_at(text, i, j) if j - i == 4 else (j, None)
        if value is None:
            end = _word_end(text, end)
        out.append((i, end, value))
        i = end
    return out


def _identifiers(text: str) -> list[tuple[int, int, Any]]:
    """Every run of letters, digits and hyphens. It must stand apart: past any run of ASCII
    punctuation and Hangul syllables on either side ("INV-2024를", "번호:INV") lies an end or
    ASCII whitespace, never another letter or digit ("INV_2024", "12가3456", "AB가_CD") and
    never an unlisted character ("AB12\\u00b9")."""
    out: list[tuple[int, int, Any]] = []
    n, i = len(text), 0
    while i < n:
        if text[i] not in _ID_CHARS:
            i += 1
            continue
        j = _skip(text, i, _ID_CHARS)
        if text[i:j].strip("-"):
            left, right = i, j
            while left > 0 and (text[left - 1] in _ID_JOIN or _hangul(text[left - 1])):
                left -= 1
            while right < n and (text[right] in _ID_JOIN or _hangul(text[right])):
                right += 1
            whole = (left == 0 or text[left - 1] in _WS) and (right == n or text[right] in _WS)
            out.append((i, j, text[i:j].replace("-", "").upper() if whole else None))
        i = j
    return out


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


def _lower(text: str) -> str:
    """Lower case, one character for one, so positions in the result are positions in text."""
    low = text.lower()
    if len(low) == len(text):
        return low
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


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
    text, anchor = _fold(text), _anchor(field)
    hit = _lower(text).find(_lower(anchor))
    if hit < 0:
        return None
    # ponytail: first anchor occurrence only, as a substring. A repeated label is not
    # disambiguated, and an anchor that is a prefix of an earlier label binds to that label
    # ("영업이익" hits "영업이익률 5.2%, 영업이익 1,234억" at 영업이익률). Gold must name an anchor
    # whose first occurrence is the field's own label; upgrade = anchor occurrence index.
    tail = text[hit + len(anchor) :]
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
