"""The instruments must catch what they claim to catch, and refuse what they don't.

These are contract tests on the instruments themselves, not on the model. An
instrument that returns a constant looks identical, in a receipt, to a system
with no defects -- which is how the first version of both of these produced a
null result that meant nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1].parent / "H1-A9-01" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from holdout_power_calculation import fisher_exact_two_sided  # noqa: E402
from repaired_output_instruments import (  # noqa: E402
    evidence_defects,
    evidence_validity,
    structural_defects,
    structural_validity,
    table_shapes,
)

HTML_TABLE = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"


def test_the_parser_reads_html_tables_because_that_is_what_the_model_emits():
    tables, cells = table_shapes(HTML_TABLE)
    assert tables == [[2, 2]]
    assert cells == 4


def test_colspan_counts_toward_row_width():
    tables, _ = table_shapes(
        '<table><tr><td colspan="3">a</td></tr><tr><td>b</td></tr></table>'
    )
    assert tables == [[3, 1]]


def test_an_unclosed_table_still_counts():
    tables, cells = table_shapes("<table><tr><td>a</td></tr>")
    assert tables == [[1]]
    assert cells == 1


def test_a_ragged_table_is_a_structural_defect_and_a_square_one_is_not():
    assert structural_defects(HTML_TABLE)["ragged_tables"] == 0
    ragged = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"
    assert structural_defects(ragged)["ragged_tables"] == 1
    assert structural_validity(ragged) < structural_validity(HTML_TABLE)


@pytest.mark.parametrize(
    "text,field",
    [
        ("Revised 13/45/2026.", "impossible_dates"),
        ("Dated 2026-02-31.", "impossible_dates"),
        ("Total 12..7 units.", "malformed_numbers"),
        ("Price $ each.", "orphan_currency_symbols"),
        ("Change --5 percent.", "double_signs"),
    ],
)
def test_each_evidence_defect_is_detected(text: str, field: str):
    assert evidence_defects(text)[field] >= 1
    assert evidence_validity(text) < 1.0


@pytest.mark.parametrize(
    "text",
    [
        "Dated 2026-02-28 and 12/31/2025.",
        "Price $1,250.00 and $(340).",
        "Change -5 percent, then +3 percent.",
        HTML_TABLE,
    ],
)
def test_well_formed_text_is_not_flagged(text: str):
    assert evidence_validity(text) == 1.0


def test_the_fast_fisher_agrees_with_the_exact_integer_form():
    """lgamma replaced math.comb for speed; the decision must not have moved."""
    import math

    def exact(a: int, b: int, c: int, d: int) -> float:
        rows, cols, total = (a + b, c + d), (a + c, b + d), a + b + c + d
        if total == 0 or 0 in rows or 0 in cols:
            return 1.0

        def probability(x: int) -> float:
            return (
                math.comb(cols[0], x)
                * math.comb(cols[1], rows[0] - x)
                / math.comb(total, rows[0])
            )

        observed = probability(a)
        low, high = max(0, rows[0] - cols[1]), min(rows[0], cols[0])
        return min(
            1.0,
            sum(
                probability(x)
                for x in range(low, high + 1)
                if probability(x) <= observed + 1e-12
            ),
        )

    for cells in [(7, 174, 5, 12), (1, 99, 1, 99), (0, 10, 5, 5), (12, 186, 0, 0)]:
        assert fisher_exact_two_sided(*cells) == pytest.approx(exact(*cells), abs=1e-9)


def test_r4_treats_a_missing_second_parser_as_abstention() -> None:
    """Amendment 01 must hold in the cost analysis too, not only in the test.

    On the discovery set every page had a second-parser prediction, so this
    branch was unreachable and `r4_marginal_analysis` read the file
    unconditionally. On the 800-page holdout 15 pages have none, and the
    unconditional read raised FileNotFoundError mid-analysis.

    The dangerous repair would have been to treat a missing prediction as
    agreement: that accepts exactly the pages carrying the least evidence, and
    it would put the cost analysis and the confirmatory test on different gates.
    The fix scores them at zero agreement so they fall below any floor.
    """
    source = (
        Path(__file__).resolve().parents[4]
        / "research" / "experiments" / "H1-A9-01" / "scripts"
        / "r4_marginal_analysis.py"
    ).read_text(encoding="utf-8")

    assert "other_path.is_file()" in source, (
        "the second-parser prediction must be probed, not assumed present"
    )
    assert '"agreement": 0.0 if mismatches is None else' in source, (
        "a missing second-parser prediction must score zero agreement, so that "
        "it falls below every floor and abstains"
    )
    assert '.read_text(\n            "utf-8"\n        )' not in source, (
        "the unconditional read of the second-parser prediction is back"
    )
