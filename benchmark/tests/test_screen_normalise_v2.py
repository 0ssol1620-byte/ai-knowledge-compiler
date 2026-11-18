"""Markup normaliser v2 (WO-D10-0V, decision 5H-11): v1 plus the markup v1 left on real pages.

Every fixture is a constructed string; no stored model output, no gold, no real page.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.screen import normalise_v1 as n1
from benchmark.screen import normalise_v2 as n2
from benchmark.screen.critical_fields import gold_value, value_after_anchor

N = "nemotron_parse_3_5"
BS = "\\"
BOX, BREAK = BS + "mbox{}", BS + "linebreak{}"


def _field(anchor: str, value: str) -> dict[str, str]:
    return {"field_id": "f", "kind": "number", "anchor": anchor, "value": value}


def _tabular(*rows: str) -> str:
    return (
        BS
        + "begin{tabular}{ccc}\n"
        + "".join(r + " " + BS * 2 + "\n" for r in rows)
        + (BS + "end{tabular}")
    )


# ---------------------------------------------------------------- pins


def test_v1_is_byte_identical_and_v2_extends_exactly_it() -> None:
    v1 = "sha256:" + hashlib.sha256(Path(n1.__file__).read_bytes()).hexdigest()
    assert v1 == n1.MODULE_SHA256 == n2.V1_SHA256
    assert n2.V1_SHA256.endswith("26ab") and n2.V1_SHA256.startswith("sha256:94bfe9f5")


def test_module_sha256_is_the_file() -> None:
    data = Path(n2.__file__).read_bytes()
    assert n2.MODULE_SHA256 == "sha256:" + hashlib.sha256(data).hexdigest() != n1.MODULE_SHA256


def test_v2_refuses_to_load_on_another_v1(tmp_path: Path) -> None:
    """A changed v1 changes v2's behaviour under the same v2 digest: v2 does not load."""
    root = Path(n1.__file__).resolve().parents[2]
    pkg = tmp_path / "benchmark" / "screen"
    pkg.mkdir(parents=True)
    (tmp_path / "benchmark" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "normalise_v1.py").write_bytes(Path(n1.__file__).read_bytes() + b"\n# changed\n")
    (pkg / "normalise_v2.py").write_bytes(Path(n2.__file__).read_bytes())
    code = "import benchmark.screen.normalise_v2"
    r = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r}); {code}"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert r.returncode != 0 and b"not the v1 that normalise_v2 extends" in r.stderr
    assert root != tmp_path


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="no normaliser profile"):
        n2.normalise("gemini_api", "x")


# ---------------------------------------------------------------- each construct, glued and spaced

NEMOTRON = [
    (f"a {BOX} b", "a   b"),  # between spaces
    (f"a{BOX}b", "a b"),  # glued between letters
    (f"Total{BOX}\n1", "Total \n1"),  # before a line end
    (f"{BS}thead{{Total{BOX}}}", "Total "),  # inside another command's braces
    (f"{BS}thead{{{BOX}}}", " "),  # a header that held only an empty box
    (f"Dec 31,{BREAK}2025", "Dec 31, 2025"),  # directly before a digit
    (f"net{BREAK}income", "net income"),  # between letters
    (f"{BS}thead{{Dec 31,{BREAK}2025}}", "Dec 31, 2025"),
    (f"{BS}multirow{{2}}{{*}}{{Total{BOX}}}", "Total "),
    (f"{BS}multicolumn{{3}}{{c}}{{{BS}thead{{Year{BREAK}ended}}}}", "Year ended"),
    (f"{BS}multirow{{2}}{{*}}{{{BS}textbf{{Net{BOX}loss}}}}", "Net loss"),
]


@pytest.mark.parametrize(("text", "out"), NEMOTRON)
def test_nemotron_empty_boxes_become_a_space_and_their_wrappers_unwrap(text: str, out: str) -> None:
    assert n1.normalise(N, text)[1] > 0  # what v1 left
    assert n2.normalise(N, text) == (out, 0)
    assert n2.normalise(N, out) == (out, 0)


@pytest.mark.parametrize("provider", sorted(n1.PROFILES))
def test_empty_boxes_are_nemotron_markup_only(provider: str) -> None:
    text = f"a{BOX}b{BREAK}c"
    if provider != N:
        assert n2.normalise(provider, text) == n1.normalise(provider, text)


def test_a_box_after_an_odd_backslash_run_is_text_after_a_row_end() -> None:
    row_end_then_text = f"x {BS * 2}mbox{{}} y"  # \\ ends a row; "mbox{}" is then text
    assert n2.normalise(N, row_end_then_text) == n1.normalise(N, row_end_then_text)
    row_end_then_box = f"x {BS * 2}{BOX} y"  # \\ then a real empty box
    assert n2.normalise(N, row_end_then_box) == n1.normalise(N, f"x {BS * 2}  y")
    inside = _tabular(f"Revenue & 1,234 {BS * 2}{BOX} & 5")
    lines = [[c.strip() for c in x.split("|")] for x in n2.normalise(N, inside)[0].split("\n")]
    assert ["Revenue", "1,234"] in lines and ["", "5"] in lines


SUP_IMG = [
    ("<sup>", " "),
    ("</sup>", " "),
    ('<sup class="fn" id="a1">', " "),
    ("<SUP>", " "),
    ("</sup >", " "),
    ("<sup/>", " "),
    ('<img src="figure.png" alt="chart"/>', " "),
    ("<img>", " "),
]


@pytest.mark.parametrize("provider", sorted(n1.PROFILES))
@pytest.mark.parametrize(("tag", "space"), SUP_IMG)
def test_sup_and_img_become_one_space_in_every_profile(provider: str, tag: str, space: str) -> None:
    for text, want in ((f"a{tag}1", f"a{space}1"), (f"a {tag} 1", f"a {space} 1")):
        assert n2.normalise(provider, text) == (want, 0), (tag, text)
    assert n1.normalise(provider, f"a{tag}1")[1] == 1  # what v1 left


def test_a_tag_that_only_starts_like_sup_or_img_is_left_and_counted() -> None:
    for tag in ("<super>", "<imgx>", "<supx a>"):
        out, residual = n2.normalise("ovis_ocr2", f"a{tag}1")
        assert out == f"a{tag}1" and residual == 1


def test_an_unclosed_or_overlong_sup_is_left_as_it_is() -> None:
    long = "<sup " + "x" * 201 + ">"
    assert n2.normalise("ovis_ocr2", "a<sup 1")[0] == "a<sup 1"
    assert n2.normalise("ovis_ocr2", long + "1")[0] == long + "1"


# ---------------------------------------------------------------- the symbol join (5H-11)


def _cells(text: str) -> list[list[str]]:
    return [[c.strip() for c in line.split("|")] for line in text.splitlines()]


def test_a_cell_holding_only_an_empty_box_is_an_empty_cell_for_the_symbol_join() -> None:
    assert n2.normalise(N, f"$ | {BOX} | 1,234") == n1.normalise(N, "$ | | 1,234")
    for cells, value in (
        (["Revenue", BS + "$", BOX, "1,234"], "$ 1,234"),
        (["Revenue", "(1,234", BOX, ")"], "(1,234)"),
        (["Margin", "1.5", BOX, BS + "%"], "1.5%"),
        (["Revenue", BOX, "1,234"], "1,234"),
    ):
        text = _tabular(" & ".join(cells))
        out = n2.normalise(N, text)[0]
        empty = _tabular(" & ".join("" if c == BOX else c for c in cells))
        assert _cells(out) == _cells(n1.normalise(N, empty)[0]), repr(out)  # one space more
        field = _field(cells[0], value)
        assert value_after_anchor(field, out) == gold_value(field), repr(out)
        if value != "1,234":  # a symbol cell: v1 kept the box as a non-empty cell, no join
            assert value_after_anchor(field, n1.normalise(N, text)[0]) != gold_value(field)


def test_two_value_cells_stay_apart_across_an_empty_box() -> None:
    out = n2.normalise(N, _tabular(f"Revenue & 1,234 & {BOX} & 5"))[0]
    held = [c.strip() for line in out.split("\n") for c in line.split("|")]
    assert "1,234" in held and "5" in held


# ---------------------------------------------------------------- the frozen reader after v2


def test_a_footnote_marker_after_a_value_no_longer_hides_the_value() -> None:
    field = _field("Revenue", "1,234")
    for provider, text in (
        ("ovis_ocr2", "<table><tr><td>Revenue</td><td>1,234<sup>(a)</sup></td></tr></table>"),
        ("ovis_ocr3", "| Revenue | 1,234<sup>1</sup> |"),
        (N, _tabular("Revenue & 1,234<sup>(a)</sup>")),
    ):
        assert value_after_anchor(field, n1.normalise(provider, text)[0]) is None
        assert value_after_anchor(field, n2.normalise(provider, text)[0]) == ("1234", "num", None)


def test_a_footnote_marker_between_label_and_value_is_read_as_the_first_token() -> None:
    """The work order asks ``Revenue<sup>(1)</sup> | 1,234`` to read 1,234. With ``<sup>`` as
    one space (the rule as written) the frozen reader reads the marker (1) as the first token
    after the anchor: -1. v1 read nothing (the token was glued to markup). Reaching 1,234
    would need the marker's digits removed or moved, which the v1 guarantees forbid; the lead
    decides (proposed delta). This test states what the code does, so the decision is visible."""
    field = _field("Revenue", "1,234")
    for provider in ("ovis_ocr2", N):
        text = "Revenue<sup>(1)</sup> | 1,234"
        assert value_after_anchor(field, n1.normalise(provider, text)[0]) is None
        assert n2.normalise(provider, text)[0] == "Revenue (1)  | 1,234"
        assert value_after_anchor(field, n2.normalise(provider, text)[0]) == ("-1", "num", None)


# ---------------------------------------------------------------- nesting to TEX_PASSES


@pytest.mark.parametrize("depth", range(1, n2.TEX_PASSES + 2))
def test_nesting_with_a_box_unwraps_as_without_it_to_the_bound(depth: int) -> None:
    wrapped = (BS + "textbf{") * depth + f"x{BOX}" + "}" * depth
    plain = (BS + "textbf{") * depth + "x " + "}" * depth
    assert n2.normalise(N, wrapped) == n1.normalise(N, plain)
    want = 0 if depth <= n2.TEX_PASSES else 1  # past the bound: left visible, counted
    assert n2.normalise(N, wrapped)[1] == want


# ---------------------------------------------------------------- properties


class _Draw:
    """A seeded deterministic draw for generated inputs (a 64-bit LCG; nothing secret)."""

    def __init__(self, seed: str) -> None:
        self.state = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big")

    def below(self, n: int) -> int:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) % 2**64
        return (self.state >> 16) % n

    def choice(self, seq: list[str] | str) -> str:
        return seq[self.below(len(seq))]

    def randint(self, a: int, b: int) -> int:
        return a + self.below(b - a + 1)

    def random(self) -> float:
        return self.below(1_000_000) / 1_000_000


V1_TOKENS = [
    "<td>",
    "</td>",
    "<tr>",
    "</tr>",
    '<th class="h">',
    "</th>",
    "<table>",
    "<br/>",
    "<p>",
    "<fcel>",
    "<ecel>",
    "<lcel>",
    "<ched>",
    "<nl>",
    "<x_0.51>",
    "<y_0.2>",
    "<class_Text>",
    BS + "textbf{",
    BS + "thead{",
    BS + "text{",
    BS + "multirow{2}{*}{",
    BS + "multicolumn{3}{c}{",
    "}",
    "{",
    BS + "begin{tabular}{cc}",
    BS + "end{tabular}",
    "&",
    BS * 2,
    BS + "&",
    BS + "$",
    BS + "%",
    BS + "hline",
    "|",
    "$",
    "€",
    "(",
    ")",
    "%",
    "-",
    "\u2212",
    "+",
    "1,234",
    "5",
    "2025",
    "Revenue",
    "Net",
    " ",
    " ",
    "\n",
    "\u00a0",
    "&amp;",
    "&#160;",
    "&para",
    BS + "mbox{x}",
    BS + "mbox",
    BS + "linebreak",
    "{}",
    "<su",
    "p>",
    "<i",
    "mg>",
    "</s",
    "up>",
    "<span>",
    BS + "frac",
    "<",
]
# independent of v2's own patterns: any input holding a construct v2 adds is left out
NEW = re.compile(r"\\(?:mbox|linebreak)\{\}|<\s*/?\s*(?:sup|img)", re.IGNORECASE)


def test_v2_equals_v1_on_inputs_without_the_new_constructs() -> None:
    rng = _Draw("v2-equals-v1")
    checked = 0
    for _ in range(1500):
        text = "".join(rng.choice(V1_TOKENS) for _ in range(rng.randint(0, 40)))
        if NEW.search(text):
            continue
        checked += 1
        for provider in n1.PROFILES:
            assert n2.normalise(provider, text) == n1.normalise(provider, text), (provider, text)
    assert checked > 1000


DIGITS, SIGNS, CURRENCY = "0123456789", "-+\u2212", "$€£¥"
CONTENT = DIGITS + SIGNS + CURRENCY + "abcRXZ" + " ,.()%"
FREE = ["<sup>", "</sup>", '<sup id="n1">', '<img src="f.png" alt="x"/>', "<SUP>"]
TEX = [BOX, BREAK]
WRAPS = [BS + "thead{", BS + "textbf{", BS + "textit{", BS + "text{"]
WRAPS += [BS + "multirow{2}{*}{", BS + "multicolumn{3}{c}{"]


def _classes(text: str) -> list[str]:
    out = []
    for c in text:
        if c in DIGITS:
            out.append("digit")
        elif c in SIGNS:
            out.append("sign:" + c)
        elif c in CURRENCY:
            out.append("cur:" + c)
        elif c.isalpha():
            out.append("letter:" + c)
    return out


def _generate(rng: _Draw, tex: bool, depth: int = 0) -> tuple[str, str]:
    """(text, its content alone): content characters among markup v2 removes entirely."""
    text, content = [], []
    for _ in range(rng.randint(0, 12)):
        roll = rng.random()
        if roll < 0.5:
            c = "".join(rng.choice(CONTENT) for _ in range(rng.randint(1, 4)))
            text.append(c)
            content.append(c)
        elif roll < 0.7:
            text.append(rng.choice(FREE))
        elif tex and roll < 0.85:
            text.append(rng.choice(TEX))
        elif tex and depth < 3:
            inner, inner_content = _generate(rng, tex, depth + 1)
            text.append(rng.choice(WRAPS) + inner + "}")
            content.append(inner_content)
    return "".join(text), "".join(content)


@pytest.mark.parametrize("provider", sorted(n1.PROFILES))
def test_digits_signs_currency_and_letters_are_never_added_removed_or_reordered(
    provider: str,
) -> None:
    """Over generated inputs: the sequence of digit, sign, currency and letter characters of
    v2's output is the input's with only the removed command and tag names (and their
    arguments) taken out, and nothing is left over."""
    rng = _Draw(provider)
    for _ in range(600):
        text, content = _generate(rng, tex=provider == N)
        if rng.random() < 0.3 and provider == N:  # also inside a tabular span
            text = BS + "begin{tabular}{cc}\n" + text + " " + BS * 2 + "\n" + BS + "end{tabular}"
        out, residual = n2.normalise(provider, text)
        assert _classes(out) == _classes(content), (provider, text, out)
        assert residual == 0, (provider, text, out)


# ---------------------------------------------------------------- linear in the input
# The shape of v1's linearity test (same sizes, ratio, floor, 1 MB bound and retries), each
# measurement in a fresh `-I` interpreter as WO-D10-0T moved v1's there: the CPU time of the
# call alone, so a full collection over the test process's heap is never in the timer. The
# module is loaded from n2.__file__ (a mutant copy put first on the path is what is measured);
# v1 comes from the repository it was imported from.

UNITS = {
    "box_spaced": BOX + " ",
    "box_glued": "a" + BOX,
    "linebreak": "1" + BREAK,
    "box_in_thead": BS + "thead{x" + BOX + "}",
    "box_in_multirow": BS + "multirow{2}{*}{" + BOX + "}",
    "box_unclosed": BS + "mbox{",
    "backslash_run": BS * 3,
    "backslash_run_box": BS * 101 + BOX,
    "sup_pair": "a<sup>(1)</sup>",
    "sup_unclosed": "<sup ",
    "img": '<img src="a.png"/>',
    "img_unclosed": "<img ",
    "symbol_box_cell": "$ | " + BOX + " | ",
}
SIZES = (250_000, 500_000, 1_000_000, 2_000_000)
RATIO, FLOOR_S, ONE_MB_S = 3.0, 0.1, 5.0
RETRIES = 4
CHILD = (
    "import gc, importlib.util, json, sys, time\n"
    "job = json.loads(sys.stdin.buffer.read())\n"
    "sys.path.insert(0, job['root'])\n"
    "spec = importlib.util.spec_from_file_location('normalise_v2_under_test', job['module'])\n"
    "n2 = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(n2)\n"
    "text = job['unit'] * (job['size'] // len(job['unit']))\n"
    "gc.collect()\n"
    "start = time.process_time()\n"
    "n2.normalise(job['provider'], text)\n"
    "print(json.dumps(time.process_time() - start))\n"
)


def _cpu_seconds(provider: str, unit: str, size: int) -> float:
    job = {
        "root": str(Path(n1.__file__).resolve().parents[2]),
        "module": n2.__file__,
        "provider": provider,
        "unit": unit,
        "size": size,
    }
    r = subprocess.run(
        [sys.executable, "-I", "-c", CHILD],
        input=json.dumps(job).encode("ascii"),
        capture_output=True,
        timeout=120,
        check=True,
    )
    return float(json.loads(r.stdout))


@pytest.mark.parametrize("provider", ["mineru", N])
@pytest.mark.parametrize("shape", list(UNITS))
def test_normalise_is_linear_in_its_input(provider: str, shape: str) -> None:
    took: list[float] = []
    for size in SIZES:
        took.append(_cpu_seconds(provider, UNITS[shape], size))
        for _ in range(RETRIES):
            if len(took) < 2 or took[-1] <= RATIO * max(took[-2], FLOOR_S):
                break
            took[-1] = min(took[-1], _cpu_seconds(provider, UNITS[shape], size))
        if len(took) > 1:
            assert took[-1] <= RATIO * max(took[-2], FLOOR_S), (size, took)
        if size == 1_000_000:
            assert took[-1] < ONE_MB_S, took


# ---------------------------------------------------------------- residual counted as v1 counts


def test_residual_is_counted_the_same_way() -> None:
    text = f"<span>1</span> {BS}frac <sup>2</sup> {BOX}"
    out, residual = n2.normalise(N, text)
    assert residual == len(n1._RESIDUAL.findall(out)) == 3  # <span>, </span>, \frac


# ---------------------------------------------------------------- mutants


def test_mutant_box_without_the_backslash_rule_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(n2, "_EMPTY_BOX", re.compile(r"()\\(?:mbox|linebreak)\{\}"))
    with pytest.raises(AssertionError):
        test_a_box_after_an_odd_backslash_run_is_text_after_a_row_end()


def test_mutant_sup_removed_without_a_space_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    loose = re.compile(r"</?sup\b[^<>]{0,200}>|<img\b[^<>]{0,200}>", re.IGNORECASE)
    monkeypatch.setattr(n2, "_SUP_IMG", type("M", (), {"sub": lambda _, r, t: loose.sub("", t)})())
    with pytest.raises(AssertionError):
        test_sup_and_img_become_one_space_in_every_profile("ovis_ocr2", "<sup>", " ")


def test_mutant_box_after_the_wrapper_fixed_point_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    after = n1._nemotron
    monkeypatch.setitem(n2._STEPS, "nemotron", lambda t: n2._EMPTY_BOX.sub(r"\1 ", after(t)))
    with pytest.raises(AssertionError):
        test_nemotron_empty_boxes_become_a_space_and_their_wrappers_unwrap(*NEMOTRON[3])
