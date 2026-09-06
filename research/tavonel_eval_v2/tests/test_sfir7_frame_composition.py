"""Controls for the composition description of the frozen roster.

The description is written before the census runs, which is the only time a
limitation costs anything to register. These controls exist so that it describes
the roster it claims to and so that it stays incapable of anticipating a result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_frame as frame  # noqa: E402
import sfir7_frame_composition as composition  # noqa: E402

FREEZE = NS / "receipts/sfir7-roster-freeze.json"
RECEIPT = NS / "receipts/sfir7-frame-composition.json"


def _freeze() -> dict:
    return json.loads(FREEZE.read_text(encoding="utf-8"))


def test_the_description_is_bound_to_the_roster_it_describes():
    """A description that survives a changed roster describes nothing."""
    body = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert body["describes_roster_fingerprint"] == _freeze()["roster_fingerprint"]


def test_a_roster_that_does_not_match_its_own_count_is_refused():
    freeze = _freeze()
    freeze["roster"] = freeze["roster"][:10]
    with pytest.raises(composition.CompositionRefused, match="not the roster"):
        composition.describe(freeze, declared_licences=frame.SPDX_ALLOWLIST)


def test_the_description_computes_no_capacity_and_no_yield():
    """The whole point of running it before the census."""
    body = composition.describe(_freeze(), declared_licences=frame.SPDX_ALLOWLIST)
    assert body["computes_no_capacity"] is True
    assert body["computes_no_yield"] is True
    assert body["census_started"] is False
    text = json.dumps(body)
    for numeral in frame.FORBIDDEN_NUMERALS:
        assert numeral not in text, numeral


def test_the_language_limitation_is_registered_with_a_real_imbalance():
    """A limitation nobody could have violated is not a limitation."""
    body = composition.describe(_freeze(), declared_licences=frame.SPDX_ALLOWLIST)
    largest = max(body["languages"].values())
    assert largest > body["roots"] / 2, "no imbalance to register"
    limitation = next(row for row in body["registered_limitations"] if row["id"] == "SFIR7-L1")
    assert str(largest) in limitation["limitation"]
    assert limitation["why_it_is_not_repaired"]


def test_absent_licence_families_are_named_rather_than_summarised():
    body = composition.describe(_freeze(), declared_licences=frame.SPDX_ALLOWLIST)
    absent = body["declared_licences_absent_from_the_roster"]
    present = set(body["licences_as_published"])
    for value in frame.SPDX_ALLOWLIST:
        spellings = set(frame.catalog_spellings(value))
        assert (value in absent) is not bool(spellings & present)


def test_overlap_with_earlier_roots_is_reported_and_not_excluded():
    """SFIR7 does not curate the external universe, so overlap is a diagnostic."""
    body = composition.describe(_freeze(), declared_licences=frame.SPDX_ALLOWLIST)
    overlap = body["overlap_with_earlier_git_roots"]
    assert overlap["count"] == len(overlap["shared"])
    assert overlap["earlier_roots"] == 20
    charter_rule = frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256="sha256:" + "0" * 64,
        snapshot_date_utc="2020-01-12",
    )
    assert not any(
        "sfir" in str(predicate.value).casefold() for predicate in charter_rule.predicates
    ), "no predicate may exclude earlier roots"
