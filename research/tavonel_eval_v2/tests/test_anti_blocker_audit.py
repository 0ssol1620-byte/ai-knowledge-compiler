"""Every check in the anti-blocker audit is driven red on a module built to fail it.

WHY THIS FILE IS NOT OPTIONAL. The audit's output is a verdict about the chains
that have not run yet, and a scanner that reports PASS because its checks cannot
fire is worse than no scanner -- it converts "we did not look" into "we looked
and it was clean". INC-V2-044 in this study's own ledger: a check that can only
return one answer is not a measurement.

So each of the fifteen classes gets a synthetic module carrying exactly its
defect, and the check must find it. Several also get the OPPOSITE module, so a
check that flagged everything would not pass either.

The audit's verdict on the REAL repository is asserted at the bottom, and it is
deliberately the weakest assertion here: it says the scan runs and reports, not
that a particular number of findings is correct.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import anti_blocker_audit as aba  # noqa: E402


def _tree(text: str) -> tuple[str, ast.Module]:
    return text, ast.parse(text)


def _classes(findings: list[aba.Finding]) -> set[int]:
    return {finding.defect_class for finding in findings}


def _severities(findings: list[aba.Finding], defect_class: int) -> set[str]:
    return {f.severity for f in findings if f.defect_class == defect_class}


# ---------------------------------------------------------------------------
# 1 and 12 -- borrowing from a spent study


BORROWS = "from score_sfi1 import MET\n\ndef score():\n    return MET\n"
BORROWS_AND_CHECKS = (
    "from score_sfi1 import MET\n\n"
    "def require_shared_vocabulary():\n    assert MET == 'MET'\n\n"
    "def score():\n    require_shared_vocabulary()\n    return MET\n"
)


def test_borrowing_from_a_spent_study_without_a_check_is_a_blocker():
    text, tree = _tree(BORROWS)
    found = aba._class_1_and_12("tools/x.py", text, tree)
    assert _classes(found) == {12}
    assert _severities(found, 12) == {aba.BLOCKER}


def test_borrowing_with_an_agreement_check_is_accepted_not_ignored():
    """Still reported. The shape is present; what changed is its power."""
    text, tree = _tree(BORROWS_AND_CHECKS)
    found = aba._class_1_and_12("tools/x.py", text, tree)
    assert _classes(found) == {1}
    assert _severities(found, 1) == {aba.ACCEPTED}


def test_a_module_borrowing_nothing_is_not_flagged():
    text, tree = _tree("import json\n\ndef score():\n    return json\n")
    assert aba._class_1_and_12("tools/x.py", text, tree) == []


# ---------------------------------------------------------------------------
# 2 and 14 -- naming a protocol without binding to it


def test_a_protocol_path_with_no_digest_check_is_a_blocker():
    text, tree = _tree('PROTOCOL = NS / "p.yaml"\n\ndef run():\n    return PROTOCOL\n')
    found = aba._class_2_and_14("tools/x.py", text, tree)
    assert 2 in _classes(found)


def test_a_protocol_path_with_a_digest_check_is_not_flagged():
    text = 'PROTOCOL = NS / "p.yaml"\n\ndef run():\n    return protocol_sha256\n'
    assert 2 not in _classes(aba._class_2_and_14("tools/x.py", *_tree(text)))


def test_a_receipt_that_records_no_binding_is_a_blocker():
    text, tree = _tree(
        'PROTOCOL = NS / "p.yaml"\n\n'
        "def run():\n"
        "    require_frozen()\n"
        '    return write_immutable("x", {})\n'
    )
    found = aba._class_2_and_14("tools/x.py", text, tree)
    assert 14 in _classes(found)


def test_a_receipt_that_records_a_binding_is_not_flagged():
    text, tree = _tree(
        'PROTOCOL = NS / "p.yaml"\n\n'
        "def run():\n"
        "    require_frozen()\n"
        '    return write_immutable("x", {"protocol_sha256": 1})\n'
    )
    assert 14 not in _classes(aba._class_2_and_14("tools/x.py", text, tree))


# ---------------------------------------------------------------------------
# 5 and 10 -- a live closure reachable from a test


def test_an_unguarded_closure_call_in_a_test_is_a_blocker():
    text, tree = _tree("def test_x():\n    scorer.run()\n")
    found = aba._class_5_and_10("tests/test_x.py", text, tree)
    assert _classes(found) == {5}


def test_a_closure_call_inside_pytest_raises_is_not_flagged():
    """The guard is the point; a scan that could not see it would flag it."""
    text, tree = _tree(
        "def test_x():\n"
        "    with pytest.raises(RuntimeError):\n"
        "        scorer.run()\n"
    )
    assert aba._class_5_and_10("tests/test_x.py", text, tree) == []


def test_a_main_call_without_execute_is_not_flagged():
    text, tree = _tree('def test_x():\n    scorer.main(["--write-receipt"])\n')
    assert aba._class_5_and_10("tests/test_x.py", text, tree) == []


def test_a_main_call_with_execute_is_a_blocker():
    text, tree = _tree('def test_x():\n    scorer.main(["--execute"])\n')
    assert _classes(aba._class_5_and_10("tests/test_x.py", text, tree)) == {5}


def test_a_cohort_entry_point_with_no_test_runner_refusal_is_reported():
    text, tree = _tree("def run():\n    return 1\n")
    assert _classes(aba._class_5_and_10("tools/x.py", text, tree)) == {10}


def test_a_cohort_entry_point_that_checks_sys_modules_is_not_flagged():
    text, tree = _tree(
        "def run():\n"
        '    if "pytest" in sys.modules:\n'
        "        raise RuntimeError\n"
        "    return 1\n"
    )
    assert aba._class_5_and_10("tools/x.py", text, tree) == []


# ---------------------------------------------------------------------------
# 6 -- work at import time


def test_reading_a_file_at_import_time_is_a_blocker():
    text, tree = _tree('BODY = PATH.read_text(encoding="utf-8")\n')
    assert _classes(aba._class_6("tools/x.py", text, tree)) == {6}


def test_reading_through_a_local_helper_at_import_time_is_also_caught():
    """The shape that actually appears: a constant assigned from a reader."""
    text, tree = _tree(
        "def _load(path):\n"
        '    return path.read_text(encoding="utf-8")\n\n'
        "BODY = _load(PATH)\n"
    )
    assert _classes(aba._class_6("tools/x.py", text, tree)) == {6}


def test_a_main_guard_is_not_import_time_work():
    """Otherwise every CLI entry point in the repository is a finding."""
    text, tree = _tree(
        "def main():\n"
        '    return PATH.read_text(encoding="utf-8")\n\n'
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n"
    )
    assert aba._class_6("tools/x.py", text, tree) == []


# ---------------------------------------------------------------------------
# 7 and 11 -- newest-wins, and a mutable path segment


NEWEST_WINS = 'def latest():\n    return sorted(D.glob("x--*.json"))[-1]\n'


def test_newest_wins_with_no_explicit_receipt_is_a_blocker():
    text, tree = _tree(NEWEST_WINS)
    found = aba._class_7_and_11("tools/x.py", text, tree)
    assert _severities(found, 7) == {aba.BLOCKER}


def test_newest_wins_alongside_an_explicit_receipt_flag_is_accepted():
    text = NEWEST_WINS + '\nFLAG = "--receipt"\n'
    text, tree = _tree(text)
    found = aba._class_7_and_11("tools/x.py", text, tree)
    assert _severities(found, 7) == {aba.ACCEPTED}


def test_a_path_built_through_latest_is_a_blocker():
    text, tree = _tree('P = NS / "receipts" / "latest" / "x.json"\n')
    found = aba._class_7_and_11("tools/x.py", text, tree)
    assert _severities(found, 11) == {aba.BLOCKER}


def test_refusing_the_string_latest_is_not_using_it():
    """The guard against this class, which an earlier version read as the class.

    INC-V2-036 pointed at the auditor rather than the audited: a check that
    cannot tell a refusal from a use reports the safest module as the worst.
    """
    text, tree = _tree(
        "def check(revision):\n"
        '    if revision == "latest":\n'
        '        raise ValueError("exact revision required")\n'
        '    return revision != "latest"\n'
    )
    assert aba._class_7_and_11("tools/x.py", text, tree) == []


def test_a_sealed_frame_lowers_the_severity_but_keeps_the_finding():
    text, tree = _tree(
        'P = NS / "receipts" / "latest" / "x.json"\n\n'
        "def read():\n"
        '    return BODY["points_to"]\n\n'
        "def frame_digest(rows):\n"
        '    return "sha256:0"\n'
    )
    found = aba._class_7_and_11("acquisition/x.py", text, tree)
    assert _severities(found, 11) == {aba.FINDING}


# ---------------------------------------------------------------------------
# 8 and 9 -- output before a return, a receipt inside a loop


def test_output_before_the_final_return_is_reported():
    text, tree = _tree("def run():\n    print(1)\n    return 2\n")
    assert 8 in _classes(aba._class_8_and_9("tools/x.py", text, tree))


def test_output_after_everything_is_not_reported():
    text, tree = _tree("def run():\n    return 2\n")
    assert aba._class_8_and_9("tools/x.py", text, tree) == []


def test_a_receipt_written_inside_a_loop_is_a_blocker():
    text, tree = _tree(
        "def run(rows):\n"
        "    for row in rows:\n"
        '        write_immutable("x", row)\n'
        "    return 1\n"
    )
    found = aba._class_8_and_9("tools/x.py", text, tree)
    assert _severities(found, 9) == {aba.BLOCKER}


# ---------------------------------------------------------------------------
# 3, 4 and 13 -- literals that should be one constant


def test_an_endpoint_id_in_two_modules_of_one_study_is_a_blocker():
    modules = {
        "tools/score_sfi3.py": _tree('A = "E1_no_unclassified_changed_regions"\n'),
        "tools/rehearse_sfi3_execution.py": _tree(
            'B = "E1_no_unclassified_changed_regions"\n'
        ),
    }
    found = aba._class_3_4_13(modules)
    assert _severities(found, 3) == {aba.BLOCKER}


def test_the_same_id_in_two_different_studies_is_not_drift():
    """SFI2's E1 and SFI3's E1 are two studies' endpoints sharing a name.

    Neither reads the other, so neither can drift from it, and reporting the
    collision would make the audit unpassable for a reason about nothing.
    """
    modules = {
        "tools/score_sfi3.py": _tree('A = "E1_no_unclassified_changed_regions"\n'),
        "tools/launch_gpu_successor.py": _tree('B = "E1_no_unclassified_changed_regions"\n'),
    }
    assert 3 not in _classes(aba._class_3_4_13(modules))


def test_a_test_re_spelling_an_endpoint_id_is_a_finding_not_a_blocker():
    modules = {
        "tools/score_sfi3.py": _tree('A = "E7_unresolved_fails_closed"\n'),
        "tests/test_sfi3_scoring.py": _tree('B = "E7_unresolved_fails_closed"\n'),
    }
    found = aba._class_3_4_13(modules)
    assert _severities(found, 4) == {aba.FINDING}


def test_a_duplicated_schema_id_is_a_blocker():
    modules = {
        "tools/four_link_gate.py": _tree('S = "tavonel.v2.four_link_gate.v1"\n'),
        "tools/four_link_validator.py": _tree('S = "tavonel.v2.four_link_gate.v1"\n'),
    }
    found = aba._class_3_4_13(modules)
    assert _severities(found, 13) == {aba.BLOCKER}


def test_prose_naming_an_endpoint_is_not_a_duplicate_literal():
    """A docstring explaining E1 is documentation, not a second copy of the key."""
    modules = {
        "tools/score_sfi3.py": _tree('A = "E1_no_unclassified_changed_regions"\n'),
        "tools/rehearse_sfi3_execution.py": _tree(
            '"""E1_no_unclassified_changed_regions is graded by score_sfi3."""\n'
        ),
    }
    assert 3 not in _classes(aba._class_3_4_13(modules))


# ---------------------------------------------------------------------------
# 15 -- acceptance domain vs executable grading domain
#
# The class INC-V2-067 would have been caught by. Whether the two domains are
# equal is a question only `invariant_domain` can answer, by executing the
# grader; what an AST scan establishes is whether anybody asks.
# ---------------------------------------------------------------------------

UNCHECKED_SET = 'ENDPOINTS = ("E1_a", "E2_b")\n'
CHECKED_SET = 'ENDPOINTS = ("E1_a",)\n\ndef frozen():\n    require_declared_endpoints()\n'
REPORTS_DOMAIN = (
    'REQUIRED_ENDPOINTS = ("E1_a",)\n\n'
    "def gate(body):\n"
    '    return {"acceptance_domain": {"graded_but_not_gated": []}}\n'
)
OWNS_THE_ANCHOR = (
    'CANONICAL_INVARIANTS = ("INVARIANT_1_a",)\n\n'
    "def _require_canonical_is_well_formed():\n"
    "    return True\n"
)


def test_an_unchecked_acceptance_set_is_a_blocker():
    found = aba._class_15("tools/x.py", *_tree(UNCHECKED_SET))
    assert _severities(found, 15) == {aba.BLOCKER}


def test_an_acceptance_set_routed_through_a_domain_check_is_accepted():
    found = aba._class_15("tools/x.py", *_tree(CHECKED_SET))
    assert _severities(found, 15) == {aba.ACCEPTED}


def test_a_module_reporting_its_domain_comparison_is_accepted():
    """Reporting the difference proves both sides were computed."""
    found = aba._class_15("tools/x.py", *_tree(REPORTS_DOMAIN))
    assert _severities(found, 15) == {aba.ACCEPTED}


def test_a_module_declaring_no_acceptance_set_is_not_flagged():
    assert aba._class_15("tools/x.py", *_tree("def run():\n    return 1\n")) == []


def test_the_anchor_module_is_not_required_to_check_itself_against_itself():
    """It is the thing others are compared to, and it verifies its own shape."""
    assert aba._class_15("tools/x.py", *_tree(OWNS_THE_ANCHOR)) == []


# ---------------------------------------------------------------------------
# every class is reachable, and the real scan runs


def test_all_fifteen_classes_can_be_produced():
    """A closed list whose members cannot all be produced is not a taxonomy."""
    produced: set[int] = set()
    produced |= _classes(aba._class_1_and_12("tools/x.py", *_tree(BORROWS)))
    produced |= _classes(aba._class_1_and_12("tools/x.py", *_tree(BORROWS_AND_CHECKS)))
    produced |= _classes(
        aba._class_2_and_14(
            "tools/x.py",
            *_tree('PROTOCOL = NS / "p.yaml"\n\ndef run():\n    write_immutable("x", {})\n'),
        )
    )
    produced |= _classes(aba._class_5_and_10("tests/t.py", *_tree("def t():\n    scorer.run()\n")))
    produced |= _classes(aba._class_5_and_10("tools/x.py", *_tree("def run():\n    return 1\n")))
    produced |= _classes(aba._class_6("tools/x.py", *_tree('B = P.read_text(encoding="utf-8")\n')))
    produced |= _classes(aba._class_7_and_11("tools/x.py", *_tree(NEWEST_WINS)))
    produced |= _classes(
        aba._class_7_and_11("tools/x.py", *_tree('P = NS / "receipts" / "latest" / "x.json"\n'))
    )
    produced |= _classes(
        aba._class_8_and_9("tools/x.py", *_tree("def run():\n    print(1)\n    return 2\n"))
    )
    produced |= _classes(
        aba._class_8_and_9(
            "tools/x.py",
            *_tree("def run(r):\n    for x in r:\n        write_immutable('x', x)\n    return 1\n"),
        )
    )
    produced |= _classes(aba._class_15("tools/x.py", *_tree(UNCHECKED_SET)))
    produced |= _classes(
        aba._class_3_4_13(
            {
                "tools/score_sfi3.py": _tree('A = "E1_no_unclassified_changed_regions"\n'),
                "tools/rehearse_sfi3_execution.py": _tree(
                    'B = "E1_no_unclassified_changed_regions"\n'
                ),
                "tests/test_sfi3_scoring.py": _tree('C = "E1_no_unclassified_changed_regions"\n'),
                "tools/four_link_gate.py": _tree('S = "tavonel.v2.four_link_gate.v1"\n'),
                "tools/four_link_validator.py": _tree('S = "tavonel.v2.four_link_gate.v1"\n'),
            }
        )
    )
    assert produced == set(aba.CLASS_NAMES), sorted(set(aba.CLASS_NAMES) - produced)


def test_the_audit_scans_the_declared_surface_and_finds_every_module():
    body = aba.audit()
    assert body["modules_absent"] == []
    assert len(body["modules_scanned"]) == len(aba.ACTIVE_TOOLS) + len(aba.ACTIVE_TESTS)
    assert set(body["classes_checked"]) == {str(k) for k in aba.CLASS_NAMES}


def test_the_audit_reports_its_findings_rather_than_only_a_verdict():
    """A PASS with the findings withheld would be an assertion, not a report."""
    body = aba.audit()
    assert isinstance(body["findings"], list)
    assert body["verdict"] == (
        "ANTI_BLOCKER_AUDIT_PASS" if body["blocker_count"] == 0 else "BLOCKED"
    )
    for finding in body["findings"]:
        assert finding["severity"] in {aba.BLOCKER, aba.FINDING, aba.ACCEPTED}
        assert finding["defect_class"] in aba.CLASS_NAMES
        assert finding["detail"]


@pytest.mark.parametrize("name", [name for name, _ in aba.STUDY_SURFACES])
def test_every_declared_study_surface_matches_at_least_one_active_module(name: str):
    """A surface nothing belongs to would silently scope a class into nothing."""
    assert any(
        aba._study_of(rel) == name for rel in aba.ACTIVE_TOOLS + aba.ACTIVE_TESTS
    )
