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
``0-9`` only. Field first: a field is a run of non-whitespace, and a token is its whole field
or nothing. Before it only named opening punctuation and label separators ``: = |`` may
stand ("A :5"), after it only closing or sentence punctuation and one run of Hangul particles
("5억원이다.", "INV-2024를"); anything else refuses it, so a prefix or suffix of a field is
never read ("5:3", "12가3456", "x=5", "약5억", "번호:INV-1", "INV_"). A date uses one
separator ("2024-03/05" is refused). Parts of a number or a date join
across ASCII spaces only, so past those spaces neither side may hold an unlisted character,
which could hide a part, nor (for numbers) a Korean unit the grammar did not take, and after a
unit or scale word only a word that cannot be a further part may follow. A plain number
followed by a space and exactly three digits ("1 000") is refused: ASCII-space grouping cannot
be told from two numbers. A percent or currency a number did not take refuses it: past any
punctuation or symbols ("5 :%", "5 ;원", "5,원"), past spaces alone ("(5) %"), or anywhere in a
bracket group opened after it ("5 (단위: %)"), unless it is another number's own prefix or
suffix ("5 ($3)", "5 (12%)"). So does a scale word the grammar does not read ("5 mn", "5 M",
"12 lakh"). A bracket that ends in a currency is a unit label (text) only if it holds nothing
but ASCII letters, Hangul syllables, spaces, ":" and "," ("(단위: 원)"); any other ("[-원]",
"(단위 [x] 원)"), and letters before a "$" that spell no listed currency ("R$ 5"), refuse
the number after them. A currency before accounting parentheses reads negative ("$ (700)").
Every digit run is a
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
# A field is a run of non-whitespace. The only text a token may leave in its field: named
# opening punctuation or label separators before it ("A :5", "A =INV-1", "A |5|": the
# anchor's own punctuation), and after it closing or sentence punctuation and one run of
# Hangul particles. Anything else makes the token a prefix or suffix of its field.
_OPEN = frozenset("([{\"':=|")
_CLOSE = frozenset(")]}\"'.,;:!?|")
_SIGN = {"-": True, "+": False, "△": True, "▲": True}  # sign -> negative
_PAIR = {")": "(", "]": "[", "}": "{"}  # closing bracket -> its opening bracket
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
    "CNY": "CNY",
    "RMB": "CNY",
    "HKD": "HKD",
    "TWD": "TWD",
    "SGD": "SGD",
    "AUD": "AUD",
    "CAD": "CAD",
    "CHF": "CHF",
    "INR": "INR",
    "US$": "USD",
    "HK$": "HKD",
    "NT$": "TWD",
    "S$": "SGD",
    "A$": "AUD",
    "C$": "CAD",
}
_CUR_KEYS = sorted(_CURRENCY, key=len, reverse=True)
_CUR_FIRST = frozenset({k[0] for k in _CURRENCY} | {k[0].lower() for k in _CURRENCY})
_START = _DIGIT | _CUR_FIRST | {"("} | set(_SIGN)
# The only characters a unit label may hold between its opening bracket and its currency
# ("(단위: 원)", "[금액, USD]"), besides Hangul syllables. Anything else ("[-원]", "[~원]",
# "(단위 [x] 원)", "[1원]") makes the bracket group not a label.
_LABEL_TEXT = _ASCII_LETTER | {" ", ":", ","}
# Scale words the grammar does not read: after a number they refuse it ("5 mn", "12 lakh").
# Matched case-insensitively, also with a plural "s". The single letters are matched in this
# case only and only standing alone as a word ("5 M", but not "200 B: 100" or "width 5 m").
_SCALE_WORDS = frozenset({"mn", "mm", "bn", "tn", "lakh", "lac", "crore", "hundred"})
_SCALE_LETTERS = frozenset("MKBT")
_ALONE_END = frozenset(")]}\"'.,;!?") | _WS
# Values are exact to this many significant digits; one that would round is refused.
_PREC = 100
_EXACT = Context(prec=_PREC, traps=[Inexact, InvalidOperation, Overflow, DivisionByZero])

_DATE_SEP = frozenset("-/.")
# An identifier is letters, digits and hyphens; any other ASCII punctuation between two such
# runs joins them into something that is not one identifier ("INV_2024", "v1.2.3").
_ID_CHARS = _DIGIT | _ASCII_LETTER | {"-"}


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def _hangul(c: str) -> bool:
    return "\uac00" <= c <= "\ud7a3"  # syllables only; a lone jamo is unlisted


def _unlisted(c: str) -> bool:
    return not (c.isascii() or _hangul(c) or c in _LISTED)


def _clean_left(text: str, i: int) -> bool:
    """Does a token at ``i`` start its field: past named opening punctuation only, the text
    starts or ASCII whitespace stands. Anything else ("x=5", "<5", "약5억", "마이너스5",
    "번호:INV-1", "\\u200b;5") makes the token a suffix of its field, which is never read."""
    while i > 0 and text[i - 1] in _OPEN:
        i -= 1
    return i == 0 or text[i - 1] in _WS


def _clean_right(text: str, j: int) -> bool:
    """Does a token ending at ``j`` end its field: past closing or sentence punctuation and
    one run of Hangul particles ("5.", "1,234,", "5억원이다.", "(2024-03-05)이후"), the text
    ends or ASCII whitespace stands; never a digit, a letter, a unit, other punctuation or an
    unlisted character ("5:3", "5억가3", "5.억", "INV_", "5=")."""
    n = len(text)
    k = _skip(text, j, _CLOSE)
    while k < n and _hangul(text[k]) and text[k] not in _KO_CHARS:
        k += 1
    k = _skip(text, k, _CLOSE)
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
    English scale, or closing punctuation and particles that end the word."""
    c = text[s]
    return (
        c == "("
        or _currency_at(text, s) is not None
        or (english and c in _ASCII_LETTER)
        or _clean_right(text, s)
    )


def _mark_at(text: str, k: int) -> bool:
    """Is ``text[k]`` a percent, or a currency that no digit follows across spaces."""
    if text[k : k + 1] == "%":
        return True
    cur = _currency_at(text, k)
    if cur is None:
        return False
    after = _skip(text, cur[1], _SPACE)
    return text[after : after + 1] not in _DIGIT


def _skip_back(text: str, k: int, chars: frozenset[str]) -> int:
    while k > 0 and text[k - 1] in chars:
        k -= 1
    return k


def _suffix_of_a_number(text: str, k: int) -> bool:
    """Is the mark at ``k`` the suffix of a number before it: digits, then across ASCII spaces
    an optional English scale word and Korean scale syllables ("10억원", "12 %", "3 million
    USD"). Like a currency with a digit after it ("$3"), it is that number's own, not a unit
    for another ("12억원 (전년 10억원)"). "(백만원)" and "(단위: %)" have no digit: marks."""
    j = _skip_back(text, k, _SPACE)
    w = j
    while w > 0 and j - w < 9 and text[w - 1] in _ASCII_LETTER:
        w -= 1
    if w < j and text[w:j].lower() in _EN_SCALE:
        j = _skip_back(text, w, _SPACE)
    j = _skip_back(text, _skip_back(text, j, _KO_CHARS), _SPACE)
    return j > 0 and text[j - 1] in _DIGIT


def _marked_groups(text: str) -> frozenset[int]:
    """Positions of the opening brackets whose group holds a percent or a currency mark
    (``_mark_at``) anywhere inside, nested groups included, unless that mark is a number's own
    (``_suffix_of_a_number``); an unclosed group runs to the end of the text. One pass: a
    closed group hands its mark to the group around it."""
    marked: set[int] = set()
    stack: list[tuple[int, bool]] = []
    for k, c in enumerate(text):
        if c in _PAIR.values():
            stack.append((k, False))
        elif c in _PAIR and stack and text[stack[-1][0]] == _PAIR[c]:
            p, has = stack.pop()
            if has:
                marked.add(p)
                if stack:
                    stack[-1] = (stack[-1][0], True)
        elif (
            stack
            and not stack[-1][1]
            and (c == "%" or c in _CUR_FIRST)
            and _mark_at(text, k)
            and not _suffix_of_a_number(text, k)
        ):
            stack[-1] = (stack[-1][0], True)
    carry = False
    for p, has in reversed(stack):
        carry = carry or has
        if carry:
            marked.add(p)
    return frozenset(marked)


def _mark_follows(text: str, end: int, marked: frozenset[int]) -> bool:
    """Does a percent or currency the token ending at ``end`` did not take follow it.

    Past ASCII whitespace and a run of anything that is not an ASCII letter, ASCII digit or
    Hangul syllable ("5 :%", "5 ;원", "5,원", "5 :- %", "5 \\u200b%"), a mark refuses the token;
    so does one past ASCII spaces alone or nothing, which the grammar would have taken had it
    belonged to the number ("(5) %", "(5)원", "5원 %"). After a tab or line break alone a mark
    is not the token's ("5\\t%" stays plain 5). A bracket opened in that run whose group holds a
    mark anywhere refuses it too ("5 (단위: %)", "5 (in %)", "5 (USD thousands)"). A currency
    with a digit after it is the next number's prefix, not a mark ("5 ($3)", "5 :$3")."""
    n = len(text)
    k, punct, broke = end, False, False
    while k < n:
        c = text[k]
        if k in marked:
            return True
        if (c == "%" or c in _CUR_FIRST) and _mark_at(text, k):
            return punct or not broke
        if c in _WS:
            broke = broke or c != " "
        elif c in _ASCII_LETTER or c in _DIGIT or _hangul(c):
            return False
        else:
            punct = True
        k += 1
    return False


def _scale_word_follows(text: str, end: int) -> bool:
    """Is the word after ``end`` (past ASCII whitespace, or glued) a scale word the grammar did
    not read ("5 mn", "5 M", "12 lakh", "3 hundred")."""
    w = _skip(text, end)
    e = _skip(text, w, _ASCII_LETTER)
    word = text[w:e]
    if word in _SCALE_LETTERS:
        return e == len(text) or text[e] in _ALONE_END
    low = word.lower()
    return len(low) > 1 and (low in _SCALE_WORDS or (low[-1] == "s" and low[:-1] in _SCALE_WORDS))


def _stray_mark(text: str, i: int, inner: str | None, clean: bool) -> bool:
    """A currency at ``i`` that no token took, but that says something about the numbers near
    it: refused, so the number after it is never read without it.

    A currency glued to a closing bracket is a unit label (text) only when the bracket closes
    ``inner``, the innermost bracket still open, and everything between that opener and the
    currency is ``_LABEL_TEXT`` or Hangul (``clean``): "[~원]", "(단위:-원)", "[금액-원]", "x원)",
    "(단위:원]" are refused wherever the currency stands. Letters glued before a "$" must spell
    a currency of the table ("US$"); any other spelling ("R$", "NZ$", "CA$") is refused."""
    if text[i] == "$" and i > 0 and text[i - 1] in _ASCII_LETTER:
        s = i - 1
        while s > 0 and text[s - 1] in _ASCII_LETTER:
            s -= 1
        if text[s : i + 1] not in _CURRENCY:
            return True
    if not any(c in _PAIR for c in text[i + 1 : i + 4]):
        return False
    cur = _currency_at(text, i)
    close = text[cur[1] : cur[1] + 1] if cur else ""
    return close in _PAIR and not (clean and _PAIR[close] == inner)


def _number_at(
    text: str,
    i: int,
    open_bracket: str | None = None,
    marked: frozenset[int] = frozenset(),
) -> tuple[int, Any] | None:
    """The token starting at ``i`` as ``(end, canonical value or None when refused)``.

    None when nothing was consumed at ``i``, or when the sign, paren or currency consumed there
    is glued, with no whitespace anywhere, into a word ("원가", "-x", "(주)") or, glued to a
    closing bracket, closes a unit label: the bracket pairs with its own "(" or, with none,
    with ``open_bracket``, the innermost bracket still open before ``i`` ("(원)", "(단위:
    원)", "[원]", "{USD}"): nothing is read here, and whether that is a unit label (text) or is
    refused ("[-원] 5", "(단위: -원) 5") ``_stray_mark`` decides at the currency, which the
    scan reaches next. Any other bracket after a currency ("원) 5", "$] 5", "[원) 5",
    "(원] 5") is refused like any non-digit. A sign or paren standing alone is never
    text ("- 원가 5"). Any other consumed prefix with no digit after it is refused, so the scan
    never restarts past it and reads the number without it ("- :5", "$ [5]", "$ - 5", "-\\t5",
    "-- 5"), except a currency before an accounting paren ("$ (700)", "USD (700)"), which
    is the negative amount in that currency. Once a digit is reached the token is read whole
    or refused; ``marked`` are the bracket groups that hold a percent or currency
    (``_marked_groups``).
    """
    n = len(text)
    k, opened, negative = i, False, False
    if text[k] == "(":
        opened, k = True, k + 1
    elif text[k] in _SIGN:
        negative, k = _SIGN[text[k]], k + 1
    end_of_prefix = k
    k = _skip(text, k, _SPACE)
    # Whitespace after the sign or paren makes it standalone: a word after it is not glued to
    # it, however the word begins ("- 원가 5", "( $) 5"), so it can no longer be text.
    standalone = k > end_of_prefix
    prefix = _currency_at(text, k)
    if prefix:
        end_of_prefix = prefix[1]
        k = _skip(text, end_of_prefix, _SPACE)
        # A currency before accounting parentheses ("$ (700)", "$(700)", "USD ( 700 )"): the
        # paren is read as when it comes first, so it must close after the number.
        inside = _skip(text, k + 1, _SPACE)
        paren = text[k : k + 1] == "(" and text[inside : inside + 1] in _DIGIT
        if paren and not opened and text[i] not in _SIGN:
            opened, k = True, inside
    if k >= n or text[k] not in _DIGIT:
        c = text[k : k + 1]
        glued = k == end_of_prefix > i and c != "" and not standalone
        # A currency symbol before a letter is two currencies, not a word ("$USD").
        symbol = prefix is not None and not text[end_of_prefix - 1].isalpha()
        word = glued and (c in _ASCII_LETTER or _hangul(c)) and not symbol
        closes = "(" if opened else open_bracket
        unit_label = glued and prefix is not None and c in _PAIR and _PAIR[c] == closes
        if k == i or word or unit_label:
            return None
        return k, None
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
    # A plain number, a space, then exactly three digits is ASCII-space thousands grouping
    # ("1 000", "12 345 678"), as is a separator glued to the next digits ("5 ,000"): which
    # number it is cannot be told, so it is refused.
    grouped = _skip(text, s, _DIGIT) - s == 3
    grouped = grouped or (text[s : s + 1] in (",", ".") and text[s + 1 : s + 2] in _DIGIT)
    if not unit and end < s and grouped:
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
    # The same holds past a currency, percent or paren that ended a scaled token
    # ("12억 3456만원 7898" is not 12억 3456만원).
    s = _skip(text, end, _SPACE)
    if unit and end < s < n and not _ends_scaled(text, s, unit in _EN_SCALE):
        return s + 1, None
    if (
        not _clean_right(text, end)
        or not _apart(text, i, end, _KO_CHARS)
        or (prefix and suffix and prefix[0] != suffix[0])
    ):
        return end, None
    # A percent or currency the grammar did not take says what the number is: refused,
    # never read plain ("5 :%", "5 ;원", "5 (in %)", "(5) %"). So is a scale word the grammar
    # does not read ("5 mn", "5 M", "12 lakh").
    if _mark_follows(text, end, marked) or _scale_word_follows(text, end):
        return end, None
    value = _amount(groups, negative)
    if value is None:
        return end, None
    currency = prefix[0] if prefix else suffix[0] if suffix else None
    return end, (value, "pct" if pct else "num", currency)


def _numbers(text: str) -> list[tuple[int, int, Any]]:
    out: list[tuple[int, int, Any]] = []
    n, i = len(text), 0
    # Would a token at i begin its field (_clean_left), carried one character at a time so a
    # run of opening punctuation is never walked again from each "(" in it.
    ok = True
    # Brackets still open before ``seen``, innermost last, each with whether everything
    # walked since it opened is label text (``_LABEL_TEXT`` or Hangul; a nested bracket is
    # not): every character up to i is walked once, inside read tokens too, so a ")" a token
    # consumed still closes its "(".
    brackets: list[tuple[str, bool]] = []
    seen = 0
    marked = _marked_groups(text)
    while i < n:
        c = text[i]
        for b in text[seen:i]:
            if b in _PAIR.values():
                if brackets:
                    brackets[-1] = (brackets[-1][0], False)
                brackets.append((b, True))
            elif b in _PAIR and brackets and brackets[-1][0] == _PAIR[b]:
                brackets.pop()
            elif brackets and brackets[-1][1] and not (b in _LABEL_TEXT or _hangul(b)):
                brackets[-1] = (brackets[-1][0], False)
        seen = i
        inner, clean = brackets[-1] if brackets else (None, False)
        if c in _DIGIT and not ok:  # a digit is never skipped: glued to a word, it is refused
            end = _word_end(text, i)
            out.append((i, end, None))
        elif c in _START and ok and (tok := _number_at(text, i, inner, marked)) is not None:
            end, value = tok
            # Nothing restarts inside a refused token: the rest of its word goes with it.
            if value is None:
                end = _word_end(text, end)
            out.append((i, end, value))
        elif c in _CUR_FIRST and _stray_mark(text, i, inner, clean):
            end = _word_end(text, i)
            out.append((i, end, None))
        else:
            ok = c in _WS or (c in _OPEN and ok)
            i += 1
            continue
        i = end
        ok = _clean_left(text, i)  # walks back inside the token just read, never further
    return out


def _date_at(text: str, i: int, j: int) -> tuple[int, Any]:
    """The date whose year is the four digits ``text[i:j]``, as ``(end, ISO date or None)``.

    ``YYYY s M s D`` with one separator ``s`` of ``- / .`` used both times, or
    ``YYYY년 M월 D일``. ASCII spaces may stand only after a separator of the dotted or the
    년/월/일 form ("2024. 3. 5.", "2024년 3월 5일"), and the dotted form may end in its own
    ".". A spaced date is refused when the next field holds an ASCII digit, which could be a
    split part of it ("2024. 3. 1 5."), unless that field is parenthesised. Anything else
    after the year ("2024-03/05", "2024 - 03 - 05") refuses the token where the grammar
    stopped.
    """
    marks = "년월" if text[j : j + 1] == "년" else text[j : j + 1] * 2
    if marks[:1] not in _DATE_SEP | {"년"}:
        return j, None
    parts, k, spaced = [int(text[i:j])], j, False
    for mark in marks:
        if text[k : k + 1] != mark:
            return k, None
        k += 1
        if mark in ".년월":
            s = _skip(text, k, _SPACE)
            spaced, k = spaced or s > k, s
        e = _skip(text, k, _DIGIT)
        if not 1 <= e - k <= 2:
            return e, None
        parts.append(int(text[k:e]))
        k = e
    if marks == "년월":
        if text[k : k + 1] != "일":
            return k, None
        k += 1
    elif marks == ".." and text[k : k + 1] == ".":
        k += 1
    if not (_clean_left(text, i) and _clean_right(text, k) and _apart(text, i, k)):
        return k, None
    if spaced:
        s = _skip(text, _word_end(text, k), _SPACE)
        if text[s : s + 1] != "(" and any(c in _DIGIT for c in text[s : _word_end(text, s)]):
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
    """Every run of letters, digits and hyphens. It must be its whole field but for opening
    punctuation before it and closing punctuation and one particle run after it
    ("INV-2024를", "(AB12)"); a run inside a longer field is refused ("INV_2024", "INV_",
    "12가3456", "번호:INV-1", "AB12\\u00b9")."""
    out: list[tuple[int, int, Any]] = []
    n, i = len(text), 0
    while i < n:
        if text[i] not in _ID_CHARS:
            i += 1
            continue
        j = _skip(text, i, _ID_CHARS)
        if text[i:j].strip("-"):
            # A hyphen at either end joins the run to something it does not hold ("INV- 2024").
            whole = "-" not in (text[i], text[j - 1]) and _clean_left(text, i)
            whole = whole and _clean_right(text, j)
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
