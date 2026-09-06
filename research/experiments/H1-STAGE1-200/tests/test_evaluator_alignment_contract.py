"""The instrument's table unit must stay the evaluator's table unit.

The 88-versus-60 gap was investigated on the assumption that nested tables were
being double counted. They were not: the extraction unit was already identical to
the evaluator's, and the gap is the model over-segmenting. These tests pin that
identity so a future edit cannot quietly reintroduce the discrepancy the
investigation ruled out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1].parent / "H1-A9-01" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from evaluator_aligned_instruments import (  # noqa: E402
    CORRUPTIONS,
    aligned_table_count,
    detect_critical_field,
    detect_evidence,
    extract_html_table,
    page_structural_flag,
)
from repaired_output_instruments import evidence_defects, without_math  # noqa: E402

EVALUATOR = (
    Path(__file__).resolve().parents[4]
    / "benchmark"
    / "cache"
    / "omnidoc"
    / "src"
    / "core"
    / "preprocess"
    / "extract.py"
)

NESTED = "<table><tr><td><table><tr><td>inner</td></tr></table></td></tr></table>"
FLAT = "<table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table>"


def test_a_nested_table_counts_once_as_its_outermost_parent():
    assert aligned_table_count(NESTED) == 1


def test_sibling_tables_count_separately():
    assert aligned_table_count(FLAT) == 2


def test_positions_delimit_the_tables_they_name():
    tables, positions = extract_html_table(FLAT)
    for table, (start, end) in zip(tables, positions, strict=True):
        assert FLAT[start:end] == table


@pytest.mark.skipif(not EVALUATOR.exists(), reason="official evaluator not vendored")
def test_the_copy_still_matches_the_evaluators_own_function():
    """If the evaluator is upgraded and its extractor changes, this must fail."""
    source = EVALUATOR.read_text(encoding="utf-8")
    start = source.index("def extract_html_table(text):")
    end = source.index("def extract_node_content(", start)
    namespace: dict[str, object] = {}
    exec(compile("import re\n" + source[start:end], "<evaluator>", "exec"), namespace)  # noqa: S102
    official = namespace["extract_html_table"]

    for sample in (NESTED, FLAT, "no tables here", "<table><tr><td>unclosed"):
        assert official(sample) == extract_html_table(sample)


def test_the_page_flag_is_presence_not_a_rate():
    """A page with many clean tables must not outscore a page with one."""
    many = FLAT * 12
    assert page_structural_flag(many)["tables"] == 24
    assert page_structural_flag(many)["structurally_defective"] is False
    ragged = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"
    assert page_structural_flag(ragged)["structurally_defective"] is True
    assert page_structural_flag(ragged + FLAT * 12)["structurally_defective"] is True


# --- the LaTeX math correction ---------------------------------------------

def test_math_delimiters_are_not_currency_symbols():
    """The defect that produced a retracted p = 0.0014."""
    priced = r"Smaller plates $\$$6-$\$$18, larger plates $\$$18-$\$$32"
    assert evidence_defects(priced)["orphan_currency_symbols"] == 0


def test_a_real_orphan_currency_symbol_is_still_caught():
    assert evidence_defects("Price $ each.")["orphan_currency_symbols"] == 1


def test_stripping_math_preserves_offsets():
    text = r"a $x^2$ b"
    assert len(without_math(text)) == len(text)
    assert without_math(text).endswith(" b")


# --- the corruption fixtures actually corrupt -------------------------------

TABLE_DOC = (
    "<table><tr><td>Revenue</td><td>1200</td></tr>"
    "<tr><td>Cost</td><td>-340</td></tr></table>\n\n"
    "Reported 2026-02-11 by Acme, up 12 km over 45 days."
)


@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
def test_every_corruption_changes_the_document(name: str):
    import random

    corrupted = CORRUPTIONS[name](TABLE_DOC, random.Random(1))  # noqa: S311
    assert corrupted is not None, f"{name} could not be applied to the fixture"
    assert corrupted != TABLE_DOC


@pytest.mark.parametrize(
    "name", ["number_change", "sign_change", "date_change", "unit_change"]
)
def test_the_reference_based_instrument_sees_field_level_corruption(name: str):
    import random

    corrupted = CORRUPTIONS[name](TABLE_DOC, random.Random(1))  # noqa: S311
    assert detect_critical_field(corrupted, TABLE_DOC) is True


def test_the_output_only_evidence_instrument_does_not_claim_to_see_them():
    """Recorded as a property, not a defect: it has no reference to compare with."""
    import random

    corrupted = CORRUPTIONS["number_change"](TABLE_DOC, random.Random(1))  # noqa: S311
    assert detect_evidence(corrupted) is False
