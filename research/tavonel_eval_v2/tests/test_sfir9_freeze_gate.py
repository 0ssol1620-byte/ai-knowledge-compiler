"""Controls for the freeze gate.

A gate is only worth the failures it can report, so almost everything here
drives a condition to FAIL or UNPROVEN and checks that the gate stays shut. The
one test that runs the real gate is last, and it is not the point: a gate that
opens is easy, and a gate that cannot close is worthless.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_freeze_gate as fg  # noqa: E402


def write_receipt(root, name, body, *, digest_key, digest=None):
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    payload = dict(body)
    payload[digest_key] = digest or (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    (root / "receipts" / name).write_bytes(
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    )
    return root / "receipts" / name


# ------------------------------------------------------- receipts are verified


def test_a_green_receipt_passes(tmp_path):
    write_receipt(tmp_path, "r.json", {"audit_passes": True}, digest_key="audit_digest")
    assert fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest").state == fg.PASS


def test_a_receipt_reporting_failure_fails(tmp_path):
    write_receipt(tmp_path, "r.json", {"audit_passes": False}, digest_key="audit_digest")
    outcome = fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest")
    assert outcome.state == fg.FAIL
    assert "False" in outcome.detail


def test_a_receipt_edited_after_it_was_written_fails(tmp_path):
    """The whole reason the digest is recomputed rather than read."""
    path = write_receipt(
        tmp_path, "r.json", {"audit_passes": False}, digest_key="audit_digest"
    )
    body = json.loads(path.read_text(encoding="utf-8"))
    body["audit_passes"] = True
    path.write_bytes(json.dumps(body, indent=2, sort_keys=True).encode("utf-8"))
    outcome = fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest")
    assert outcome.state == fg.FAIL
    assert "edited after it was written" in outcome.detail


def test_an_absent_receipt_is_unproven_not_failed(tmp_path):
    """Different problems. A missing measurement is not a negative one."""
    (tmp_path / "receipts").mkdir()
    outcome = fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest")
    assert outcome.state == fg.UNPROVEN


def test_an_unreadable_receipt_is_unproven(tmp_path):
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts/r.json").write_bytes(b"{not json")
    assert (
        fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest").state
        == fg.UNPROVEN
    )


def test_a_receipt_missing_its_verdict_is_unproven(tmp_path):
    write_receipt(tmp_path, "r.json", {"something_else": True}, digest_key="audit_digest")
    outcome = fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest")
    assert outcome.state == fg.UNPROVEN
    assert "carries no audit_passes" in outcome.detail


def test_a_truthy_verdict_is_not_a_true_one(tmp_path):
    """`1`, `"yes"` and a non-empty list are not a passing audit."""
    for value in (1, "yes", ["ok"]):
        write_receipt(tmp_path, "r.json", {"audit_passes": value}, digest_key="audit_digest")
        assert (
            fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest").state
            == fg.FAIL
        ), value


def test_a_receipt_with_no_digest_at_all_fails(tmp_path):
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts/r.json").write_bytes(b'{"audit_passes": true}')
    assert (
        fg.read_receipt(tmp_path, "r.json", "audit_passes", "audit_digest").state == fg.FAIL
    )


# --------------------------------------------------------- the roster stays shut


def test_the_gate_closes_once_a_real_cohort_exists(tmp_path):
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts/sfir9-cohort-roster--20260901T000000Z-abc.json").write_bytes(b"{}")
    outcome = fg.check_roster_unopened(tmp_path)
    assert outcome.state == fg.FAIL
    assert "already been opened" in outcome.detail


def test_the_gate_is_open_on_this_question_while_nothing_has_been_opened(tmp_path):
    (tmp_path / "receipts").mkdir()
    assert fg.check_roster_unopened(tmp_path).state == fg.PASS


@pytest.mark.parametrize(
    "name",
    [
        "sfir9-cohort-roster--x.json",
        "sfir9-census--x.json",
        "sfir9-roster--x.json",
    ],
)
def test_every_cohort_artifact_shape_closes_the_gate(tmp_path, name):
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / name).write_bytes(b"{}")
    assert fg.check_roster_unopened(tmp_path).state == fg.FAIL


def test_an_unrelated_receipt_does_not_close_the_gate(tmp_path):
    """Otherwise the previous test would pass for any file at all."""
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts/sfir9-hostile-audit.json").write_bytes(b"{}")
    assert fg.check_roster_unopened(tmp_path).state == fg.PASS


# ------------------------------------------------------------- the closure


def test_a_tree_without_the_components_is_unproven_not_passed(tmp_path):
    outcome = fg.check_closure(tmp_path)
    assert outcome.state in (fg.FAIL, fg.UNPROVEN)
    assert outcome.state != fg.PASS


# ------------------------------------------------------------ the verdict


def _rows(*states):
    return [
        {"condition": f"c{i}", "establishes": "x", "state": state, "detail": "", "how": "y"}
        for i, state in enumerate(states)
    ]


def test_the_gate_opens_only_when_every_condition_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (
            fg.Condition("a", "x", lambda _root: fg.Outcome(fg.PASS, "")),
            fg.Condition("b", "y", lambda _root: fg.Outcome(fg.PASS, "")),
        ),
    )
    assert fg.gate(tmp_path)["gate_opens"] is True


def test_one_failing_condition_closes_the_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (
            fg.Condition("a", "x", lambda _root: fg.Outcome(fg.PASS, "")),
            fg.Condition("b", "y", lambda _root: fg.Outcome(fg.FAIL, "nope")),
        ),
    )
    report = fg.gate(tmp_path)
    assert report["gate_opens"] is False
    assert report["conditions_passed"] == 1


def test_an_unproven_condition_closes_the_gate(monkeypatch, tmp_path):
    """The one that would otherwise read as a clean bill from a broken checker."""
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (fg.Condition("a", "x", lambda _root: fg.Outcome(fg.UNPROVEN, "could not run")),),
    )
    report = fg.gate(tmp_path)
    assert report["gate_opens"] is False
    assert report["conditions_passed"] == 0


def test_the_report_names_what_each_condition_establishes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "a real claim", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    row = fg.gate(tmp_path)["conditions"][0]
    assert row["establishes"] == "a real claim"
    assert row["how"] == "evaluated in this run"


def test_the_report_says_whether_a_slow_condition_was_read_or_re_derived(
    monkeypatch, tmp_path
):
    """Reading a receipt and re-deriving it are different evidence."""
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (fg.Condition("mutation_baselines", "x", lambda _r: fg.Outcome(fg.PASS, "")),),
    )
    read = fg.gate(tmp_path)["conditions"][0]
    assert read["how"] == "read from its receipt, digest recomputed"
    monkeypatch.setattr(fg, "_rerun", lambda *_a: fg.Outcome(fg.PASS, "re-derived: ok"))
    rerun = fg.gate(tmp_path, rerun_slow=True)["conditions"][0]
    assert rerun["how"] == "re-derived in this run"


def test_the_digest_moves_with_the_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    first = fg.gate(tmp_path)
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.FAIL, "")),)
    )
    assert first["gate_digest"] != fg.gate(tmp_path)["gate_digest"]


def test_the_gate_says_what_it_does_not_establish(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    report = fg.gate(tmp_path)
    assert "calibrated" in report["what_this_gate_does_not_establish"]
    assert "different problems" in report["unproven_does_not_pass"]


# ------------------------------------------------------ the conditions declared


def test_every_precondition_the_ruling_names_is_a_condition():
    named = {condition.name for condition in fg.CONDITIONS}
    assert named == {
        "sfir8_equivalence_j1_j2",
        "component_suites",
        "seam_verification",
        "execution_closure",
        "historical_isolation",
        "hostile_audit",
        "legacy_failure_taxonomy",
        "mutation_baselines",
        "roster_not_yet_opened",
    }


def test_every_condition_says_what_it_establishes():
    for condition in fg.CONDITIONS:
        assert condition.what_it_establishes.strip(), condition.name
        assert callable(condition.check), condition.name


def test_the_roster_question_is_asked_last():
    """It is the one that stops being true the moment the freeze succeeds."""
    assert fg.CONDITIONS[-1].name == "roster_not_yet_opened"


def test_both_slow_conditions_have_a_script_to_re_derive_them():
    assert set(fg.SLOW) <= {condition.name for condition in fg.CONDITIONS}
    for name, script in fg.SLOW.items():
        assert (NS / script).is_file(), name


# ------------------------------------------------- running a suite, and failing
#
# Seven mutations survived the first pass, every one of them in a branch these
# controls never reached: the suite runner, the closure's two "could not" exits,
# the re-derivation, and main(). A branch nothing drives is not defended.


@pytest.fixture
def suite_tree(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_ok.py").write_text("def test_ok():\n    assert True\n", "utf-8")
    (tmp_path / "tests/test_bad.py").write_text("def test_bad():\n    assert False\n", "utf-8")
    return tmp_path


def test_a_passing_suite_passes(suite_tree):
    assert fg._run_suite(suite_tree, ["tests/test_ok.py"]).state == fg.PASS


def test_a_failing_suite_fails(suite_tree):
    outcome = fg._run_suite(suite_tree, ["tests/test_bad.py"])
    assert outcome.state == fg.FAIL
    assert outcome.state != fg.PASS


def test_a_suite_that_collected_nothing_is_unproven(suite_tree):
    """Exit code 5. Non-zero, but nothing was measured, so it is not a failure."""
    outcome = fg._run_suite(suite_tree, ["tests/test_ok.py", "-k", "nothing_matches"])
    assert outcome.state == fg.UNPROVEN
    assert "collected no tests" in outcome.detail


def test_a_suite_that_could_not_be_run_is_unproven(suite_tree, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(fg.subprocess, "run", refuse)
    outcome = fg._run_suite(suite_tree, ["tests/test_ok.py"])
    assert outcome.state == fg.UNPROVEN
    assert "could not be run" in outcome.detail


def test_a_suite_that_timed_out_is_unproven(suite_tree, monkeypatch):
    def hang(*_args, **_kwargs):
        raise fg.subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(fg.subprocess, "run", hang)
    assert fg._run_suite(suite_tree, ["tests/test_ok.py"]).state == fg.UNPROVEN


# --------------------------------------------- the closure's two "could not" exits


def test_a_closure_that_raises_something_unexpected_is_unproven(tmp_path, monkeypatch):
    """Not a pass. An exception nobody anticipated measured nothing."""
    import sfir9_execution_closure as closure

    monkeypatch.setattr(
        closure, "require_component_lists_agree", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    outcome = fg.check_closure(tmp_path)
    assert outcome.state == fg.UNPROVEN
    assert "could not be evaluated" in outcome.detail


def test_a_closure_that_cannot_be_imported_is_unproven(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sfir9_execution_closure", None)
    outcome = fg.check_closure(tmp_path)
    assert outcome.state == fg.UNPROVEN
    assert "could not be imported" in outcome.detail


# ------------------------------------------------------ re-derivation and main


def test_a_failed_re_derivation_closes_the_gate(monkeypatch, tmp_path):
    """The re-run's answer has to be the one reported, not a hardcoded pass."""
    monkeypatch.setattr(
        fg,
        "CONDITIONS",
        (fg.Condition("mutation_baselines", "x", lambda _r: fg.Outcome(fg.PASS, "read")),),
    )
    monkeypatch.setattr(fg, "_rerun", lambda *_a: fg.Outcome(fg.FAIL, "re-derived: survivors"))
    report = fg.gate(tmp_path, rerun_slow=True)
    assert report["gate_opens"] is False
    assert report["conditions"][0]["state"] == fg.FAIL


def test_a_re_derivation_that_could_not_run_is_unproven(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(fg.subprocess, "run", refuse)
    assert fg._rerun(tmp_path, "tools/whatever.py").state == fg.UNPROVEN


def test_the_exit_code_follows_the_gate(monkeypatch, tmp_path):
    """A zero exit on a closed gate is how a weakened instrument gets frozen."""
    monkeypatch.setattr(fg, "OUTPUT", tmp_path / "gate.json")
    monkeypatch.setattr(fg, "REPO", tmp_path)
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    assert fg.main(["--root", str(tmp_path)]) == 0
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.FAIL, "")),)
    )
    assert fg.main(["--root", str(tmp_path)]) == 1


def test_the_runner_writes_the_report_it_prints(monkeypatch, tmp_path):
    target = tmp_path / "gate.json"
    monkeypatch.setattr(fg, "OUTPUT", target)
    monkeypatch.setattr(fg, "REPO", tmp_path)
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "ok")),)
    )
    fg.main(["--root", str(tmp_path)])
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["gate_opens"] is True
    assert written["conditions"][0]["condition"] == "a"


def test_the_gate_records_why_the_seam_is_asked_about_separately(monkeypatch, tmp_path):
    """`-k sfir9` already collects the seam tests, so the narrow condition looks
    redundant. It is not: a deleted seam file passes the broad condition and
    reports UNPROVEN under the narrow one."""
    monkeypatch.setattr(
        fg, "CONDITIONS", (fg.Condition("a", "x", lambda _r: fg.Outcome(fg.PASS, "")),)
    )
    note = fg.gate(tmp_path)["why_the_seam_has_its_own_condition"]
    assert "UNPROVEN" in note
    assert "vanished" in note
