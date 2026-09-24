"""ReDoS regressions for the CodeQL py/redos, py/polynomial-redos and
py/bad-tag-filter alerts of 2026-09-24.

Where the old pattern is safe to keep, it stays here verbatim as the oracle:
the replacement must agree with it on every short string over the characters
that drive the pattern. The old WebVTT speaker and C-comment patterns are
themselves CodeQL findings (py/redos, py/bad-tag-filter), so their oracles are
explicit case tables recorded from the old patterns instead. Every replacement
must stay linear on inputs built to make the old pattern backtrack.
"""

from __future__ import annotations

import contextlib
import itertools
import random
import re
import time
from collections.abc import Callable, Iterator

import pytest
from akc_compiler_runtime import extraction
from akc_domain_packs import registry
from akc_domain_packs.registry import SchemaPolicyError
from akc_native_parsers import subtitle_parser
from akc_security import UnsafeMarkupError, ensure_portable_markdown_safe, markup

OLD_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
OLD_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
OLD_WIKILINK = re.compile(r"\[\[([^|\]]+)(?:\|[^\]]*)?]]")
OLD_NESTED_QUANTIFIER = re.compile(r"\([^)]*[*+][^)]*\)[*+{]")

# Linear work on these sizes is milliseconds; the old patterns take seconds to
# hours. The bound is loose so a slow CI runner cannot flake it.
BUDGET_SECONDS = 1.0


def _strings(alphabet: str, max_length: int) -> Iterator[str]:
    for length in range(max_length + 1):
        for letters in itertools.product(alphabet, repeat=length):
            yield "".join(letters)


def _random_strings(alphabet: str, count: int, max_length: int) -> Iterator[str]:
    rng = random.Random(20260924)
    for _ in range(count):
        yield "".join(rng.choice(alphabet) for _ in range(rng.randint(0, max_length)))


def _corpus(alphabet: str, max_length: int) -> Iterator[str]:
    yield from _strings(alphabet, max_length)
    yield from _random_strings(alphabet, 20_000, 40)


def _short_id(value: object) -> str:
    return repr(value)[:16]


def _elapsed(call: Callable[[], object]) -> float:
    started = time.perf_counter()
    call()
    return time.perf_counter() - started


# --- akc_security.markup -----------------------------------------------------


def test_html_tag_scan_matches_old_regex() -> None:
    for text in _corpus("<>/a1 ", 6):
        assert markup._has_html_tag(text) == bool(OLD_HTML_TAG.search(text)), repr(text)


def test_markdown_link_scan_matches_old_regex() -> None:
    for text in _corpus("[]()!a \"'", 6):
        expected = [match.group(1) for match in OLD_MARKDOWN_LINK.finditer(text)]
        assert list(markup._markdown_link_targets(text)) == expected, repr(text)


def test_wikilink_scan_matches_old_regex() -> None:
    for text in _corpus("[]|a", 8):
        expected = [match.group(1) for match in OLD_WIKILINK.finditer(text)]
        assert list(markup._wikilink_targets(text)) == expected, repr(text)


@pytest.mark.parametrize(
    "hostile",
    [
        "<a" * 100_000,
        "</a" * 100_000,
        "[" * 200_000,
        "[](" * 100_000,
        "[](a" * 100_000,
        '[](a "x' * 60_000,
        "[](a " * 100_000,
        "[[" * 100_000,
        "[[a|" * 100_000,
        "[[a]" * 100_000,
    ],
    ids=_short_id,
)
def test_markdown_safety_is_linear_on_hostile_input(hostile: str) -> None:
    def check() -> None:
        with contextlib.suppress(UnsafeMarkupError):
            ensure_portable_markdown_safe(hostile)

    assert _elapsed(check) < BUDGET_SECONDS


def test_hostile_padding_does_not_hide_an_unsafe_link() -> None:
    padding = "[](" * 50_000 + "\n"
    with pytest.raises(UnsafeMarkupError, match="unsafe_markdown_link"):
        ensure_portable_markdown_safe(padding + "[x](javascript:alert(1))")
    with pytest.raises(UnsafeMarkupError, match="unsafe_markdown_link"):
        ensure_portable_markdown_safe('[](a "x' * 20_000 + '[x](data:text/html "t")')
    with pytest.raises(UnsafeMarkupError, match="unsafe_wikilink"):
        ensure_portable_markdown_safe("[[a|" * 50_000 + "]]" + "[[../../escape|x]]")
    with pytest.raises(UnsafeMarkupError, match="raw_html_forbidden"):
        ensure_portable_markdown_safe("<a" * 50_000 + ">")
    assert ensure_portable_markdown_safe("[docs](https://example.com/a(b) 'T')") == (
        "[docs](https://example.com/a(b) 'T')"
    )


# --- akc_domain_packs.registry -----------------------------------------------


def test_nested_quantifier_check_matches_old_regex() -> None:
    for text in _corpus("()*+{a", 7):
        assert registry._has_quantified_group_with_inner_quantifier(text) == bool(
            OLD_NESTED_QUANTIFIER.search(text)
        ), repr(text)


@pytest.mark.parametrize("pattern", ["(a+)+", "(a*)*", "(ab+){2}", "x(y*z)+"])
def test_nested_quantifier_patterns_stay_forbidden(pattern: str) -> None:
    with pytest.raises(SchemaPolicyError, match="forbidden backtracking"):
        registry._validate_pattern(pattern)


def test_nested_quantifier_check_is_linear() -> None:
    hostile = "(" * 200_000 + "*"
    assert _elapsed(lambda: registry._has_quantified_group_with_inner_quantifier(hostile)) < (
        BUDGET_SECONDS
    )


# --- akc_native_parsers.subtitle_parser ---------------------------------------


# Recorded from the pre-2026-09-24 pattern ``^<v(?:\.[^ >]+)*\s+([^>]+)>(.*)$``
# on space-separated tags. WebVTT separates the voice annotation with a space,
# tab or line feed; the old pattern let a tab or line feed sit inside a class
# name, the new one ends the class there, as the spec does.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<v Bob>hi", ("Bob", "hi")),
        ("<v.loud Ana Lee>hey", ("Ana Lee", "hey")),
        ("<v.a.b Bob>hi", ("Bob", "hi")),
        ("<v  Bob>x", ("Bob", "x")),
        ("<v   >x", (" ", "x")),
        ("<v Bob>", ("Bob", "")),
        ("<v Bob>a>b", ("Bob", "a>b")),
        ("<v.x.y Ann Lee>line\nnext", ("Ann Lee", "line\nnext")),
        ("<v .a>x", (".a", "x")),
        ("<v.a Bob> x ", ("Bob", " x ")),
        ("<v >x", None),
        ("<v>x", None),
        ("<vBob>x", None),
        ("<v.a>x", None),
        ("<v. >x", None),
        ("<v.a.b>x", None),
        ("<v Bob", None),
        ("x<v Bob>hi", None),
    ],
    ids=_short_id,
)
def test_vtt_speaker_pattern_keeps_old_results(text: str, expected: tuple[str, str] | None) -> None:
    match = subtitle_parser._VTT_SPEAKER.match(text)
    assert (None if match is None else (match.group(1), match.group(2))) == expected


@pytest.mark.parametrize(
    ("raw", "speaker", "body"),
    [
        ("<v Bob>hi", "Bob", "hi"),
        ("<v.loud Ana Lee>hey", "Ana Lee", "hey"),
        ("<v.a.b\tBob>hi", "Bob", "hi"),
        ("<v   >x", "", "x"),
    ],
)
def test_vtt_speaker_extraction(raw: str, speaker: str, body: str) -> None:
    assert subtitle_parser._speaker_and_text(raw) == (speaker, body)


@pytest.mark.parametrize(
    "hostile",
    [
        "<v" + "." * 100_000,
        "<v" + ".a" * 100_000,
        "<v" + ".a" * 100_000 + " ",
        "<v" + ".\t" * 100_000,  # the old pattern took 3.3 s at 26 repeats, x4 per repeat
        "<v" + " " * 100_000,
        "<v" + "\t" * 100_000 + "x",
    ],
    ids=_short_id,
)
def test_vtt_speaker_is_linear(hostile: str) -> None:
    assert _elapsed(lambda: subtitle_parser._speaker_and_text(hostile)) < BUDGET_SECONDS


# --- akc_compiler_runtime.extraction ------------------------------------------


# Recorded from the pre-2026-09-24 pattern
# ``^\s*(?://|/?\*|<!--)\s?(.*?)(?:\*/|-->)?\s*$`` (group 1, stripped).
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("// hello", "hello"),
        ("//hello", "hello"),
        ("   // indented */", "indented"),
        ("/* block */", "block"),
        ("/** doc */", "* doc"),
        (" * star line", "star line"),
        ("*/", "/"),
        ("<!-- html -->", "html"),
        ("<!--x-->", "x"),
        ("<!-- open", "open"),
        ("// a */ -->", "a */"),
        ("// trailing */   ", "trailing"),
        ("//", ""),
        ("/*/", "/"),
        ("<!---->", ""),
        ("*-->", ""),
        ("// x*/*/", "x*/"),
        ("/", None),
        ("<!-", None),
        ("code // not at start", None),
        ("x", None),
        ("", None),
        ("   ", None),
    ],
    ids=_short_id,
)
def test_c_comment_body_keeps_old_results(line: str, expected: str | None) -> None:
    assert extraction._c_comment_body(line) == expected


def test_c_comment_extraction_keeps_claim_text() -> None:
    lines = [
        "// The launch deadline is 2026-10-15 for all regions.",
        "<!-- The freeze is effective October 15, 2026 -->",
        "/* Pricing must be approved before launch */",
    ]
    claims = extraction._parse_code(lines, "src/app.ts", extraction.AuthorityClass.DRAFT)
    assert [claim.text for claim in claims] == [
        "The launch deadline is 2026-10-15 for all regions.",
        "The freeze is effective October 15, 2026",
        "Pricing must be approved before launch",
    ]


def test_c_comment_extraction_is_linear() -> None:
    hostile = "//" + " " * 100_000 + "x"
    assert _elapsed(lambda: extraction._c_comment_body(hostile)) < BUDGET_SECONDS
