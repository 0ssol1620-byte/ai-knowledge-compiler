"""INC-V2-107's repair: the corrected pagination contract, scoped and restored."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
import sfir6_protocol as p6  # noqa: E402


def test_the_corrected_set_is_the_frozen_one_plus_exactly_the_two_added_fields():
    assert {
        "retries_total",
        "transport_retries",
    } == p6.CORRECTED_PAGINATION_FIELDS - protocol.CAPACITY_PAGINATION_FIELDS
    assert set() == protocol.CAPACITY_PAGINATION_FIELDS - p6.CORRECTED_PAGINATION_FIELDS


def test_the_frozen_default_really_is_missing_them():
    """The defect, asserted rather than described. If this ever goes green the
    frozen module has been edited and INC-V2-107's premise no longer holds."""
    assert "retries_total" not in protocol.CAPACITY_PAGINATION_FIELDS
    assert "transport_retries" not in protocol.CAPACITY_PAGINATION_FIELDS


def test_the_contract_is_restored_after_use():
    before = set(protocol.CAPACITY_PAGINATION_FIELDS)
    with p6.corrected_pagination_contract():
        assert "retries_total" in protocol.CAPACITY_PAGINATION_FIELDS
    assert before == protocol.CAPACITY_PAGINATION_FIELDS


def test_the_contract_is_restored_even_when_the_seal_raises():
    """Scoped means scoped. A refused seal that left the contract widened would
    change how every later study's seal behaves, depending only on whether this
    module had been imported."""
    before = set(protocol.CAPACITY_PAGINATION_FIELDS)
    with pytest.raises(RuntimeError), p6.corrected_pagination_contract():
        raise RuntimeError("seal refused")
    assert before == protocol.CAPACITY_PAGINATION_FIELDS


def test_the_correction_does_not_widen_itself_to_whatever_a_census_carries():
    """A contract derived from the census it is checking would accept any drift,
    which is the defect wearing a repair's clothes. The two fields are named."""
    assert {"retries_total", "transport_retries"} == p6.FIELDS_ADDED_BY_INC_V2_098
    assert "some_future_field" not in p6.CORRECTED_PAGINATION_FIELDS


def test_the_frozen_module_is_byte_identical_after_a_seal(monkeypatch, tmp_path):
    before = p6.frozen_module_digest()
    monkeypatch.setattr(protocol, "seal_capacity", lambda *a, **k: tmp_path / "x.json")
    p6.seal_capacity(tmp_path, {}, {}, tmp_path / "c.json", tmp_path / "x.json", "t")
    assert p6.frozen_module_digest() == before


def test_sfir6_does_not_touch_the_capacity_criterion():
    """The repair is a schema comparison. The criterion stays in the frozen
    module at the numbers SFIR5 was judged against.

    Checked over the parsed AST, not the source text: a first version of this
    control grepped for "750" and went red on a docstring saying the threshold
    was unchanged. A test that cannot tell a description of a number from a use
    of one is not testing what it claims.
    """
    import ast

    frozen = (NS / "tools" / "sfir4_protocol.py").read_text(encoding="utf-8")
    assert "count < 750 or quota < 600" in frozen

    tree = ast.parse((NS / "tools" / "sfir6_protocol.py").read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    assert not ({750, 600, 1000} & literals), sorted(literals)
