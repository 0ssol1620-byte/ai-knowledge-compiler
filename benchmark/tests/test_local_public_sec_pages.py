"""WO-LPC-3: filer-page segmentation and DOM acceptance. Synthetic fixtures only."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lxml import etree

from benchmark.local_public import sec_pages
from benchmark.local_public.sec_align import IX, Candidate
from benchmark.local_public.sec_pages import (
    SegmentRefused,
    accept,
    dom_text,
    excerpt_html,
    has_script,
    segments,
)

NS = '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">'
BREAK = '<div style="Page-Break-After: ALWAYS"></div>'


def row(label: str, n: int) -> str:
    return (
        f'<tr><td>{label}</td><td><ix:nonFraction name="us-gaap:X" contextRef="c">{n}'
        "</ix:nonFraction></td></tr>"
    )


def page(*rows: str) -> str:
    return f"<table>{''.join(rows)}</table>"


def html(*pages: str, head: str = "") -> bytes:
    body = BREAK.join(pages)
    hid = '<div style="display:none"><ix:header>secret hidden</ix:header></div>'
    style = "<style>td{color:red}</style>"
    return f"{NS}<head>{style}{head}</head><body>{hid}{body}</body></html>".encode()


def cands(data: bytes) -> list[Candidate]:
    root = etree.fromstring(data, etree.XMLParser(huge_tree=True, recover=True))
    out = []
    for el in root.iter(f"{{{IX}}}nonFraction"):
        tr = next(a for a in el.iterancestors() if a.tag.endswith("tr"))
        label = " ".join("".join(tr[0].itertext()).split())
        out.append(
            Candidate(
                field_id=f"f{len(out)}", adsh="a", tag="X", anchor=label, gold="1", context_id="c",
                start=None, end="2025-01-01", scale=0, sign=None, sign_basis="match",
                ddate_rounded=False, dom_path=root.getroottree().getpath(el),
                fsds={"ddate": "20250101", "qtrs": "0"},
            )
        )  # fmt: skip
    return out


def reasons(res) -> list[str]:
    return [e.reason for e in res[1]]


GOOD = page(row("Revenue", 1), row("Cost", 2), row("Profit", 3))


def test_both_marker_spellings_split() -> None:
    a = (
        NS + '<body><p>a</p><p style="page-break-before:always">b</p>'
        '<p style="break-after: page">c</p><p>d</p></body></html>'
    ).encode()
    assert len(segments(a)) == 3


def test_no_markers_refused() -> None:
    with pytest.raises(SegmentRefused) as e:
        segments(b'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>a</p></body></html>')
    assert e.value.reason == "no_filer_page_breaks"


def test_marker_inside_table_is_nested() -> None:
    inner = page(
        row("Revenue", 1),
        '<tr style="page-break-before:always"><td>x</td></tr>',
        row("Cost", 2),
        row("Profit", 3),
    )
    d = html(inner, GOOD)
    segs = segments(d)
    res = accept(segs[0], cands(d))
    assert segs[0].nested and not res[0]
    assert set(reasons(res)) == {"nested_page_break"}


def test_accepts_three_unshadowed_fields() -> None:
    # marker-free page 0 plus the trailing page: use two pages so a marker exists
    d = html(GOOD, page(row("Other", 9)))
    s = segments(d)
    ok, bad = accept(s[0], cands(d))
    assert [c.anchor for c in ok] == ["Revenue", "Cost", "Profit"] and not bad


def test_total_in_earlier_row_shadows_later_row() -> None:
    p = page(row("Total", 1), row("Cost", 2), row("Profit", 3), row("Net", 4), row("Total", 5))
    d = html(p, page(row("Other", 9)))
    ok, bad = accept(segments(d)[0], cands(d))
    assert [e.reason for e in bad] == ["anchor_shadowed"] and len(ok) == 4


def test_shadowing_is_nfkc_casefold_substring_of_earlier_text() -> None:
    # an earlier heading containing the anchor shadows it, exactly as a substring search would
    p = "<p>Net TOTAL revenues\u00a0for the year</p>" + page(
        row("total revenues", 1), row("Cost", 2), row("Profit", 3), row("Gain", 4)
    )
    d = html(p, page(row("Other", 9)))
    ok, bad = accept(segments(d)[0], cands(d))
    assert [e.reason for e in bad] == ["anchor_shadowed"] and len(ok) == 3
    # fullwidth letters fold under NFKC
    p2 = "<p>\uff34\uff2f\uff34\uff21\uff2c</p>" + page(
        row("total", 1), row("Cost", 2), row("Profit", 3), row("Net", 4)
    )
    d2 = html(p2, page(row("Other", 9)))
    assert reasons(accept(segments(d2)[0], cands(d2))) == ["anchor_shadowed"]


def test_same_label_in_other_segment_does_not_shadow() -> None:
    d = html(page(row("Total", 1), row("Cost", 2), row("Profit", 3)), page(row("Total", 5)))
    s = segments(d)
    ok, bad = accept(s[0], cands(d))
    assert len(ok) == 3 and not bad
    assert reasons(accept(s[1], cands(d))) == ["too_few_fields"]


def test_too_few_fields() -> None:
    d = html(page(row("Revenue", 1), row("Cost", 2)), GOOD)
    s = segments(d)
    ok, bad = accept(s[0], cands(d))
    assert not ok and set(reasons((ok, bad))) == {"too_few_fields"}


def test_excerpt_is_standalone_and_clean() -> None:
    d = html(
        '<script>x()</script><link rel="stylesheet" href="a.css"/><base href="/b"/>' + GOOD,
        page(row("Other", 9)),
        head='<script>y()</script><link href="c.css"/><base href="/"/>',
    )
    s = segments(d)
    ex = excerpt_html(d, s[0]).decode()
    low = ex.lower()
    assert low.startswith("<!doctype html>") and '<meta charset="utf-8">' in ex
    assert re.search(r"<style[^>]*>td\{color:red\}</style>", ex)
    for bad in ("<script", "<link", "<base", "ix:header", "display:none", "secret hidden", "Other"):
        assert bad not in (ex if bad == "Other" else low)
    assert "Revenue" in ex
    with pytest.raises(ValueError):
        excerpt_html(d + b" ", s[0])


def test_dom_text_matches_segment_and_excludes_style() -> None:
    d = html(GOOD, page(row("Other", 9)))
    t = dom_text(excerpt_html(d, segments(d)[0]))
    assert t == "Revenue 1 Cost 2 Profit 3"


def test_has_script_any_case() -> None:
    assert has_script(b"<html><SCRIPT>1</SCRIPT></html>") and not has_script(b"<html>script</html>")


def test_module_imports_no_pdf_library() -> None:
    src = Path(sec_pages.__file__).read_text(encoding="utf-8")
    assert not any(w in src for w in ("pypdf", "pypdfium2", "fitz", "pdfminer", "PdfReader"))
    code = (
        "import benchmark.local_public.sec_pages, sys; "
        "print(sorted(k for k in sys.modules if 'pdf' in k.lower()))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_excerpt_br_is_not_doubled() -> None:
    d = html("<p>a<br/>b</p>" + GOOD, page(row("Other", 9)))
    ex = excerpt_html(d, segments(d)[0]).decode()
    assert "</br>" not in ex and "<br>" in ex


def test_word_split_across_inline_spans_shadows() -> None:
    p = "<p><span>Reven</span><span>ue</span></p>" + page(
        row("Revenue", 1), row("Cost", 2), row("Profit", 3), row("Net", 4)
    )
    d = html(p, page(row("Other", 9)))
    ok, bad = accept(segments(d)[0], cands(d))
    assert reasons((ok, bad)) == ["anchor_shadowed"] and len(ok) == 3


def test_anchor_inside_earlier_row_label_shadows() -> None:
    p = page(
        row("Cost of services and products (exclusive of depreciation and amortization)", 1),
        row("Depreciation and amortization", 2),
        row("Current portion of long-term debt", 3),
        row("Long-term debt", 4),
        row("Profit", 5),
    )
    d = html(p, page(row("Other", 9)))
    ok, bad = accept(segments(d)[0], cands(d))
    assert reasons((ok, bad)) == ["anchor_shadowed", "anchor_shadowed"] and len(ok) == 3


# ---------------------------------------------------------------- WO-LPC-4B delivery tag

TAG = b'<script type="text/javascript"  src="/7VAEeeTCJ/EoKUL1mR/Xrme"></script>'
FILED = b"<html><body><p>filed</p><table><tr><td>Revenue</td><td>1</td></tr></table>"


def tag(src: bytes = b"/a/b", head: bytes = b'<script type="text/javascript"  src="') -> bytes:
    return head + src + b'"></script>'


def gate(x: bytes) -> tuple[bytes, bool, bool]:
    """(bytes after the strip, stripped?, accepted by the script gate?)"""
    out, stripped = sec_pages.strip_delivery_tag(x)
    return out, stripped, not has_script(out)


@pytest.mark.parametrize(
    "tail",
    [b"</body></html>", b"</body> </html>\n", b"</body>\r\n</html>\r\n", b"\n</body>\t</html>"],
)
def test_delivery_tag_at_the_end_is_stripped_and_offsets_kept(tail: bytes) -> None:
    out, stripped, ok = gate(FILED + TAG + tail)
    assert (out, stripped, ok) == (FILED + tail, True, True)


REFUSED = {
    "second script earlier": b"<html><body><script>x=1</script><p>a</p>" + TAG + b"</body></html>",
    "two exact tags": FILED + TAG + TAG + b"</body></html>",
    "tag with a body": FILED + tag(b"/a/b").replace(b"></", b">x</") + b"</body></html>",
    "network path": FILED + tag(b"//evil.example/a") + b"</body></html>",
    # no dot: refused for the leading "//" alone (a forged tag is inert only if host-relative)
    "network path, no dot": FILED + tag(b"//evil/a") + b"</body></html>",
    "scheme": FILED + tag(b"http://evil.example/a") + b"</body></html>",
    "dot": FILED + tag(b"/a/b.js") + b"</body></html>",
    "query": FILED + tag(b"/a?b") + b"</body></html>",
    "dot segment": FILED + tag(b"/a/../b") + b"</body></html>",
    "empty src": FILED + tag(b"") + b"</body></html>",
    "root src": FILED + tag(b"/") + b"</body></html>",
    "empty segment": FILED + tag(b"/a//b") + b"</body></html>",
    "trailing slash": FILED + tag(b"/a/b/") + b"</body></html>",
    "async": FILED + tag(head=b'<script type="text/javascript"  async src="') + b"</body></html>",
    "onload": FILED
    + tag(head=b'<script type="text/javascript" onload="x" src="')
    + b"</body></html>",
    "defer": FILED + tag(head=b'<script defer type="text/javascript"  src="') + b"</body></html>",
    "single quotes": FILED + b"<script type='text/javascript'  src='/a/b'></script></body></html>",
    "one space": FILED + tag(head=b'<script type="text/javascript" src="') + b"</body></html>",
    "upper case": FILED + tag(head=b'<SCRIPT type="text/javascript"  src="') + b"</body></html>",
    "upper close": FILED + TAG.replace(b"</script>", b"</SCRIPT>") + b"</body></html>",
    "module": FILED + tag(head=b'<script type="module"  src="') + b"</body></html>",
    "text after": FILED + TAG + b"x</body></html>",
    "comment after": FILED + TAG + b"<!-- c --></body></html>",
    "element after": FILED + TAG + b"<p>a</p></body></html>",
    "after html": FILED + TAG + b"</body></html>x",
    "comment after html": FILED + TAG + b"</body></html><!-- c -->",
    "middle of body": b"<html><body>" + TAG + b"<p>real content</p></body></html>",
    "in a comment": FILED + b"<!--" + TAG + b"--></body></html>",
    "in CDATA": FILED + b"<![CDATA[" + TAG + b"]]></body></html>",
    "no closing body": FILED + TAG + b"</html>",
    "no closing html": FILED + TAG + b"</body>",
    "vertical tab is not ASCII whitespace": FILED + TAG + b"\v</body></html>",
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_delivery_tag_counter_examples_are_refused(name: str) -> None:
    assert gate(REFUSED[name])[2] is False


def test_no_script_is_unchanged_and_accepted() -> None:
    x = FILED + b"</body></html>"
    assert gate(x) == (x, False, True)


@pytest.mark.parametrize(
    "x",
    [
        b'<script type="text/javascript"  src="/' + b"a/" * 500_000,
        (b'<script type="text/javascript"  src="/a/a/a/a' * 25_000) + b"</body></html>",
        b'<script type="text/javascript"  src="/'
        + b"a" * 1_000_000
        + b'"></script>'
        + b" " * 100_000
        + b"x</body></html>",
    ],
    ids=["unterminated", "repeated", "trailing text"],
)
def test_unterminated_megabyte_is_refused_in_linear_time(x: bytes) -> None:
    import time

    t = time.perf_counter()
    out, stripped, ok = gate(x)
    assert time.perf_counter() - t < 1.0
    assert (out, stripped, ok) == (x, False, False)


_WS = rb"[ \t\n\f\r]*"
_ORACLE = re.compile(
    rb'(.*)<script type="text/javascript"  src="/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*"></script>'
    + rb"("
    + _WS
    + rb"</body>"
    + _WS
    + rb"</html>"
    + _WS
    + rb")",
    re.S,
)
_SRC = st.text(alphabet="/aZ9_-.?:", max_size=6).map(str.encode)
_BODY = st.sampled_from([b"", b"y"])
_PIECE = st.one_of(
    st.sampled_from(
        [TAG, b"<p>a</p>", b"text", b"<script>", b"<SCRIPT ", b"</script>", b" ", b"\n", b"\v",
         b"</body>", b"</html>", b"<!--", b"-->", b"<![CDATA[", b"]]>", b"x"]
    ),
    st.builds(lambda s, b: tag(s).replace(b"></", b">" + b + b"</"), _SRC, _BODY),
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(st.lists(_PIECE, max_size=12))
def test_strip_removes_at_most_one_tail_tag_and_gate_is_no_script_left(parts: list[bytes]) -> None:
    x = b"".join(parts)
    out, stripped, ok = gate(x)
    m = _ORACLE.fullmatch(x)
    assert (out, stripped) == ((m[1] + m[2], True) if m else (x, False))
    assert ok is (re.search(rb"<script", out, re.I) is None)
