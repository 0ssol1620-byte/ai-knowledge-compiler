"""Controls for the legacy-failure taxonomy.

`D == 0` is a freeze precondition, so the interesting question is not whether
the classifier can produce a zero -- anything can produce a zero -- but whether
it can still produce a D. Most of what follows drives the classifier towards
the answer that blocks the freeze and checks that it gets there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_legacy_taxonomy as tax  # noqa: E402

RECEIPT = NS / "receipts/sfir9-legacy-failure-taxonomy.json"


def record(**overrides):
    body = {
        "nodeid": "tests/test_something.py::test_it",
        "phase": "call",
        "exception": "ModuleNotFoundError: No module named 'tokenizers'",
        "traceback_tail": "  import tokenizers",
    }
    body.update(overrides)
    return body


# ------------------------------------------------- the classifier can say D


def test_an_unrecognised_failure_is_a_d():
    """The default blocks the freeze. A permissive default would be quietest
    exactly when a new, unexamined failure appeared."""
    row = tax.classify(record(exception="ValueError: something nobody has seen"))
    assert row["category"] == tax.D
    assert row["signature"] is None
    assert row["why"] == tax.UNCLASSIFIED
    assert row["value_bearing_for_sfir9"] is True


def test_an_unrecognised_failure_makes_the_freeze_condition_fail():
    report = tax.taxonomy([record(exception="ValueError: novel")])
    assert report["counts"]["D"] == 1
    assert report["freeze_condition_met"] is False


@pytest.mark.parametrize("module", tax.SFIR9_COMPONENT_MODULES)
def test_a_failure_touching_a_frozen_component_is_a_d_whatever_else_it_matches(module):
    """Even a traceback that also matches a benign signature.

    Without this, a genuine defect inside a bound component could be waved
    through by an unrelated `ModuleNotFoundError` further up the stack.
    """
    row = tax.classify(
        record(
            exception="ModuleNotFoundError: No module named 'tokenizers'",
            traceback_tail=f"  File 'tools/{module}.py', line 4, in freeze",
        )
    )
    assert row["category"] == tax.D
    assert row["signature"] == "sfir9_component_in_traceback"
    assert row["sfir9_components_in_traceback"] == [module]


def test_the_component_check_does_not_fire_on_an_unrelated_traceback():
    """Otherwise the previous test would pass for the wrong reason."""
    row = tax.classify(record())
    assert row["sfir9_components_in_traceback"] == []
    assert row["category"] == tax.C


def test_every_component_the_freeze_binds_is_watched_for():
    """The list is the closure's list, not a subset someone trimmed."""
    import sfir9_execution_closure as closure

    assert set(tax.SFIR9_COMPONENT_MODULES) == {c.module for c in closure.COMPONENTS}


# ------------------------------------------------ classification is by cause


def test_no_signature_matches_on_a_test_name():
    """The rule the ruling states outright: not by name, by root cause."""
    for signature in tax.SIGNATURES:
        assert "test_" not in signature.pattern, signature.key
        assert "::" not in signature.pattern, signature.key


def test_a_test_whose_name_promises_a_pass_is_still_classified_by_its_cause():
    row = tax.classify(
        record(
            nodeid="tests/test_x.py::test_everything_is_completely_fine",
            exception="ValueError: novel",
        )
    )
    assert row["category"] == tax.D


def test_a_benign_name_does_not_rescue_a_component_failure():
    row = tax.classify(
        record(
            nodeid="tests/test_x.py::test_tokenizers_are_absent",
            exception="AssertionError: the roster resealed",
            traceback_tail="  File 'tools/sfir9_cohort_roster.py', line 9",
        )
    )
    assert row["category"] == tax.D


# --------------------------------------------------- each signature is real


@pytest.mark.parametrize("signature", tax.SIGNATURES, ids=lambda s: s.key)
def test_every_signature_declares_a_category_and_a_reason(signature):
    assert signature.category in tax.CATEGORIES
    assert signature.why.strip()
    assert signature.key.strip()


@pytest.mark.parametrize(
    ("text", "expected", "key"),
    [
        (
            "EnumerationRefused: artifacts/development/sfi3_lineages.json exists.",
            tax.A,
            "sfi3_frame_materialised",
        ),
        (
            "AssertionError: a real sfi3-protocol-freeze receipt exists; ...",
            tax.A,
            "sfi3_protocol_freeze_receipt_exists",
        ),
        ("AssertionError: assert 16 == 12", tax.A, "more_source_modules_than_v2r3_declared"),
        (
            "FreezeRefused: a frozen scorer module has changed since rung 3: x.py",
            tax.B,
            "frozen_scorer_module_changed",
        ),
        (
            "FreezeRefused: the protocol attests files that have since changed",
            tax.B,
            "attested_files_since_changed",
        ),
        (
            "SpentAuthorityRefused: mandatory spent source digest drift: root_identity.py",
            tax.B,
            "spent_source_digest_drift",
        ),
        (
            "HandoffRefused: the reservation no longer describes what SFI3 declares",
            tax.B,
            "reservation_no_longer_describes_sfi3",
        ),
        ("AssertionError: cohort_floor_190", tax.B, "frozen_contract_digest_moved"),
        (
            "ModuleNotFoundError: No module named 'tokenizers'",
            tax.C,
            "absent_third_party_dependency",
        ),
        (
            "live_cohort_guard.LiveCohortRefused: preflight_sfi3_roots.run touches a "
            "live cohort",
            tax.C,
            "live_cohort_guard",
        ),
        (
            "conftest.RealNetworkForbidden: this test tried to open a real socket",
            tax.C,
            "real_network_guard",
        ),
    ],
)
def test_each_declared_root_cause_lands_where_it_should(text, expected, key):
    row = tax.classify(record(exception=text, traceback_tail=""))
    assert (row["category"], row["signature"]) == (expected, key)


def test_the_frame_absence_signature_needs_both_halves():
    """`assert not True` alone is not this cause -- it is any failed negation."""
    assert tax.classify(record(exception="AssertionError: assert not True"))[
        "category"
    ] == tax.D
    row = tax.classify(
        record(
            exception="AssertionError: assert not True",
            traceback_tail="  where True = ...sfi3_lineages.json.exists",
        )
    )
    assert row["signature"] == "sfi3_frame_present_but_asserted_absent"


# --------------------------------------------------------------- the receipt


def test_only_category_d_is_value_bearing_for_sfir9():
    assert {tax.D} == tax.VALUE_BEARING_FOR_SFIR9
    for name in (tax.A, tax.B, tax.C):
        row = tax.classify(record(exception=_example_for(name)))
        assert row["category"] == name
        assert row["value_bearing_for_sfir9"] is False


def _example_for(category):
    return {
        tax.A: "EnumerationRefused: sfi3_lineages.json exists.",
        tax.B: "SpentAuthorityRefused: mandatory spent source digest drift: x.py",
        tax.C: "ModuleNotFoundError: No module named 'tokenizers'",
    }[category]


def test_the_receipt_carries_one_row_per_failure_with_its_own_signature():
    report = tax.taxonomy([record(nodeid="a::b"), record(nodeid="c::d")])
    assert [row["nodeid"] for row in report["rows"]] == ["a::b", "c::d"]
    for row in report["rows"]:
        assert row["failure_signature"]
        assert row["phase"] == "call"


def test_the_counts_add_up_to_the_failures_examined():
    report = tax.taxonomy(
        [record(), record(exception="ValueError: novel"), record(exception=_example_for(tax.B))]
    )
    assert sum(report["counts"].values()) == report["failures_examined"] == 3


def test_the_digest_moves_with_the_classification():
    first = tax.taxonomy([record()])
    second = tax.taxonomy([record(exception="ValueError: novel")])
    assert first["taxonomy_digest"] != second["taxonomy_digest"]
    assert first["taxonomy_digest"].startswith("sha256:")


def test_every_category_is_defined_in_the_receipt():
    report = tax.taxonomy([record()])
    assert set(report["category_definitions"]) == {tax.A, tax.B, tax.C, tax.D}
    assert set(report["counts"]) == {tax.A, tax.B, tax.C, tax.D}
    assert report["unclassified_defaults_to"] == tax.D


def test_an_empty_run_does_not_read_as_a_cleared_repository():
    """Zero failures is a real state, but it must be visible as zero examined."""
    report = tax.taxonomy([])
    assert report["failures_examined"] == 0
    assert report["freeze_condition_met"] is True


# ---------------------------------------------- the receipt actually on disk


@pytest.mark.skipif(not RECEIPT.exists(), reason="taxonomy has not been run yet")
def test_the_recorded_taxonomy_meets_the_freeze_condition():
    """The precondition itself, against the run that produced the receipt."""
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert report["schema"] == tax.SCHEMA
    assert report["counts"]["D"] == 0
    assert report["freeze_condition_met"] is True
    assert report["failures_examined"] == sum(report["counts"].values())


@pytest.mark.skipif(not RECEIPT.exists(), reason="taxonomy has not been run yet")
def test_the_recorded_taxonomy_examined_a_non_empty_set():
    """A zero-failure receipt would meet `D == 0` while proving nothing."""
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert report["failures_examined"] > 0
    assert all(row["signature"] for row in report["rows"])


@pytest.mark.skipif(not RECEIPT.exists(), reason="taxonomy has not been run yet")
def test_no_recorded_failure_reaches_a_component_the_freeze_binds():
    report = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for row in report["rows"]:
        assert row["sfir9_components_in_traceback"] == [], row["nodeid"]


# ------------------------------------------------ the collector and the runner
#
# These were the four mutations that survived the first pass: the classifier was
# well covered and the machinery feeding it was not, which is the same thing as
# not being covered at all.


class _Report:
    def __init__(self, outcome, nodeid="tests/test_x.py::test_y", when="call", body=""):
        self.outcome = outcome
        self.nodeid = nodeid
        self.when = when
        self.longrepr = body


def test_the_collector_records_only_failures():
    collector = tax._Collector()
    collector.pytest_runtest_logreport(_Report("passed"))
    collector.pytest_runtest_logreport(_Report("skipped"))
    assert collector.rows == []
    collector.pytest_runtest_logreport(_Report("failed", body="E   ValueError: x"))
    assert len(collector.rows) == 1


def test_the_collector_keeps_the_traceback_not_only_the_headline():
    """The signatures match on traceback text, so a headline-only record would
    silently reclassify everything that needs its second half."""
    body = "\n".join(
        [
            "    def test_y():",
            ">       assert not enumerator.SFI3_FRAME.exists()",
            "E       AssertionError: assert not True",
            "E        +  where True = ...artifacts/development/sfi3_lineages.json.exists",
        ]
    )
    collector = tax._Collector()
    collector.pytest_runtest_logreport(_Report("failed", body=body))
    record_ = collector.rows[0]
    assert record_["exception"].startswith("+  where True")
    assert "sfi3_lineages.json" in record_["traceback_tail"]
    assert tax.classify(record_)["signature"] == "sfi3_frame_present_but_asserted_absent"


def test_the_collector_normalises_the_nodeid_separator():
    collector = tax._Collector()
    collector.pytest_runtest_logreport(
        _Report("failed", nodeid="tests" + chr(92) + "test_x.py::test_y", body="E  ValueError")
    )
    assert collector.rows[0]["nodeid"] == "tests/test_x.py::test_y"


def test_the_collector_records_the_phase_the_failure_happened_in():
    """A setup failure and a call failure are different problems."""
    collector = tax._Collector()
    collector.pytest_runtest_logreport(
        _Report("failed", when="setup", body="E  ValueError")
    )
    assert collector.rows[0]["phase"] == "setup"


@pytest.mark.parametrize("signature", tax.SIGNATURES, ids=lambda s: s.key)
def test_a_matched_row_carries_the_signatures_own_reason(signature):
    """Not an empty string, and not some other signature's reason."""
    row = tax.classify(record(exception="", traceback_tail=_matching_text(signature)))
    assert row["signature"] == signature.key
    assert row["why"] == signature.why
    assert row["why"].strip()


def _matching_text(signature):
    return {
        "sfi3_frame_materialised": "sfi3_lineages.json exists",
        "sfi3_frame_present_but_asserted_absent": (
            "assert not True\n where True = sfi3_lineages.json.exists"
        ),
        "sfi3_protocol_freeze_receipt_exists": "a real sfi3-protocol-freeze receipt exists",
        "more_source_modules_than_v2r3_declared": "assert 16 == 12",
        "frozen_scorer_module_changed": "a frozen scorer module has changed since rung 3",
        "attested_files_since_changed": "attests files that have since changed",
        "spent_source_digest_drift": "mandatory spent source digest drift",
        "reservation_no_longer_describes_sfi3": (
            "the reservation no longer describes what SFI3 declares"
        ),
        "frozen_contract_digest_moved": "AssertionError: cohort_floor_190",
        "absent_third_party_dependency": "ModuleNotFoundError: No module named 'x'",
        "live_cohort_guard": "LiveCohortRefused",
        "real_network_guard": "RealNetworkForbidden",
    }[signature.key]


def test_the_runner_exit_code_follows_the_freeze_condition(tmp_path, monkeypatch):
    """A green exit on a D is how an unexamined failure would reach the freeze."""
    monkeypatch.setattr(tax, "OUTPUT", tmp_path / "taxonomy.json")
    monkeypatch.setattr(tax, "REPO", tmp_path)
    monkeypatch.setattr(tax, "collect", lambda *a, **k: [record()])
    assert tax.main() == 0
    monkeypatch.setattr(
        tax, "collect", lambda *a, **k: [record(exception="ValueError: novel")]
    )
    assert tax.main() == 1


def test_the_runner_writes_the_receipt_it_reports_on(tmp_path, monkeypatch):
    target = tmp_path / "taxonomy.json"
    monkeypatch.setattr(tax, "OUTPUT", target)
    monkeypatch.setattr(tax, "REPO", tmp_path)
    monkeypatch.setattr(tax, "collect", lambda *a, **k: [record()])
    tax.main()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["failures_examined"] == 1
    assert written["counts"]["C"] == 1
