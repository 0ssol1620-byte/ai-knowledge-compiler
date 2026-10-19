r"""Korean-aware key-token extraction for KB1 metric M3 (KOREAN-BENCHMARK-DESIGN §5.3 M3, §2.3).

``akc_quality.numeric`` is not used: its ``(?![\w])`` lookaround treats a Hangul
syllable as a word character, so ``1,000원`` is read as ``1`` and ``30일`` yields
nothing (design §2.3, receipt ``KO-NUMERIC-PROBE.out.txt`` sha256 ``cdd7e95e…``).
A truncating extractor is worse than none: ``1,000원`` and ``1,999원`` both
become ``1`` and a wrong output scores as right.

Rules here:

* digit boundaries are digit-based, not ``\w``-based, so a number may sit next
  to Hangul (``제3자``, ``30일까지``) without being truncated or dropped;
* a malformed digit group (``12,3456``) yields no token rather than a shorter
  number — a missing token is a visible recall miss, a truncated one is a lie;
* only ASCII digits are read; fullwidth digits stay unread (NFC does not fold
  them, and the KB1 normalisation is NFC);
* the same extractor runs on gold and on output, so tokenisation choices are
  symmetric; ``value`` is what M3 compares, ``surface`` is the NFKC,
  whitespace-free matched text.

Token kinds: ``date``, ``article`` (조항), ``phone``, ``business_id``
(사업자등록번호), ``amount`` (금액), ``percent``, ``number_unit``, ``number``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

TOKENIZER_REVISION = "kb1-ko-tokens-r1"


class Token(NamedTuple):
    kind: str
    value: str
    surface: str


_NUM = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?![0-9])(?!,[0-9])"
# Look-alikes via chr() (U+2212 minus sign, U+FF05 fullwidth percent) keep RUF001 useful.
_MINUS_SIGN, _FULLWIDTH_PERCENT = chr(0x2212), chr(0xFF05)
_SIGNED = r"(?:(?<![\w.,])[+\-" + _MINUS_SIGN + r"])?(?<![0-9.,])" + _NUM
# 천만, 백만, 십억 … or a lone 십/백/천. Must touch the digits it multiplies.
_MULT = r"(?:[십백천]?[만억조경]|[십백천])"
_QTY = _SIGNED + r"(?:" + _MULT + r"(?:\s*" + _NUM + _MULT + r")*)?"
_KO_UNITS = (
    "개월|분기|반기|세대|시간|페이지|년|월|주|일|시|분|초|명|개|"
    "건|곳|쪽|회|차|배|세|층|호|권|장|부|대|인|점|위"
)
_LATIN_UNITS = r"(?:km|kg|mm|cm|mL|m²|m2|m|g|t|KiB|MiB|GiB|KB|MB|GB|ha|L|°C|℃|㎡|㎢|㎞|㎏|㎜|㎝)"
_ARTICLE_PART = r"제\s*[0-9]+\s*(?:편|장|절|관|조(?:\s*의\s*[0-9]+)?|항|호)"

_TOKEN = re.compile(
    "|".join(
        (
            # 2026년 10월 17일 / 2026. 10. 17. / 2026.10.17 / 2026-10-17
            r"(?P<date>(?<![0-9])[0-9]{4}\s*년\s*[0-9]{1,2}\s*월(?:\s*[0-9]{1,2}\s*일)?"
            r"|(?<![0-9])[0-9]{4}\s*\.\s*[0-9]{1,2}\s*\.(?:\s*[0-9]{1,2}(?![0-9])\.?)?"
            r"|(?<![0-9])[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}(?![0-9]))",
            r"(?P<article>" + _ARTICLE_PART + r"(?:\s*" + _ARTICLE_PART + r")*)",
            r"(?P<phone>(?<![0-9])0[0-9]{1,2}-[0-9]{3,4}-[0-9]{4}(?![0-9]))",
            r"(?P<business_id>(?<![0-9])[0-9]{3}-[0-9]{2}-[0-9]{5}(?![0-9]))",
            r"(?P<amount>[$€£¥₩￦]\s*" + _QTY + r"|" + _QTY + r"\s*(?:원|달러))",
            r"(?P<percent>" + _SIGNED + r"\s*(?:%p|%|" + _FULLWIDTH_PERCENT + r"|퍼센트))",
            r"(?P<number_unit>"
            + _QTY
            + r"(?:(?:"
            + _KO_UNITS
            + r")|\s?"
            + _LATIN_UNITS
            + r"(?![A-Za-z]))"
            + r")",
            r"(?P<number>" + _QTY + r")",
        )
    )
)


def _compact(surface: str) -> str:
    return "".join(unicodedata.normalize("NFKC", surface).split())


def extract(text: str) -> list[Token]:
    """Return the key tokens of ``text`` (NFC-normalised first) in reading order."""
    tokens: list[Token] = []
    for match in _TOKEN.finditer(unicodedata.normalize("NFC", text)):
        kind = match.lastgroup
        assert kind is not None
        surface = _compact(match.group(0))
        if kind == "date":
            year, *rest = re.findall(r"[0-9]+", surface)
            value = "-".join([year, *(f"{int(part):02d}" for part in rest)])
        else:
            value = surface
        tokens.append(Token(kind, value, surface))
    return tokens
